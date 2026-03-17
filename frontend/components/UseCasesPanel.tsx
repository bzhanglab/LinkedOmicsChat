"use client"

import { ArrowRight, Activity, Network, Pill, TrendingUp, FlaskConical, Dna } from "lucide-react"
import { cn } from "@/lib/utils"

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
    // Expression & Biomarkers
    {
        id: "pan-cancer-expression",
        title: "Pan-cancer Expression Screen",
        description: "Check whether a gene is overexpressed or downregulated in tumor vs. normal tissue across 10 cancer types, at both RNA and protein levels.",
        exampleQuery: "Is EGFR overexpressed at the protein level in lung cancer compared to normal tissue?",
        tools: ["cancer_gene_expression"],
        category: "Expression & Biomarkers",
        icon: Activity,
    },
    {
        id: "survival-biomarker",
        title: "Survival Biomarker Analysis",
        description: "Determine whether high or low expression of a gene is associated with better or worse overall survival across cancer cohorts.",
        exampleQuery: "Does high ESR1 expression predict better or worse survival in breast cancer?",
        tools: ["overall_survival_per_cancer", "cancer_gene_expression"],
        category: "Expression & Biomarkers",
        icon: TrendingUp,
    },
    {
        id: "multi-omics-regulation",
        title: "Multi-omics Regulatory Analysis",
        description: "Identify what drives a gene's expression — RNA transcription, gene copy number amplification (SCNV), or DNA methylation silencing.",
        exampleQuery: "What drives EGFR overexpression in glioblastoma — gene amplification, methylation, or RNA levels?",
        tools: ["get_cis_correlations", "cancer_gene_expression"],
        category: "Expression & Biomarkers",
        icon: Dna,
    },
    // Drug & Clinical
    {
        id: "drug-target",
        title: "Drug Target Assessment",
        description: "Look up whether a gene is an FDA-approved oncology target, identify associated drugs, and check cancer cell line dependency.",
        exampleQuery: "Is TP53 a druggable oncology target, and what drugs or clinical trials are associated with it?",
        tools: ["get_target", "clinical_trial_information"],
        category: "Drug & Clinical",
        icon: Pill,
    },
    {
        id: "treatment-resistance",
        title: "Treatment Response Prediction",
        description: "Find drugs where a gene's expression level predicts sensitivity or resistance, based on clinical trial and pharmacogenomics data.",
        exampleQuery: "Which chemotherapy drugs are patients with high BRCA1 expression likely to be resistant to?",
        tools: ["clinical_trial_information"],
        category: "Drug & Clinical",
        icon: FlaskConical,
    },
    // Functional Networks
    {
        id: "functional-network",
        title: "Functional Network & Pathway Analysis",
        description: "Discover proteins that are functionally related to a gene in the FunMap network, then identify the biological pathways and GO terms they share.",
        exampleQuery: "What proteins are functionally related to TP53, and what biological pathways do they enrich?",
        tools: ["funmap_neighborhood", "webgestalt"],
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

const CATEGORIES = ["Expression & Biomarkers", "Drug & Clinical", "Functional Networks"]

const CATEGORY_COLORS: Record<string, { badge: string; line: string }> = {
    "Expression & Biomarkers": {
        badge: "bg-teal-100 text-teal-700 dark:bg-teal-950 dark:text-teal-300",
        line: "bg-teal-200 dark:bg-teal-800",
    },
    "Drug & Clinical": {
        badge: "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300",
        line: "bg-violet-200 dark:bg-violet-800",
    },
    "Functional Networks": {
        badge: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
        line: "bg-emerald-200 dark:bg-emerald-800",
    },
}

const TOOL_LABELS: Record<string, string> = {
    cancer_gene_expression: "Expression",
    overall_survival_per_cancer: "Survival",
    get_cis_correlations: "Cis-correlation",
    get_target: "Drug Target",
    clinical_trial_information: "Clinical Trials",
    funmap_neighborhood: "FunMap Network",
    webgestalt: "Pathway Enrichment",
}

interface UseCasesPanelProps {
    onStartChat: (query: string) => void
}

export function UseCasesPanel({ onStartChat }: UseCasesPanelProps) {
    return (
        <div className="flex flex-col h-full overflow-y-auto bg-background">
            {/* Header */}
            <div className="px-8 pt-8 pb-6 border-b border-border">
                <h1 className="text-2xl font-semibold text-foreground">Use Cases</h1>
                <p className="mt-2 text-sm text-muted-foreground max-w-2xl">
                    Example analyses you can run using the chat interface. Click any use case to try it — the query will be loaded into the chat automatically.
                </p>
            </div>

            {/* Use case groups */}
            <div className="px-8 py-6 space-y-10">
                {CATEGORIES.map((category) => {
                    const items = USE_CASES.filter((uc) => uc.category === category)
                    return (
                        <section key={category}>
                            <div className="flex items-center gap-3 mb-4">
                                <span className={cn(
                                    "text-xs font-bold tracking-wide px-3 py-1 rounded-full",
                                    CATEGORY_COLORS[category]?.badge
                                )}>
                                    {category}
                                </span>
                                <div className={cn("flex-1 h-px", CATEGORY_COLORS[category]?.line)} />
                            </div>
                            <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
                                {items.map((uc) => {
                                    const Icon = uc.icon
                                    return (
                                        <div
                                            key={uc.id}
                                            className="group flex flex-col bg-card border border-border rounded-xl p-5 hover:border-primary/50 hover:shadow-sm transition-all"
                                        >
                                            {/* Icon + title */}
                                            <div className="flex items-start gap-3 mb-3">
                                                <div className="mt-0.5 p-2 rounded-lg bg-primary/10 text-primary shrink-0">
                                                    <Icon className="w-4 h-4" />
                                                </div>
                                                <h3 className="font-semibold text-foreground text-sm leading-snug">
                                                    {uc.title}
                                                </h3>
                                            </div>

                                            {/* Description */}
                                            <p className="text-xs text-muted-foreground leading-relaxed mb-4 flex-1">
                                                {uc.description}
                                            </p>

                                            {/* Tool badges */}
                                            <div className="flex flex-wrap gap-1.5 mb-4">
                                                {uc.tools.map((tool) => (
                                                    <span
                                                        key={tool}
                                                        className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border font-mono"
                                                    >
                                                        {TOOL_LABELS[tool] ?? tool}
                                                    </span>
                                                ))}
                                            </div>

                                            {/* Example query preview */}
                                            <div className="text-xs text-muted-foreground italic bg-muted/50 rounded-lg px-3 py-2 mb-4 border border-border/50">
                                                &ldquo;{uc.exampleQuery}&rdquo;
                                            </div>

                                            {/* CTA */}
                                            <button
                                                onClick={() => onStartChat(uc.exampleQuery)}
                                                className={cn(
                                                    "flex items-center justify-center gap-2 w-full px-4 py-2 rounded-lg text-xs font-medium transition-all",
                                                    "bg-primary/10 text-primary hover:bg-primary hover:text-primary-foreground",
                                                    "group-hover:bg-primary group-hover:text-primary-foreground"
                                                )}
                                            >
                                                Try this query
                                                <ArrowRight className="w-3.5 h-3.5" />
                                            </button>
                                        </div>
                                    )
                                })}
                            </div>
                        </section>
                    )
                })}
            </div>

            {/* Footer note */}
            <div className="px-8 pb-8">
                <p className="text-xs text-muted-foreground">
                    More use cases will be added as new data sources and tools are integrated.
                </p>
            </div>
        </div>
    )
}
