"use client"

import { useState } from "react"
import { ArrowRight, Activity, Network, Pill, TrendingUp, FlaskConical, Dna, BarChart2, HeartPulse, ClipboardList, Zap, Library } from "lucide-react"

interface UseCase {
    id: string
    title: string
    description: string
    exampleQuery: string
    tools: string[]
    category: string
    icon: React.ElementType
}

const USE_CASES: UseCase[] = [
    // Expression Analysis
    {
        id: "tumor-normal-expression",
        title: "Tumor vs Normal Expression",
        description: "Check whether a gene is significantly up- or downregulated in a specific CPTAC cohort.",
        exampleQuery: "How is EGFR expressed tumor vs normal in LUAD?",
        tools: ["cancer_gene_expression"],
        category: "Expression Analysis",
        icon: BarChart2,
    },
    {
        id: "cptac-cis-correlations",
        title: "CPTAC Cis-correlations",
        description: "Inspect RNA, protein, methylation, and copy-number relationships for one gene across CPTAC cohorts.",
        exampleQuery: "Show cis-correlations for BRCA1 across CPTAC cohorts.",
        tools: ["get_cis_correlations"],
        category: "Expression Analysis",
        icon: Dna,
    },
    {
        id: "tcga-cis-association",
        title: "TCGA Cis-association",
        description: "Query within-gene cross-omics associations in TCGA for a cohort or across available omics pairs.",
        exampleQuery: "Show cis associations for TP53 in BRCA across available omics pairs.",
        tools: ["tcga_cis_association_analysis"],
        category: "Expression Analysis",
        icon: Activity,
    },
    // Survival Analysis
    {
        id: "survival-brca-overview",
        title: "BRCA Survival Overview",
        description: "Ask whether a gene is associated with overall survival and compare evidence across LinkedOmics cohorts.",
        exampleQuery: "Show TP53 overall survival in BRCA.",
        tools: ["overall_survival_per_cancer", "tcga_survival_analysis"],
        category: "Survival Analysis",
        icon: HeartPulse,
    },
    {
        id: "tcga-methylation-survival",
        title: "TCGA Methylation Survival",
        description: "Focus survival analysis on one TCGA omics layer such as methylation, RNAseq, RPPA, or SCNA.",
        exampleQuery: "Show TP53 methylation survival in BRCA from TCGA.",
        tools: ["tcga_survival_analysis"],
        category: "Survival Analysis",
        icon: HeartPulse,
    },
    {
        id: "multi-omics-survival-comparison",
        title: "Multi-omics Survival Comparison",
        description: "Compare whether different TCGA omics layers for the same gene show distinct survival associations.",
        exampleQuery: "Compare survival impact of ESR1 methylation vs RNA in BRCA.",
        tools: ["tcga_survival_analysis"],
        category: "Survival Analysis",
        icon: Activity,
    },
    // Drug Targets
    {
        id: "single-gene-target",
        title: "Single-gene Target Check",
        description: "Check whether a gene is a validated oncology target and review its evidence tiers.",
        exampleQuery: "Is EGFR a validated oncology target?",
        tools: ["get_target"],
        category: "Drug Targets",
        icon: Pill,
    },
    {
        id: "target-family-search",
        title: "Target Family Search",
        description: "List genes in a target tier, protein family, or antigen class from the full target index.",
        exampleQuery: "Which kinases are FDA-approved oncology targets?",
        tools: ["search_targets"],
        category: "Drug Targets",
        icon: Pill,
    },
    {
        id: "target-antigen-search",
        title: "Tumor Antigen Search",
        description: "Find tumor-associated or tumor-specific antigens within a selected target tier.",
        exampleQuery: "Which genes are tumor-associated antigens in T1 tier?",
        tools: ["search_targets"],
        category: "Drug Targets",
        icon: Dna,
    },
    {
        id: "target-ranking",
        title: "Target Prioritization",
        description: "Rank therapeutic candidates by LinkedOmics evidence, antigen status, and target tier context.",
        exampleQuery: "What are the most attractive therapeutic targets for cancer?",
        tools: ["rank_targets"],
        category: "Drug Targets",
        icon: TrendingUp,
    },
    // Clinical Trials
    {
        id: "single-gene-trial-response",
        title: "Single-gene Treatment Response",
        description: "Find therapies where high expression of one gene predicts sensitivity or resistance.",
        exampleQuery: "Which drugs are patients likely to be resistant to if they have high EGFR expression?",
        tools: ["clinical_trial_information"],
        category: "Clinical Trials",
        icon: FlaskConical,
    },
    {
        id: "multi-gene-trial-response",
        title: "Multi-gene Treatment Response",
        description: "Test a short gene panel against clinical studies to find shared response or resistance signals.",
        exampleQuery: "Which drugs do ESR1 and ERBB2 predict resistance to?",
        tools: ["batch_clinical_trial_information"],
        category: "Clinical Trials",
        icon: FlaskConical,
    },
    {
        id: "pathway-trial-response",
        title: "Pathway Treatment Response",
        description: "Ask whether pathway activity predicts response or resistance to a specific therapy.",
        exampleQuery: "Does the HALLMARK_ESTROGEN_RESPONSE pathway predict tamoxifen sensitivity?",
        tools: ["gene_set_trial_information"],
        category: "Clinical Trials",
        icon: Activity,
    },
    {
        id: "trial-discovery",
        title: "Clinical Study Discovery",
        description: "Find which studies in the trials resource tested a given drug in a specific disease setting.",
        exampleQuery: "Which studies tested nivolumab in melanoma?",
        tools: ["filter_clinical_trials"],
        category: "Clinical Trials",
        icon: ClipboardList,
    },
    {
        id: "trial-gene-meta-analysis",
        title: "Cross-study Gene Meta-analysis",
        description: "Identify genes that repeatedly predict response across matched treatment studies.",
        exampleQuery: "Which genes best predict paclitaxel response in breast cancer?",
        tools: ["meta_analysis_predictive_genes"],
        category: "Clinical Trials",
        icon: TrendingUp,
    },
    {
        id: "trial-pathway-meta-analysis",
        title: "Cross-study Pathway Meta-analysis",
        description: "Identify pathways whose activity consistently predicts treatment resistance or sensitivity.",
        exampleQuery: "What pathways predict platinum resistance in ovarian cancer?",
        tools: ["meta_analysis_predictive_gene_sets"],
        category: "Clinical Trials",
        icon: TrendingUp,
    },
    {
        id: "study-gene-ranking",
        title: "Per-study Gene Ranking",
        description: "Inspect the top gene-level predictors of response within a specific study series.",
        exampleQuery: "Which genes predict response in study GSE25066?",
        tools: ["get_study_predictive_genes"],
        category: "Clinical Trials",
        icon: TrendingUp,
    },
    {
        id: "study-details",
        title: "Study Details Lookup",
        description: "Pull the metadata and study summary for a specific clinical study or series ID.",
        exampleQuery: "What was study GSE25066 about?",
        tools: ["get_study_info"],
        category: "Clinical Trials",
        icon: ClipboardList,
    },
    // Functional Networks
    {
        id: "funmap-neighborhood",
        title: "FunMap Neighborhood",
        description: "Find genes that are functionally connected to a query gene in the proteogenomic network.",
        exampleQuery: "Find functional neighbors of TP53 in the FunMap network.",
        tools: ["funmap_neighborhood"],
        category: "Functional Networks",
        icon: Network,
    },
    {
        id: "target-discovery-pipeline",
        title: "Network-to-target Pipeline",
        description: "Chain neighborhood discovery into target and survival follow-up for candidate prioritization.",
        exampleQuery: "Find functional partners of BRCA1, identify which are druggable oncology targets, and check if any predict survival in breast cancer.",
        tools: ["funmap_neighborhood", "get_target", "overall_survival_per_cancer"],
        category: "Functional Networks",
        icon: Network,
    },
    // Pathway Enrichment
    {
        id: "pathway-enrichment-go",
        title: "GO Enrichment on a Gene List",
        description: "Run pathway enrichment on a custom gene set to summarize shared biological processes.",
        exampleQuery: "Run pathway enrichment analysis on TP53, MDM2, CDKN1A, ATM, and BRCA1.",
        tools: ["webgestalt"],
        category: "Pathway Enrichment",
        icon: Zap,
    },
    {
        id: "pathway-enrichment-panel",
        title: "Enrichment of Oncogenic Panels",
        description: "Test whether a focused oncogene panel converges on common pathways or processes.",
        exampleQuery: "What pathways are enriched in this gene set: EGFR, MET, ERBB2, ALK, RET?",
        tools: ["webgestalt"],
        category: "Pathway Enrichment",
        icon: Zap,
    },
    // Literature
    {
        id: "literature-search",
        title: "PubMed Literature Search",
        description: "Search recent PubMed papers for a gene, disease, drug, or clinical question.",
        exampleQuery: "Find recent papers on ESR1 and breast cancer survival.",
        tools: ["search_pubmed"],
        category: "Literature",
        icon: Library,
    },
    {
        id: "literature-abstract",
        title: "PubMed Abstract Lookup",
        description: "Fetch the title, abstract, and citation details for a specific PMID.",
        exampleQuery: "Get the abstract for PMID 25892560.",
        tools: ["get_pubmed_abstract"],
        category: "Literature",
        icon: Library,
    },
    // Gene Utilities
    {
        id: "resolve-gene-id",
        title: "Gene ID Resolution",
        description: "Resolve Ensembl or UniProt identifiers to HGNC symbols before downstream analysis.",
        exampleQuery: "What gene is ENSG00000141510?",
        tools: ["resolve_gene_identifier"],
        category: "Gene Utilities",
        icon: Dna,
    },
]

interface CategoryDef {
    label: string
    icon: React.ElementType
    color: string
    borderColor: string
}

const CATEGORIES: CategoryDef[] = [
    {
        label: "Expression Analysis",
        icon: BarChart2,
        color: "bg-teal-100 text-teal-600 dark:bg-teal-900/30 dark:text-teal-400",
        borderColor: "border-teal-400 dark:border-teal-500",
    },
    {
        label: "Survival Analysis",
        icon: HeartPulse,
        color: "bg-rose-100 text-rose-600 dark:bg-rose-900/30 dark:text-rose-400",
        borderColor: "border-rose-400 dark:border-rose-500",
    },
    {
        label: "Drug Targets",
        icon: Pill,
        color: "bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400",
        borderColor: "border-amber-400 dark:border-amber-500",
    },
    {
        label: "Clinical Trials",
        icon: ClipboardList,
        color: "bg-rose-100 text-rose-600 dark:bg-rose-900/30 dark:text-rose-400",
        borderColor: "border-rose-400 dark:border-rose-500",
    },
    {
        label: "Pathway Enrichment",
        icon: FlaskConical,
        color: "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400",
        borderColor: "border-emerald-400 dark:border-emerald-500",
    },
    {
        label: "Functional Networks",
        icon: Network,
        color: "bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400",
        borderColor: "border-blue-400 dark:border-blue-500",
    },
    {
        label: "Literature",
        icon: Library,
        color: "bg-indigo-100 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400",
        borderColor: "border-indigo-400 dark:border-indigo-500",
    },
    {
        label: "Gene Utilities",
        icon: Dna,
        color: "bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400",
        borderColor: "border-violet-400 dark:border-violet-500",
    },
]

const TOOL_LABELS: Record<string, string> = {
    resolve_gene_identifier: "ID Resolve",
    cancer_gene_expression: "Expression",
    overall_survival_per_cancer: "Survival",
    tcga_survival_analysis: "TCGA Survival",
    get_cis_correlations: "Cis-correlation",
    tcga_cis_association_analysis: "TCGA Cis",
    get_target: "Drug Target",
    search_targets: "Target Search",
    rank_targets: "Target Ranking",
    clinical_trial_information: "Clinical Trials",
    batch_clinical_trial_information: "Batch Trials",
    get_study_info: "Study Details",
    gene_set_trial_information: "Pathway Trials",
    filter_clinical_trials: "Trial Filter",
    meta_analysis_predictive_genes: "Gene Meta-analysis",
    meta_analysis_predictive_gene_sets: "Pathway Meta-analysis",
    get_study_predictive_genes: "Study Gene Rankings",
    get_study_predictive_gene_sets: "Study Pathway Rankings",
    funmap_neighborhood: "FunMap Network",
    webgestalt: "Pathway Enrichment",
    search_pubmed: "PubMed Search",
    get_pubmed_abstract: "PubMed Abstract",
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
        ? USE_CASES.filter((uc) => uc.category === activeCategory)
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
                            const items = USE_CASES.filter((uc) => uc.category === cat.label)
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
