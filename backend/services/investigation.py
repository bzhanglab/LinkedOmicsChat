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


def _failed(line: str, source: str, layer: str, result: Dict[str, Any]) -> Dict[str, Any]:
    return _line(line, source, layer, "failed", note=str(result.get("error"))[:200])


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
        if result is None or "error" in result:
            out.append(_failed(line, "CPTAC", layer, result or {"error": "not run"}))
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
        if result is None or "error" in result:
            out.append(_failed("copy_number", "CPTAC", layer, result or {"error": "not run"}))
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
    if result is None or "error" in result:
        return _failed("copy_number", "TCGA", layer, result or {"error": "not run"})
    rows = result.get("results") or []
    if not rows:
        return _line("copy_number", "TCGA", layer, "no_data", note="No data for this gene")
    r, p = float(rows[0]["correlation"]), float(rows[0]["pvalue"])
    return _line("copy_number", "TCGA", layer, "tested", direction=(1 if r > 0 else -1) if p < 0.05 else None,
                 effect=r, effect_name="r", p=p, n=rows[0].get("n"))


def _tcga_survival(result: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One line per TCGA layer; RNA and protein (RPPA) are always listed, as no data when missing."""
    if result is None or "error" in result:
        return [_failed("survival", "TCGA", layer, result or {"error": "not run"}) for layer in ("RNA", "protein (RPPA)")]
    by_layer = {_TCGA_LAYERS[r["omics"]]: r for r in result.get("results") or [] if r.get("omics") in _TCGA_LAYERS}
    out = []
    for layer in _TCGA_LAYERS.values():
        row = by_layer.get(layer)
        if row is None:
            if layer in ("RNA", "protein (RPPA)"):
                out.append(_line("survival", "TCGA", layer, "no_data", note="No data for this gene"))
            continue
        hr, p = float(row["hr"]), float(row["pvalue"])
        # HR > 1: the higher group has poorer survival
        out.append(_line("survival", "TCGA", layer, "tested", direction=(1 if hr > 1 else -1) if p < 0.05 else None,
                         effect=hr, effect_name="HR", p=p, n=row.get("n")))
    return out


def _dependency(profile: Optional[Dict[str, Any]], cancer: str) -> Dict[str, Any]:
    if profile is None or "error" in profile:
        return _failed("dependency", "LinkedOmics Targets", "cell lines", profile or {"error": "not run"})
    if cancer in SOURCE_GAPS[("dependency", "cell lines")][0]:
        return _no_data("dependency", "LinkedOmics Targets", "cell lines", cancer)
    text = (profile.get("result") or profile).get("cell_line_dependency") or ""
    dependent = [c.strip() for c in text.split(":", 1)[1].split(",")] if text.startswith("Dependent cell lines:") else []
    return _line("dependency", "LinkedOmics Targets", "cell lines", "tested", direction=1 if cancer in dependent else None,
                 note=f"Dependent in {len(dependent)} of {_DEPENDENCY_COHORTS} cancers with cell-line data")


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
    if result is None or "error" in result:
        return [_failed("treatment_response", "LinkedOmics Trials", "RNA", result or {"error": "not run"})]
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


def extract_evidence(gene: str, cancer: str, question: str, tool_results: Dict[str, Any]) -> Dict[str, Any]:
    """Turn the investigation's tool results ({"tool_id#n": {"_args", "_result"}}) into lines of evidence."""
    tcga, trials_cancer = COHORTS[cancer]
    get = lambda tool, **args: _find(tool_results, f"linkedomics::{tool}", **args)
    studies = _trial_studies(trials_cancer)
    lines: List[Dict[str, Any]] = []
    context: Dict[str, Any] = {"trial_studies": len(studies)}

    if question == "target":
        lines += _cptac_lines("tumor_vs_normal", get("compare_cptac_tumor_normal_expression"), cancer)
        lines += _cptac_copy_number(get("analyze_cptac_cis_associations"), cancer)
        lines.append(_tcga_copy_number(get("analyze_tcga_cis_associations", target_omics="RNAseq"), "RNA"))
        lines.append(_tcga_copy_number(get("analyze_tcga_cis_associations", target_omics="RPPA"), "protein (RPPA)"))
    lines += _cptac_lines("survival", get("analyze_cptac_gene_survival_associations"), cancer)
    lines += _tcga_survival(get("analyze_tcga_survival_associations"))
    if question == "target":
        profile = get("get_drug_target_profile")
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
