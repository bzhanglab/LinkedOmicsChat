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

# TCGA protein (RPPA) is left out: on 2026-11-19 the TCGA service returned identical RPPA values for
# unrelated genes (18 of 48 in breast cancer, in 3 groups: ESR1, ERBB2, MET, MTOR and 8 more share one),
# apparently matching genes to the wrong probe. RNA showed no such collisions.
_TCGA_LAYERS = {"RNAseq": "RNA", "Methylation": "methylation", "SCNA": "copy number"}


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
    """One line per TCGA layer; RNA is always listed, as no data when missing."""
    if _is_error(result):
        return [_failed("survival", "TCGA", "RNA", result)]
    by_layer = {_TCGA_LAYERS[r["omics"]]: r for r in result.get("results") or [] if r.get("omics") in _TCGA_LAYERS}
    out = []
    for layer in _TCGA_LAYERS.values():
        row = by_layer.get(layer)
        if row is None:
            if layer == "RNA":
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
                             note=f"{', '.join(str(study.get('treatment') or '').split(','))} "
                                  f"({str(study.get('study_id') or '').removesuffix('.csv')})"))
    if not out:
        n = len(studies)
        out.append(_line("treatment_response", "LinkedOmics Trials", "RNA", "tested",
                         note=f"No significant link in {n or 'any'} {trials_cancer.lower()} stud{'y' if n == 1 else 'ies'}"))
    return out


# The lines a question's verdict rests on; cell-line dependency and treatment response are context
RATED_LINES = {"target": ("tumor_vs_normal", "copy_number", "survival"), "prognostic": ("survival",)}
# Layers measuring the gene's own level count; survival by methylation or copy number is shown, not rated
_RATED_LAYERS = {"protein", "RNA"}
_PROTEIN_LAYERS = {"protein"}


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
        # Kept for the label: a significant result in the other direction is no support, not no result
        rating["opposite"] = any(l["direction"] == -1 for l in significant)
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


# ── Requests and the written report ───────────────────────────────────────────

CANCER_NAMES = {
    "BRCA": "breast cancer", "CCRCC": "clear cell renal cell carcinoma", "COAD": "colon cancer",
    "GBM": "glioblastoma", "HNSCC": "head and neck squamous cell carcinoma",
    "LSCC": "lung squamous cell carcinoma", "LUAD": "lung adenocarcinoma", "OV": "ovarian cancer",
    "PDAC": "pancreatic ductal adenocarcinoma", "UCEC": "endometrial cancer",
}
_CANCER_ALIASES = {
    "BRCA": ("breast", "breast cancer", "breast invasive carcinoma"),
    "CCRCC": ("kirc", "kidney", "kidney cancer", "renal cell carcinoma", "clear cell renal cell carcinoma",
              "kidney renal clear cell carcinoma"),
    "COAD": ("colon", "colon cancer", "colon adenocarcinoma", "colorectal cancer", "coadread"),
    "GBM": ("glioblastoma", "glioblastoma multiforme"),
    "HNSCC": ("hnsc", "head and neck", "head and neck cancer", "head and neck squamous cell carcinoma"),
    "LSCC": ("lusc", "lung squamous", "lung squamous cell carcinoma", "squamous cell lung cancer"),
    "LUAD": ("lung adeno", "lung adenocarcinoma"),
    "OV": ("ovarian", "ovarian cancer", "ovarian serous carcinoma"),
    "PDAC": ("paad", "pancreatic", "pancreatic cancer", "pancreatic ductal adenocarcinoma"),
    "UCEC": ("uterine", "uterine cancer", "endometrial", "endometrial cancer", "uterine corpus endometrial carcinoma"),
}
_CANCER_LOOKUP = {
    re.sub(r"[^a-z0-9]", "", alias.lower()): code
    for code, aliases in _CANCER_ALIASES.items() for alias in (code, *aliases)
}
# "Investigate CDK4 as a drug target in breast cancer", "Investigate SPP1 as a prognostic marker in LUAD"
_REQUEST_RE = re.compile(
    r"^\s*investigate\s+(?P<gene>[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?)\s+as\s+(?:an?\s+)?"
    r"(?P<question>(?:drug\s+)?target|prognostic\s+(?:bio)?marker)\s+in\s+(?P<cancer>.+?)\s*[.?!]?\s*$",
    re.IGNORECASE,
)


def parse_request(query: str) -> Optional[Dict[str, Any]]:
    """The gene, question and cancer an investigation request names, or None when the query is not
    one. "cancer" is None when the cancer is not one of the 10 covered."""
    match = _REQUEST_RE.match(query or "")
    if not match:
        return None
    cancer = _CANCER_LOOKUP.get(re.sub(r"[^a-z0-9]", "", match.group("cancer").lower()))
    question = "prognostic" if match.group("question").lower().startswith("prognostic") else "target"
    return {"gene": match.group("gene").upper(), "question": question, "cancer": cancer}


_CANCER_MENTIONS = sorted(
    ((alias.lower(), code) for code, aliases in _CANCER_ALIASES.items() for alias in (code, *aliases)),
    key=lambda item: -len(item[0]),
)
_TARGET_WORDS = re.compile(r"\b(?:target\w*|druggable|inhibitors?|drugs?|therap(?:y|ies|eutic))\b", re.IGNORECASE)
_PROGNOSTIC_WORDS = re.compile(r"\b(?:surviv\w*|prognos\w*|outcomes?|hazard)\b", re.IGNORECASE)


def _mentioned_cancer(text: str) -> Optional[str]:
    """The one covered cancer a question names, or None when it names none or several."""
    lowered = (text or "").lower()
    codes = {code for alias, code in _CANCER_MENTIONS
             if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lowered)}
    return codes.pop() if len(codes) == 1 else None


def offer_request(query: str, genes: List[str]) -> Optional[str]:
    """The investigation to offer under an ordinary answer: one gene, one covered cancer, and a target
    or survival question. Returns the request text, which parse_request reads back."""
    cancer = _mentioned_cancer(query)
    if len(genes) != 1 or cancer is None:
        return None
    if _TARGET_WORDS.search(query or ""):
        asked = "a drug target"
    elif _PROGNOSTIC_WORDS.search(query or ""):
        asked = "a prognostic marker"
    else:
        return None
    return f"Investigate {genes[0]} as {asked} in {CANCER_NAMES[cancer]}"


def unsupported_cancer_message(gene: str, question: str) -> str:
    covered = ", ".join(f"{name} ({code})" for code, name in CANCER_NAMES.items())
    example = f"Investigate {gene} as {'a prognostic marker' if question == 'prognostic' else 'a drug target'} in breast cancer"
    return (f"Investigation mode covers 10 cancers, each in both CPTAC and TCGA: {covered}. "
            f"Name one of them, for example \"{example}\".")


_RATING_LABELS = {"strong": "Strong", "moderate": "Moderate", "weak": "Weak", "against": "Against", "mixed": "Mixed",
                  "no_association": "No association", "no_data": "No data", "failed": "Failed"}
_VERDICT_LABELS = {"strong": "Strong", "moderate": "Moderate", "limited": "Limited", "mixed": "Mixed",
                   "against": "Against", "none": "None found", "insufficient_data": "Insufficient data"}
_SHORT_LABELS = {"tumor_vs_normal": "tumor vs normal", "copy_number": "copy number", "survival": "survival"}
_LINE_LABELS = {
    "tumor_vs_normal": "Higher in tumor than normal",
    "copy_number": "Driven by its own copy number",
    "survival": "Higher levels, poorer survival",
    "dependency": "Cancer cell lines depend on it",
    "treatment_response": "Treatment response in trials",
}


def _p(p: float) -> str:
    """ "p = 0.033", or "p ≈ 0" where the source rounds a tiny p-value to 0."""
    return "p ≈ 0" if p == 0 else f"p = {p:.1e}" if p < 0.001 else f"p = {p:.2g}"


def _result_text(l: Dict[str, Any]) -> str:
    """One result as the report's table shows it, e.g. "TCGA RNA: r = 0.24, p = 1.7e-15, n = 1,075"."""
    source = l["source"] if l["source"] != "LinkedOmics Targets" or l["line"] == "dependency" else "LinkedOmics Targets call"
    where = source if l["source"] == "LinkedOmics Trials" or "call" in l["layer"] or l["line"] == "dependency" else f"{source} {l['layer']}"
    if l["status"] == "failed":
        return f"{where}: failed"
    if l["status"] == "no_data":
        reason = "too few samples" if "Too few" in l["note"] else "no data for this cancer" if "this cancer" in l["note"] else "no data for this gene"
        return f"{where}: {reason}"
    up, down = l["direction"] == 1, l["direction"] == -1
    if "call" in l["layer"]:
        called = "overexpressed in tumor" if l["line"] == "tumor_vs_normal" else "a copy-number driver"
        return f"{where}: {'called' if up else 'not called'} {called}"
    if l["line"] == "dependency":
        return f"{where}: {'dependent' if up else 'not dependent'} here ({l['note'][0].lower() + l['note'][1:]})"
    if l["line"] == "treatment_response":
        if l["p"] is None:
            return l["note"]
        return (f"{'higher level, better' if up else 'higher level, worse'} response to {l['note']}: "
                f"AUROC {l['effect']:.2f}, {_p(l['p'])}" + (f", n = {l['n']:,}" if l["n"] else ""))
    stats = []
    if l["effect"] is not None:
        stats.append(f"{l['effect_name']} {'= ' if l['effect_name'] == 'r' else ''}{l['effect']:.2f}")
    stats.append(_p(l["p"]))
    if l["n"]:
        stats.append(f"n = {l['n']:,}")
    if l["effect"] is None:
        words = {
            "tumor_vs_normal": ("higher in tumor", "lower in tumor", "no difference"),
            "survival": ("higher level, poorer survival", "higher level, better survival", "no association"),
        }[l["line"]]
        stats.insert(0, words[0] if up else words[1] if down else words[2])
    return f"{where}: {', '.join(stats)}"


def _rating_text(rating: Dict[str, Any]) -> str:
    # Copy number moves most genes' levels, so a gene without the driver call is "not a driver",
    # which reads right beside significant correlations; "no association" would not
    if rating["line"] == "copy_number" and rating["rating"] == "no_association":
        return "Not a driver"
    if rating.get("opposite") and rating["rating"] == "no_association":
        return "No support (higher levels, better survival)"
    return _RATING_LABELS[rating["rating"]]


def _rows(evidence: Dict[str, Any]) -> List[Tuple[str, List[Dict[str, Any]], str]]:
    """The report table's rows: label, results, rating. Rated lines first, then context."""
    question, lines = evidence["question"], evidence["lines"]
    rows = []
    for rating in evidence["ratings"]:
        group = [l for l in lines if l["line"] == rating["line"]
                 and (l["line"] != "survival" or l["layer"] in _RATED_LAYERS)]
        label = _LINE_LABELS[rating["line"]] if question == "target" else "Levels linked to survival"
        text = _rating_text(rating) if question == "target" else _RATING_LABELS[rating["rating"]]
        if question == "prognostic" and rating["direction"]:
            text += f" ({'higher level, poorer' if rating['direction'] == 1 else 'higher level, better'} survival)"
        rows.append((label, group, text))
    if question == "prognostic":
        other = [l for l in lines if l["line"] == "survival" and l["layer"] not in _RATED_LAYERS]
        if other:
            rows.append(("Survival by methylation or copy number", other, "Context"))
    for line in ("dependency", "treatment_response"):
        group = [l for l in lines if l["line"] == line]
        if group:
            rows.append((_LINE_LABELS[line], group, "Context"))
    return rows


def _verdict_reason(evidence: Dict[str, Any]) -> str:
    ratings, cancer = evidence["ratings"], CANCER_NAMES[evidence["cancer"]]
    if evidence["question"] == "prognostic":
        rating = ratings[0]
        if rating["direction"]:
            return (f"Higher levels go with {'poorer' if rating['direction'] == 1 else 'better'} survival, "
                    f"in {' and '.join(rating['sources'])}.")
        return {"mixed": "CPTAC and TCGA disagree on the direction.",
                "no_association": "No layer is significantly linked to survival."}.get(
            rating["rating"], f"Neither CPTAC nor TCGA has survival data for this gene in {cancer}.")
    with_data = sum(r["rating"] not in ("no_data", "failed") for r in ratings)
    if evidence["verdict"] == "insufficient_data":
        return f"Only {with_data} of the 3 rated lines {'has' if with_data == 1 else 'have'} data for {cancer}."
    text = "; ".join(f"{_SHORT_LABELS[r['line']]}: {_rating_text(r).lower()}" for r in ratings) + "."
    return text[0].upper() + text[1:]


def report_markdown(evidence: Dict[str, Any]) -> str:
    """The investigation's report: verdict, evidence table, gaps and clinical status. Built from the
    ratings alone, so the written summary cannot change what it shows."""
    gene, cancer, question = evidence["gene"], evidence["cancer"], evidence["question"]
    asked = "a prognostic marker" if question == "prognostic" else "a drug target"
    out = [
        f"## Investigation: {gene} as {asked} in {CANCER_NAMES[cancer]} ({cancer})",
        "",
        f"**Support in these data: {_VERDICT_LABELS[evidence['verdict']]}.** {_verdict_reason(evidence)}",
        "",
        "| Evidence | Results | Rating |",
        "|---|---|---|",
    ]
    for label, group, rating in _rows(evidence):
        out.append(f"| {label} | {'; '.join(_result_text(l) for l in group)} | {rating} |")
    gaps = sorted({l["note"].replace("this cancer", CANCER_NAMES[cancer]) for l in evidence["lines"]
                   if l["status"] == "no_data" and "this cancer" in l["note"]})
    if gaps:
        out += ["", "**Gaps:** " + " ".join(f"{gap}." for gap in gaps)]
    status = evidence["context"].get("clinical_status")
    if status:
        approved = [d["name"] for d in status["drugs"] if d["tier"] == "T1"]
        others = len(status["drugs"]) - len(approved)
        drugs = (f"approved oncology drugs {', '.join(approved)}" if approved else "no approved oncology drug")
        drugs += f"; {others} other drug{'s' if others != 1 else ''} in its LinkedOmics Targets profile" if others else ""
        studied = [str(s).removesuffix(".csv") for s in evidence["context"].get("studies_of_its_drugs") or []]
        listed = ", ".join(studied[:3]) + (f" and {len(studied) - 3} more" if len(studied) > 3 else "")
        trials = (f" Trial-linked studies of these drugs in {CANCER_NAMES[cancer]}: {listed}." if studied
                  else f" No trial-linked study tested them in {CANCER_NAMES[cancer]}." if evidence["trials_cancer"] else "")
        out += ["", f"**Clinical status** (not rated): tier {status['tier'] or 'none'}; {drugs}.{trials}"]
    out += ["", "_Ratings follow fixed rules and cover only these resources. A strong rating means consistent "
                "signals across sources, not proof of clinical value._"]
    return "\n".join(out)


def summary_prompt(evidence: Dict[str, Any]) -> str:
    """What the summary step is asked to write: the verdict and the evidence for and against, from
    the ratings, which it may not change."""
    gene, cancer = evidence["gene"], CANCER_NAMES[evidence["cancer"]]
    asked = "a prognostic marker" if evidence["question"] == "prognostic" else "a drug target"
    rows = "\n".join(f"- {label}: {rating}. {'; '.join(_result_text(l) for l in group)}"
                     for label, group, rating in _rows(evidence))
    status = evidence["context"].get("clinical_status")
    clinical = f"\nClinical status (not rated): tier {status['tier']}; drugs: {', '.join(d['name'] for d in status['drugs'][:8])}." if status else ""
    return f"""Investigation of {gene} as {asked} in {cancer}. The app has rated each line of evidence with fixed rules; the ratings and the verdict are final.

Verdict: Support in these data: {_VERDICT_LABELS[evidence['verdict']]}. {_verdict_reason(evidence)}
Lines of evidence (label: rating. results):
{rows}{clinical}

Write the summary of this investigation from these ratings only, with no headings and no numbered items. Start with one sentence that states the verdict as "Support in these data: {_VERDICT_LABELS[evidence['verdict']].lower()}" and gives the main reason. Then write three bullets, each one or two sentences citing at most two numbers (the table shows the rest):
- **For:** the lines rated Strong, Moderate or Weak, or "none".
- **Against:** the lines rated Against or Mixed, or "none". A line rated No association or Not a driver is neither for nor against: it found no support.
- **Gaps:** the lines rated No data or Failed, saying "no data for {cancer}" where the results say so. A single layer missing for this gene, or a Context line, is not a gap.
End with one sentence saying the verdict covers only what these resources show.

Rules: never change, raise or soften a rating, and never rate anything yourself. Lines marked Context are not rated; mention them only as context. Do not explain the rating rules or these instructions, and do not list what you leave out. Use only the numbers above. Do not discuss other cancers. Use **bold** for gene names and statistics. Do not offer a follow-up analysis."""


def ratings_text(evidence: Dict[str, Any]) -> str:
    """The rated lines as plain text, for the number check: the summary's numbers come from here."""
    return "\n".join(_result_text(l) for l in evidence["lines"])
