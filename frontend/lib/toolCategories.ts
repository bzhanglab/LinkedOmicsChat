// Canonical tool taxonomy — single source of truth for the frontend.
//
// Tools are grouped by their "MCP server" (the data source that backs them),
// not by the file they happen to be defined in. Each server has a friendly
// display label, the raw server name (shown as a subtitle/badge), an inline
// citation source key (used in `#source:KEY` hrefs), and a resource URL.
//
// Keep this in sync with backend/services/tool_categories.py.

export type CategoryKey =
    | "ClinicalOmicsDB"
    | "LinkedOmics Targets"
    | "LinkedOmicsKB"
    | "LinkedOmics"
    | "FunMap"
    | "MyGene"
    | "PubMed"
    | "WebGestalt"

export interface CategoryMeta {
    /** Raw "MCP server" name, shown as a subtitle/badge. */
    server: CategoryKey
    /** Human-friendly label shown as the primary heading. */
    label: string
    /** Slug used in inline citations: [Source](#source:sourceKey). */
    sourceKey: string
    /** Canonical resource URL for the underlying data source. */
    url: string
}

export const CATEGORY_META: Record<CategoryKey, CategoryMeta> = {
    "ClinicalOmicsDB": { server: "ClinicalOmicsDB", label: "Clinical Trials", sourceKey: "trials", url: "https://trials.linkedomics.org" },
    "LinkedOmics Targets": { server: "LinkedOmics Targets", label: "Drug Targets", sourceKey: "targets", url: "https://targets.linkedomics.org" },
    "LinkedOmicsKB": { server: "LinkedOmicsKB", label: "CPTAC Multi-omics", sourceKey: "cptac", url: "https://kb.linkedomics.org" },
    "LinkedOmics": { server: "LinkedOmics", label: "TCGA Multi-omics", sourceKey: "tcga", url: "https://www.linkedomics.org" },
    "FunMap": { server: "FunMap", label: "Functional Networks", sourceKey: "funmap", url: "https://funmap.linkedomics.org" },
    "MyGene": { server: "MyGene", label: "Gene Utilities", sourceKey: "mygene", url: "https://mygene.info" },
    "PubMed": { server: "PubMed", label: "Literature", sourceKey: "pubmed", url: "https://pubmed.ncbi.nlm.nih.gov" },
    "WebGestalt": { server: "WebGestalt", label: "Pathway Enrichment", sourceKey: "webgestalt", url: "https://www.webgestalt.org" },
}

/** Bare tool name (after "::") → MCP-server category. */
export const TOOL_CATEGORY: Record<string, CategoryKey> = {
    // ClinicalOmicsDB — clinical trial biomarkers
    search_gene_response_trials: "ClinicalOmicsDB",
    batch_search_gene_response_trials: "ClinicalOmicsDB",
    search_gene_set_response_trials: "ClinicalOmicsDB",
    search_trial_studies: "ClinicalOmicsDB",
    meta_analyze_response_genes: "ClinicalOmicsDB",
    meta_analyze_response_gene_sets: "ClinicalOmicsDB",
    get_trial_study_details: "ClinicalOmicsDB",
    rank_study_response_genes: "ClinicalOmicsDB",
    rank_study_response_gene_sets: "ClinicalOmicsDB",
    // LinkedOmics Targets — drug target index
    get_drug_target_profile: "LinkedOmics Targets",
    batch_get_drug_target_profiles: "LinkedOmics Targets",
    rank_drug_targets: "LinkedOmics Targets",
    search_drug_target_index: "LinkedOmics Targets",
    // LinkedOmicsKB — CPTAC
    analyze_cptac_cis_associations: "LinkedOmicsKB",
    batch_analyze_cptac_cis_associations: "LinkedOmicsKB",
    compare_cptac_tumor_normal_expression: "LinkedOmicsKB",
    batch_compare_cptac_tumor_normal_expression: "LinkedOmicsKB",
    analyze_cptac_gene_survival_associations: "LinkedOmicsKB",
    batch_analyze_cptac_gene_survival_associations: "LinkedOmicsKB",
    // LinkedOmics — TCGA
    analyze_tcga_cis_associations: "LinkedOmics",
    analyze_tcga_survival_associations: "LinkedOmics",
    // FunMap
    get_funmap_functional_neighborhood: "FunMap",
    // MyGene
    resolve_gene_identifier: "MyGene",
    // PubMed
    search_pubmed_articles: "PubMed",
    get_pubmed_article_details: "PubMed",
    // WebGestalt
    run_webgestalt_go_enrichment: "WebGestalt",
}

/** Strip the "server::" prefix and any "#index" suffix from a tool id. */
export function bareToolName(toolIdOrName: string): string {
    const afterPrefix = toolIdOrName.includes("::") ? toolIdOrName.split("::").pop()! : toolIdOrName
    return afterPrefix.replace(/#\d+$/, "")
}

export function categoryForToolName(name: string): CategoryKey | null {
    return TOOL_CATEGORY[bareToolName(name)] ?? null
}

export function categoryForToolId(toolId: string): CategoryKey | null {
    return categoryForToolName(toolId)
}

/** Inline citation source key for a tool, or null if uncategorized. */
export function sourceKeyForTool(toolIdOrName: string): string | null {
    const cat = categoryForToolName(toolIdOrName)
    return cat ? CATEGORY_META[cat].sourceKey : null
}
