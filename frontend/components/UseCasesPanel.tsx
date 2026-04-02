"use client"

import { useState } from "react"
import { ArrowRight, Activity, Network, Pill, TrendingUp, FlaskConical, Dna, BarChart2, HeartPulse, ClipboardList, Zap } from "lucide-react"

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
        id: "pan-cancer-expression",
        title: "Pan-cancer Expression Screen",
        description: "Check whether a gene is overexpressed or downregulated in tumor vs. normal tissue across 10 cancer types, at both RNA and protein levels.",
        exampleQuery: "Is EGFR overexpressed at the protein level in lung cancer compared to normal tissue?",
        tools: ["cancer_gene_expression"],
        category: "Expression Analysis",
        icon: BarChart2,
    },
    {
        id: "multi-omics-regulation",
        title: "Multi-omics Regulatory Analysis",
        description: "Identify what drives a gene's expression — RNA transcription, gene copy number amplification (SCNV), or DNA methylation silencing.",
        exampleQuery: "What drives EGFR overexpression in glioblastoma — gene amplification, methylation, or RNA levels?",
        tools: ["get_cis_correlations", "cancer_gene_expression"],
        category: "Expression Analysis",
        icon: Dna,
    },
    // Survival Analysis
    {
        id: "survival-biomarker",
        title: "Survival Biomarker Analysis",
        description: "Determine whether high or low expression of a gene is associated with better or worse overall survival across cancer cohorts.",
        exampleQuery: "Does high ESR1 expression predict better or worse survival in breast cancer?",
        tools: ["overall_survival_per_cancer", "cancer_gene_expression"],
        category: "Survival Analysis",
        icon: HeartPulse,
    },
    // Drug Targets
    {
        id: "drug-target",
        title: "Drug Target Assessment",
        description: "Look up whether a gene is an FDA-approved oncology target, identify associated drugs, and check cancer cell line dependency.",
        exampleQuery: "Is TP53 a druggable oncology target, and what drugs or clinical trials are associated with it?",
        tools: ["get_target", "clinical_trial_information"],
        category: "Drug Targets",
        icon: Pill,
    },
    {
        id: "treatment-resistance",
        title: "Treatment Response Prediction",
        description: "Find drugs where a gene's expression level predicts sensitivity or resistance, based on clinical trial and pharmacogenomics data.",
        exampleQuery: "Which chemotherapy drugs are patients with high BRCA1 expression likely to be resistant to?",
        tools: ["clinical_trial_information"],
        category: "Drug Targets",
        icon: FlaskConical,
    },
    // Clinical Trials
    {
        id: "chemotherapy-biomarkers",
        title: "Chemotherapy Biomarker Discovery",
        description: "Run a meta-analysis across all chemotherapy clinical studies to identify which genes most strongly predict sensitivity or resistance.",
        exampleQuery: "Which genes are most predictive of chemotherapy response across all studies?",
        tools: ["meta_analysis_predictive_genes"],
        category: "Clinical Trials",
        icon: FlaskConical,
    },
    {
        id: "immunotherapy-pathways",
        title: "Immunotherapy Pathway Predictors",
        description: "Identify biological pathways whose activity predicts response to checkpoint inhibitor immunotherapy across multiple clinical studies.",
        exampleQuery: "Which pathways predict immunotherapy sensitivity across clinical trials?",
        tools: ["meta_analysis_predictive_gene_sets"],
        category: "Clinical Trials",
        icon: Activity,
    },
    {
        id: "study-gene-ranking",
        title: "Per-Study Gene Rankings",
        description: "Get the ranked list of genes predicting treatment response within a specific clinical study, and look up its details and abstract.",
        exampleQuery: "What genes best predict paclitaxel response in study GSE25066, and what was that study about?",
        tools: ["get_study_predictive_genes", "get_study_info"],
        category: "Clinical Trials",
        icon: TrendingUp,
    },
    {
        id: "filter-trials",
        title: "Clinical Study Discovery",
        description: "Find which clinical studies in the database tested a specific drug or treatment class in a given cancer type.",
        exampleQuery: "Which studies tested nivolumab in melanoma?",
        tools: ["filter_clinical_trials"],
        category: "Clinical Trials",
        icon: ClipboardList,
    },
    // Pathway Enrichment
    {
        id: "pathway-enrichment",
        title: "GO & Pathway Enrichment",
        description: "Run gene ontology and pathway enrichment analysis on a list of genes to identify overrepresented biological processes, molecular functions, and KEGG pathways.",
        exampleQuery: "Run GO enrichment on TP53, BRCA1, RB1, CDKN2A, MDM2, PTEN, ATM, CHEK2, RAD51, and CCND1.",
        tools: ["webgestalt"],
        category: "Pathway Enrichment",
        icon: Zap,
    },
    {
        id: "functional-network",
        title: "Functional Network Analysis",
        description: "Discover proteins that are functionally related to a gene in the FunMap network based on co-expression, co-regulation, and protein interaction data.",
        exampleQuery: "What proteins are functionally related to TP53 in the FunMap network?",
        tools: ["funmap_neighborhood"],
        category: "Functional Networks",
        icon: Network,
    },
    {
        id: "target-discovery-pipeline",
        title: "Target Discovery Pipeline",
        description: "Run a full multi-step pipeline: find functional partners of a gene, check which are druggable targets, and assess their survival impact.",
        exampleQuery: "Find functional partners of BRCA1, identify which ones are druggable oncology targets, and check if any predict survival in breast cancer.",
        tools: ["funmap_neighborhood", "get_target", "overall_survival_per_cancer"],
        category: "Functional Networks",
        icon: Network,
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
]

const TOOL_LABELS: Record<string, string> = {
    cancer_gene_expression: "Expression",
    overall_survival_per_cancer: "Survival",
    get_cis_correlations: "Cis-correlation",
    get_target: "Drug Target",
    search_targets: "Target Search",
    rank_targets: "Target Ranking",
    clinical_trial_information: "Clinical Trials",
    batch_clinical_trial_information: "Clinical Trials",
    get_study_info: "Study Details",
    gene_set_trial_information: "Pathway Trials",
    filter_clinical_trials: "Trial Filter",
    meta_analysis_predictive_genes: "Gene Meta-analysis",
    meta_analysis_predictive_gene_sets: "Pathway Meta-analysis",
    get_study_predictive_genes: "Study Gene Rankings",
    get_study_predictive_gene_sets: "Study Pathway Rankings",
    funmap_neighborhood: "FunMap Network",
    webgestalt: "Pathway Enrichment",
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
            className="group flex flex-col items-start text-left p-4 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:border-teal-300 dark:hover:border-teal-700 hover:bg-teal-50/50 dark:hover:bg-teal-900/20 hover:shadow-md transition-all duration-200"
        >
            {/* Icon + title */}
            <div className="flex items-center gap-3 w-full mb-2">
                <div className={`h-9 w-9 rounded-lg flex items-center justify-center flex-shrink-0 ${color}`}>
                    <Icon className="h-4 w-4" />
                </div>
                <h3 className="font-semibold text-gray-900 dark:text-gray-100 group-hover:text-teal-600 dark:group-hover:text-teal-400 transition-colors text-sm leading-snug">
                    {uc.title}
                </h3>
            </div>

            {/* Description */}
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed mb-3 line-clamp-2">
                {uc.description}
            </p>

            {/* Tool badges */}
            <div className="flex flex-wrap gap-1.5 mb-3">
                {uc.tools.map((tool) => (
                    <span
                        key={tool}
                        className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 border border-gray-200 dark:border-gray-600 font-mono"
                    >
                        {TOOL_LABELS[tool] ?? tool}
                    </span>
                ))}
            </div>

            {/* Example query */}
            <p className="text-xs text-gray-400 dark:text-gray-500 italic line-clamp-2 mb-3">
                &ldquo;{uc.exampleQuery}&rdquo;
            </p>

            {/* CTA */}
            <div className="flex items-center gap-1.5 text-xs font-medium text-teal-500 dark:text-teal-400 group-hover:text-teal-600 dark:group-hover:text-teal-300 transition-colors mt-auto">
                Try this query
                <ArrowRight className="w-3.5 h-3.5" />
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
                    More use cases will be added as new data sources and tools are integrated.
                </p>
            </div>
        </div>
    )
}
