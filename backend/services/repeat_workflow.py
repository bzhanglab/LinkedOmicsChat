"""Repeat an answer's analyses for other genes, without the model.

An answer's saved tool calls are the steps. Each gene-specific step is re-run with the new genes swapped
in: one call per step through the batch tool where one exists, otherwise one call per gene. Steps that
are not about a single gene (a trial meta-analysis, a pathway enrichment, a literature search) are
listed as not repeated. The result starts with a combined table: one row per gene and one headline
value per step.
"""

import json
import statistics
from typing import Any, Dict, List, Optional, Tuple

MAX_REPEAT_GENES = 10
# Per-gene steps without a batch tool draw a section per call, so their details are shown for the first
# few genes only; the combined table always covers every gene
DETAIL_GENES = 3

# Gene-specific tools and the argument that names the gene
_GENE_ARG = {
    "linkedomics::compare_cptac_tumor_normal_expression": "protein",
    "linkedomics::analyze_cptac_gene_survival_associations": "protein",
    "linkedomics::get_drug_target_profile": "protein",
    "linkedomics::search_gene_response_trials": "protein",
    "linkedomics::analyze_cptac_cis_associations": "protein",
    "linkedomics::get_funmap_functional_neighborhood": "protein",
    "linkedomics::analyze_tcga_survival_associations": "gene",
    "linkedomics::analyze_tcga_cis_associations": "gene",
}
_BATCH_OF = {
    "linkedomics::compare_cptac_tumor_normal_expression": "linkedomics::batch_compare_cptac_tumor_normal_expression",
    "linkedomics::analyze_cptac_gene_survival_associations": "linkedomics::batch_analyze_cptac_gene_survival_associations",
    "linkedomics::get_drug_target_profile": "linkedomics::batch_get_drug_target_profiles",
    "linkedomics::search_gene_response_trials": "linkedomics::batch_search_gene_response_trials",
    "linkedomics::analyze_cptac_cis_associations": "linkedomics::batch_analyze_cptac_cis_associations",
}
_SINGLE_OF = {batch: single for single, batch in _BATCH_OF.items()}

_LABELS = {
    "linkedomics::compare_cptac_tumor_normal_expression": "Tumor vs normal (CPTAC)",
    "linkedomics::analyze_cptac_gene_survival_associations": "Survival (CPTAC)",
    "linkedomics::analyze_tcga_survival_associations": "Survival (TCGA)",
    "linkedomics::get_drug_target_profile": "Drug target",
    "linkedomics::search_gene_response_trials": "Treatment response",
    "linkedomics::analyze_cptac_cis_associations": "Cis-correlations (CPTAC)",
    "linkedomics::analyze_tcga_cis_associations": "Cis-correlations (TCGA)",
    "linkedomics::get_funmap_functional_neighborhood": "FunMap neighbors",
    # Steps that are not about one gene, named for the "not repeated" note
    "literature::search_pubmed_articles": "literature search",
    "literature::get_pubmed_article_details": "article details",
    "linkedomics::run_webgestalt_go_enrichment": "pathway enrichment",
    "linkedomics::search_trial_studies": "study search",
    "linkedomics::get_trial_study_details": "study details",
    "linkedomics::meta_analyze_response_genes": "response meta-analysis",
    "linkedomics::meta_analyze_response_gene_sets": "gene set meta-analysis",
    "linkedomics::rank_study_response_genes": "study gene ranking",
    "linkedomics::rank_study_response_gene_sets": "study gene set ranking",
    "linkedomics::match_signature_to_treatment_response": "treatment response matching",
    "linkedomics::search_gene_set_response_trials": "gene set response search",
    "linkedomics::rank_drug_targets": "target ranking",
    "linkedomics::search_drug_target_index": "target index search",
}


def _label(tool_id: str, args: Dict[str, Any]) -> str:
    label = _LABELS.get(tool_id, tool_id.split("::")[-1].replace("_", " "))
    detail = " ".join(str(args[k]) for k in ("cohort", "omics") if args.get(k))
    return f"{label}, {detail}" if detail else label


def plan_repeat(tool_calls: List[Dict[str, Any]], genes: List[str]) -> Dict[str, Any]:
    """Turn an answer's tool calls into the calls that repeat them for ``genes``."""
    steps: List[Dict[str, Any]] = []
    calls: List[Tuple[str, Dict[str, Any]]] = []
    skipped: List[str] = []
    seen_steps = set()
    for call in tool_calls:
        tool_id = str(call.get("tool_id") or "")
        args = dict(call.get("arguments") or {})
        if call.get("status") in ("error", "missing"):
            continue  # did not run in the chat either
        if tool_id in _SINGLE_OF:
            base, gene_key = _SINGLE_OF[tool_id], "protein"
            base_args = {k: v for k, v in args.items() if k != "proteins"}
        elif tool_id in _GENE_ARG and args.get(_GENE_ARG[tool_id]):
            base, gene_key = tool_id, _GENE_ARG[tool_id]
            base_args = {k: v for k, v in args.items() if k != gene_key}
        else:
            label = _label(tool_id, args)
            if label not in skipped and not tool_id.endswith("resolve_gene_identifier"):
                skipped.append(label)
            continue
        step_key = json.dumps([base, base_args], sort_keys=True)
        if step_key in seen_steps:
            continue
        seen_steps.add(step_key)
        step = {"tool_id": base, "args": base_args, "gene_key": gene_key, "label": _label(base, base_args)}
        steps.append(step)
        if len(genes) == 1:
            calls.append((base, {**base_args, gene_key: genes[0]}))
        elif base in _BATCH_OF:
            calls.append((_BATCH_OF[base], {**base_args, "proteins": list(genes)}))
        else:
            calls.extend((base, {**base_args, gene_key: gene}) for gene in genes)
    return {"steps": steps, "calls": calls, "skipped": skipped, "genes": list(genes)}


# ── Headline values for the combined table ────────────────────────────────


def _cohort_counts(payload: Dict[str, Any], layer: str, is_survival: bool) -> Tuple[int, int]:
    from services.mcp_orchestrator import _parse_tile_entry

    up = down = 0
    for message in ((payload.get(layer) or {}).get("data") or {}).values():
        direction, _, significant = _parse_tile_entry(str(message), is_survival)
        if significant:
            up += direction > 0
            down += direction < 0
    return up, down


def _tumor_normal(payload: Dict[str, Any]) -> str:
    pu, pd = _cohort_counts(payload, "protein_level", False)
    ru, rd = _cohort_counts(payload, "RNA_level", False)
    return f"protein ↑{pu} ↓{pd} · RNA ↑{ru} ↓{rd}"


def _cptac_survival(payload: Dict[str, Any]) -> str:
    pu, pd = _cohort_counts(payload, "protein_level", True)
    ru, rd = _cohort_counts(payload, "RNA_level", True)
    high, low = pu + ru, pd + rd
    if not high and not low:
        return "none significant"
    return ", ".join(part for part in (f"high→worse ×{high}" if high else "", f"low→worse ×{low}" if low else "") if part)


def _pvalue(value: Any) -> str:
    return f"{float(value):.2g}"


def _tcga_results(payload: Dict[str, Any], value_key: str, value_label: str) -> str:
    rows = [r for r in (payload.get("results") or []) if isinstance(r, dict) and r.get("pvalue") is not None]
    if not rows:
        return "no data"
    if len(rows) == 1:
        return f"{value_label} {float(rows[0][value_key]):.2f}, p = {_pvalue(rows[0]['pvalue'])}"
    significant = [r for r in rows if float(r["pvalue"]) < 0.05]
    best = min(rows, key=lambda r: float(r["pvalue"]))
    where = best.get("cohort") or best.get("omics") or ""
    return f"{len(significant)} of {len(rows)} p < 0.05; strongest {where} {value_label} {float(best[value_key]):.2f}".replace("  ", " ")


def _drug_target(payload: Dict[str, Any]) -> str:
    profile = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    # The target index writes "NA" for a missing tier or drug list
    tier = str(profile.get("tier") or "").strip()
    drugs = [d for d in str(profile.get("drugs") or "").split(";") if d.strip() and d.strip().upper() != "NA"]
    if not tier or tier.upper() == "NA":
        return "no tier" + (f", {len(drugs)} drug{'s' if len(drugs) != 1 else ''}" if drugs else "")
    return f"{tier}, {len(drugs)} drug{'s' if len(drugs) != 1 else ''}" if drugs else f"{tier}, no drugs"


def _trials(payload: Dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    total = data.get("total_studies")
    if total is None:
        return "no data"
    return f"{data.get('total_significant', 0)} of {total} studies significant"


def _cptac_cis(payload: Dict[str, Any]) -> str:
    values = [
        float(record["val"])
        for records in ((payload.get("data") or {}).values() if isinstance(payload.get("data"), dict) else [])
        for record in (records if isinstance(records, list) else [])
        if isinstance(record, dict) and _is_number(record.get("val"))
    ]
    return f"median r {statistics.median(values):.2f} ({len(values)} values)" if values else "no data"


def _funmap(payload: Dict[str, Any]) -> str:
    neighbors = [str(n) for n in (payload.get("neighborhood") or [])]
    return ", ".join(neighbors[:3]) + (f" +{len(neighbors) - 3}" if len(neighbors) > 3 else "") if neighbors else "not in FunMap"


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


_HEADLINES = {
    "linkedomics::compare_cptac_tumor_normal_expression": _tumor_normal,
    "linkedomics::analyze_cptac_gene_survival_associations": _cptac_survival,
    "linkedomics::analyze_tcga_survival_associations": lambda p: _tcga_results(p, "hr", "HR"),
    "linkedomics::get_drug_target_profile": _drug_target,
    "linkedomics::search_gene_response_trials": _trials,
    "linkedomics::analyze_cptac_cis_associations": _cptac_cis,
    "linkedomics::analyze_tcga_cis_associations": lambda p: _tcga_results(p, "correlation", "r"),
    "linkedomics::get_funmap_functional_neighborhood": _funmap,
}


def _payload_for(raw_results: Dict[str, Any], step: Dict[str, Any], gene: str) -> Optional[Dict[str, Any]]:
    """The result of one step for one gene, from a single-gene or a batch call."""
    base, gene_key, args = step["tool_id"], step["gene_key"], step["args"]
    for key, wrapped in raw_results.items():
        tool_id = key.rsplit("#", 1)[0]
        call_args = (wrapped or {}).get("_args") or {}
        if any(call_args.get(k) != v for k, v in args.items()):
            continue
        result = (wrapped or {}).get("_result")
        if not isinstance(result, dict):
            continue
        if tool_id == base and str(call_args.get(gene_key, "")).upper() == gene:
            return result
        if tool_id == _BATCH_OF.get(base) and gene in [str(g).upper() for g in call_args.get("proteins") or []]:
            entry = (result.get("data") or {}).get(gene)
            return entry if isinstance(entry, dict) else None
    return None


def combined_table(plan: Dict[str, Any], raw_results: Dict[str, Any]) -> str:
    """The combined table that opens a repeat answer, with a short key and any steps not repeated."""
    steps, genes = plan["steps"], plan["genes"]
    lines: List[str] = []
    if steps:
        lines.append(f"## Repeated analyses: {len(genes)} {'gene' if len(genes) == 1 else 'genes'}")
        lines.append("")
        lines.append("| Gene | " + " | ".join(step["label"] for step in steps) + " |")
        lines.append("|---" * (len(steps) + 1) + "|")
        for gene in genes:
            cells = []
            for step in steps:
                payload = _payload_for(raw_results, step, gene)
                if payload is None:
                    cells.append("no result")
                elif payload.get("error") or payload.get("status") == "error":
                    cells.append("error")
                else:
                    try:
                        cells.append(_HEADLINES.get(step["tool_id"], lambda _p: "done")(payload))
                    except Exception:
                        cells.append("see details")
            lines.append(f"| {gene} | " + " | ".join(cells) + " |")
        lines.append("")
        key = []
        if any(s["tool_id"].endswith("compare_cptac_tumor_normal_expression") for s in steps):
            key.append("Tumor vs normal counts the CPTAC cohorts where levels are significantly higher (↑) or lower (↓) in tumors.")
        if any(s["tool_id"].endswith("analyze_cptac_gene_survival_associations") for s in steps):
            key.append("Survival (CPTAC) counts the cohorts where higher (high→worse) or lower (low→worse) levels go with worse survival.")
        detail_steps = [s["label"] for s in steps if s["tool_id"] not in _BATCH_OF]
        if len(genes) > DETAIL_GENES and detail_steps:
            key.append(f"Details below show {', '.join(detail_steps)} for the first {DETAIL_GENES} genes; the table covers all {len(genes)}.")
        if key:
            lines.append("_" + " ".join(key) + "_")
            lines.append("")
    if plan["skipped"]:
        lines.append(f"_Not repeated, because they are not about one gene: {', '.join(plan['skipped'])}._")
        lines.append("")
    return "\n".join(lines).strip()


def detail_results(plan: Dict[str, Any], raw_results: Dict[str, Any]) -> Dict[str, Any]:
    """The results to draw as plots and tables: every batch call, and per-gene calls for the first genes."""
    shown = set(plan["genes"][:DETAIL_GENES])
    kept: Dict[str, Any] = {}
    for key, wrapped in raw_results.items():
        args = (wrapped or {}).get("_args") or {}
        gene = args.get("protein") or args.get("gene")
        if "proteins" in args or gene is None or str(gene).upper() in shown:
            kept[key] = wrapped
    return kept
