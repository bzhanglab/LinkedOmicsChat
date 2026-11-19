"""Gene signatures matched against treatment response in ClinicalOmicsDB trial cohorts.

ClinicalOmicsDB ranks every measured gene in each trial-linked study by how well it separates
responders from non-responders (AUROC; below 0.5 means higher in responders). A signature is
matched by testing whether its genes, as a group, sit at one end of each study's ranking.

The 67 study tables are about 130 MB as JSON and tool calls run in fresh processes, so the
rankings are kept on disk as one gene x study matrix that loads in milliseconds. The backend
refreshes it in the background at startup when it is missing or more than a week old; run
`python mcp_servers/signature_matching.py --refresh` to refresh it by hand.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import requests

API = "https://trials.linkedomics.org/api"
# /filter returns nothing for empty filters, so the study list is every cancer type it knows
CANCERS = ["Breast", "Ovarian", "Lung", "Leukemia", "Myeloma", "Melanoma", "Esophageal",
           "Kidney", "Bladder", "Gastric", "Glioblastoma"]
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "clinicalomicsdb"
RANKINGS_PATH = CACHE_DIR / "rankings.npz"
STUDIES_PATH = CACHE_DIR / "studies.json"
MAX_AGE_SECONDS = 7 * 24 * 60 * 60
_INFO_FIELDS = ("series", "disease", "subtype", "treatment", "response_eval", "sample_size",
                "responder_size", "non_responder_size", "clinical_trial_id", "pub_med_id", "platform")


@dataclass
class Rankings:
    genes: np.ndarray       # gene symbols, sorted
    studies: list[dict]     # one dict per column: study_id, series, disease, treatment, sizes, ...
    auc: np.ndarray         # genes x studies, float32, NaN where a study did not measure a gene
    fdr: np.ndarray         # genes x studies, signed like the API (negative: higher in responders)
    built_at: float

    def gene_rows(self, symbols: list[str]) -> dict[str, int]:
        """Row index of each symbol that is in any study."""
        index = {g: i for i, g in enumerate(self.genes.tolist())}
        return {s: index[s] for s in symbols if s in index}


def _get(url: str, timeout: int = 120) -> Any:
    """GET with one retry; the service sometimes drops a connection under load."""
    for attempt in range(2):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt:
                raise
            time.sleep(2)


def _study_ids() -> list[str]:
    response = requests.post(f"{API}/filter", json={"drugs": [], "cancers": CANCERS}, timeout=60)
    response.raise_for_status()
    return [s if isinstance(s, str) else s.get("study_id") for s in response.json().get("study_list") or []]


def _current_names(names: set[str], log: Callable[[str], None]) -> dict[str, str]:
    """Old gene names in the study tables (AARS, A1BG.AS1), mapped to the current symbols that
    users' lists are converted to (AARS1, A1BG-AS1). Ambiguous names are left as they are."""
    backend_dir = str(Path(__file__).resolve().parents[1])
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from services.gene_list import _VALID_GENES, _query_mygene

    stale = [g for g in names if g not in _VALID_GENES]
    renames = {g: g.replace(".", "-") for g in stale if "." in g and g.replace(".", "-") in _VALID_GENES}
    found = _query_mygene([g for g in stale if g not in renames])
    if found is None:
        log("  MyGene.info lookup failed; old gene names are kept as they are")
    renames.update({g: matches[0] for g, matches in (found or {}).items() if len(matches) == 1})
    return renames


def refresh_cache(log: Callable[[str], None] = print, pause: float = 0.3) -> dict[str, Any]:
    """Download every study's gene ranking and details, and replace the cache files."""
    started = time.time()
    ids = _study_ids()
    if not ids:
        raise RuntimeError("ClinicalOmicsDB returned no studies")
    tables: dict[str, dict[str, tuple[float, float]]] = {}
    studies: list[dict] = []
    failed: list[str] = []
    for n, study_id in enumerate(ids, 1):
        try:
            info = _get(f"{API}/info/{study_id}", timeout=60)
            rows = _get(f"{API}/table/study/gene/{study_id}")
        except (requests.RequestException, ValueError) as exc:
            failed.append(study_id)
            log(f"  {study_id}: failed ({exc})")
            continue
        values = {}
        for row in rows:
            symbol = str(row.get("analyte") or "").strip().upper()
            try:
                values[symbol] = (float(row["auc"]), float(row["fdr"]))
            except (KeyError, TypeError, ValueError):
                continue
        values.pop("", None)
        tables[study_id] = values
        studies.append({"study_id": study_id, "n_genes": len(values),
                        **{k: str((info or {}).get(k) or "") for k in _INFO_FIELDS}})
        if n % 10 == 0:
            log(f"  {n} of {len(ids)} studies")
        time.sleep(pause)
    if not tables:
        raise RuntimeError("no study tables could be downloaded")

    # A study keeps its own current-name entry when it has one; otherwise the old name is renamed
    renames = _current_names({g for values in tables.values() for g in values}, log)
    renamed = 0
    for values in tables.values():
        for old, new in renames.items():
            if old in values and new not in values:
                values[new] = values.pop(old)
                renamed += 1

    genes = np.array(sorted({g for values in tables.values() for g in values}))
    row = {g: i for i, g in enumerate(genes.tolist())}
    auc = np.full((len(genes), len(studies)), np.nan, dtype=np.float32)
    fdr = np.full((len(genes), len(studies)), np.nan, dtype=np.float32)
    for column, study in enumerate(studies):
        for gene, (a, f) in tables[study["study_id"]].items():
            auc[row[gene], column] = a
            fdr[row[gene], column] = f

    # Write both files under temporary names, then swap them in, so a tool call never reads a mix
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_rankings = CACHE_DIR / f"rankings.{os.getpid()}.tmp.npz"
    tmp_studies = CACHE_DIR / f"studies.{os.getpid()}.tmp.json"
    np.savez_compressed(tmp_rankings, genes=genes, auc=auc, fdr=fdr)
    tmp_studies.write_text(json.dumps({"built_at": started, "failed": failed, "studies": studies}))
    tmp_rankings.replace(RANKINGS_PATH)
    tmp_studies.replace(STUDIES_PATH)
    summary = {"studies": len(studies), "failed": failed, "genes": len(genes), "renamed": renamed,
               "seconds": round(time.time() - started, 1), "bytes": RANKINGS_PATH.stat().st_size}
    log(f"ClinicalOmicsDB cache: {summary}")
    return summary


def cache_is_stale(max_age: float = MAX_AGE_SECONDS) -> bool:
    if not (RANKINGS_PATH.exists() and STUDIES_PATH.exists()):
        return True
    return time.time() - STUDIES_PATH.stat().st_mtime > max_age


def load_rankings() -> Optional[Rankings]:
    """The cached rankings, or None while the first download has not finished."""
    if not (RANKINGS_PATH.exists() and STUDIES_PATH.exists()):
        return None
    meta = json.loads(STUDIES_PATH.read_text())
    with np.load(RANKINGS_PATH) as data:
        return Rankings(genes=data["genes"], studies=meta["studies"], auc=data["auc"], fdr=data["fdr"],
                        built_at=float(meta.get("built_at") or 0))


MIN_SIGNATURE_GENES = 5
SMALL_GROUP = 10  # studies with fewer responders or non-responders than this are flagged
DRIVING_GENES = 5
# How a signature's score translates to the AUROC a patient-level signature score would have:
# 0.5 - AUC ~ 0.172 * tanh(3.32 * score). Fitted on the 50 Hallmark sets in all 67 studies
# against ClinicalOmicsDB's own patient-level gene-set AUROCs (2026-11-19; Spearman 0.73).
_AUC_SCALE = 0.172
_AUC_STEEPNESS = 3.32


def _benjamini_hochberg(p: np.ndarray) -> np.ndarray:
    order = np.argsort(p)
    ranked = p[order] * len(p) / np.arange(1, len(p) + 1)
    adjusted = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty_like(adjusted)
    out[order] = np.minimum(adjusted, 1.0)
    return out


def _size(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _patient_level_p(score: float, responders: int, non_responders: int) -> float:
    """Two-sided p for the AUROC the score implies, given the study's patient counts
    (normal approximation to the Mann-Whitney test across patients)."""
    from scipy.stats import norm

    if responders < 1 or non_responders < 1:
        return 1.0
    implied = _AUC_SCALE * np.tanh(_AUC_STEEPNESS * score)
    se = np.sqrt((responders + non_responders + 1) / (12.0 * responders * non_responders))
    return float(2 * norm.sf(abs(implied) / se))


def match_signature(
    genes: list[str],
    rankings: Rankings,
    cancers: Optional[list[str]] = None,
    treatments: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Test a gene signature against treatment response in every cached study, or in the
    studies of the given cancers and treatments (drug names; a study matches any of them).

    In each study, the signature genes' AUROCs are compared with those of all other measured
    genes (two-sided Mann-Whitney). The score is the rank-biserial correlation, from -1 (every
    signature gene ranks toward non-responders) to +1 (every one toward responders).

    That gene-level p-value alone is far too optimistic, because a signature's genes are
    usually co-expressed: on the Hallmark sets it called 54% of study tests significant where
    ClinicalOmicsDB's patient-level tests called 16%. The p-value used is therefore the larger
    of the gene-level p and a patient-level p (from the AUROC the score implies and the
    study's numbers of responders and non-responders), and FDR is Benjamini-Hochberg across
    the studies tested. Checked 2026-11-19: random gene sets of 5-100 genes reach FDR < 0.05
    in under 0.01% of study tests; on held-out Hallmark sets, 55% of FDR < 0.05 calls are also
    significant in the patient-level data, always in the same direction.
    """
    from scipy.stats import mannwhitneyu

    wanted = list(dict.fromkeys(str(g).strip().upper() for g in genes if str(g).strip()))
    rows = rankings.gene_rows(wanted)
    cancer_filter = {c.strip().lower() for c in cancers or [] if c.strip()}
    treatment_filter = [t.strip().lower() for t in treatments or [] if t.strip()]

    tested: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    p_values: list[float] = []
    for column, study in enumerate(rankings.studies):
        if cancer_filter and study["disease"].lower() not in cancer_filter:
            continue
        if treatment_filter and not any(t in study["treatment"].lower() for t in treatment_filter):
            continue
        auc = rankings.auc[:, column]
        measured = ~np.isnan(auc)
        in_signature = np.zeros(len(auc), dtype=bool)
        in_signature[list(rows.values())] = True
        signature = measured & in_signature
        n_signature = int(signature.sum())
        if n_signature < MIN_SIGNATURE_GENES:
            skipped.append({"study_id": study["study_id"], "genes_measured": n_signature})
            continue
        toward_responders = 0.5 - auc  # positive: higher in responders
        sig_values, other_values = toward_responders[signature], toward_responders[measured & ~in_signature]
        u, gene_level_p = mannwhitneyu(sig_values, other_values, alternative="two-sided")
        score = 2.0 * u / (len(sig_values) * len(other_values)) - 1.0
        fdr = rankings.fdr[:, column]
        significant = signature & (np.abs(fdr) < 0.05)
        sig_genes = rankings.genes[signature]
        order = np.argsort(-sig_values if score >= 0 else sig_values)[:DRIVING_GENES]
        responders, non_responders = _size(study["responder_size"]), _size(study["non_responder_size"])
        p = max(float(gene_level_p), _patient_level_p(score, responders, non_responders))
        tested.append({
            "study_id": study["study_id"].removesuffix(".csv"),
            "series": study["series"] or study["study_id"].removesuffix(".csv"),
            "cancer": study["disease"],
            "subtype": study["subtype"],
            "treatment": study["treatment"],
            "response": study["response_eval"],
            "responders": responders,
            "non_responders": non_responders,
            "small_study": min(responders, non_responders) < SMALL_GROUP,
            "genes_measured": n_signature,
            "higher_in": "responders" if score > 0 else "non-responders",
            "score": round(float(score), 3),
            "p_value": float(p),
            "genes_significant_responders": int((significant & (auc < 0.5)).sum()),
            "genes_significant_non_responders": int((significant & (auc > 0.5)).sum()),
            "driving_genes": [
                {"gene": str(sig_genes[i]), "auc": round(float(0.5 - sig_values[i]), 3)} for i in order
            ],
            "clinical_trial_id": study["clinical_trial_id"],
            "pubmed_id": study["pub_med_id"],
        })
        p_values.append(float(p))

    if tested:
        for row, q in zip(tested, _benjamini_hochberg(np.array(p_values))):
            row["fdr"] = float(q)
        tested.sort(key=lambda r: (r["fdr"], -abs(r["score"])))
    found = set(rows)
    return {
        "genes_given": len(wanted),
        "genes_in_studies": len(found),
        "genes_not_in_any_study": [g for g in wanted if g not in found],
        "studies_tested": len(tested),
        "studies_skipped": skipped,
        "results": tested,
    }


def by_treatment_class(results: list[dict[str, Any]], classes: dict[str, set[str]]) -> list[dict[str, Any]]:
    """How consistently the signature falls on one side within each treatment class.

    Most single studies are too small to reach significance, so the count of studies on each
    side is often the clearest result. A combination counts in each class it belongs to.
    """
    summary = []
    for name, drugs in classes.items():
        members = [r for r in results if any(d in r["treatment"].lower() for d in drugs)]
        if members:
            summary.append({
                "treatment_class": name,
                "studies": len(members),
                "higher_in_responders": sum(r["higher_in"] == "responders" for r in members),
                "higher_in_non_responders": sum(r["higher_in"] == "non-responders" for r in members),
                "fdr_below_0_05": sum(r["fdr"] < 0.05 for r in members),
            })
    return summary


MODEL_ROWS = 15


def compact_for_model(payload: dict[str, Any], rows: int = MODEL_ROWS) -> dict[str, Any]:
    """The tool result as the chat model and the summary step see it: every study row is about
    700 characters, so they get the overview fields and the top rows with their key fields."""
    results = payload.get("results")
    if not isinstance(results, list):
        return payload
    keep = ("study_id", "cancer", "treatment", "responders", "non_responders", "small_study",
            "genes_measured", "higher_in", "score", "fdr")
    return {
        **{k: v for k, v in payload.items() if k != "results"},
        "results_shown": f"top {min(rows, len(results))} of {len(results)} studies by FDR",
        "results": [
            {**{k: r.get(k) for k in keep}, "fdr": float(f"{r.get('fdr', 1.0):.2g}"),
             "driving_genes": [g["gene"] for g in r.get("driving_genes") or []]}
            for r in results[:rows]
        ],
    }


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh_cache()
    else:
        rankings = load_rankings()
        print("no cache yet; run with --refresh" if rankings is None else
              f"{len(rankings.studies)} studies, {len(rankings.genes)} genes, built "
              f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(rankings.built_at))}")
