"use client"

import { useState } from "react"
import { ChevronDown, ChevronRight, ExternalLink, Info } from "lucide-react"

export type ToolCategoryGuideKey =
    | "drug-targets"
    | "clinical-trials"
    | "functional-networks"
    | "pathway-enrichment"
    | "survival-analysis"
    | "expression-analysis"

type GuideItem = {
    badge?: string
    badgeClass?: string
    label?: string
    description: string
}

type GuideLink = {
    label: string
    url: string
}

type GuideConfig = {
    title: string
    intro: string
    links?: GuideLink[]
    items: GuideItem[]
    notes?: string[]
}

export const DRUG_TARGET_TIER_GUIDE = [
    { tier: "T1", definition: "Target of drugs approved for oncology", badge: "bg-green-100 text-green-800 border-green-300" },
    { tier: "T2", definition: "Target of drugs approved for indications other than oncology", badge: "bg-blue-100 text-blue-800 border-blue-300" },
    { tier: "T3", definition: "Target of drugs classified as investigational or experimental", badge: "bg-yellow-100 text-yellow-800 border-yellow-300" },
    { tier: "T4", definition: "Potentially druggable target by small molecules", badge: "bg-orange-100 text-orange-800 border-orange-300" },
    { tier: "T5", definition: "Cell surface membrane protein", badge: "bg-gray-100 text-gray-700 border-gray-300" },
] as const

const DRUG_TARGET_TIER_DEFINITION_MAP = Object.fromEntries(
    DRUG_TARGET_TIER_GUIDE.map(({ tier, definition }) => [tier, definition])
) as Record<string, string>

export function getDrugTargetTierDefinition(tier?: string | null): string | undefined {
    if (!tier) return undefined
    return DRUG_TARGET_TIER_DEFINITION_MAP[tier]
}

const GUIDE_CONFIG: Record<ToolCategoryGuideKey, GuideConfig> = {
    "drug-targets": {
        title: "Drug Targets Guide",
        intro: "LinkedOmics Targets prioritizes therapeutic candidates using pan-cancer proteogenomic analyses from CPTAC and related public datasets.",
        links: [
            { label: "Resource", url: "https://targets.linkedomics.org" },
            { label: "Savage et al., Cell (2024)", url: "https://doi.org/10.1016/j.cell.2024.05.039" },
        ],
        items: DRUG_TARGET_TIER_GUIDE.map(({ tier, definition, badge }) => ({
            badge: tier,
            badgeClass: badge,
            description: definition,
        })),
        notes: [
            "Antigen labels: TSA = tumor-specific antigen; TAA = tumor-associated antigen.",
            "Score guide: Search results use the LinkedOmics evidence score. Ranked target tables use a composite score that combines tier, approved-drug count, antigen bonus, and LinkedOmics evidence.",
        ],
    },
    "clinical-trials": {
        title: "Clinical Trials Guide",
        intro: "LinkedOmics Trials links gene expression or pathway activity to treatment response across public clinical studies, including single-study analyses and cross-study meta-analyses.",
        links: [
            { label: "Resource", url: "https://trials.linkedomics.org" },
        ],
        items: [
            {
                label: "Sensitive",
                description: "Higher gene expression or pathway activity is associated with better response or lower IC50.",
            },
            {
                label: "Resistant",
                description: "Higher gene expression or pathway activity is associated with worse response or higher IC50.",
            },
            {
                label: "Study-level result",
                description: "A biomarker association observed within one specific study or series ID.",
            },
            {
                label: "Meta-analysis",
                description: "A cross-study ranking that combines matched studies to find biomarkers that generalize across datasets.",
            },
            {
                label: "Treatment categories",
                description: "Broad trial filters include chemotherapy, targeted, and combinations.",
            },
        ],
        notes: [
            "How to read AUROC: values below 0.5 usually indicate sensitivity, while values above 0.5 usually indicate resistance.",
            "How to read statistics: smaller FDR or p value indicates stronger statistical evidence.",
            "Interpret in context: disease, subtype, treatment, and response evaluation can differ substantially across studies.",
            "Study IDs matter: single-study tools describe one study, while meta-analysis tools summarize many matched studies together.",
        ],
    },
    "functional-networks": {
        title: "Functional Networks Guide",
        intro: "FunMap is a functional proteogenomic network used to identify genes that are likely to share biological roles, pathway context, or coordinated regulation with the query gene.",
        links: [
            { label: "Resource", url: "https://funmap.linkedomics.org" },
        ],
        items: [
            {
                label: "Network edge",
                description: "An edge indicates a predicted functional relationship, not necessarily a direct physical interaction.",
            },
            {
                label: "Neighborhood",
                description: "The neighborhood highlights genes that may be co-functional, co-regulated, or involved in related pathways.",
            },
            {
                label: "Node color",
                description: "Node color reflects the signed tumor-versus-normal expression signal shown in the legend, not edge confidence.",
            },
            {
                label: "Best use",
                description: "Use FunMap for hypothesis generation, pathway expansion, and follow-up enrichment analysis.",
            },
        ],
        notes: [
            "Interpret cautiously: network proximity suggests related biology, but does not by itself prove mechanism.",
            "A strong next step is to run pathway enrichment on the neighborhood to summarize shared functions.",
        ],
    },
    "pathway-enrichment": {
        title: "Pathway Enrichment Guide",
        intro: "WebGestalt tests whether your input gene list is overrepresented in known biological processes compared with a background reference set.",
        links: [
            { label: "Resource", url: "https://www.webgestalt.org" },
        ],
        items: [
            {
                label: "FDR",
                description: "Use FDR as the main significance measure; smaller values indicate stronger corrected statistical evidence.",
            },
            {
                label: "Overlap",
                description: "Overlap is the number of your input genes that fall into a given term or pathway.",
            },
            {
                label: "Enrichment ratio",
                description: "Enrichment ratio compares observed overlap with the overlap expected by chance; larger values suggest stronger enrichment.",
            },
            {
                label: "GO scope",
                description: "These LinkedOmicsChat results focus on Gene Ontology Biological Process terms unless otherwise noted.",
            },
        ],
        notes: [
            "Best with moderate gene lists: very small lists may yield no results, while very large lists can dilute specific signal.",
            "Enrichment suggests shared biology, not causality or direct regulation.",
        ],
    },
    "survival-analysis": {
        title: "Survival Analysis Guide",
        intro: "These tools test whether higher or lower expression of a gene is associated with overall survival across cancer cohorts.",
        links: [
            { label: "LinkedOmics", url: "https://www.linkedomics.org" },
        ],
        items: [
            {
                label: "Poor survival",
                description: "If higher expression is associated with poor survival, patients with higher expression tend to have worse outcomes in that cohort.",
            },
            {
                label: "Lower expression",
                description: "If lower expression is associated with poor survival, reduced expression tracks with worse outcomes in that cohort.",
            },
            {
                label: "Not significant",
                description: "A non-significant result means the association was not strong enough in that dataset; it is not proof of no effect.",
            },
            {
                label: "RNA vs protein",
                description: "RNA- and protein-level survival associations can differ and should be interpreted as separate molecular readouts.",
            },
        ],
        notes: [
            "These are associations, not causal effects.",
            "Survival interpretation is cohort-specific; cancer type, sample size, and platform all matter.",
        ],
    },
    "expression-analysis": {
        title: "Expression & Regulation Guide",
        intro: "This category combines tumor-versus-normal expression analysis with cis-regulatory correlations across RNA, protein, methylation, and copy-number layers.",
        links: [
            { label: "LinkedOmics", url: "https://www.linkedomics.org" },
            { label: "CPTAC", url: "https://proteomics.cancer.gov/programs/cptac" },
        ],
        items: [
            {
                label: "Tumor vs normal",
                description: "Expression results report direction and statistical significance of change between tumor and normal tissue, not effect size alone.",
            },
            {
                label: "RNA vs protein",
                description: "RNA and protein are related but distinct layers, so they may show different patterns across cohorts.",
            },
            {
                label: "RNA ↔ Protein",
                description: "This pair helps assess transcript-to-protein concordance and possible translation-related regulation.",
            },
            {
                label: "RNA ↔ Methylation",
                description: "This pair helps assess whether epigenetic silencing or activation may be linked to expression changes.",
            },
            {
                label: "RNA ↔ SCNV",
                description: "This pair helps assess copy-number dosage effects on expression.",
            },
        ],
        notes: [
            "Cis-correlations are evidence for regulatory hypotheses, not definitive mechanisms.",
            "Interpret each cohort separately because the same gene can behave differently across cancers.",
        ],
    },
}

export function getToolCategoryGuideKeyFromLabel(label?: string | null): ToolCategoryGuideKey | null {
    if (label === "Drug Targets") return "drug-targets"
    if (label === "Clinical Trials") return "clinical-trials"
    if (label === "Functional Networks") return "functional-networks"
    if (label === "Pathway Enrichment") return "pathway-enrichment"
    if (label === "Survival Analysis") return "survival-analysis"
    if (label === "Expression Analysis") return "expression-analysis"
    return null
}

interface ToolCategoryGuideProps {
    category: ToolCategoryGuideKey
    className?: string
    compact?: boolean
    collapsible?: boolean
    defaultExpanded?: boolean
}

export function ToolCategoryGuide({
    category,
    className = "",
    compact = false,
    collapsible = false,
    defaultExpanded = true,
}: ToolCategoryGuideProps) {
    const [expanded, setExpanded] = useState(defaultExpanded)
    const config = GUIDE_CONFIG[category]
    const wrapperClass = compact
        ? "rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50/70 dark:bg-amber-950/20 p-3"
        : "rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/70 dark:bg-amber-950/20 p-4"
    const titleClass = compact ? "text-sm font-semibold text-amber-900 dark:text-amber-100" : "text-base font-semibold text-amber-900 dark:text-amber-100"
    const bodyTextClass = compact ? "text-xs leading-relaxed text-amber-900/90 dark:text-amber-100/90" : "text-sm leading-relaxed text-amber-900/90 dark:text-amber-100/90"
    const itemTextClass = compact ? "text-xs leading-relaxed text-foreground" : "text-sm leading-relaxed text-foreground"
    const noteTextClass = compact ? "text-[11px] leading-relaxed text-muted-foreground" : "text-xs leading-relaxed text-muted-foreground"

    const content = (
        <div className="space-y-3">
            <div className={bodyTextClass}>
                {config.intro}
                {config.links?.length ? (
                    <>
                        {" "}
                        {config.links.map((link, index) => (
                            <span key={link.url}>
                                {index === 0 ? "" : " · "}
                                <a
                                    href={link.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1 text-amber-900 underline decoration-amber-400 underline-offset-2 hover:text-amber-700 dark:text-amber-200 dark:hover:text-amber-100"
                                >
                                    {link.label}
                                    <ExternalLink className="h-3 w-3" />
                                </a>
                            </span>
                        ))}
                    </>
                ) : null}
            </div>

            <div className="space-y-2">
                {config.items.map((item, index) => (
                    <div key={`${item.label ?? item.badge ?? "item"}-${index}`} className="flex items-start gap-3">
                        {item.badge ? (
                            <span className={`inline-flex min-w-9 items-center justify-center rounded border px-2 py-0.5 text-xs font-semibold ${item.badgeClass ?? "bg-muted text-foreground border-border"}`}>
                                {item.badge}
                            </span>
                        ) : item.label ? (
                            <span className="min-w-[88px] text-xs font-semibold uppercase tracking-wide text-foreground/80">
                                {item.label}
                            </span>
                        ) : null}
                        <p className={itemTextClass}>{item.description}</p>
                    </div>
                ))}
            </div>

            {config.notes?.length ? (
                <div className="space-y-1.5">
                    {config.notes.map((note) => (
                        <p key={note} className={noteTextClass}>
                            {note}
                        </p>
                    ))}
                </div>
            ) : null}
        </div>
    )

    if (!collapsible) {
        return (
            <div className={`${wrapperClass} ${className}`.trim()}>
                <div className="flex items-start gap-2">
                    <Info className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-700 dark:text-amber-300" />
                    <div className="min-w-0 flex-1">
                        <h3 className={titleClass}>{config.title}</h3>
                        <div className="mt-3">{content}</div>
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div className={`${wrapperClass} ${className}`.trim()}>
            <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                className="flex w-full items-center gap-2 text-left"
            >
                {expanded ? (
                    <ChevronDown className="h-4 w-4 flex-shrink-0 text-amber-700 dark:text-amber-300" />
                ) : (
                    <ChevronRight className="h-4 w-4 flex-shrink-0 text-amber-700 dark:text-amber-300" />
                )}
                <Info className="h-4 w-4 flex-shrink-0 text-amber-700 dark:text-amber-300" />
                <span className={titleClass}>{config.title}</span>
            </button>
            {expanded && <div className="mt-3">{content}</div>}
        </div>
    )
}
