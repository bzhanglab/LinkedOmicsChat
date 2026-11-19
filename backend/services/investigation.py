"""Investigation mode: a fixed set of analyses for one gene in one cancer, for one question
(is it a drug target, is it a prognostic marker), and the lines of evidence they give.

Each line comes from one source and one molecular layer and keeps what the source reports:
direction, effect size, p-value and sample size. "No data" (the source has nothing for this
cancer or this gene) is kept apart from a tested result with no association, and a failed call is
marked as failed, so missing evidence never reads as negative evidence. Rating the lines is a
separate step.
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

QUESTIONS = ("target", "prognostic")

# CPTAC cohort -> the TCGA cohort for the same cancer, and its name in the trial-linked studies
# (None: no study for that cancer)
COHORTS: Dict[str, Tuple[str, Optional[str]]] = {
    "BRCA": ("BRCA", "Breast"),
    "CCRCC": ("KIRC", "Kidney"),
    "COAD": ("COADREAD", None),
    "GBM": ("GBM", "Glioblastoma"),
    "HNSCC": ("HNSC", None),
    "LSCC": ("LUSC", "Lung"),
    "LUAD": ("LUAD", "Lung"),
    "OV": ("OV", "Ovarian"),
    "PDAC": ("PAAD", None),
    "UCEC": ("UCEC", None),
}

# Cancers a source has no data for at all: none of 20 genes had any (checked 2026-11-19).
# The report uses this to say why a line is empty.
SOURCE_GAPS: Dict[Tuple[str, str], Tuple[set, str]] = {
    ("tumor_vs_normal", "protein"): ({"BRCA", "GBM"}, "CPTAC has no normal-tissue protein data for this cancer"),
    ("tumor_vs_normal", "RNA"): ({"BRCA", "COAD", "GBM", "OV", "UCEC"}, "CPTAC has no normal-tissue RNA data for this cancer"),
    ("survival", "protein"): ({"BRCA"}, "CPTAC has no survival data for this cancer"),
    ("survival", "RNA"): ({"BRCA"}, "CPTAC has no survival data for this cancer"),
    # Even common essential genes (PCNA, RPL3) are never marked dependent in these two
    ("dependency", "cell lines"): ({"BRCA", "GBM"}, "LinkedOmics Targets has no cell-line data for this cancer"),
}
_DEPENDENCY_COHORTS = 8  # the CPTAC cancers with cell-line data

_TCGA_LAYERS = {"RNAseq": "RNA", "RPPA": "protein (RPPA)", "Methylation": "methylation", "SCNA": "copy number"}


def investigation_calls(gene: str, cancer: str, question: str) -> List[Tuple[str, Dict[str, Any]]]:
    """The analyses for a question, in report order. Each call covers the one cancer, or all
    cancers where the tool takes no cancer argument."""
    tcga, _ = COHORTS[cancer]
    survival = [
        ("linkedomics::analyze_cptac_gene_survival_associations", {"protein": gene}),
        ("linkedomics::analyze_tcga_survival_associations", {"gene": gene, "cohort": tcga}),
    ]
    trials = [("linkedomics::search_gene_response_trials", {"protein": gene})]
    if question == "prognostic":
        return survival + trials
    return [
        ("linkedomics::compare_cptac_tumor_normal_expression", {"protein": gene}),
        ("linkedomics::analyze_cptac_cis_associations",
         {"protein": gene, "pairs": ["SCNV vs Protein", "SCNV vs RNA"], "cancers": [cancer]}),
        ("linkedomics::analyze_tcga_cis_associations",
         {"gene": gene, "cohort": tcga, "source_omics": "SCNA", "target_omics": "RNAseq"}),
        ("linkedomics::analyze_tcga_cis_associations",
         {"gene": gene, "cohort": tcga, "source_omics": "SCNA", "target_omics": "RPPA"}),
        *survival,
        ("linkedomics::get_drug_target_profile", {"protein": gene}),
        *trials,
        ("linkedomics::get_funmap_functional_neighborhood", {"protein": gene}),
    ]


def _line(line: str, source: str, layer: str, status: str, *, direction: Optional[int] = None,
          effect: Optional[float] = None, effect_name: Optional[str] = None, p: Optional[float] = None,
          n: Optional[int] = None, note: str = "") -> Dict[str, Any]:
    """One line of evidence. status: "tested", "no_data" or "failed". direction: +1 or -1 in the
    line's own sense (higher in tumor, positive correlation, higher level with poorer survival,
    dependent, higher level with better response), None when not significant or not tested."""
    return {
        "line": line, "source": source, "layer": layer, "status": status, "direction": direction,
        "effect": effect, "effect_name": effect_name, "p": p, "n": n,
        "significant": None if p is None else p < 0.05, "note": note,
    }


def _no_data(line: str, source: str, layer: str, cancer: str, gap_key: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
    cancers, reason = SOURCE_GAPS.get(gap_key or (line, layer), (set(), ""))
    return _line(line, source, layer, "no_data", note=reason if cancer in cancers else "No data for this gene")


def _is_error(result: Optional[Dict[str, Any]]) -> bool:
    """A call that failed: not run, raised, or answered with status "error" (the TCGA service's
    "read of closed file" under load comes back this way)."""
    return result is None or "error" in result or result.get("status") == "error"


def _failed(line: str, source: str, layer: str, result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result = result or {"error": "not run"}
    return _line(line, source, layer, "failed", note=str(result.get("error") or result.get("message"))[:200])


def _find(tool_results: Dict[str, Any], tool_id: str, **args: Any) -> Optional[Dict[str, Any]]:
    """The result of a call, matched by tool and by the arguments given."""
    for key, wrapped in tool_results.items():
        if key.split("#")[0] != tool_id or not isinstance(wrapped, dict):
            continue
        call_args = wrapped.get("_args") or {}
        if all(call_args.get(k) == v for k, v in args.items()):
            result = wrapped.get("_result")
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except ValueError:
                    result = {"error": result}
            return result if isinstance(result, dict) else {"error": f"unexpected result: {str(result)[:100]}"}
    return None


_CPTAC_TEXT = [
    (re.compile(r"Significantly higher expressed in tumor \(p=([^)]+)\)"), 1),
    (re.compile(r"Significantly lower expressed in tumor \(p=([^)]+)\)"), -1),
    (re.compile(r"No significant difference between tumor and normal \(p=([^)]+)\)"), None),
    (re.compile(r"Higher expression associated with poor survival \(p=([^)]+)\)"), 1),
    (re.compile(r"Lower expression associated with poor survival \(p=([^)]+)\)"), -1),
    (re.compile(r"No significant association with survival \(p=([^)]+)\)"), None),
]


def _cptac_lines(line: str, result: Optional[Dict[str, Any]], cancer: str) -> List[Dict[str, Any]]:
    """Tumor vs normal or survival from the CPTAC tools' per-cancer sentences."""
    out = []
    for key, layer in (("protein_level", "protein"), ("RNA_level", "RNA")):
        if _is_error(result):
            out.append(_failed(line, "CPTAC", layer, result))
            continue
        text = ((result.get(key) or {}).get("data") or {}).get(cancer)
        if not text or text == "Data unavailable":
            out.append(_no_data(line, "CPTAC", layer, cancer))
            continue
        for pattern, direction in _CPTAC_TEXT:
            match = pattern.fullmatch(text)
            if match:
                out.append(_line(line, "CPTAC", layer, "tested", direction=direction, p=float(match.group(1))))
                break
        else:
            out.append(_failed(line, "CPTAC", layer, {"error": f"unrecognized result: {text}"}))
    return out


def _cptac_copy_number(result: Optional[Dict[str, Any]], cancer: str) -> List[Dict[str, Any]]:
    out = []
    records = ((result or {}).get("data") or {}).get(cancer) or []
    for layer in ("protein", "RNA"):
        if _is_error(result):
            out.append(_failed("copy_number", "CPTAC", layer, result))
            continue
        record = next((r for r in records if {r.get("x"), r.get("y")} == {"SCNV", layer}), None)
        if record is None:
            out.append(_no_data("copy_number", "CPTAC", layer, cancer))
            continue
        r, p = float(record["val"]), float(record["pval"])
        out.append(_line("copy_number", "CPTAC", layer, "tested", direction=(1 if r > 0 else -1) if p < 0.05 else None,
                         effect=r, effect_name="r", p=p))
    return out


def _tcga_copy_number(result: Optional[Dict[str, Any]], layer: str) -> Dict[str, Any]:
    if _is_error(result):
        return _failed("copy_number", "TCGA", layer, result)
    rows = result.get("results") or []
    if not rows:
        return _line("copy_number", "TCGA", layer, "no_data", note="No data for this gene")
    r, p = float(rows[0]["correlation"]), float(rows[0]["pvalue"])
    return _line("copy_number", "TCGA", layer, "tested", direction=(1 if r > 0 else -1) if p < 0.05 else None,
                 effect=r, effect_name="r", p=p, n=rows[0].get("n"))


def _tcga_survival(result: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One line per TCGA layer; RNA and protein (RPPA) are always listed, as no data when missing."""
    if _is_error(result):
        return [_failed("survival", "TCGA", layer, result) for layer in ("RNA", "protein (RPPA)")]
    by_layer = {_TCGA_LAYERS[r["omics"]]: r for r in result.get("results") or [] if r.get("omics") in _TCGA_LAYERS}
    out = []
    for layer in _TCGA_LAYERS.values():
        row = by_layer.get(layer)
        if row is None:
            if layer in ("RNA", "protein (RPPA)"):
                out.append(_line("survival", "TCGA", layer, "no_data", note="No data for this gene"))
            continue
        if row.get("error"):
            # One layer can fail inside a good result, most often for too few samples (ovarian methylation)
            enough = "Too few samples" not in str(row["error"])
            out.append(_line("survival", "TCGA", layer, "failed" if enough else "no_data",
                             note=str(row["error"])[-200:] if enough else "Too few samples for this layer"))
            continue
        hr, p = float(row["hr"]), float(row["pvalue"])
        # HR > 1: the higher group has poorer survival
        out.append(_line("survival", "TCGA", layer, "tested", direction=(1 if hr > 1 else -1) if p < 0.05 else None,
                         effect=hr, effect_name="HR", p=p, n=row.get("n")))
    return out


def _dependency(profile: Optional[Dict[str, Any]], cancer: str) -> Dict[str, Any]:
    if _is_error(profile):
        return _failed("dependency", "LinkedOmics Targets", "cell lines", profile)
    if cancer in SOURCE_GAPS[("dependency", "cell lines")][0]:
        return _no_data("dependency", "LinkedOmics Targets", "cell lines", cancer)
    text = (profile.get("result") or profile).get("cell_line_dependency") or ""
    dependent = [c.strip() for c in text.split(":", 1)[1].split(",")] if text.startswith("Dependent cell lines:") else []
    return _line("dependency", "LinkedOmics Targets", "cell lines", "tested", direction=1 if cancer in dependent else None,
                 note=f"Dependent in {len(dependent)} of {_DEPENDENCY_COHORTS} cancers with cell-line data")


def _targets_calls(profile: Optional[Dict[str, Any]], cancer: str) -> List[Dict[str, Any]]:
    """LinkedOmics Targets' own calls for this cancer (Savage et al., Cell 2024): protein overexpressed
    in tumors (tumor vs normal Wilcoxon test), and copy-number driver (amplified by GISTIC2, and copy
    number correlating with both protein and mRNA, Spearman p < 0.01)."""
    calls = (("tumor_vs_normal", "overexpressed (call)", "tumor_overexpression", "Overexpressed in "),
             ("copy_number", "driver (call)", "cnv_driver", "CNV driver in: "))
    if _is_error(profile):
        return [_failed(line, "LinkedOmics Targets", layer, profile) for line, layer, _, _ in calls]
    info = profile.get("result") or profile
    out = []
    for line, layer, field, prefix in calls:
        if line == "tumor_vs_normal" and cancer in SOURCE_GAPS[("tumor_vs_normal", "protein")][0]:
            out.append(_no_data(line, "LinkedOmics Targets", layer, cancer, ("tumor_vs_normal", "protein")))
            continue
        text = str(info.get(field) or "")
        listed = [c.strip() for c in text[len(prefix):].split(",")] if text.startswith(prefix) else []
        out.append(_line(line, "LinkedOmics Targets", layer, "tested", direction=1 if cancer in listed else None,
                         note=text))
    return out


def _trial_studies(trials_cancer: Optional[str]) -> List[Dict[str, Any]]:
    """The trial-linked studies for a cancer, from treatment response matching's cache."""
    if not trials_cancer:
        return []
    from mcp_servers import signature_matching
    try:
        studies = json.loads(signature_matching.STUDIES_PATH.read_text())["studies"]
    except (OSError, ValueError, KeyError):
        return []
    studies = studies.values() if isinstance(studies, dict) else studies
    return [s for s in studies if s.get("disease") == trials_cancer]


def _treatment_response(result: Optional[Dict[str, Any]], cancer: str, studies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One line per study in this cancer where the gene's expression went with response."""
    _, trials_cancer = COHORTS[cancer]
    if trials_cancer is None:
        return [_line("treatment_response", "LinkedOmics Trials", "RNA", "no_data",
                      note="No trial-linked study for this cancer")]
    if _is_error(result):
        return [_failed("treatment_response", "LinkedOmics Trials", "RNA", result)]
    data = result.get("data") or {}
    out = []
    for side, direction in (("sensitive", 1), ("resistant", -1)):
        for study in data.get(side) or []:
            if study.get("disease") != trials_cancer:
                continue
            out.append(_line("treatment_response", "LinkedOmics Trials", "RNA", "tested", direction=direction,
                             effect=study.get("auroc"), effect_name="AUROC", p=abs(float(study["p_value"])),
                             n=int(study["sample_size"]) if str(study.get("sample_size", "")).isdigit() else None,
                             note=f"{study.get('treatment')} ({study.get('study_id')})"))
    if not out:
        out.append(_line("treatment_response", "LinkedOmics Trials", "RNA", "tested",
                         note=f"No significant link in {len(studies) or 'any'} {trials_cancer.lower()} studies"))
    return out


# The lines a question's verdict rests on; cell-line dependency and treatment response are context
RATED_LINES = {"target": ("tumor_vs_normal", "copy_number", "survival"), "prognostic": ("survival",)}
# Layers measuring the gene's own level count; survival by methylation or copy number is shown, not rated
_RATED_LAYERS = {"protein", "RNA", "protein (RPPA)"}
_PROTEIN_LAYERS = {"protein", "protein (RPPA)"}


def rate_line(lines: List[Dict[str, Any]], line: str, question: str) -> Dict[str, Any]:
    """Rate survival (or any line without a LinkedOmics Targets call) from its layers' significant results.

    strong: significant in the same direction in both CPTAC and TCGA; moderate: p < 0.01 in one
    source only; weak: p < 0.05 in one source only; against: significant only in the opposite
    direction; mixed: both. For a prognostic marker either direction is a marker, so significant
    results in opposite directions make the line mixed. For a target, only higher levels with
    poorer survival count; better survival is no argument against a target, since patients whose
    tumors carry an established one are often treated for it (HER2-positive breast cancer).
    """
    layers = [l for l in lines if l["line"] == line and l["layer"] in _RATED_LAYERS]
    tested = [l for l in layers if l["status"] == "tested"]
    rating: Dict[str, Any] = {"line": line, "direction": None, "sources": [], "protein": False, "best_p": None}
    if not tested:
        return {**rating, "rating": "failed" if any(l["status"] == "failed" for l in layers) else "no_data"}
    significant = [l for l in tested if l["significant"] and l["direction"]]
    if question == "target":
        significant = [l for l in significant if l["direction"] == 1]
    if not significant:
        return {**rating, "rating": "no_association"}
    if question == "prognostic" and len({l["direction"] for l in significant}) > 1:
        return {**rating, "rating": "mixed"}
    support = [l for l in significant if question == "prognostic" or l["direction"] == 1]
    if len(support) < len(significant):
        return {**rating, "rating": "mixed" if support else "against"}
    sources = sorted({l["source"] for l in support})
    best_p = min(l["p"] for l in support)
    if len(sources) >= 2:
        value = "strong"
    else:
        value = "moderate" if best_p < 0.01 else "weak"
    return {**rating, "rating": value, "direction": support[0]["direction"], "sources": sources,
            "protein": any(l["layer"] in _PROTEIN_LAYERS for l in support), "best_p": best_p}


def _rate_called_line(lines: List[Dict[str, Any]], line: str) -> Dict[str, Any]:
    """Tumor vs normal or copy number for a target, led by LinkedOmics Targets' call. In cohorts this
    size most genes reach p < 0.05 on both: on 2026-11-19 copy number alone rated strong for 7 of 20
    random genes, while 0 of the 20 were called copy-number drivers and 1 was called overexpressed.

    strong: the call, confirmed by an independent test (CPTAC RNA higher in tumor; TCGA copy number
    raising RNA); moderate: the call alone; weak: tumor vs normal significant without the call (copy
    number moves most genes' levels, so it counts only with the call); against: protein
    significantly lower in tumor.
    """
    rating: Dict[str, Any] = {"line": line, "direction": None, "sources": [], "protein": False, "best_p": None}
    group = [l for l in lines if l["line"] == line]
    call = next((l for l in group if l["source"] == "LinkedOmics Targets"), None)
    tests = [l for l in group if l["source"] != "LinkedOmics Targets" and l["status"] == "tested"]
    up = [l for l in tests if l["significant"] and l["direction"] == 1]
    if line == "tumor_vs_normal" and any(l["layer"] == "protein" and l["significant"] and l["direction"] == -1 for l in tests):
        return {**rating, "rating": "against"}
    if call is not None and call["status"] == "failed":
        return {**rating, "rating": "failed"}
    if call is not None and call["status"] == "tested" and call["direction"] == 1:
        confirm = ("CPTAC", "RNA") if line == "tumor_vs_normal" else ("TCGA", "RNA")
        confirmed = [l for l in up if (l["source"], l["layer"]) == confirm]
        return {**rating, "rating": "strong" if confirmed else "moderate", "direction": 1,
                "sources": ["LinkedOmics Targets"] + [l["source"] for l in confirmed], "protein": True,
                "best_p": min((l["p"] for l in up), default=None)}
    if line == "tumor_vs_normal" and up:
        return {**rating, "rating": "weak", "direction": 1, "sources": sorted({l["source"] for l in up}),
                "protein": any(l["layer"] in _PROTEIN_LAYERS for l in up), "best_p": min(l["p"] for l in up)}
    if (call is None or call["status"] != "tested") and not tests:
        return {**rating, "rating": "failed" if any(l["status"] == "failed" for l in group) else "no_data"}
    return {**rating, "rating": "no_association"}


def verdict(ratings: List[Dict[str, Any]], question: str) -> str:
    """The report's verdict from its rated lines: strong, moderate, limited, mixed, against, none,
    or insufficient_data. A target needs data on at least two of its three lines."""
    values = [r["rating"] for r in ratings]
    if question == "prognostic":
        return {"strong": "strong", "moderate": "moderate", "weak": "limited", "mixed": "mixed",
                "no_association": "none"}.get(values[0], "insufficient_data")
    with_data = [v for v in values if v not in ("no_data", "failed")]
    if len(with_data) < 2:
        return "insufficient_data"
    support = [v for v in with_data if v in ("strong", "moderate", "weak")]
    against = [v for v in with_data if v in ("against", "mixed")]
    if against:
        return "mixed" if support else "against"
    if with_data.count("strong") >= 2:
        return "strong"
    if "strong" in with_data or with_data.count("moderate") >= 2:
        return "moderate"
    return "limited" if support else "none"


def rate(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """The evidence with each rated line's rating and the verdict added."""
    question = evidence["question"]
    ratings = [
        _rate_called_line(evidence["lines"], line) if question == "target" and line != "survival"
        else rate_line(evidence["lines"], line, question)
        for line in RATED_LINES[question]
    ]
    return {**evidence, "ratings": ratings, "verdict": verdict(ratings, question)}


def extract_evidence(gene: str, cancer: str, question: str, tool_results: Dict[str, Any]) -> Dict[str, Any]:
    """Turn the investigation's tool results ({"tool_id#n": {"_args", "_result"}}) into lines of evidence."""
    tcga, trials_cancer = COHORTS[cancer]
    get = lambda tool, **args: _find(tool_results, f"linkedomics::{tool}", **args)
    studies = _trial_studies(trials_cancer)
    lines: List[Dict[str, Any]] = []
    context: Dict[str, Any] = {"trial_studies": len(studies)}

    if question == "target":
        profile = get("get_drug_target_profile")
        lines += _targets_calls(profile, cancer)
        lines += _cptac_lines("tumor_vs_normal", get("compare_cptac_tumor_normal_expression"), cancer)
        lines += _cptac_copy_number(get("analyze_cptac_cis_associations"), cancer)
        lines.append(_tcga_copy_number(get("analyze_tcga_cis_associations", target_omics="RNAseq"), "RNA"))
        lines.append(_tcga_copy_number(get("analyze_tcga_cis_associations", target_omics="RPPA"), "protein (RPPA)"))
    lines += _cptac_lines("survival", get("analyze_cptac_gene_survival_associations"), cancer)
    lines += _tcga_survival(get("analyze_tcga_survival_associations"))
    if question == "target":
        lines.append(_dependency(profile, cancer))
        info = (profile or {}).get("result") or profile or {}
        drugs = [d.strip() for d in str(info.get("drugs") or "").split(";") if d.strip()]
        tiers = [t.strip() for t in str(info.get("drug_tiers") or "").split(";")]
        context["clinical_status"] = {"tier": info.get("tier"), "drugs": [
            {"name": name, "tier": tiers[i] if i < len(tiers) else None} for i, name in enumerate(drugs)]}
        names = {d.lower() for d in drugs}
        context["studies_of_its_drugs"] = [
            s.get("study_id") for s in studies
            if names & {t.strip().lower() for t in str(s.get("treatment") or "").split(",")}
        ]
        neighbors = get("get_funmap_functional_neighborhood") or {}
        context["neighbors"] = list(neighbors.get("neighborhood") or [])[:10]
    lines += _treatment_response(get("search_gene_response_trials"), cancer, studies)
    return {"gene": gene, "cancer": cancer, "tcga_cohort": tcga, "trials_cancer": trials_cancer,
            "question": question, "lines": lines, "context": context}
