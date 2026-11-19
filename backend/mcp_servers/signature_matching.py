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


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh_cache()
    else:
        rankings = load_rankings()
        print("no cache yet; run with --refresh" if rankings is None else
              f"{len(rankings.studies)} studies, {len(rankings.genes)} genes, built "
              f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(rankings.built_at))}")
