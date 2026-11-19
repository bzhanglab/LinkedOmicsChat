import type { ToolCallRecord } from "./api"

// The gene-specific tools a repeat can re-run, and the argument that names the gene.
// Keep in sync with _GENE_ARG and _BATCH_OF in backend/services/repeat_workflow.py.
const GENE_ARG: Record<string, string> = {
    "linkedomics::compare_cptac_tumor_normal_expression": "protein",
    "linkedomics::analyze_cptac_gene_survival_associations": "protein",
    "linkedomics::get_drug_target_profile": "protein",
    "linkedomics::search_gene_response_trials": "protein",
    "linkedomics::analyze_cptac_cis_associations": "protein",
    "linkedomics::get_funmap_functional_neighborhood": "protein",
    "linkedomics::analyze_tcga_survival_associations": "gene",
    "linkedomics::analyze_tcga_cis_associations": "gene",
}
const BATCH_TOOLS = new Set([
    "linkedomics::batch_compare_cptac_tumor_normal_expression",
    "linkedomics::batch_analyze_cptac_gene_survival_associations",
    "linkedomics::batch_get_drug_target_profiles",
    "linkedomics::batch_search_gene_response_trials",
    "linkedomics::batch_analyze_cptac_cis_associations",
])

function ran(call: ToolCallRecord): boolean {
    return call.status !== "error" && call.status !== "missing"
}

/** The calls in an answer that a repeat would run again for other genes. */
export function repeatableCalls(calls?: ToolCallRecord[]): ToolCallRecord[] {
    return (calls ?? []).filter((call) => {
        if (!ran(call)) return false
        if (BATCH_TOOLS.has(call.tool_id)) return true
        const geneArg = GENE_ARG[call.tool_id]
        return !!geneArg && !!call.arguments?.[geneArg]
    })
}

/** Calls that ran but are not about one gene (a meta-analysis, an enrichment, a literature search). */
export function notRepeatableCalls(calls?: ToolCallRecord[]): ToolCallRecord[] {
    const repeatable = new Set(repeatableCalls(calls))
    return (calls ?? []).filter((call) => ran(call) && !repeatable.has(call) && !call.tool_id.endsWith("resolve_gene_identifier"))
}

/** The gene or genes a call used, for showing the steps. */
export function callGenes(call: ToolCallRecord): string {
    const args = call.arguments ?? {}
    const proteins = args.proteins
    if (Array.isArray(proteins)) return proteins.length > 3 ? `${proteins.length} genes` : proteins.join(", ")
    return String(args[GENE_ARG[call.tool_id]] ?? "")
}
