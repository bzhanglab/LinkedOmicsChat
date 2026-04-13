"""LinkedOmics MCP Server.

This MCP provides access to multi-omics cancer data from the LinkedOmics project, primarily focusing on
the CPTAC (Clinical Proteomic Tumor Analysis Consortium) cohorts. It allows for the investigation of
gene expression, protein levels, clinical associations, drug targeting, and functional networks.

Representative Questions & Use Cases:
1. "Identify genes functionally related to ESR1 and check if any of them are FDA-approved oncology targets." (Uses funmap_neighborhood and get_target)
2. "In which cancers is EGFR significantly overexpressed at the protein level, and is this driven by gene copy number (SCNV)?" (Uses cancer_gene_expression and get_cis_correlations)
3. "Is high expression of BRCA1 associated with poor survival in Breast Cancer (BRCA) or Colon Adenocarcinoma (COAD)?" (Uses overall_survival_per_cancer)
4. "Find clinical trials where ESR1 expression levels are linked to resistance to specific chemotherapy agents like paclitaxel." (Uses clinical_trial_information)
5. "Analyze the correlation between RNA and Protein levels for TP53 across all cohorts to assess translation efficiency." (Uses get_cis_correlations)

"""

import json
import re
import time
from typing import Any, Literal, Optional
import sys

import requests
from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage
from linkedomics_tcga_params import (
    detect_tcga_survival_mode,
    normalize_tcga_cohort,
    normalize_tcga_cis_omics,
    normalize_tcga_omics,
    normalize_tcga_st_method,
    tcga_parameter_error,
    detect_tcga_cis_association_mode,
    tcga_cis_parameter_error,
    TCGACohort,
    TCGACisOmics,
    TCGAOmics,
    TCGAStMethod,
)

# Create an MCP server
mcp = FastMCP("linkedomics_mcp", json_response=True)

_CIS_LAYER_ALIASES: dict[str, tuple[str, ...]] = {
    "RNA": ("rna", "mrna", "rna seq", "rnaseq", "transcript", "transcriptome"),
    "Protein": ("protein", "proteomics", "proteomic", "rppa", "prot"),
    "Methylation": ("methylation", "meth", "dna methylation", "dna-methylation"),
    "SCNV": ("scnv", "scna", "cnv", "cna", "copy number", "copy-number", "copy number variation"),
}
_CIS_LAYER_LOOKUP: dict[str, str] = {
    re.sub(r"[^a-z0-9]+", "", alias.lower()): canonical
    for canonical, aliases in _CIS_LAYER_ALIASES.items()
    for alias in (canonical, *aliases)
}
_CPTAC_COHORT_ALIASES: dict[str, tuple[str, ...]] = {
    "BRCA": ("brca", "breast", "breast cancer", "breast invasive carcinoma"),
    "COAD": ("coad", "colon", "colon cancer", "colon adenocarcinoma"),
    "CCRCC": ("ccrcc", "kidney", "kidney cancer", "clear cell renal cell carcinoma", "renal clear cell carcinoma"),
    "GBM": ("gbm", "glioblastoma", "glioblastoma multiforme", "brain cancer"),
    "HNSCC": ("hnscc", "head and neck", "head and neck cancer", "head and neck squamous cell carcinoma"),
    "LSCC": ("lscc", "lung squamous", "lung squamous cell carcinoma", "lung squamous cancer"),
    "LUAD": ("luad", "lung adeno", "lung adenocarcinoma", "lung adenocarcinoma cancer"),
    "OV": ("ov", "ovarian", "ovarian cancer", "ovarian serous carcinoma"),
    "PDAC": ("pdac", "pancreatic", "pancreatic cancer", "pancreatic ductal adenocarcinoma"),
    "UCEC": ("ucec", "uterine", "uterine cancer", "endometrial", "endometrial cancer", "uterine corpus endometrial carcinoma"),
}
_CPTAC_COHORT_LOOKUP: dict[str, str] = {
    re.sub(r"[^a-z0-9]+", "", alias.lower()): canonical
    for canonical, aliases in _CPTAC_COHORT_ALIASES.items()
    for alias in (canonical, *aliases)
}
_CIS_PAIR_SPLIT_RE = re.compile(r"\s*(?:vs\.?|versus|↔|<->|->|to|/|,)\s*", re.IGNORECASE)


def _canonicalize_cis_layer(value: Any) -> str | None:
    """Normalize user- or source-provided omics layer names to the LinkedOmics canonical labels."""
    token = re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())
    if not token:
        return None
    return _CIS_LAYER_LOOKUP.get(token)


def _canonicalize_cis_pair(left: Any, right: Any) -> str | None:
    """Return a direction-independent cis pair label such as 'Protein ↔ RNA'."""
    left_layer = _canonicalize_cis_layer(left)
    right_layer = _canonicalize_cis_layer(right)
    if not left_layer or not right_layer:
        return None
    first, second = sorted((left_layer, right_layer), key=str.upper)
    return f"{first} ↔ {second}"


def _canonicalize_cptac_cohort(value: Any) -> str | None:
    """Normalize user-provided CPTAC cancer names to LinkedOmics cohort abbreviations."""
    token = re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())
    if not token:
        return None
    return _CPTAC_COHORT_LOOKUP.get(token)


def _parse_cis_pair_filters(pairs: Optional[list[str]]) -> tuple[set[str] | None, list[str], list[str], list[str]]:
    """Parse requested omics pairs into canonical, order-independent labels."""
    requested_pairs = [str(pair).strip() for pair in (pairs or []) if str(pair).strip()]
    if not requested_pairs:
        return None, [], [], []

    applied_pairs: list[str] = []
    applied_set: set[str] = set()
    ignored_pairs: list[str] = []

    for raw_pair in requested_pairs:
        parts = [part.strip() for part in _CIS_PAIR_SPLIT_RE.split(raw_pair) if part.strip()]
        if len(parts) != 2:
            ignored_pairs.append(raw_pair)
            continue
        canonical_pair = _canonicalize_cis_pair(parts[0], parts[1])
        if canonical_pair is None:
            ignored_pairs.append(raw_pair)
            continue
        if canonical_pair not in applied_set:
            applied_set.add(canonical_pair)
            applied_pairs.append(canonical_pair)

    return applied_set, requested_pairs, applied_pairs, ignored_pairs


def _parse_cis_cancer_filters(cancers: Optional[list[str]]) -> tuple[set[str] | None, list[str], list[str], list[str]]:
    """Parse requested cancer filters into canonical CPTAC cohort abbreviations."""
    requested_cancers = [str(cancer).strip() for cancer in (cancers or []) if str(cancer).strip()]
    if not requested_cancers:
        return None, [], [], []

    applied_cancers: list[str] = []
    applied_set: set[str] = set()
    ignored_cancers: list[str] = []

    for raw_cancer in requested_cancers:
        canonical_cancer = _canonicalize_cptac_cohort(raw_cancer)
        if canonical_cancer is None:
            ignored_cancers.append(raw_cancer)
            continue
        if canonical_cancer not in applied_set:
            applied_set.add(canonical_cancer)
            applied_cancers.append(canonical_cancer)

    return applied_set, requested_cancers, applied_cancers, ignored_cancers


def _filter_cis_correlation_data(
    cor_data: dict[str, Any],
    pair_filters: set[str] | None,
    cancer_filters: set[str] | None,
) -> dict[str, Any]:
    """Filter a cohort->records mapping down to the requested molecular pairs and cancer types."""
    if not pair_filters and not cancer_filters:
        return cor_data

    filtered: dict[str, Any] = {}
    for cohort, records in cor_data.items():
        canonical_cohort = _canonicalize_cptac_cohort(cohort) or str(cohort or "").strip().upper()
        if cancer_filters and canonical_cohort not in cancer_filters:
            continue
        if not isinstance(records, list):
            continue
        kept_records = []
        for record in records:
            if not isinstance(record, dict):
                continue
            pair_label = _canonicalize_cis_pair(record.get("x"), record.get("y"))
            if pair_label in pair_filters:
                kept_records.append(record)
        if kept_records:
            filtered[cohort] = kept_records
    return filtered


def _parse_drug_details(html: str) -> list[dict[str, Any]]:
    """Parse drug table rows (name, databases, indication) from the drug card HTML sections."""
    HEADER_TO_TIER: dict[str, str] = {
        "approved oncology drugs": "T1",
        "approved non-oncology drugs": "T2",
        "investigational drugs": "T3",
        "pre-clinical": "T4",
        "surface": "T5",
    }
    results: list[dict[str, Any]] = []
    # Split HTML by drug card h5 headings
    sections = re.split(r'<h5[^>]*class=["\']mb-0["\'][^>]*>', html)
    for section in sections[1:]:
        h5_end = section.find("</h5>")
        if h5_end == -1:
            continue
        title_raw = re.sub(r"<[^>]+>", "", section[:h5_end]).strip().lower().rstrip(":")
        tier: str | None = None
        for key, t in HEADER_TO_TIER.items():
            if key in title_raw:
                tier = t
                break
        if tier is None:
            continue
        row_pat = re.compile(r"<tr><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td></tr>", re.DOTALL)
        for m in row_pat.finditer(section):
            name_html, db_html, ind_html = m.group(1), m.group(2), m.group(3)
            name = re.sub(r"<[^>]+>", "", name_html).strip()
            databases: list[dict[str, str]] = []
            for link in re.finditer(r"href=['\"]([^'\"]*)['\"][^>]*>([^<]+)<", db_html):
                databases.append({"name": link.group(2).strip(), "url": link.group(1)})
            indication: dict[str, str] | None = None
            ind_link = re.search(r"href=['\"]([^'\"]*)['\"][^>]*>([^<]+)<", ind_html)
            if ind_link:
                indication = {"name": ind_link.group(2).strip(), "url": ind_link.group(1)}
            results.append({"name": name, "tier": tier, "databases": databases, "indication": indication})
    return results


def _parse_target_html(html: str) -> dict[str, Any]:
    """Extract all data sections from a drugtarget HTML page."""
    result: dict[str, Any] = {}

    # tn is split across 4 concat groups:
    #   1 = cell line dependency
    #   2 = increased in tumor, summary
    #   3 = increased in tumor, protein
    #   4 = increased in tumor, phospho sites
    tn_match = re.search(
        r"const tn = (\[.*?\])\.concat\((.*?)\)\.concat\((.*?)\)\.concat\((.*?)\);",
        html, re.DOTALL,
    )
    def _plot_ids_for(row: dict) -> list[str]:
        """Extract plot_id(s) from a data row, filtering out None / 'NA'."""
        pid = row.get("plot_id")
        if not pid or pid == "NA":
            return []
        return pid if isinstance(pid, list) else [pid]

    # plot_map: feature_field → cohort → [plot_id, ...]  (used by the interactive grid)
    plot_map: dict[str, dict[str, list[str]]] = {}

    if tn_match:
        def _positive_cohorts(raw: str) -> list[str]:
            return [r["cohort"] for r in json.loads(raw) if r.get("value") == 1]

        cl_rows = json.loads(tn_match.group(1))
        dep = [r["cohort"] for r in cl_rows if r.get("value") == 1]
        result["cell_line_dependency"] = (
            f"Dependent cell lines: {', '.join(dep)}" if dep
            else "No evidence of cell line dependency"
        )
        for r in cl_rows:
            pids = _plot_ids_for(r)
            if r.get("value") == 1 and pids:
                plot_map.setdefault("cell_line_dependency", {})[r["cohort"]] = pids

        summary = _positive_cohorts(tn_match.group(2))
        result["tumor_increase_summary"] = (
            f"Increased in tumor (summary): {', '.join(summary)}" if summary
            else "No evidence of tumor increase"
        )

        prot_rows = json.loads(tn_match.group(3))
        prot = [r["cohort"] for r in prot_rows if r.get("value") == 1]
        result["tumor_overexpression"] = (
            f"Overexpressed in {', '.join(prot)}" if prot
            else "No evidence of tumor overexpression"
        )
        # Store protein-level presence as list for orchestrator to build sub-row
        result["tumor_increase_protein"] = [{"cohort": r["cohort"]} for r in prot_rows if r.get("value") == 1]
        # Protein plots go under "tumor_increase_protein" (sub-row of the summary)
        for r in prot_rows:
            pids = _plot_ids_for(r)
            if r.get("value") == 1 and pids:
                plot_map.setdefault("tumor_increase_protein", {})[r["cohort"]] = pids

        site_rows = json.loads(tn_match.group(4))
        # Collect all unique sites (ordered by first appearance), with positive cohorts per site
        all_sites_order: list[str] = []
        sites: dict[str, list[str]] = {}
        for s in site_rows:
            site_key = s["site"]
            if site_key not in sites:
                all_sites_order.append(site_key)
                sites[site_key] = []
            if s.get("value") == 1:
                sites[site_key].append(s["cohort"])
        # Include ALL sites (even those with no positive cohorts) so the frontend
        # can display the full phospho sub-row grid regardless of which cohort was clicked
        result["hyperactivated_sites"] = (
            [{"site": site, "cohorts": sites[site]} for site in all_sites_order]
            if all_sites_order else "No evidence of hyperactivated sites"
        )
        # Store per-site phospho presence as list for orchestrator sub-rows
        for site_key in all_sites_order:
            cohort_list = sites[site_key]
            if cohort_list:
                result[f"phospho_{site_key}"] = [{"cohort": c} for c in cohort_list]
        # Phospho plot_map: key is "phospho_{site}" — already consistent with result keys
        for r in site_rows:
            pids = _plot_ids_for(r)
            if r.get("value") == 1 and pids:
                plot_map.setdefault(f"phospho_{r['site']}", {})[r["cohort"]] = pids

    # Standalone array variables — search each by name to avoid cross-variable regex capture
    # (a greedy-enough tn match can swallow const mut because tn ends with ]); not ];)
    var_data: dict[str, list] = {}
    for name in ("mut", "meth", "cnv", "tsg", "neo", "fus", "taa"):
        m = re.search(
            rf"(?:const|var|let)\s+{name}\s*=\s*(\[[\s\S]*?\]);",
            html,
        )
        if m:
            try:
                var_data[name] = json.loads(m.group(1))
            except Exception:
                pass

    def _cohort_list(rows: list, label: str, absent: str) -> str:
        cohorts = [r["cohort"] for r in rows if r.get("value") == 1]
        return f"{label}: {', '.join(cohorts)}" if cohorts else absent

    _STANDALONE: list[tuple[str, str, str, str]] = [
        ("mut",  "mutation_cis_effect",     "Mutation cis effect in",       "No evidence of mutation cis effect"),
        ("meth", "methylation_driver",      "Methylation driver in",        "No evidence of methylation driver"),
        ("cnv",  "cnv_driver",              "CNV driver in",                "No evidence of CNV driver"),
        ("tsg",  "tsg_dependency",          "TSG-associated dependency in", "No evidence of TSG-associated dependency"),
        ("taa",  "tumor_associated_antigen","Tumor-associated antigen in",  "No evidence of tumor-associated antigen"),
    ]
    for varname, field, label_prefix, absent_msg in _STANDALONE:
        if varname not in var_data:
            continue
        result[field] = _cohort_list(var_data[varname], label_prefix, absent_msg)
        for r in var_data[varname]:
            pids = _plot_ids_for(r)
            if r.get("value") == 1 and pids:
                plot_map.setdefault(field, {})[r["cohort"]] = pids

    result["_plot_map"] = plot_map

    # table_map: feature_field → cohort → list of row dicts (for grid cells that show tables, not plots)
    table_map: dict[str, dict[str, list[dict]]] = {}

    if "neo" in var_data:
        neo_entries = []
        for row in var_data["neo"]:
            if row.get("value") == 1:
                entry: dict[str, Any] = {"cohort": row["cohort"]}
                try:
                    table = json.loads(row.get("neo_mut_table", "[]"))
                    # Pass all columns through as-is
                    if table:
                        table_map.setdefault("neoantigen_mutations", {})[row["cohort"]] = table
                    entry["neoepitopes"] = table
                except Exception:
                    pass
                neo_entries.append(entry)
        result["neoantigen_mutations"] = neo_entries if neo_entries else "No neoantigen mutations identified"

    if "fus" in var_data:
        fus_entries = []
        for row in var_data["fus"]:
            if row.get("value") == 1:
                entry = {"cohort": row["cohort"]}
                try:
                    table = json.loads(row.get("neo_fus_table", "[]"))
                    # Pass all columns through as-is
                    if table:
                        table_map.setdefault("neoantigen_fusions", {})[row["cohort"]] = table
                    entry["fusion_neoepitopes"] = table
                except Exception:
                    pass
                fus_entries.append(entry)
        result["neoantigen_fusions"] = fus_entries if fus_entries else "No fusion neoantigens identified"

    result["_table_map"] = table_map
    result["_drug_details"] = _parse_drug_details(html)
    return result


def get_target_json() -> dict[str, dict[str, str]]:
    """Get the target JSON data from the LinkedOmics API."""
    json_req = requests.get("https://targets.linkedomics.org/index.json", timeout=5000)

    targets_orig = json_req.json()

    targets = {}

    # make the gene the key; preserve count as int, stringify everything else
    for entry in targets_orig:
        targets[entry["gene"]] = {}
        for key in entry.keys():
            if key == "gene":
                continue
            if key == "count":
                try:
                    targets[entry["gene"]][key] = int(entry[key])
                except (ValueError, TypeError):
                    targets[entry["gene"]][key] = 0
            else:
                targets[entry["gene"]][key] = str(entry[key])

    return targets


targets = get_target_json()


def _build_target_filter_metadata(
    *,
    tier: Optional[str] = None,
    tiers: Optional[list[str]] = None,
    family: Optional[str] = None,
    antigen: Optional[str] = None,
    drug_name: Optional[str] = None,
) -> tuple[dict[str, str], str]:
    applied_filters: dict[str, str] = {}
    parts: list[str] = []

    if tier:
        applied_filters["tier"] = tier.upper()
        parts.append(f"tier={tier.upper()}")
    if tiers:
        normalized_tiers = []
        for value in tiers:
            token = str(value).upper().strip()
            if token and token not in normalized_tiers:
                normalized_tiers.append(token)
        if normalized_tiers:
            applied_filters["tiers"] = ",".join(normalized_tiers)
            parts.append(f"tiers={','.join(normalized_tiers)}")
    if family:
        applied_filters["family"] = family
        parts.append(f"family={family}")
    if antigen:
        applied_filters["antigen"] = antigen.upper()
        parts.append(f"antigen={antigen.upper()}")
    if drug_name:
        applied_filters["drug_name"] = drug_name
        parts.append(f"drug={drug_name}")

    return applied_filters, ", ".join(parts) if parts else "all targets"


@mcp.tool()
def search_targets(
    tier: Optional[Literal["T1", "T2", "T3", "T4", "T5"]] = None,
    family: Optional[Literal["Kinase", "Enzyme", "GPCR", "oGPCR", "Transporter", "Ion Channel", "Transcription Factor", "Epigenetic", "Nuclear Receptor", "TF-Epigenetic", "Other"]] = None,
    antigen: Optional[Literal["TSA", "TAA"]] = None,
    drug_name: Optional[str] = None,
) -> dict[str, Any]:
    """Search and filter the full LinkedOmics drug target index across all ~19,700 genes by tier, family, antigen, or drug name.

    Use this tool when the query involves:
    - Discovering which genes belong to a specific tier or protein family
    - Counting or listing targets by category
    - Finding genes associated with a specific drug
    - Identifying tumor-associated or tumor-specific antigens
    - Comparing numbers of targets across families or tiers

    Use cases:
    - "Which kinases are FDA-approved oncology targets (T1)?"
    - "How many T1, T2, T3 targets exist?"
    - "List all T1 receptor tyrosine kinase targets"
    - "Which genes are targeted by Imatinib?"
    - "How many tumor-associated antigens (TAA) are T1 targets?"
    - "Which enzyme targets have approved oncology drugs?"

    Notes:
    - For ranking by attractiveness, use rank_targets instead.
    - Results are sorted by tier then gene name alphabetically.

    Args:
        tier (str, optional): Filter by tier — one of T1 (FDA-approved oncology), T2 (approved non-oncology),
            T3 (investigational), T4 (pre-clinical/druggable), T5 (surface proteins).
        family (str, optional): Filter by protein family, e.g. "Kinase", "Enzyme", "GPCR".
        antigen (str, optional): Filter by antigen class — "TSA" (tumor-specific) or "TAA" (tumor-associated).
        drug_name (str, optional): Filter to genes targeted by a specific drug (substring match).

    Returns:
        total (int): Number of matching genes.
        genes (list): Sorted by tier then gene name; each entry has gene, tier, family, drugs, antigen, count (LinkedOmics evidence score).
    """
    results = []
    for gene, info in targets.items():
        gene_tier = info.get("tier", "")
        gene_family = info.get("Family", "") or info.get("family", "")
        gene_antigen = info.get("antigen", "")
        gene_drugs = info.get("drugs", "")

        if tier and gene_tier != tier.upper():
            continue
        if family and family.lower() not in gene_family.lower():
            continue
        if antigen and antigen.lower() not in gene_antigen.lower():
            continue
        if drug_name and drug_name.lower() not in gene_drugs.lower():
            continue

        results.append({
            "gene": gene,
            "tier": gene_tier,
            "family": gene_family,
            "drugs": gene_drugs,
            "antigen": gene_antigen,
            "count": info.get("count", 0),
        })

    results.sort(key=lambda x: (x["tier"] or "Z", x["gene"]))
    applied_filters, filter_label = _build_target_filter_metadata(
        tier=tier,
        family=family,
        antigen=antigen,
        drug_name=drug_name,
    )
    return {
        "total": len(results),
        "genes": results,
        "applied_filters": applied_filters,
        "filter_label": filter_label,
    }


_ESTABLISHED_TIER_WEIGHT = {"T1": 50, "T2": 30, "T3": 10, "T4": 5, "T5": 2}
_EXPLORATORY_TIER_WEIGHT = {"T1": 2, "T2": 5, "T3": 10, "T4": 30, "T5": 50}
_ANTIGEN_BONUS = {"TSA": 10, "TAA": 5}
_RANKABLE_TIERS = ("T1", "T2", "T3", "T4", "T5")
_TARGET_RANKING_MODE_LABELS = {
    "balanced": "Balanced evidence-first",
    "established": "Established / clinically advanced",
    "exploratory": "Exploratory / discovery-stage",
}


def _normalize_target_ranking_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode in _TARGET_RANKING_MODE_LABELS:
        return mode
    return "balanced"


def _target_ranking_score_label(ranking_mode: str) -> str:
    mode = _normalize_target_ranking_mode(ranking_mode)
    if mode == "established":
        return "Clinical Readiness Score"
    if mode == "exploratory":
        return "Exploratory Score"
    return "Balanced Score"


def _target_ranking_explanation(ranking_mode: str) -> str:
    mode = _normalize_target_ranking_mode(ranking_mode)
    if mode == "established":
        return (
            "Established ranking favors clinically advanced targets: tier weight "
            "(T1 = 50 pts, T2 = 30 pts, T3 = 10 pts, T4 = 5 pts, T5 = 2 pts) "
            "+ approved oncology drug count × 5 pts each "
            "+ antigen status (TSA = +10 pts, TAA = +5 pts) "
            "+ LinkedOmics evidence score × 2 pts."
        )
    if mode == "exploratory":
        return (
            "Exploratory ranking favors discovery-stage targets: novelty weight "
            "(T5 = 50 pts, T4 = 30 pts, T3 = 10 pts, T2 = 5 pts, T1 = 2 pts) "
            "+ antigen status (TSA = +10 pts, TAA = +5 pts) "
            "+ LinkedOmics evidence score × 2 pts. Approved-drug counts do not increase rank."
        )
    return (
        "Balanced ranking is evidence-first and does not favor established or exploratory tiers: "
        "antigen status (TSA = +10 pts, TAA = +5 pts) "
        "+ LinkedOmics evidence score × 2 pts. Tier is shown for context but does not change rank."
    )


def _composite_score(info: dict[str, Any], ranking_mode: str = "balanced") -> int:
    ranking_mode = _normalize_target_ranking_mode(ranking_mode)
    tier = info.get("tier", "")
    drug_tiers_raw = str(info.get("drug_tiers", "") or "")
    antigen = str(info.get("antigen", "") or "").strip()
    lo_score = int(info.get("count") or 0)

    approved_drug_count = sum(
        1 for t in drug_tiers_raw.split(";") if t.strip() == "T1"
    )
    antigen_bonus = _ANTIGEN_BONUS.get(antigen, 2 if antigen else 0)
    evidence_score = lo_score * 2

    if ranking_mode == "established":
        return (
            _ESTABLISHED_TIER_WEIGHT.get(tier, 0)
            + approved_drug_count * 5
            + antigen_bonus
            + evidence_score
        )
    if ranking_mode == "exploratory":
        return _EXPLORATORY_TIER_WEIGHT.get(tier, 0) + antigen_bonus + evidence_score
    return antigen_bonus + evidence_score


@mcp.tool()
def rank_targets(
    tiers: Optional[list[Literal["T1", "T2", "T3", "T4", "T5"]]] = None,
    ranking_mode: Literal["balanced", "established", "exploratory"] = "balanced",
    family: Optional[Literal["Kinase", "Enzyme", "GPCR", "oGPCR", "Transporter", "Ion Channel", "Transcription Factor", "Epigenetic", "Nuclear Receptor", "TF-Epigenetic", "Other"]] = None,
    antigen: Optional[Literal["TSA", "TAA"]] = None,
    top_n: int = 50,
) -> dict[str, Any]:
    """Rank cancer targets by therapeutic attractiveness using a composite score.

    Use this tool when the query is about:
    - Most attractive, promising, or high-priority therapeutic targets
    - Best-validated or most druggable cancer targets
    - Ranking targets by clinical readiness, exploratory novelty, or biological evidence
    - Top targets within a specific protein family

    Use cases:
    - "What are the most attractive therapeutic targets for cancer?"
    - "Which kinases are the best validated oncology targets?"
    - "Rank the top immune checkpoint or GPCR targets for cancer therapy"
    - "Rank discovery-stage T4 and T5 membrane-associated targets"
    - "Among T3-T5 targets, show the strongest evidence without favoring established or exploratory tiers"

    Notes:
    - `tiers` controls which tiers are eligible for ranking.
    - `ranking_mode` controls how eligible targets are prioritized:
      - `balanced` (default): ranks by LinkedOmics evidence + antigen status only; tier is shown for context but does not change rank.
      - `established`: favors clinically advanced targets with T1 > T2 > T3 > T4 > T5 and approved-drug bonuses.
      - `exploratory`: favors discovery-stage targets with T5 > T4 > T3 > T2 > T1 and no approved-drug bonus.
    - By default, all tiers (T1-T5) are eligible. Use `tiers` to restrict ranking to specific tiers.

    Args:
        tiers (list[str], optional): Restrict ranking to one or more tiers, e.g.
            ["T1", "T2"] or ["T4", "T5"]. If omitted, all tiers (T1-T5) are included.
        ranking_mode (str): How to prioritize eligible targets — `balanced`, `established`, or `exploratory`.
        family (str, optional): Restrict to a protein family, e.g. "Kinase", "Enzyme", "GPCR".
        antigen (str, optional): Restrict to antigen class — "TSA" (tumor-specific) or "TAA" (tumor-associated).
        top_n (int): Number of top-ranked targets to return (default 50, max 200).

    Returns:
        total (int): Number of candidates scored after applying tier/family/antigen filters.
        genes (list): Top-ranked entries sorted by composite score; each has gene, tier, family, drugs, antigen, count (composite score), lo_score (raw LinkedOmics score).
        ranking_mode (str): The normalized ranking mode applied to this result.
        ranking_mode_label (str): Human-readable label for the applied ranking mode.
        ranking_explanation (str): Human-readable explanation of how the score was computed.
    """
    top_n = min(int(top_n), 200)
    ranking_mode = _normalize_target_ranking_mode(ranking_mode)
    ranking_mode_label = _TARGET_RANKING_MODE_LABELS[ranking_mode]
    ranking_explanation = _target_ranking_explanation(ranking_mode)
    score_label = _target_ranking_score_label(ranking_mode)
    included_tiers = list(_RANKABLE_TIERS)
    if tiers:
        requested_tiers = [str(value).upper() for value in tiers if str(value).strip()]
        included_tiers = [tier for tier in _RANKABLE_TIERS if tier in requested_tiers]
        if not included_tiers:
            return {
                "total": 0,
                "top_n": top_n,
                "genes": [],
                "ranking_mode": ranking_mode,
                "ranking_mode_label": ranking_mode_label,
                "ranking_explanation": ranking_explanation,
                "score_label": score_label,
                "applied_filters": {"tiers": ",".join(requested_tiers)} if requested_tiers else {},
                "filter_label": f"tiers={','.join(requested_tiers)}" if requested_tiers else "all targets",
            }
    candidates = []
    for gene, info in targets.items():
        gene_tier = info.get("tier", "")
        if gene_tier not in included_tiers:
            continue
        gene_family = info.get("Family", "") or info.get("family", "")
        gene_antigen = str(info.get("antigen", "") or "")
        gene_drugs = info.get("drugs", "")

        if family and family.lower() not in gene_family.lower():
            continue
        if antigen and antigen.lower() not in gene_antigen.lower():
            continue

        score = _composite_score(info, ranking_mode=ranking_mode)
        candidates.append({
            "gene": gene,
            "tier": gene_tier,
            "family": gene_family,
            "drugs": gene_drugs,
            "antigen": gene_antigen,
            "count": score,
            "lo_score": int(info.get("count") or 0),
        })

    candidates.sort(key=lambda x: -x["count"])
    applied_filters, filter_label = _build_target_filter_metadata(
        tiers=included_tiers if tiers else None,
        family=family,
        antigen=antigen,
    )
    return {
        "total": len(candidates),
        "top_n": top_n,
        "genes": candidates[:top_n],
        "ranking_mode": ranking_mode,
        "ranking_mode_label": ranking_mode_label,
        "ranking_explanation": ranking_explanation,
        "score_label": score_label,
        "applied_filters": applied_filters,
        "filter_label": filter_label,
    }


@mcp.tool()
def funmap_neighborhood(protein: str) -> dict:
    """Retrieve the functional neighborhood of a protein in the FunMap network.

    FunMap is a functional network where proteins are connected if a connection is predicted by a
    machine learning model trained on expression correlation across different cancer types
    and previously identified protein-protein interactions (PPI). This tool is useful for
    identifying genes that may share similar functions, belong to related pathways, or participate in the same biological network or module.

    Use this tool when the query involves:
    - Functional partners
    - Co-expression relationships
    - Co-regulation
    - Pathway expansion
    - Network-based inference

    Use cases:
    - "Which genes are functionally related to ESR1 in the FunMap network?"
    - "Find potential novel members of the Estrogen Receptor signaling pathway by looking at the ESR1 neighborhood."
    - "Identify co-regulated partners of TP53 that might cooperate in tumor suppression."

    Args:
        protein (str): The gene symbol of the protein of interest (e.g., "ESR1", "TP53").

    Returns:
        dict: A dictionary with:
            - "nodes" (list[dict]): Each node has "name" (gene symbol) and "value" (score string).
              The score is a p-value derived from the difference in average protein abundance
              between tumor and normal samples using the Wilcoxon rank-sum test, based on data
              from 5 cohorts: CCRCC, HCC, HNSCC, LSCC, and LUAD.
            - "edges" (list[dict]): Each edge has "source" and "target" gene symbols representing functional connections.
            - "neighborhood" (list[str]): Flat list of neighbor gene symbols for quick reference.
    """
    req = requests.get(
        f"https://funmap.linkedomics.org/data/dag/gene/{protein.upper()}.json",
        timeout=1000,
    )
    if req.status_code != 200:
        print(f"Got status code: {req.status_code}")
        return {"nodes": [], "edges": [], "neighborhood": []}  # Could not find protein

    data = req.json()
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    neighborhood = [node["name"] for node in nodes if node.get("name") != protein.upper()]
    return {"nodes": nodes, "edges": edges, "neighborhood": neighborhood}


@mcp.tool()
def get_target(protein: str) -> dict[str, Any]:
    """Retrieve clinical targeting data, oncology tiers, and tumor dependency for a gene.

    This tool integrates data from multiple sources to provide a comprehensive snapshot of a gene's
    clinical and therapeutic potential:
    - **Tier / Drugs**: Clinical relevance tier (T1: FDA-approved oncology, T2: FDA-approved other
      indication, T3: clinical trials, T4: pre-clinical/druggable, T5: surface proteins) and
      associated drug names.
    - **Cell Line Dependency**: Whether the gene is essential for cancer cell survival (DepMap/Achilles).
    - **Tumor Increase Summary**: Whether the gene is broadly increased in tumor vs. normal.
    - **Tumor Overexpression (protein)**: Specific cohorts where the protein is overexpressed.
    - **Hyperactivated Phospho Sites**: Phosphorylation sites with elevated activity in tumors.
    - **Methylation Driver**: Cohorts where the gene acts as a methylation driver.
    - **CNV Driver**: Cohorts where somatic copy-number variation drives expression.
    - **TSG Dependency**: Cohorts showing TSG-associated dependency.
    - **Tumor-Associated Antigen**: Cohorts where the protein is a tumor-associated antigen.
    - **Neoantigen Mutations**: Somatic mutations generating neoantigens, with peptide, HLA type,
      and NetMHCpan binding affinity details.
    - **Neoantigen Fusions**: Gene fusions generating neoantigens, with same detail level.

    Use this tool when asking whether a gene is a therapeutic target.

    Use cases:
    - "Is ESR1 a validated oncology target, and what drugs are approved for it?"
    - "Does TP53 show dependency in any cancer cell lines, suggesting it's essential for survival?"
    - "What are the hyperactivated phosphorylation sites for EGFR across different cancers?"
    - "Which tier does the gene BRCA1 fall into for drug development?"
    - "Does EGFR generate neoantigens in any cancer type?"

    Args:
        protein (str): The gene symbol (e.g., "ESR1").

    Returns:
        dict[str, Any]: A result dictionary with all available targeting and tumor biology fields.
    """
    global targets

    if protein.upper() not in targets:
        return {"result": "No target information found"}

    base = targets[protein.upper()]

    html: str | None = None
    try:
        req = requests.get(
            f"https://targets.linkedomics.org/{protein.upper()}/",
            timeout=10,
        )
        if req.status_code == 200:
            html = req.text
    except Exception:
        pass

    if html:
        base.update(_parse_target_html(html))

    return {"result": base}


@mcp.tool()
def batch_get_target(proteins: list[str]) -> dict[str, Any]:
    """Retrieve clinical targeting data, oncology tiers, and tumor dependency for multiple genes.

    This tool integrates data from multiple sources to provide a comprehensive snapshot of each gene's
    clinical and therapeutic potential, including tier, drugs, cell line dependency, tumor overexpression,
    hyperactivated phospho sites, methylation/CNV drivers, TSG dependency, tumor-associated antigens,
    and neoantigen mutations/fusions.

    Use this tool when asking whether a list of genes contains a therapeutic target.

    Use cases:
    - "From the list of genes provided, which ones are FDA-approved oncology targets?"
    - "What genes are have strong indications for cell line dependency? What does this mean"
    - "Do any of these genes have hyperactivated phosphorylation sites?"
    - "In this list of genes, are all of them overexpressed in cancer?"

    Args:
        proteins (list[str]): List of gene symbols (e.g., ["ESR1", "TP53"]).

    Returns:
        dict[str, Any]: A result dictionary containing tier, family, drugs, dependency, and overexpression summaries for each gene.
            status of error should not used to formulate the response.
    """
    results = {}
    for protein in proteins:
        try:
            targets = get_target(protein)
        except Exception as e:
            targets = {"status": "error", "message": str(e)}
        results[protein] = targets
    return {"status": "available", "data": results}


def transform_tn(
    data: dict[str, Any], sig_threshold: float = 0.05
) -> tuple[bool, dict[str, Any]]:
    CANCER_TYPES = [
        "CCRCC",
        "HNSCC",
        "LSCC",
        "LUAD",
        "PDAC",
        "BRCA",
        "COAD",
        "GBM",
        "OV",
        "UCEC",
    ]
    is_available = False
    ret_val = {}

    for cancer in CANCER_TYPES:
        if cancer in data:
            pval = float(data[cancer]["pval"])
            if abs(pval) < sig_threshold:
                if pval < 0:
                    ret_val[cancer] = (
                        f"Significantly lower expressed in tumor (p={pval:.3e})"
                    )
                else:
                    ret_val[cancer] = (
                        f"Significantly higher expressed in tumor (p={pval:.3e})"
                    )
            else:
                ret_val[cancer] = (
                    f"No significant difference between tumor and normal (p={pval:.3e})"
                )
        else:
            ret_val[cancer] = "Data unavailable"
    is_available = True  # Data ready
    return (is_available, ret_val)


def transform_os(
    data: dict[str, Any], sig_threshold: float = 0.05
) -> tuple[bool, dict[str, Any]]:
    CANCER_TYPES = [
        "CCRCC",
        "HNSCC",
        "LSCC",
        "LUAD",
        "PDAC",
        "BRCA",
        "COAD",
        "GBM",
        "OV",
        "UCEC",
    ]
    is_available = False
    ret_val = {}

    for cancer in CANCER_TYPES:
        if cancer in data:
            pval = float(data[cancer]["pval"])
            if abs(pval) < sig_threshold:
                if pval < 0:
                    ret_val[cancer] = (
                        f"Lower expression associated with poor survival (p={pval:.3e})"
                    )
                else:
                    ret_val[cancer] = (
                        f"Higher expression associated with poor survival (p={pval:.3e})"
                    )
            else:
                ret_val[cancer] = (
                    f"No significant difference between tumor and normal (p={pval:.3e})"
                )
        else:
            ret_val[cancer] = "Data unavailable"
    is_available = True  # Data ready
    return (is_available, ret_val)


@mcp.tool()
def cancer_gene_expression(protein: str) -> dict[str, Any]:
    """Evaluate tumor–normal differential expression of a gene at RNA and protein levels across 10 CPTAC cancer cohorts.

    This tool performs Tumor-Normal (TN) comparison using CPTAC data. It reports direction and statistical significance of expression changes.
    Significant results indicate potential oncogenic overexpression or tumor-suppressive downregulation.

    Use this tool when the query involves:
    - Differential expression between tumor and normal tissue in a certain cancer type
    - Overexpression or downregulation in cancer
    - RNA vs protein concordance
    - Cross-cancer expression comparison

    Use cases:
    - "Is ESR1 significantly overexpressed in BRCA at the protein level compared to normal tissue?"
    - "Identify cancer types where TP53 RNA expression is significantly lower in tumors."
    - "Compare the protein vs. RNA expression patterns of EGFR across all available cancer types."

    Args:
        protein (str): The gene symbol (e.g., "ESR1").

    Returns:
        dict[str, Any]: RNA and Protein expression status (Higher/Lower/No difference) for each cohort.

    Notes:
    - Available cohorts: BRCA (Breast), COAD (Colon), CCRCC (Kidney), GBM (Brain), HNSCC (Head/Neck), LSCC (Lung Squamous), LUAD (Lung Adeno), OV (Ovarian), PDAC (Pancreatic), UCEC (Uterine).
    - Available omic types: RNA, protein.
    """
    req = requests.get(
        f"https://kb.linkedomics.org/data/tn/gene?gene={protein.upper()}&sort=metap&order=asc&offset=0&limit=10",
        timeout=1000,
    )
    rna_data = {"status": "unavailable", "data": {}}
    protein_data = {"status": "unavailable", "data": {}}
    if req.status_code == 200:
        data = req.json()
        for element in data:
            if element.get("datatype", "") == "RNA":
                (is_available, processed_data) = transform_tn(element)
                rna_data["data"] = processed_data
                rna_data["status"] = "available" if is_available else rna_data["status"]
            elif element.get("datatype", "") == "protein":
                (is_available, processed_data) = transform_tn(element)
                protein_data["data"] = processed_data
                protein_data["status"] = (
                    "available" if is_available else protein_data["status"]
                )
    return {"protein_level": protein_data, "RNA_level": rna_data}


@mcp.tool()
def batch_cancer_gene_expression(proteins: list[str]) -> dict[str, Any]:
    """Evaluate tumor–normal differential expression of multiple genes at RNA and protein levels across 10 CPTAC cancer cohorts.

    This tool performs Tumor-Normal (TN) comparison using CPTAC data. It reports direction and statistical significance of expression changes.
    Significant results indicate potential oncogenic overexpression or tumor-suppressive downregulation.

    Use this tool when the query involves:
    - Differential expression between tumor and normal tissue for a list of genes
    - Overexpression or downregulation patterns across a gene set
    - RNA vs protein concordance comparison for multiple genes
    - Cross-cancer expression comparison for a panel of genes

    Use cases:
    - "Are any of these genes significantly overexpressed in BRCA at the protein level?"
    - "Identify cancer types where this neighborhood of proteins' RNA expression is lower in tumors."
    - "Compare the protein vs. RNA expression patterns of these proteins across all cancer types."

    Args:
        proteins (list[str]): The gene symbols (e.g., ["ESR1", "TP53"]).

    Returns:
        dict[str, Any]: RNA and Protein expression status (Higher/Lower/No difference) per cohort for each gene.

    Notes:
    - Available cohorts: BRCA (Breast), COAD (Colon), CCRCC (Kidney), GBM (Brain), HNSCC (Head/Neck), LSCC (Lung Squamous), LUAD (Lung Adeno), OV (Ovarian), PDAC (Pancreatic), UCEC (Uterine).
    - Available omic types: RNA, protein.
    """
    results = {}
    for protein in proteins:
        try:
            targets = cancer_gene_expression(protein)
        except Exception as e:
            targets = {"status": "error", "message": str(e)}
        results[protein] = targets
    return {"status": "available", "data": results}


@mcp.tool()
def overall_survival_per_cancer(protein: str) -> dict[str, Any]:
    """Evaluate the association between gene expression and overall survival across 10 CPTAC cancer cohorts.

    Expression levels are stratified (e.g., high vs. low), determines if high or low expression (RNA/Protein) is a significant predictor of overall survival.
    "Higher expression associated with poor survival" suggests the gene may serve as a negative prognostic biomarker.

    Use this tool when the query involves:
    - Prognostic value of a gene
    - Survival association
    - Overall survival correlation
    - Risk stratification by expression

    Use cases:
    - "Does high expression of ESR1 correlate with better or worse survival outcomes in Breast Cancer (BRCA)?"
    - "Which cancers show that TP53 protein levels are a significant prognostic factor for survival?"
    - "Is low expression of a specific gene associated with poor survival in Lung Adenocarcinoma (LUAD)?"

    Args:
        protein (str): The gene symbol (e.g., "ESR1").

    Returns:
        dict[str, Any]: Survival association results for RNA and Protein levels across 10 cohorts.

    Notes:
    - Available omic types: RNA, protein.
    - Available cohorts: BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC.
    """
    req = requests.get(
        f"https://kb.linkedomics.org/data/associations/phenotype/gene?phenotype=clinical__overall_survival&gene={protein.upper()}",
        timeout=1000,
    )
    rna_data = {"status": "unavailable", "data": {}}
    protein_data = {"status": "unavailable", "data": {}}
    if req.status_code == 200:
        data = req.json()

        for element in data:
            if element.get("datatype", "") == "RNA":
                (is_available, processed_data) = transform_os(element)
                rna_data["data"] = processed_data
                rna_data["status"] = "available" if is_available else rna_data["status"]
            elif element.get("datatype", "") == "protein":
                (is_available, processed_data) = transform_os(element)
                protein_data["data"] = processed_data
                protein_data["status"] = (
                    "available" if is_available else protein_data["status"]
                )
    return {"protein_level": protein_data, "RNA_level": rna_data}


@mcp.tool()
def batch_overall_survival_per_cancer(proteins: list[str]) -> dict[str, Any]:
    """Evaluate the association between gene expression and overall survival across 10 CPTAC cancer cohorts for a list of genes.

    Expression levels are stratified (e.g., high vs. low), determines if high or low expression (RNA/Protein) is a significant predictor of overall survival.
    "Higher expression associated with poor survival" suggests the gene may serve as a negative prognostic biomarker.

    Use this tool when the query involves:
    - Prognostic value of multiple genes
    - Comparing survival associations across a gene set
    - Risk stratification by expression for a panel of genes

    Use cases:
    - "Does high expression of ESR1 correlate with worse survival in BRCA? How does it compare to TP53 and IDO1?"
    - "Which cancers show that TP53 protein levels are a significant prognostic factor but not IDO1?"
    - "Is low expression of these genes associated with poor survival in Lung Adenocarcinoma (LUAD)?"

    Args:
        proteins (list[str]): The gene symbols (e.g., ["ESR1", "TP53"]).

    Returns:
        dict[str, Any]: Survival association results for RNA and Protein levels across 10 cohorts per gene.

    Notes:
    - Available omic types: RNA, protein.
    - Available cohorts: BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC.
    """
    results = {}
    for protein in proteins:
        try:
            targets = overall_survival_per_cancer(protein)
        except Exception as e:
            targets = {"status": "error", "message": str(e)}
        results[protein] = targets
    return {"status": "available", "data": results}


def get_top_n_trials(
    data: list[dict[str, Any]], sig_threshold: float = 0.05
) -> dict[str, Any]:
    """Get all significant trials in both directions."""
    filtered = [s for s in data if abs(float(s["fdr"])) < sig_threshold]
    pos = sorted([s for s in filtered if float(s["fdr"]) > 0], key=lambda s: -s["sorted_fdr"])
    neg = sorted([s for s in filtered if float(s["fdr"]) < 0], key=lambda s: s["sorted_fdr"])

    def _fmt(s: dict[str, Any]) -> dict[str, Any]:
        return {
            "series": s["series"],
            "study_id": s.get("study_id", ""),
            "treatment": s["treatment"],
            "disease": s.get("disease", ""),
            "subtype": s.get("subtype", ""),
            "clinical_trial_id": s.get("clinical_trial_id", ""),
            "sample_size": s.get("sample_size", ""),
            "auroc": round(float(s["auroc"]), 3),
            "fdr": float(s["fdr"]),
            "p_value": s.get("p_value") or s.get("pvalue") or s.get("pVal") or s.get("p_val"),
            "response_evaluation": s.get("response_evaluation") or s.get("responseEvaluation") or s.get("response_eval", ""),
        }

    return {
        "resistant": [_fmt(s) for s in pos],
        "sensitive": [_fmt(s) for s in neg],
        "total_significant": len(filtered),
        "total_studies": len(data),
    }


@mcp.tool()
def clinical_trial_information(protein: str) -> dict[str, Any]:
    """Identify drugs and trials where gene expression predicts treatment response.

    Uses public clinical trial data (GSE series) to find associations between a gene's expression
    and drug sensitivity or resistance.
    - **Sensitive**: Higher gene expression correlates with better response (or lower IC50).
    - **Resistant**: Higher gene expression correlates with worse response (or higher IC50).

    Use this tool when:
    - The query involves drug sensitivity or resistance
    - Treatment response biomarkers
    - Expression-associated drug response
    - Gene–drug association


    Use cases:
    - "Which drugs are patients likely to be resistant to if they have high ESR1 expression?"
    - "Find clinical trials where TP53 expression is a marker for drug sensitivity."
    - "What treatments are associated with resistance when BRCA1 is overexpressed?"

    Args:
        protein (str): The gene symbol (e.g., "ESR1").

    Returns:
        dict[str, Any]: Significant resistant and sensitive study lists, each with fields:
            series, study_id, treatment, disease, subtype, clinical_trial_id, sample_size,
            auroc, fdr, p_value, and response_evaluation. Also includes total_significant
            and total_studies counts.
    """
    ret_val = {"status": "unavailable", "data": {}}
    req = requests.get(
        f"https://trials.linkedomics.org/api/table/gene/{protein.upper()}", timeout=1000
    )
    if req.status_code == 200:
        ret_val["status"] = "available"
        ret_val["data"] = get_top_n_trials(req.json())
    return ret_val


@mcp.tool()
def batch_clinical_trial_information(proteins: list[str]) -> dict[str, Any]:
    """Identify drugs and trials where gene expression predicts treatment response for a list of proteins.

    Uses public clinical trial data (GSE series) to find associations between a gene's expression
    and drug sensitivity or resistance.
    - **Sensitive**: Higher gene expression correlates with better response (or lower IC50).
    - **Resistant**: Higher gene expression correlates with worse response (or higher IC50).

    Use this tool when:
    - The query involves drug sensitivity or resistance for multiple proteins
    - Treatment response biomarkers
    - Expression-associated drug response
    - Gene–drug association


    Use cases:
    - "Which drugs are patients likely to be resistant to if they have high ESR1 or TP53 expression?"
    - "Find clinical trials where expression of these genes is a marker for drug sensitivity."
    - "What treatments are associated with resistance when any of these genes are overexpressed?"

    Args:
        proteins (list[str]): The gene symbols (e.g., ["ESR1", "TP53"]).

    Returns:
        dict[str, Any]: Per-protein results, each with resistant and sensitive study lists
            containing fields: series, study_id, treatment, disease, subtype,
            clinical_trial_id, sample_size, auroc, fdr, p_value, and response_evaluation.
    """
    results = {}
    for protein in proteins:
        try:
            targets = clinical_trial_information(protein)
        except Exception as e:
            targets = {"status": "error", "message": str(e)}
        results[protein] = targets
    return {"status": "available", "data": results}


@mcp.tool()
def get_study_info(study_id: str) -> dict[str, Any]:
    """Get full details about a specific clinical trial study by its series ID.

    Returns study abstract, sample size, cancer type, treatment, NCT trial ID,
    PubMed link, and data download URL.

    Use this tool when:
    - The user asks for details about a specific study (by GSE/study ID)
    - The user wants the abstract, platform, or download link for a study
    - Following up on a result from clinical_trial_information to learn more

    Args:
        study_id (str): Study series ID as returned by clinical_trial_information
            (e.g., "GSE25066" or "Choueiri_CCR_2016"). The .csv suffix is added automatically.

    Returns:
        dict: Full study metadata including abstract, sample sizes, NCT ID, PubMed ID, download URL.
    """
    sid = study_id.strip()
    if not sid.endswith(".csv"):
        sid = sid + ".csv"
    req = requests.get(f"https://trials.linkedomics.org/api/info/{sid}", timeout=30)
    if req.status_code != 200:
        return {"status": "unavailable", "data": {}}
    return {"status": "available", "data": req.json()}


@mcp.tool()
def gene_set_trial_information(gene_set: str) -> dict[str, Any]:
    """Find clinical trial studies where a gene set or pathway predicts treatment response.

    Use this tool when:
    - The query involves a pathway or gene signature (e.g., HALLMARK_HYPOXIA, EMT, cell cycle)
    - The user asks whether a biological process predicts drug sensitivity or resistance

    Use cases:
    - "Does HALLMARK_ESTROGEN_RESPONSE predict tamoxifen sensitivity?"
    - "Which trials show hypoxia signature predicting immunotherapy resistance?"

    Args:
        gene_set (str): Gene set name as used in MSigDB (e.g., "HALLMARK_HYPOXIA").
            Spaces are converted to underscores automatically.

    Returns:
        dict: Significant resistant and sensitive study lists with disease, treatment, AUROC,
            study metadata, and NCT ID.
    """
    gs = gene_set.strip().upper().replace(" ", "_")
    req = requests.get(f"https://trials.linkedomics.org/api/table/gene_set/{gs}", timeout=30)
    if req.status_code != 200:
        return {"status": "unavailable", "data": {}}
    return {"status": "available", "gene_set": gs, "data": get_top_n_trials(req.json())}


# Treatment category → drug substrings used by the LinkedOmics Trials filter API.
# Derived from the website's TreatmentSelect component (hardcoded in the frontend JS).
# The filter API does case-insensitive substring matching on study treatment strings.
TREATMENT_CATEGORIES: dict[str, list[str]] = {
    "targeted": [
        "trastuzumab", "pertuzumab", "trastuzumab-emtansine", "rituximab",
        "ipilimumab", "atezolizumab", "nivolumab", "pembrolizumab", "bevacizumab",
        "lapatinib", "neratinib", "ganetespib", "ganitumab", "trebananib",
        "sunitinib", "veliparib", "bortezomib", "MK-2206",
        "letrozole", "dexamethasone", "thalidomide",
    ],
    "chemotherapy": [
        "paclitaxel", "docetaxel", "taxane",
        "doxorubicin", "epirubicin", "anthracycline",
        "fluorouracil", "capecitabine",
        "cyclophosphamide", "chlorambucil",
        "carboplatin", "platinum",
        "ixabepilone", "thiotepa",
    ],
    "combinations": [
        # chemo + targeted combination regimens in the database
        "paclitaxel,doxorubicin,cyclophosphamide,trastuzumab",
        "paclitaxel,doxorubicin,cyclophosphamide,pertuzumab",
        "paclitaxel,doxorubicin,cyclophosphamide,MK-2206",
        "paclitaxel,doxorubicin,cyclophosphamide,ganetespib",
        "paclitaxel,doxorubicin,cyclophosphamide,ganitumab",
        "paclitaxel,doxorubicin,cyclophosphamide,neratinib",
        "paclitaxel,doxorubicin,cyclophosphamide,pembrolizumab",
        "paclitaxel,doxorubicin,cyclophosphamide,trebananib",
        "paclitaxel,doxorubicin,cyclophosphamide,veliparib",
        "paclitaxel,fluorouracil,epidoxorubicin,cyclophosphamide,lapatinib",
        "paclitaxel,fluorouracil,epidoxorubicin,cyclophosphamide,trastuzumab",
        "taxane,anthracycline,cyclophosphamide,trastuzumab",
        "taxane,fluorouracil,epirubicin,cyclophosphamide,trastuzumab",
        "carboplatin,paclitaxel,atezolizumab",
        "atezolizumab,bevacizumab",
        "nivolumab,ipilimumab",
        "pembrolizumab,ipilimumab",
        "pembrolizumab,nivolumab",
        "rituximab,chlorambucil",
        "bortezomib,thalidomide,dexamethasone",
    ],
}

def _resolve_treatment_category(
    treatment_category: Optional[str],
    drugs: Optional[list[str]],
) -> list[str]:
    """Expand a treatment category name to its constituent drug strings."""
    if not treatment_category:
        return drugs or []
    key = treatment_category.strip().lower()
    # Accept aliases
    if key in ("immunotherapy", "checkpoint inhibitor", "immune checkpoint"):
        key = "targeted"
    elif key in ("chemo", "cytotoxic"):
        key = "chemotherapy"
    elif key in ("combo", "combination therapy"):
        key = "combinations"
    resolved = TREATMENT_CATEGORIES.get(key)
    if resolved is None:
        # Unknown category — fall back to treating the string as a drug name
        return [treatment_category]
    return resolved


@mcp.tool()
def filter_clinical_trials(
    drugs: Optional[list[str]] = None,
    cancers: Optional[list[str]] = None,
    treatment_category: Optional[str] = None,
) -> dict[str, Any]:
    """Find clinical trial studies matching a specific drug, treatment category, and/or cancer type.

    Use this tool when:
    - The user wants to know which studies exist for a drug/cancer combination
    - As a discovery step before asking for gene-level analysis

    Use cases:
    - "Which studies tested nivolumab in melanoma?"
    - "How many breast cancer chemotherapy studies are in the database?"
    - "What targeted therapy studies exist for ovarian cancer?"

    Args:
        drugs (list[str]): Specific drug names to filter by (e.g., ["paclitaxel"]).
        cancers (list[str]): Cancer types to filter by (e.g., ["Breast"]).
            Available: Breast, Ovarian, Lung, Leukemia, Myeloma, Melanoma, Esophageal,
            Kidney, Bladder, Gastric, Glioblastoma.
        treatment_category (str): Broad treatment class — "chemotherapy", "targeted", or
            "combinations". Expands to all matching drug substrings automatically.
            Use instead of `drugs` when the user specifies a category rather than a specific drug.

    Returns:
        dict: Matching study list, count, and cancer types present.
    """
    resolved_drugs = _resolve_treatment_category(treatment_category, drugs)
    body: dict[str, Any] = {"drugs": resolved_drugs, "cancers": cancers or []}
    req = requests.post("https://trials.linkedomics.org/api/filter", json=body, timeout=30)
    if req.status_code != 200:
        return {"status": "unavailable", "data": {}}
    r = req.json()
    return {
        "status": "available",
        "data": {
            "study_list": r.get("study_list", []),
            "study_count": r.get("length", 0),
            "possible_cancers": r.get("possible_cancers", []),
            "filters_applied": {**body, **({"treatment_category": treatment_category} if treatment_category else {})},
        },
    }


@mcp.tool()
def meta_analysis_predictive_genes(
    drugs: Optional[list[str]] = None,
    cancers: Optional[list[str]] = None,
    treatment_category: Optional[str] = None,
    top_n: int = 200,
) -> dict[str, Any]:
    """Run a meta-analysis to find which genes best predict drug response across clinical studies.

    Filters studies by drug and/or cancer type, then runs a meta-analysis across all matching
    studies to rank genes by how significantly their expression predicts treatment outcome.

    Use this tool when:
    - The user asks which genes are the top predictors of response to a treatment
    - The user wants biomarker discovery across a drug or cancer type

    Use cases:
    - "Which genes best predict paclitaxel response?" → drugs=["paclitaxel"], cancers=[]
    - "Which genes best predict paclitaxel response in breast cancer?" → drugs=["paclitaxel"], cancers=["Breast"]
    - "What are the top biomarkers for platinum resistance in ovarian cancer?"
    - "Find the strongest predictors of nivolumab sensitivity across all studies."
    - "Which genes predict chemotherapy response?" → use treatment_category="chemotherapy"
    - "Top gene predictors of targeted therapy?" → use treatment_category="targeted"

    IMPORTANT: only set `cancers` if the user explicitly names a cancer type. Leave it empty ([]) for
    cross-cancer queries.

    Args:
        drugs (list[str]): Specific drug names to filter by (e.g., ["paclitaxel"]).
        cancers (list[str]): Cancer types to filter by (e.g., ["Breast"]). Leave empty for all cancers.
            Available: Breast, Ovarian, Lung, Leukemia, Myeloma, Melanoma, Esophageal,
            Kidney, Bladder, Gastric, Glioblastoma.
        treatment_category (str): Broad treatment class — "chemotherapy", "targeted", or
            "combinations". Expands to all matching drug substrings automatically.
            Use instead of `drugs` when the user specifies a category rather than a specific drug.
        top_n (int): Number of top genes to return (default 200).

    Returns:
        dict: Ranked gene list with meta-analysis statistics
            (meta_fdr, meta_fdr_signed, meta_fdr_sci, avg_auc, datasets, direction).
            "datasets" = number of studies where the gene was significant.
            "avg_auc" = average AUROC across studies (<0.5 = sensitive, >0.5 = resistant).
    """
    resolved_drugs = _resolve_treatment_category(treatment_category, drugs)
    body: dict[str, Any] = {"drugs": resolved_drugs, "cancers": cancers or []}
    filters_display: dict[str, Any] = {**body, **({"treatment_category": treatment_category} if treatment_category else {})}
    fr = requests.post("https://trials.linkedomics.org/api/filter", json=body, timeout=30)
    if fr.status_code != 200:
        return {"status": "unavailable", "data": {}}
    study_list = fr.json().get("study_list", [])
    if not study_list:
        return {"status": "no_studies", "data": {"filters": filters_display, "study_count": 0}}

    mr = requests.post(
        "https://trials.linkedomics.org/api/table/treatment_gene",
        json={"study_list": study_list},
        timeout=120,
    )
    if mr.status_code != 200:
        return {"status": "unavailable", "data": {}}
    rows = mr.json()

    rows_sorted = sorted(rows, key=lambda r: abs(float(r.get("fdr", 1))))[:top_n]
    genes = []
    for r in rows_sorted:
        avg_auc = float(r.get("avg_auc", 0.5))
        fdr_signed = float(r.get("fdr", 1))
        genes.append({
            "gene": r.get("analyte", ""),
            "datasets": r.get("datasets", 0),
            "meta_fdr": round(abs(fdr_signed), 6),
            "meta_fdr_signed": round(fdr_signed, 6),
            "meta_fdr_sci": f"{fdr_signed:.3e}",
            "avg_auc": round(avg_auc, 3),
            "direction": "sensitive" if avg_auc < 0.5 else "resistant",
        })
    return {
        "status": "available",
        "data": {
            "filters": filters_display,
            "study_count": len(study_list),
            "study_list": study_list,
            "top_genes": genes,
        },
    }


@mcp.tool()
def meta_analysis_predictive_gene_sets(
    drugs: Optional[list[str]] = None,
    cancers: Optional[list[str]] = None,
    treatment_category: Optional[str] = None,
    top_n: int = 200,
) -> dict[str, Any]:
    """Run a meta-analysis to find which gene sets / pathways best predict drug response across clinical studies.

    Filters studies by drug and/or cancer type, then runs a meta-analysis across all matching
    studies to rank gene sets by how significantly their activity predicts treatment outcome.

    Use this tool when:
    - The user asks which pathways are the top predictors of response to a treatment
    - The user wants pathway-level biomarker discovery across a drug or cancer type

    Use cases:
    - "Which pathways best predict paclitaxel response?" → drugs=["paclitaxel"], cancers=[]
    - "Which pathways best predict paclitaxel response in breast cancer?" → drugs=["paclitaxel"], cancers=["Breast"]
    - "What biological processes predict platinum resistance in ovarian cancer?"
    - "Find the top pathway predictors of nivolumab sensitivity across all studies."
    - "Which pathways predict chemotherapy response?" → use treatment_category="chemotherapy"
    - "Top pathway predictors of targeted therapy?" → use treatment_category="targeted"

    IMPORTANT: only set `cancers` if the user explicitly names a cancer type. Leave it empty ([]) for
    cross-cancer queries.

    Args:
        drugs (list[str]): Specific drug names to filter by (e.g., ["paclitaxel"]).
        cancers (list[str]): Cancer types to filter by (e.g., ["Breast"]). Leave empty for all cancers.
            Available: Breast, Ovarian, Lung, Leukemia, Myeloma, Melanoma, Esophageal,
            Kidney, Bladder, Gastric, Glioblastoma.
        treatment_category (str): Broad treatment class — "chemotherapy", "targeted", or
            "combinations". Expands to all matching drug substrings automatically.
            Use instead of `drugs` when the user specifies a category rather than a specific drug.
        top_n (int): Number of top gene sets to return (default 200).

    Returns:
        dict: Ranked gene set list with meta-analysis statistics (meta_fdr, avg_auc, datasets, direction).
            "datasets" = number of studies where the gene set was significant.
            "avg_auc" = average AUROC across studies (>0.5 = resistant, <0.5 = sensitive).
    """
    resolved_drugs = _resolve_treatment_category(treatment_category, drugs)
    body: dict[str, Any] = {"drugs": resolved_drugs, "cancers": cancers or []}
    filters_display: dict[str, Any] = {**body, **({"treatment_category": treatment_category} if treatment_category else {})}
    fr = requests.post("https://trials.linkedomics.org/api/filter", json=body, timeout=30)
    if fr.status_code != 200:
        return {"status": "unavailable", "data": {}}
    study_list = fr.json().get("study_list", [])
    if not study_list:
        return {"status": "no_studies", "data": {"filters": filters_display, "study_count": 0}}

    mr = requests.post(
        "https://trials.linkedomics.org/api/table/treatment_gene_set",
        json={"study_list": study_list},
        timeout=120,
    )
    if mr.status_code != 200:
        return {"status": "unavailable", "data": {}}
    rows = mr.json()

    rows_sorted = sorted(
        rows, key=lambda r: abs(float(r.get("fdr", 1)))
    )[:top_n]
    gene_sets = []
    for r in rows_sorted:
        avg_auc = float(r.get("avg_auc", 0.5))
        gene_sets.append({
            "gene_set": r.get("analyte", ""),
            "datasets": r.get("datasets", 0),
            "meta_fdr": round(abs(float(r.get("fdr", 1))), 3),
            "meta_fdr_sci": f"{abs(float(r.get('fdr', 1))):.3e}",
            "avg_auc": round(avg_auc, 3),
            "direction": "sensitive" if avg_auc < 0.5 else "resistant",
        })
    return {
        "status": "available",
        "data": {
            "filters": filters_display,
            "study_count": len(study_list),
            "study_list": study_list,
            "top_gene_sets": gene_sets,
        },
    }


def _rank_study_analytes(rows: list[dict], top_n: int) -> list[dict]:
    """Rank analytes (genes or gene sets) from a single-study response by significance."""
    rows_sorted = sorted(rows, key=lambda r: abs(float(r.get("sorted_fdr", 0))), reverse=True)[:top_n]
    result = []
    for r in rows_sorted:
        auc = float(r.get("auc", 0.5))
        result.append({
            "analyte": r.get("analyte", ""),
            "auc": round(auc, 3),
            "fdr": float(r.get("fdr", 1)),
            "direction": "sensitive" if auc < 0.5 else "resistant",
        })
    return result


@mcp.tool()
def get_study_predictive_genes(study_id: str, top_n: int = 20) -> dict[str, Any]:
    """Get the top genes that predict treatment response in a specific clinical study.

    Use this tool when:
    - The user wants to know which genes are most predictive in a specific study
    - Following up on a study returned by clinical_trial_information or filter_clinical_trials
    - The user asks "which genes predict response in study GSE25066?"

    Args:
        study_id (str): Study series ID (e.g., "GSE25066"). The .csv suffix is added automatically.
        top_n (int): Number of top genes to return (default 20).

    Returns:
        dict: Ranked gene list with auc, fdr, and direction (sensitive/resistant).
            direction="sensitive" means higher expression → better response (auc < 0.5).
            direction="resistant" means higher expression → worse response (auc > 0.5).
    """
    sid = study_id.strip()
    if not sid.endswith(".csv"):
        sid = sid + ".csv"
    req = requests.get(f"https://trials.linkedomics.org/api/table/study/gene/{sid}", timeout=60)
    if req.status_code != 200:
        return {"status": "unavailable", "data": {}}
    rows = req.json()
    return {
        "status": "available",
        "study_id": study_id,
        "data": {
            "study_id": study_id,
            "total_genes": len(rows),
            "top_genes": _rank_study_analytes(rows, top_n),
        },
    }


@mcp.tool()
def get_study_predictive_gene_sets(study_id: str, top_n: int = 20) -> dict[str, Any]:
    """Get the top gene sets / pathways that predict treatment response in a specific clinical study.

    Use this tool when:
    - The user wants to know which pathways are most predictive in a specific study
    - The user asks "which pathways predict response in study GSE25066?"
    - Following up on a study to understand the biological processes driving response

    Args:
        study_id (str): Study series ID (e.g., "GSE25066"). The .csv suffix is added automatically.
        top_n (int): Number of top gene sets to return (default 20).

    Returns:
        dict: Ranked gene set list with auc, fdr, and direction (sensitive/resistant).
    """
    sid = study_id.strip()
    if not sid.endswith(".csv"):
        sid = sid + ".csv"
    req = requests.get(f"https://trials.linkedomics.org/api/table/study/gene_set/{sid}", timeout=60)
    if req.status_code != 200:
        return {"status": "unavailable", "data": {}}
    rows = req.json()
    return {
        "status": "available",
        "study_id": study_id,
        "data": {
            "study_id": study_id,
            "total_gene_sets": len(rows),
            "top_gene_sets": _rank_study_analytes(rows, top_n),
        },
    }


@mcp.tool()
def get_cis_correlations(
    protein: str,
    pairs: Optional[list[str]] = None,
    cancers: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Analyze cis-regulatory relationships between molecular layers (RNA, Protein, Methylation, SCNV) for a gene.

    Cis-correlations help determine what drives a gene's expression levels across CPTAC cohorts.

    Use this tool when the query involves:
    - Identifying what drives a gene's expression (copy number, methylation, translation)
    - RNA vs. protein translation efficiency
    - Epigenetic regulation of a gene
    - Copy number dosage effects on expression

    Use cases:
    - "Is the high protein level of ESR1 in BRCA driven by its RNA levels or by gene amplification (SCNV)?"
    - "How much does DNA methylation influence TP53 expression in Lung Adenocarcinoma (LUAD)?"
    - "Check if there's a strong dosage effect (SCNV vs RNA) for EGFR in Glioblastoma (GBM)."

    Args:
        protein (str): The gene symbol (e.g., "ESR1").
        pairs (Optional[list[str]]): Optional molecular pair filters such as
            ["RNA vs Protein"] or ["RNA vs Protein", "RNA vs SCNV"].
            If omitted, all available pairs are returned.
        cancers (Optional[list[str]]): Optional cancer type filters such as
            ["BRCA"] or ["breast cancer", "OV"]. If omitted, all available cohorts are returned.

    Returns:
        dict[str, Any]: Correlation coefficients (val) and p-values for the requested
        molecular pairs across cohorts. Defaults to all pairs and all cohorts when no filter is provided.

    Notes:
    - RNA vs. Protein: translation efficiency (mRNA → protein conversion rate).
    - RNA vs. Methylation: epigenetic silencing or activation of transcription.
    - RNA vs. SCNV: gene copy number dosage effect on mRNA levels.
    - Available cohorts: BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC.
    """
    pair_filters, requested_pairs, applied_pairs, ignored_pairs = _parse_cis_pair_filters(pairs)
    if requested_pairs and not applied_pairs:
        return {
            "status": "error",
            "message": (
                "No valid molecular pairs were recognized. Use pair labels like "
                "'RNA vs Protein', 'RNA vs Methylation', or 'RNA vs SCNV'."
            ),
            "supported_layers": list(_CIS_LAYER_ALIASES.keys()),
            "ignored_pairs": ignored_pairs,
        }
    cancer_filters, requested_cancers, applied_cancers, ignored_cancers = _parse_cis_cancer_filters(cancers)
    if requested_cancers and not applied_cancers:
        return {
            "status": "error",
            "message": (
                "No valid cancer types were recognized. Use CPTAC cohort labels like "
                "'BRCA', 'LUAD', 'OV', or 'UCEC'."
            ),
            "supported_cancers": list(_CPTAC_COHORT_ALIASES.keys()),
            "ignored_cancers": ignored_cancers,
        }

    base_url = f"https://kb.linkedomics.org/gene/{protein.upper()}"
    req = requests.get(base_url, timeout=5000)
    html_text = req.text

    # extract the cor_data js variable using regex.
    cor_data_res = re.search(r"let cor_data = (\{.*?\})(?=\s+for)", html_text)
    if cor_data_res is None:
        return {"status": "error", "message": "Failed to extract cor_data"}
    cor_data = cor_data_res.group(1)
    cor_data = json.loads(cor_data)

    # convert all float and integer values to strings
    for cohort in cor_data:
        cohort_data = cor_data[cohort]
        for index, entry in enumerate(cohort_data):
            for key, value in entry.items():
                cor_data[cohort][index][key] = str(value)

    filtered_data = _filter_cis_correlation_data(cor_data, pair_filters, cancer_filters)

    response: dict[str, Any] = {"status": "available", "data": filtered_data}
    if requested_pairs:
        response["requested_pairs"] = requested_pairs
        response["applied_pairs"] = applied_pairs
        if ignored_pairs:
            response["ignored_pairs"] = ignored_pairs
    if requested_cancers:
        response["requested_cancers"] = requested_cancers
        response["applied_cancers"] = applied_cancers
        if ignored_cancers:
            response["ignored_cancers"] = ignored_cancers
    if not filtered_data and (requested_pairs or requested_cancers):
        filter_labels = []
        if requested_pairs:
            filter_labels.append("molecular pairs")
        if requested_cancers:
            filter_labels.append("cancer types")
        response["message"] = f"No cis-correlation records matched the requested {' and '.join(filter_labels)}."

    return response


@mcp.tool()
def batch_get_cis_correlations(
    proteins: list[str],
    pairs: Optional[list[str]] = None,
    cancers: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Analyze cis-regulatory relationships between molecular layers (RNA, Protein, Methylation, SCNV) for a list of genes.

    Cis-correlations help determine what drives each gene's expression levels across CPTAC cohorts.

    Use this tool when the query involves:
    - Identifying expression drivers for a panel of genes
    - Comparing translation efficiency or epigenetic regulation across a gene set
    - Copy number dosage effects on expression for multiple genes

    Use cases:
    - "Is the high protein level of ESR1 or TP53 in BRCA driven by RNA levels or gene amplification (SCNV)?"
    - "How much does DNA methylation influence the expression of these genes in Lung Adenocarcinoma (LUAD)?"
    - "Check if there's a strong dosage effect (SCNV vs RNA) for these proteins in Glioblastoma (GBM)."

    Args:
        proteins (list[str]): The gene symbols (e.g., ["ESR1", "TP53"]).
        pairs (Optional[list[str]]): Optional molecular pair filters such as
            ["RNA vs Protein"] or ["RNA vs Protein", "RNA vs SCNV"].
            If omitted, all available pairs are returned for each gene.
        cancers (Optional[list[str]]): Optional cancer type filters such as
            ["BRCA"] or ["breast cancer", "OV"]. If omitted, all available cohorts are returned.

    Returns:
        dict[str, Any]: Correlation coefficients (val) and p-values for the requested
        molecular pairs across cohorts per gene. Defaults to all pairs and all cohorts when no filter is provided.

    Notes:
    - RNA vs. Protein: translation efficiency (mRNA → protein conversion rate).
    - RNA vs. Methylation: epigenetic silencing or activation of transcription.
    - RNA vs. SCNV: gene copy number dosage effect on mRNA levels.
    - Available cohorts: BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC.
    """
    _pair_filters, requested_pairs, applied_pairs, ignored_pairs = _parse_cis_pair_filters(pairs)
    if requested_pairs and not applied_pairs:
        return {
            "status": "error",
            "message": (
                "No valid molecular pairs were recognized. Use pair labels like "
                "'RNA vs Protein', 'RNA vs Methylation', or 'RNA vs SCNV'."
            ),
            "supported_layers": list(_CIS_LAYER_ALIASES.keys()),
            "ignored_pairs": ignored_pairs,
        }
    _cancer_filters, requested_cancers, applied_cancers, ignored_cancers = _parse_cis_cancer_filters(cancers)
    if requested_cancers and not applied_cancers:
        return {
            "status": "error",
            "message": (
                "No valid cancer types were recognized. Use CPTAC cohort labels like "
                "'BRCA', 'LUAD', 'OV', or 'UCEC'."
            ),
            "supported_cancers": list(_CPTAC_COHORT_ALIASES.keys()),
            "ignored_cancers": ignored_cancers,
        }

    results = {}
    for protein in proteins:
        try:
            targets = get_cis_correlations(protein, pairs=pairs, cancers=cancers)
        except Exception as e:
            targets = {"status": "error", "message": str(e)}
        results[protein] = targets

    response: dict[str, Any] = {"status": "available", "data": results}
    if requested_pairs:
        response["requested_pairs"] = requested_pairs
        response["applied_pairs"] = applied_pairs
        if ignored_pairs:
            response["ignored_pairs"] = ignored_pairs
    if requested_cancers:
        response["requested_cancers"] = requested_cancers
        response["applied_cancers"] = applied_cancers
        if ignored_cancers:
            response["ignored_cancers"] = ignored_cancers

    return response


@mcp.tool()
def webgestalt(proteins: list[str], top_n: int = 5) -> dict[str, Any]:
    """Perform Gene Ontology (GO) overrepresentation analysis on a list of proteins using WebGestalt. Identifies biological processes significantly enriched in the input gene set compared to a genomic background.

    This tool answers questions like:
    - "What biological processes are shared among these cancer genes?"
    - "What pathways are enriched in the FunMap neighborhood of ESR1?"
    - "After identifying FunMap partners of MYC, what functions do they share?"

    Best used AFTER:
    - funmap_neighborhood() — to interpret what a gene's functional network does
    - A custom gene list from hypothesis-driven selection

    Args:
        proteins (list[str]):
            List of HGNC gene symbols to analyze (e.g., ["TP53", "BRCA1", "EGFR"]).
            Recommended: 10–50 genes. Too few genes will yield no enrichment;
            too many (>200) may dilute signal.

        top_n (int, optional):
            Number of top-ranked enriched GO terms to return, sorted by p-value.
            Default: 5. Recommended: 10–20 for exploratory analysis.

    Returns:
        dict with keys:
            "status" (str): "success" or error indicator.
            "data" (list[dict]): List of enriched gene sets, each containing:
                - "geneSet" (str): GO term ID (e.g., "GO:0044843")
                - "description" (str): Human-readable GO term name
                  (e.g., "cell cycle G1/S phase transition")
                - "link" (str): AmiGO URL for the GO term — use to get full term details
                - "size" (int): Total number of genes annotated to this GO term
                  in the reference genome
                - "overlap" (int): Number of your input genes found in this GO term
                - "expect" (float): Expected overlap by chance given input list size
                - "enrichmentRatio" (float): overlap / expect — values >>1 indicate
                  strong enrichment (e.g., 32.0 = 32x over background)
                - "pValue" (float): Hypergeometric p-value (uncorrected)
                - "FDR" (float): Benjamini-Hochberg corrected p-value — use this
                  for significance calls; FDR < 0.05 is the standard threshold
                - "overlapId" (str): Semicolon-delimited Entrez Gene IDs of the
                  overlapping genes (useful for identifying which input genes
                  drive the enrichment)

    Notes:
    - Sort results by FDR (already sorted in output) — not raw pValue.
    - enrichmentRatio > 5 with FDR < 0.01 = strong, reliable enrichment.
    - overlapId can be mapped back to gene symbols using NCBI Entrez.
    - Results reflect GO Biological Process terms only (not Molecular Function or Cellular Component).
    - Input genes not recognized as valid HGNC symbols are silently dropped.
    - Best used after funmap_neighborhood() to interpret a gene's functional network, or with any custom gene list.
    """
    gene_list = "\n".join(proteins)

    url = "https://www.webgestalt.org/process.php"

    payload = {
        "enrich_method": "ORA",
        "organism": "hsapiens",
        "enriched_database_category[]": "geneontology",
        "enriched_database_name[]": "Biological_Process_noRedundant",
        "gene_list": gene_list,
        "ref_set": "genome_protein-coding",
        "id_type": "genesymbol",
        "ref_file": "",  # empty like in JS
        "hasWSC": "on",
        "min_num": "3",
        "max_num": "2000",
        "fdr_method": "BH",
        "sig_method": "top",
        "sig_value": "10",
        "set_cover_num": "10",
        "kMedoid_k": "10",
        "report_num": "40",
        "color_scheme": "continuous",
    }

    response = requests.post(url, data=payload)

    process_text = response.text

    process_id_res = re.search(r"var ts = (\d+);", process_text)
    if process_id_res is None:
        return {"status": "error", "message": "Could not find process ID"}
    process_id = process_id_res.group(1)

    print("Found process ID:", process_id)

    # wait for results to have good response
    response_code = 404

    # thirty_second_timeout
    timeout = 30

    current_cycle = 0

    while response_code != 200 and current_cycle < timeout:
        response = requests.get(f"https://www.webgestalt.org/results/{process_id}/")
        response_code = response.status_code
        time.sleep(1)
        current_cycle += 1

    if response_code != 200:
        return {"status": "error", "message": "Timed out waiting for results"}

    enrich_text = response.text
    enrich_results_text = re.search(r"var enrichment = (\[.+\]);", enrich_text)
    if enrich_results_text is None:
        return {"status": "error", "message": "Could not find enrichment results"}
    enrich_results: list[dict[str, str | float]] = json.loads(
        enrich_results_text.group(1)
    )
    enrich_results.sort(key=lambda x: x["FDR"])

    ret_val = {"status": "success", "data": enrich_results[:top_n]}

    return ret_val


@mcp.tool()
def tcga_survival_analysis(
    cohort: Optional[str] = None,
    gene: Optional[str] = None,
    omics: Optional[str] = None
) -> dict:
    """Perform survival analysis using TCGA multi-omics data via the LinkedOmics API.

    Evaluates whether gene expression (or other molecular measurements) is associated
    with overall survival across TCGA cancer cohorts. Supports flexible query modes
    from single-gene analysis to genome-wide scans.

    Use this tool when:
    - The user asks about survival associations in TCGA cohorts
    - Queries involve gene expression and patient survival across TCGA cancer types
    - The user wants to scan which genes predict survival within a cohort

    Use cases:
    - "Is TP53 RNA expression associated with survival in LAML?"
    - "Which genes are prognostic in BRCA at the RNA level?"
    - "Does EGFR protein level predict survival across all TCGA cancers?"
    - "Compare survival impact of ESR1 methylation vs RNA in BRCA"

    Args:
        cohort (str, optional): TCGA cancer cohort abbreviation (e.g., "BRCA", "LUAD").
        gene (str, optional): HGNC gene symbol (e.g., "TP53", "ESR1"). Use "hsa-mir-XX" for microRNA.
        omics (str, optional): Omics type — one of: Methylation, RNAseq, RPPA, SCNA, miRNASeq.

    Returns:
        dict:
            A dictionary containing survival results from the TCGA backend.

            The response always has the form:

                {
                    "dataset": "TCGA",
                    "mode": mode,
                    "query": params,
                    "n_results": len(results),
                    "results": [...]
                }

            `results` is always a list of gene-level result objects.

            Common fields that may appear in each result item:
            - cohort
            - omics
            - gene
            - hr
            - pvalue
            - fdr
            - n
            - samples

            Returned fields depend on query mode because keys already provided
            in the request are removed from each result item.

            Mode 1 (`cohort + gene + omics`)
            - Returns one detailed single-gene result.
            - Result items typically contain:
            hr, pvalue, n, samples

            Mode 2 (`cohort + gene`)
            - Returns one detailed single-gene result per available omics type.
            - Result items typically contain:
            omics, hr, pvalue, n, samples

            Mode 3 (`gene + omics`)
            - Returns one result per cohort.
            - Result items typically contain:
            cohort, hr, pvalue, n
            - `fdr` is removed for this mode.

            Mode 4 (`cohort + omics`)
            - Returns one result per gene for the requested cohort and omics.
            - Result items typically contain:
            gene, hr, pvalue, fdr, n

            On request failure, the function returns:

                {
                    "status": "error",
                    "dataset": "TCGA",
                    "mode": mode,
                    "query": params,
                    "message": "...",
                    "results": []
                }


    Notes:
    - Four query modes: (1) cohort+gene+omics, (2) cohort+gene all omics, (3) gene+omics all cohorts, (4) cohort+omics genome-wide scan.
    - Supported cohorts: ACC, BLCA, BRCA, CESC, CHOL, COADREAD, DLBC, ESCA, GBM, GBMLGG, HNSC, KICH, KIPAN, KIRC, KIRP, LAML, LGG, LIHC, LUAD, LUSC, MESO, OV, PAAD, PCPG, PRAD, SARC, SKCM, STAD, STES, TGCT, THCA, THYM, UCEC, UCS, UVM.
    - Supported omics: Methylation, RNAseq, RPPA, SCNA, miRNASeq.
    - Significant associations rely on p-values or FDR thresholds (interpretation depends on downstream processing).
    - Positive vs. negative associations reflect directionality of risk (e.g., high expression → worse survival).
    - Mode 4 (genome-wide scan) may return large datasets; downstream filtering is recommended.
    - Missing or empty results indicate lack of data or an unsupported query combination.
    """


    base_url = "http://aws1.zhang-lab.org:8237/api/survival"
    cohort = cohort.strip() or None if cohort is not None else None
    gene = gene.strip() or None if gene is not None else None
    omics = omics.strip() or None if omics is not None else None
    mode = detect_tcga_survival_mode(cohort, gene, omics)

    # Gene-only call (no cohort, no omics) is ambiguous — default to RNAseq for
    # pan-cancer expression queries (mode 3: gene + omics, all cohorts).
    if mode is None and gene and not cohort and not omics:
        omics = "RNAseq"
        mode = detect_tcga_survival_mode(cohort, gene, omics)

    if mode is None:
        return tcga_parameter_error("Invalid parameter combination")

    try:
        params = {}

        if cohort:
            params["cohort"] = normalize_tcga_cohort(cohort)

        if gene:
            params["gene"] = gene.upper()

        if omics:
            params["omics"] = normalize_tcga_omics(omics)
    except ValueError as e:
        return tcga_parameter_error(str(e))


    try:
        r = requests.get(
            base_url,
            params=params,
            timeout=(80, 1200)
        )

        try:
            resp = r.json()
        except ValueError:
            resp = {"raw_text": r.text}

        r.raise_for_status()

        results = resp.get("results", [])
        if not isinstance(results, list):
            return {
                "status": "error",
                "error": "Unexpected API response format",
                "dataset": "TCGA",
                "mode": mode,
                "query": params,
                "raw": resp,
                "results": [],
            }

        return {
            "dataset": "TCGA",
            "mode": mode,
            "query": params,
            "n_results": len(results),
            "results": results,
        }

    except requests.exceptions.HTTPError as e:
        detail = None
        try:
            detail = r.json().get("detail")
        except Exception:
            detail = str(e)

        return {
            "status": "error",
            "dataset": "TCGA",
            "mode": mode,
            "query": params,
            "message": detail,
            "results": [],
        }

    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "dataset": "TCGA",
            "mode": mode,
            "query": params,
            "message": str(e),
            "results": [],
        }




@mcp.tool()
def tcga_cis_association_analysis(
    cohort: Optional[TCGACohort] = None,
    gene: Optional[str] = None,
    source_omics: Optional[TCGACisOmics] = None,
    target_omics: Optional[TCGACisOmics] = None,
    st_method: Optional[TCGAStMethod] = "spearman",
) -> dict[str, Any]:
    """Perform cis-association analysis using TCGA multi-omics data via the LinkedOmics API.

    Evaluates whether measurements from one molecular layer are associated with
    measurements from another layer for the same gene across TCGA cancer cohorts.
    Supports flexible query modes from single-gene association lookups to
    genome-wide scans between two omics layers.

    Use this tool when:
    - The user asks about cis associations between TCGA molecular layers
    - Queries involve the relationship between one omics measurement and another for the same gene
    - The user wants to scan which genes show strong within-gene cross-omics associations in a cohort

    Use cases:
    - "Is EGFR RNAseq associated with RPPA in LUAD?"
    - "Show cis associations for TP53 in BRCA across available omics pairs"
    - "Across TCGA cohorts, is ESR1 methylation associated with RNAseq?"
    - "Which genes have strong SCNA to RNAseq cis associations in BRCA?"

    Args:
        cohort (str, optional): TCGA cancer cohort abbreviation (e.g., "BRCA", "LUAD").
        gene (str, optional): HGNC gene symbol (e.g., "TP53", "ESR1").
        source_omics (str, optional): Source omics type — one of: Methylation, RNAseq, RPPA, SCNA
        target_omics (str, optional): Target omics type — one of: Methylation, RNAseq, RPPA, SCNA
        st_method (str, optional): Statistical method — one of: spearman, pearson.

    Returns:
        A dictionary with cis-association results. Fields depend on the query mode.
        dataset (str): Always "TCGA cis association".
        mode (int): Query mode 1–4, inferred from which parameters were provided.
        query (dict): The parameters sent to the API (cohort, gene, source_omics, target_omics, st_method).
        n_results (int): Number of result objects returned.
        results (list): List of result objects. Mode 1 — one object with correlation, pvalue, n, samples (patient-level points). Mode 2 — one object per omics pair with source_omics, target_omics, correlation, pvalue, n, samples. Mode 3 — one object per cohort with cohort, correlation, pvalue, n. Mode 4 — one object per gene with gene, correlation, pvalue, fdr, n.


    Notes:
    - Four query modes: (1) cohort+gene+source_omics+target_omics, (2) cohort+gene across all available omics pairs or filtered by only source_omics / only target_omics, (3) gene+source_omics+target_omics across all cohorts, (4) cohort+source_omics+target_omics genome-wide scan.
    - Supported cohorts: ACC, BLCA, BRCA, CESC, CHOL, COADREAD, DLBC, ESCA, GBM, GBMLGG, HNSC, KICH, KIPAN, KIRC, KIRP, LAML, LGG, LIHC, LUAD, LUSC, MESO, OV, PAAD, PCPG, PRAD, SARC, SKCM, STAD, STES, TGCT, THCA, THYM, UCEC, UCS, UVM.
    - Supported omics: Methylation, RNAseq, RPPA, SCNA.
    - Supported statistical methods: spearman, pearson.
    - Positive vs. negative correlations reflect directionality of association between the two molecular layers.
    - Mode 4 (genome-wide scan) may return large datasets; downstream filtering is recommended.
    - Missing or empty results indicate lack of data or an unsupported query combination.
    """
    base_url = "http://aws1.zhang-lab.org:8236/api/cis_association"
    cohort = cohort.strip() or None if cohort is not None else None
    gene = gene.strip() or None if gene is not None else None
    source_omics = source_omics.strip() or None if source_omics is not None else None
    target_omics = target_omics.strip() or None if target_omics is not None else None
    st_method = (st_method.strip().lower() if st_method is not None else "spearman")

    mode = detect_tcga_cis_association_mode(cohort, gene, source_omics, target_omics)
    if mode is None:
        return tcga_cis_parameter_error("Invalid parameter combination")

    try:
        params: dict[str, Any] = {}
        if cohort:
            params["cohort"] = normalize_tcga_cohort(cohort)
        if gene:
            params["gene"] = gene.upper()
        if source_omics:
            params["source_omics"] = normalize_tcga_cis_omics(source_omics)
        if target_omics:
            params["target_omics"] = normalize_tcga_cis_omics(target_omics)
        if st_method:
            params["st_method"] = normalize_tcga_st_method(st_method)
    except ValueError as e:
        return tcga_cis_parameter_error(str(e))

    try:
        r = requests.get(base_url, params=params, timeout=(80, 1200))
        try:
            resp = r.json()
        except ValueError:
            resp = {"raw_text": r.text}

        r.raise_for_status()
        results = resp.get("results", [])
        if not isinstance(results, list):
            return {
                "status": "error",
                "error": "Unexpected API response format",
                "dataset": "TCGA cis association",
                "mode": mode,
                "query": params,
                "raw": resp,
                "results": [],
            }

        return {
            "dataset": "TCGA cis association",
            "mode": mode,
            "query": params,
            "n_results": len(results),
            "results": results,
        }
    except requests.exceptions.HTTPError as e:
        detail = None
        try:
            detail = r.json().get("detail")
        except Exception:
            detail = str(e)
        return {
            "status": "error",
            "dataset": "TCGA cis association",
            "mode": mode,
            "query": params,
            "message": detail,
            "results": [],
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "dataset": "TCGA cis association",
            "mode": mode,
            "query": params,
            "message": str(e),
            "results": [],
        }


# Run with stdio transport
if __name__ == "__main__":
    mcp.run(transport="stdio")
