"use client"

import { useState } from "react"
import { ArrowRight, Activity, Network, Pill, TrendingUp, FlaskConical, Dna, BarChart2, HeartPulse, ClipboardList, Zap, Library } from "lucide-react"
import { CATEGORY_META, categoryForToolName, type CategoryKey } from "@/lib/toolCategories"

interface UseCase {
    id: string
    title: string
    description: string
    exampleQuery: string
    tools: string[]
    icon: React.ElementType
}

const USE_CASES: UseCase[] = [
    // Expression Analysis
    {
        id: "tumor-normal-expression",
        title: "Tumor vs Normal Expression",
        description: "Check whether a gene is significantly up- or downregulated in a specific CPTAC cohort.",
        exampleQuery: "How is EGFR expressed tumor vs normal in LUAD?",
        tools: ["compare_cptac_tumor_normal_expression"],
        icon: BarChart2,
    },
    {
        id: "cptac-cis-correlations",
        title: "CPTAC Cis-correlations",
        description: "Inspect RNA, protein, methylation, and copy-number relationships for one gene across CPTAC cohorts.",
        exampleQuery: "Show cis-correlations for BRCA1 across CPTAC cohorts.",
        tools: ["analyze_cptac_cis_associations"],
        icon: Dna,
    },
    {
        id: "tcga-cis-association",
        title: "TCGA Cis-association",
        description: "Query within-gene cross-omics associations in TCGA for a cohort or across available omics pairs.",
        exampleQuery: "Show cis associations for TP53 in BRCA across available omics pairs.",
        tools: ["analyze_tcga_cis_associations"],
        icon: Activity,
    },
    // Survival Analysis
    {
        id: "survival-brca-overview",
        title: "BRCA Survival Overview",
        description: "Ask whether a gene is associated with overall survival and compare evidence across LinkedOmics cohorts.",
        exampleQuery: "Show TP53 overall survival in BRCA.",
        tools: ["analyze_cptac_gene_survival_associations", "analyze_tcga_survival_associations"],
        icon: HeartPulse,
    },
    {
        id: "tcga-methylation-survival",
        title: "TCGA Methylation Survival",
        description: "Focus survival analysis on one TCGA omics layer such as methylation, RNAseq, RPPA, or SCNA.",
        exampleQuery: "Show TP53 methylation survival in BRCA from TCGA.",
        tools: ["analyze_tcga_survival_associations"],
        icon: HeartPulse,
    },
    {
        id: "multi-omics-survival-comparison",
        title: "Multi-omics Survival Comparison",
        description: "Compare whether different TCGA omics layers for the same gene show distinct survival associations.",
        exampleQuery: "Compare survival impact of ESR1 methylation vs RNA in BRCA.",
        tools: ["analyze_tcga_survival_associations"],
        icon: Activity,
    },
    // Drug Targets
    {
        id: "single-gene-target",
        title: "Single-gene Target Check",
        description: "Check whether a gene is a validated oncology target and review its evidence tiers.",
        exampleQuery: "Is EGFR a validated oncology target?",
        tools: ["get_drug_target_profile"],
        icon: Pill,
    },
    {
        id: "target-family-search",
        title: "Target Family Search",
        description: "List genes in a target tier, protein family, or antigen class from the full target index.",
        exampleQuery: "Which kinases are FDA-approved oncology targets?",
        tools: ["search_drug_target_index"],
        icon: Pill,
    },
    {
        id: "target-antigen-search",
        title: "Tumor Antigen Search",
        description: "Find tumor-associated or tumor-specific antigens within a selected target tier.",
        exampleQuery: "Which genes are tumor-associated antigens in T1 tier?",
        tools: ["search_drug_target_index"],
        icon: Dna,
    },
    {
        id: "target-ranking",
        title: "Target Prioritization",
        description: "Rank therapeutic candidates by LinkedOmics evidence, antigen status, and target tier context.",
        exampleQuery: "What are the most attractive therapeutic targets for cancer?",
        tools: ["rank_drug_targets"],
        icon: TrendingUp,
    },
    // Clinical Trials
    {
        id: "single-gene-trial-response",
        title: "Single-gene Treatment Response",
        description: "Find therapies where high expression of one gene predicts sensitivity or resistance.",
        exampleQuery: "Which drugs are patients likely to be resistant to if they have high EGFR expression?",
        tools: ["search_gene_response_trials"],
        icon: FlaskConical,
    },
    {
        id: "multi-gene-trial-response",
        title: "Multi-gene Treatment Response",
        description: "Test a short gene panel against clinical studies to find shared response or resistance signals.",
        exampleQuery: "Which drugs do ESR1 and ERBB2 predict resistance to?",
        tools: ["batch_search_gene_response_trials"],
        icon: FlaskConical,
    },
    {
        id: "pathway-trial-response",
        title: "Pathway Treatment Response",
        description: "Ask whether pathway activity predicts response or resistance to a specific therapy.",
        exampleQuery: "Does the HALLMARK_ESTROGEN_RESPONSE pathway predict tamoxifen sensitivity?",
        tools: ["search_gene_set_response_trials"],
        icon: Activity,
    },
    {
        id: "trial-discovery",
        title: "Clinical Study Discovery",
        description: "Find which studies in the trials resource tested a given drug in a specific disease setting.",
        exampleQuery: "Which studies tested nivolumab in melanoma?",
        tools: ["search_trial_studies"],
        icon: ClipboardList,
    },
    {
        id: "trial-gene-meta-analysis",
        title: "Cross-study Gene Meta-analysis",
        description: "Identify genes that repeatedly predict response across matched treatment studies.",
        exampleQuery: "Which genes best predict paclitaxel response in breast cancer?",
        tools: ["meta_analyze_response_genes"],
        icon: TrendingUp,
    },
    {
        id: "trial-pathway-meta-analysis",
        title: "Cross-study Pathway Meta-analysis",
        description: "Identify pathways whose activity consistently predicts treatment resistance or sensitivity.",
        exampleQuery: "What pathways predict platinum resistance in ovarian cancer?",
        tools: ["meta_analyze_response_gene_sets"],
        icon: TrendingUp,
    },
    {
        id: "study-gene-ranking",
        title: "Per-study Gene Ranking",
        description: "Inspect the top gene-level predictors of response within a specific study series.",
        exampleQuery: "Which genes predict response in study GSE25066?",
        tools: ["rank_study_response_genes"],
        icon: TrendingUp,
    },
    {
        id: "study-details",
        title: "Study Details Lookup",
        description: "Pull the metadata and study summary for a specific clinical study or series ID.",
        exampleQuery: "What was study GSE25066 about?",
        tools: ["get_trial_study_details"],
        icon: ClipboardList,
    },
    // Functional Networks
    {
        id: "funmap-neighborhood",
        title: "FunMap Neighborhood",
        description: "Find genes that are functionally connected to a query gene in the proteogenomic network.",
        exampleQuery: "Find functional neighbors of TP53 in the FunMap network.",
        tools: ["get_funmap_functional_neighborhood"],
        icon: Network,
    },
    {
        id: "target-discovery-pipeline",
        title: "Network-to-target Pipeline",
        description: "Chain neighborhood discovery into target and survival follow-up for candidate prioritization.",
        exampleQuery: "Find functional partners of BRCA1, identify which are druggable oncology targets, and check if any predict survival in breast cancer.",
        tools: ["get_funmap_functional_neighborhood", "get_drug_target_profile", "analyze_cptac_gene_survival_associations"],
        icon: Network,
    },
    // Pathway Enrichment
    {
        id: "pathway-enrichment-go",
        title: "GO Enrichment on a Gene List",
        description: "Run pathway enrichment on a custom gene set to summarize shared biological processes.",
        exampleQuery: "Run pathway enrichment analysis on TP53, MDM2, CDKN1A, ATM, and BRCA1.",
        tools: ["run_webgestalt_go_enrichment"],
        icon: Zap,
    },
    {
        id: "pathway-enrichment-panel",
        title: "Enrichment of Oncogenic Panels",
        description: "Test whether a focused oncogene panel converges on common pathways or processes.",
        exampleQuery: "What pathways are enriched in this gene set: EGFR, MET, ERBB2, ALK, RET?",
        tools: ["run_webgestalt_go_enrichment"],
        icon: Zap,
    },
    // Literature
    {
        id: "literature-search",
        title: "PubMed Literature Search",
        description: "Search recent PubMed papers for a gene, disease, drug, or clinical question.",
        exampleQuery: "Find recent papers on ESR1 and breast cancer survival.",
        tools: ["search_pubmed_articles"],
        icon: Library,
    },
    {
        id: "literature-abstract",
        title: "PubMed Abstract Lookup",
        description: "Fetch the title, abstract, and citation details for a specific PMID.",
        exampleQuery: "Get the abstract for PMID 25892560.",
        tools: ["get_pubmed_article_details"],
        icon: Library,
    },
    // Gene Utilities
    {
        id: "resolve-gene-id",
        title: "Gene ID Resolution",
        description: "Resolve Ensembl or UniProt identifiers to HGNC symbols before downstream analysis.",
        exampleQuery: "What gene is ENSG00000141510?",
        tools: ["resolve_gene_identifier"],
        icon: Dna,
    },
]

interface CategoryDef {
    key: CategoryKey
    label: string
    server: string
    icon: React.ElementType
    color: string
    borderColor: string
}

// Presentational config per MCP-server category. Labels and server names come
// from the canonical taxonomy (toolCategories).
const CATEGORY_STYLE: Record<CategoryKey, { icon: React.ElementType; color: string; borderColor: string }> = {
    "ClinicalOmicsDB": { icon: ClipboardList, color: "bg-rose-100 text-rose-600 dark:bg-rose-900/30 dark:text-rose-400", borderColor: "border-rose-400 dark:border-rose-500" },
    "LinkedOmics Targets": { icon: Pill, color: "bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400", borderColor: "border-amber-400 dark:border-amber-500" },
    "LinkedOmicsKB": { icon: BarChart2, color: "bg-teal-100 text-teal-600 dark:bg-teal-900/30 dark:text-teal-400", borderColor: "border-teal-400 dark:border-teal-500" },
    "LinkedOmics": { icon: HeartPulse, color: "bg-cyan-100 text-cyan-600 dark:bg-cyan-900/30 dark:text-cyan-400", borderColor: "border-cyan-400 dark:border-cyan-500" },
    "FunMap": { icon: Network, color: "bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400", borderColor: "border-blue-400 dark:border-blue-500" },
    "WebGestalt": { icon: FlaskConical, color: "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400", borderColor: "border-emerald-400 dark:border-emerald-500" },
    "PubMed": { icon: Library, color: "bg-indigo-100 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400", borderColor: "border-indigo-400 dark:border-indigo-500" },
    "MyGene": { icon: Dna, color: "bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400", borderColor: "border-violet-400 dark:border-violet-500" },
}

const CATEGORY_ORDER: CategoryKey[] = [
    "ClinicalOmicsDB", "LinkedOmics Targets", "LinkedOmicsKB", "LinkedOmics",
    "FunMap", "WebGestalt", "PubMed", "MyGene",
]

const CATEGORIES: CategoryDef[] = CATEGORY_ORDER.map((key) => ({
    key,
    label: CATEGORY_META[key].label,
    server: CATEGORY_META[key].server,
    ...CATEGORY_STYLE[key],
}))

// A use case's category is derived from its primary tool's MCP server.
const useCaseCategory = (uc: UseCase): string =>
    CATEGORY_META[(categoryForToolName(uc.tools[0]) ?? "MyGene") as CategoryKey].label

const TOOL_LABELS: Record<string, string> = {
    resolve_gene_identifier: "ID Resolve",
    compare_cptac_tumor_normal_expression: "Expression",
    analyze_cptac_gene_survival_associations: "Survival",
    analyze_tcga_survival_associations: "TCGA Survival",
    analyze_cptac_cis_associations: "Cis-correlation",
    analyze_tcga_cis_associations: "TCGA Cis",
    get_drug_target_profile: "Drug Target",
    search_drug_target_index: "Target Search",
    rank_drug_targets: "Target Ranking",
    search_gene_response_trials: "Clinical Trials",
    batch_search_gene_response_trials: "Batch Trials",
    get_trial_study_details: "Study Details",
    search_gene_set_response_trials: "Pathway Trials",
    search_trial_studies: "Trial Filter",
    meta_analyze_response_genes: "Gene Meta-analysis",
    meta_analyze_response_gene_sets: "Pathway Meta-analysis",
    rank_study_response_genes: "Study Gene Rankings",
    rank_study_response_gene_sets: "Study Pathway Rankings",
    get_funmap_functional_neighborhood: "FunMap Network",
    run_webgestalt_go_enrichment: "Pathway Enrichment",
    search_pubmed_articles: "PubMed Search",
    get_pubmed_article_details: "PubMed Abstract",
}

function UseCaseCard({ uc, catDef, onStartChat }: {
    uc: UseCase
    catDef: CategoryDef | undefined
    onStartChat: (q: string) => void
}) {
    const Icon = uc.icon
    const color = catDef?.color ?? "bg-teal-100 text-teal-600 dark:bg-teal-900/30 dark:text-teal-400"
    return (
        <button
            onClick={() => onStartChat(uc.exampleQuery)}
            className="group flex flex-col items-start text-left p-4 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:border-teal-300 dark:hover:border-teal-700 hover:bg-teal-50/50 dark:hover:bg-teal-900/20 hover:shadow-md border-l-4 border-l-transparent hover:border-l-teal-400 dark:hover:border-l-teal-500 transition-all duration-200"
        >
            {/* Example query — hero */}
            <p className="text-base font-medium text-gray-900 dark:text-gray-100 group-hover:text-teal-700 dark:group-hover:text-teal-300 transition-colors leading-snug mb-3">
                &ldquo;{uc.exampleQuery}&rdquo;
            </p>

            {/* Divider */}
            <div className="w-full border-t border-gray-100 dark:border-gray-700 mb-3" />

            {/* Icon + title + description */}
            <div className="flex items-start gap-2 w-full mb-2">
                <div className={`h-6 w-6 rounded-md flex items-center justify-center flex-shrink-0 mt-0.5 ${color} opacity-70`}>
                    <Icon className="h-3 w-3" />
                </div>
                <div className="min-w-0">
                    <p className="text-xs font-medium text-gray-500 dark:text-gray-400 leading-snug">
                        {uc.title}
                    </p>
                    <p className="text-xs text-gray-400 dark:text-gray-500 leading-relaxed line-clamp-2 mt-0.5">
                        {uc.description}
                    </p>
                </div>
            </div>

            {/* Tool badges + CTA */}
            <div className="flex items-center justify-between w-full mt-auto pt-1">
                <div className="flex flex-wrap gap-1">
                    {uc.tools.map((tool) => (
                        <span
                            key={tool}
                            className="text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-400 dark:text-gray-500 font-mono"
                        >
                            {TOOL_LABELS[tool] ?? tool}
                        </span>
                    ))}
                </div>
                <div className="flex items-center gap-1 text-xs font-medium text-teal-500 dark:text-teal-400 group-hover:text-teal-600 dark:group-hover:text-teal-300 transition-colors shrink-0 ml-2">
                    Ask
                    <ArrowRight className="w-3 h-3" />
                </div>
            </div>
        </button>
    )
}

interface UseCasesPanelProps {
    onStartChat: (query: string) => void
}

export function UseCasesPanel({ onStartChat }: UseCasesPanelProps) {
    const [activeCategory, setActiveCategory] = useState<string | null>(null)

    const filtered = activeCategory
        ? USE_CASES.filter((uc) => useCaseCategory(uc) === activeCategory)
        : USE_CASES

    const activeCatDef = CATEGORIES.find((c) => c.label === activeCategory)

    return (
        <div className="flex flex-col h-full bg-gray-50 dark:bg-gray-900">
            {/* Header */}
            <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
                <ArrowRight className="h-5 w-5 text-teal-500" />
                <h2 className="font-semibold text-gray-900 dark:text-white">Use Cases</h2>
            </div>

            {/* Sticky category pills */}
            <div className="shrink-0 px-4 py-3 bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700">
                <div className="flex flex-wrap gap-2">
                    <button
                        onClick={() => setActiveCategory(null)}
                        className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                            activeCategory === null
                                ? "bg-gray-800 dark:bg-gray-100 text-white dark:text-gray-900 border-gray-800 dark:border-gray-100"
                                : "bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700 hover:border-gray-400"
                        }`}
                    >
                        All
                    </button>
                    {CATEGORIES.map((cat) => {
                        const Icon = cat.icon
                        const isActive = activeCategory === cat.label
                        return (
                            <button
                                key={cat.label}
                                onClick={() => setActiveCategory(isActive ? null : cat.label)}
                                className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                                    isActive
                                        ? `${cat.color} ${cat.borderColor}`
                                        : "bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700 hover:border-gray-400"
                                }`}
                            >
                                <Icon className="h-3 w-3" />
                                {cat.label}
                            </button>
                        )
                    })}
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4">

                {/* Flat grid when filtered */}
                {activeCategory ? (
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                        {filtered.map((uc) => (
                            <UseCaseCard key={uc.id} uc={uc} catDef={activeCatDef} onStartChat={onStartChat} />
                        ))}
                    </div>
                ) : (
                    /* Grouped by category when "All" */
                    <div className="space-y-6">
                        {CATEGORIES.map((cat) => {
                            const Icon = cat.icon
                            const items = USE_CASES.filter((uc) => useCaseCategory(uc) === cat.label)
                            if (items.length === 0) return null
                            return (
                                <div key={cat.label}>
                                    <div className="flex items-center gap-2 mb-3">
                                        <div className={`h-6 w-6 rounded-md flex items-center justify-center ${cat.color}`}>
                                            <Icon className="h-3.5 w-3.5" />
                                        </div>
                                        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                                            {cat.label}
                                        </h3>
                                        <span className="text-[10px] font-medium text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">{cat.server}</span>
                                        <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
                                        <span className="text-xs text-gray-400">{items.length}</span>
                                    </div>
                                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                        {items.map((uc) => (
                                            <UseCaseCard key={uc.id} uc={uc} catDef={cat} onStartChat={onStartChat} />
                                        ))}
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}

                <p className="text-xs text-gray-400 dark:text-gray-500 pt-2">
                    These prompts are aligned with the current toolset and are intended to work well as one-click starting points.
                </p>
            </div>
        </div>
    )
}
