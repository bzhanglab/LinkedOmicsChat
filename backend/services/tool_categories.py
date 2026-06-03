"""Canonical tool taxonomy — single source of truth for the backend.

Tools are grouped by their "MCP server" (the data source that backs them),
not by the file they are defined in. Each server maps to an inline citation
source key used in ``[Source](#source:KEY)`` hrefs.

Keep this in sync with frontend/lib/toolCategories.py's counterpart
(frontend/lib/toolCategories.ts).
"""

# Bare tool name (after "::") -> MCP-server category.
TOOL_CATEGORY: dict[str, str] = {
    # ClinicalOmicsDB — clinical trial biomarkers
    "search_gene_response_trials": "ClinicalOmicsDB",
    "batch_search_gene_response_trials": "ClinicalOmicsDB",
    "search_gene_set_response_trials": "ClinicalOmicsDB",
    "search_trial_studies": "ClinicalOmicsDB",
    "meta_analyze_response_genes": "ClinicalOmicsDB",
    "meta_analyze_response_gene_sets": "ClinicalOmicsDB",
    "get_trial_study_details": "ClinicalOmicsDB",
    "rank_study_response_genes": "ClinicalOmicsDB",
    "rank_study_response_gene_sets": "ClinicalOmicsDB",
    # LinkedOmics Targets — drug target index
    "get_drug_target_profile": "LinkedOmics Targets",
    "batch_get_drug_target_profiles": "LinkedOmics Targets",
    "rank_drug_targets": "LinkedOmics Targets",
    "search_drug_target_index": "LinkedOmics Targets",
    # LinkedOmicsKB — CPTAC
    "analyze_cptac_cis_associations": "LinkedOmicsKB",
    "batch_analyze_cptac_cis_associations": "LinkedOmicsKB",
    "compare_cptac_tumor_normal_expression": "LinkedOmicsKB",
    "batch_compare_cptac_tumor_normal_expression": "LinkedOmicsKB",
    "analyze_cptac_gene_survival_associations": "LinkedOmicsKB",
    "batch_analyze_cptac_gene_survival_associations": "LinkedOmicsKB",
    # LinkedOmics — TCGA
    "analyze_tcga_cis_associations": "LinkedOmics",
    "analyze_tcga_survival_associations": "LinkedOmics",
    # FunMap
    "get_funmap_functional_neighborhood": "FunMap",
    # MyGene
    "resolve_gene_identifier": "MyGene",
    # PubMed
    "search_pubmed_articles": "PubMed",
    "get_pubmed_article_details": "PubMed",
    # WebGestalt
    "run_webgestalt_go_enrichment": "WebGestalt",
}

# MCP-server category -> inline citation source key (#source:KEY).
CATEGORY_SOURCE_KEY: dict[str, str] = {
    "ClinicalOmicsDB": "trials",
    "LinkedOmics Targets": "targets",
    "LinkedOmicsKB": "cptac",
    "LinkedOmics": "tcga",
    "FunMap": "funmap",
    "MyGene": "mygene",
    "PubMed": "pubmed",
    "WebGestalt": "webgestalt",
}

# All citation source keys, in display order (used by the LLM prompt + UI).
SOURCE_KEYS: list[str] = list(dict.fromkeys(CATEGORY_SOURCE_KEY.values()))


def bare_tool_name(tool_id_or_name: str) -> str:
    """Strip the ``server::`` prefix and any ``#index`` suffix from a tool id."""
    after_prefix = tool_id_or_name.split("::", 1)[1] if "::" in tool_id_or_name else tool_id_or_name
    return after_prefix.split("#", 1)[0]


def source_key_for_tool(tool_id_or_name: str) -> str | None:
    """Return the inline citation source key for a tool, or None if uncategorized."""
    category = TOOL_CATEGORY.get(bare_tool_name(tool_id_or_name))
    return CATEGORY_SOURCE_KEY.get(category) if category else None


# Bare tool name -> source key, derived from the taxonomy above.
TOOL_SOURCE_KEY: dict[str, str] = {
    name: CATEGORY_SOURCE_KEY[category] for name, category in TOOL_CATEGORY.items()
}
