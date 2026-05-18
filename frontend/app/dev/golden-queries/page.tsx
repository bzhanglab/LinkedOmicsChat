"use client"

import { useState, useRef, useMemo } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { chatAPI, type ChatResponse, type AnyVisualization } from "@/lib/api"
import { StaticPlot } from "@/components/StaticPlot"
import { NetworkPlot } from "@/components/NetworkPlot"
import { DrugTargetGrid } from "@/components/DrugTargetGrid"
import { TargetSearchTable } from "@/components/TargetSearchTable"
import { PredictiveResultsTable } from "@/components/PredictiveResultsTable"
import { TCGACisResultsTable } from "@/components/TCGACisResultsTable"

// ---------------------------------------------------------------------------
// Golden query test cases (mirrored from backend/examples/langgraph_golden_queries.json)
// ---------------------------------------------------------------------------
interface GoldenCase {
    id: string
    session_key?: string
    query: string
    expected_tools_all?: string[]
    forbidden_tools?: string[]
    expect_no_tools?: boolean
    expect_general_knowledge?: boolean
    notes?: string
}

const CASES: GoldenCase[] = [
    { id: "greeting_no_tools", query: "hello", expect_no_tools: true, notes: "Basic greeting should be answered directly." },
    { id: "platform_scope_no_tools", query: "What can you analyze?", expect_no_tools: true, notes: "Should answer from the available-data prompt section without forcing tool calls." },
    { id: "expression_luad", query: "How is EGFR expressed tumor vs normal in LUAD?", expected_tools_all: ["linkedomics::cancer_gene_expression"], forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::tcga_survival_analysis"] },
    { id: "survival_dual_dataset", query: "Show TP53 overall survival in BRCA.", expected_tools_all: ["linkedomics::overall_survival_per_cancer", "linkedomics::tcga_survival_analysis"], forbidden_tools: ["linkedomics::clinical_trial_information"] },
    { id: "survival_tcga_only_methylation", query: "Show TP53 methylation survival in BRCA from TCGA.", expected_tools_all: ["linkedomics::tcga_survival_analysis"], forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::clinical_trial_information"] },
    { id: "identifier_resolution_survival", query: "Show overall survival for ENSG00000141510 in BRCA.", expected_tools_all: ["gene_utils::resolve_gene_identifier"], notes: "Identifier should be resolved before downstream analysis." },
    { id: "literature_search", query: "Find recent papers on ESR1 and breast cancer survival.", expected_tools_all: ["literature::search_pubmed"], forbidden_tools: ["linkedomics::clinical_trial_information"] },
    { id: "out_of_scope_structure", query: "What is the 3D structure of TP53?", expect_no_tools: true, notes: "Should stay within scope handling rather than fabricating a relevant data tool." },
    { id: "general_knowledge_shortcut", query: "Answer using general knowledge: what is the 3D structure of TP53?", expect_no_tools: true, expect_general_knowledge: true, notes: "Shortcut mode should bypass tools and mark the response as general knowledge." },
    { id: "drug_target_single_gene", query: "Is EGFR a validated oncology target?", expected_tools_all: ["linkedomics::get_target"], forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::clinical_trial_information"] },
    { id: "drug_target_keyword_not_trials", query: "Is BRCA1 a drug target?", expected_tools_all: ["linkedomics::get_target"], forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::meta_analysis_predictive_genes", "linkedomics::overall_survival_per_cancer"], notes: '"drug target" should route to targets scope, not trials scope despite containing "drug".' },
    { id: "targets_druggable_keyword", query: "Is TP53 druggable?", expected_tools_all: ["linkedomics::get_target"], forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::overall_survival_per_cancer"] },
    { id: "targets_rank_attractive", query: "What are the most attractive therapeutic targets for cancer?", expected_tools_all: ["linkedomics::rank_targets"], forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::overall_survival_per_cancer", "linkedomics::cancer_gene_expression"] },
    { id: "targets_search_tier_family", query: "Which kinases are FDA-approved oncology targets?", expected_tools_all: ["linkedomics::search_targets"], forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::overall_survival_per_cancer"], notes: '"oncology target" keyword should route to targets scope; search_targets handles tier+family filtering.' },
    { id: "targets_search_antigen", query: "Which genes are tumor-associated antigens in T1 tier?", expected_tools_all: ["linkedomics::search_targets"], forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::cancer_gene_expression"], notes: '"tumor antigen" keyword should route to targets scope.' },
    { id: "clinical_trial_single_gene", query: "Which drugs are patients likely to be resistant to if they have high EGFR expression?", expected_tools_all: ["linkedomics::clinical_trial_information"], forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::cancer_gene_expression"] },
    { id: "trials_batch_multi_gene", query: "Which drugs do ESR1 and ERBB2 predict resistance to?", expected_tools_all: ["linkedomics::batch_clinical_trial_information"], forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::cancer_gene_expression"], notes: "Multiple genes should trigger the batch variant." },
    { id: "trials_gene_set", query: "Does the HALLMARK_ESTROGEN_RESPONSE pathway predict tamoxifen sensitivity?", expected_tools_all: ["linkedomics::gene_set_trial_information"], forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::overall_survival_per_cancer"], notes: "Pathway/gene-set trial query should use gene_set_trial_information, not the per-gene tool." },
    { id: "trials_filter_drug_cancer", query: "Which studies tested nivolumab in melanoma?", expected_tools_all: ["linkedomics::filter_clinical_trials"], forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::overall_survival_per_cancer"], notes: "Study discovery by drug + cancer should use filter_clinical_trials." },
    { id: "trials_meta_analysis_genes", query: "Which genes best predict paclitaxel response in breast cancer?", expected_tools_all: ["linkedomics::meta_analysis_predictive_genes"], forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::cancer_gene_expression", "linkedomics::overall_survival_per_cancer"], notes: "Cross-study biomarker discovery should use meta_analysis_predictive_genes." },
    { id: "trials_meta_analysis_gene_sets", query: "What pathways predict platinum resistance in ovarian cancer?", expected_tools_all: ["linkedomics::meta_analysis_predictive_gene_sets"], forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::webgestalt", "linkedomics::overall_survival_per_cancer"], notes: "Pathway-level cross-study biomarker discovery should use meta_analysis_predictive_gene_sets." },
    { id: "trials_meta_analysis_genes_ici_only", query: "What genes best predict immune checkpoint inhibitor response?", expected_tools_all: ["linkedomics::meta_analysis_predictive_genes"], forbidden_tools: ["linkedomics::meta_analysis_predictive_gene_sets", "linkedomics::webgestalt", "linkedomics::clinical_trial_information"], notes: "ICI biomarker queries that ask for genes should stay gene-level only and must not add pathway analysis." },
    { id: "trials_meta_analysis_genes_antibody_category", query: "What genes best predict antibody treatment response?", expected_tools_all: ["linkedomics::meta_analysis_predictive_genes"], forbidden_tools: ["linkedomics::meta_analysis_predictive_gene_sets", "linkedomics::clinical_trial_information", "linkedomics::webgestalt"], notes: "Nested treatment classes such as antibody should still route to gene-level trial meta-analysis when the user asks for genes." },
    { id: "trials_study_info_followup_anchor", session_key: "trials_study_info", query: "Which drugs are patients likely to be resistant to if they have high ESR1 expression?", expected_tools_all: ["linkedomics::clinical_trial_information"] },
    { id: "trials_study_info_followup", session_key: "trials_study_info", query: "Tell me more about the first study in those results.", expected_tools_all: ["linkedomics::get_study_info"], forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::overall_survival_per_cancer"], notes: "Follow-up asking for study details should call get_study_info with the series ID from the prior turn." },
    { id: "funmap_single_gene", query: "Find functional neighbors of TP53 in the FunMap network.", expected_tools_all: ["linkedomics::funmap_neighborhood"], forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::clinical_trial_information", "linkedomics::cancer_gene_expression"] },
    { id: "funmap_network_keyword", query: "What genes are functionally connected to BRCA1?", expected_tools_all: ["linkedomics::funmap_neighborhood"], forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::clinical_trial_information"] },
    { id: "correlation_cis_methylation", query: "Show cis-correlations for BRCA1 across CPTAC cohorts.", expected_tools_all: ["linkedomics::get_cis_correlations"], forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::clinical_trial_information"], notes: "Cis-regulatory question: methylation → expression, should use get_cis_correlations." },
    { id: "correlation_cis_explicit", query: "Show cis-correlations for MYC.", expected_tools_all: ["linkedomics::get_cis_correlations"], forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::cancer_gene_expression"] },
    { id: "pathway_enrichment_genelist", query: "Run pathway enrichment analysis on TP53, MDM2, CDKN1A, ATM, and BRCA1.", expected_tools_all: ["linkedomics::webgestalt"], forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::clinical_trial_information"] },
    { id: "pathway_enrichment_explicit", query: "What pathways are enriched in this gene set: EGFR, MET, ERBB2, ALK, RET?", expected_tools_all: ["linkedomics::webgestalt"], forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::cancer_gene_expression"] },
    { id: "followup_anchor_survival", session_key: "tp53_followup", query: "Show TP53 overall survival in BRCA.", expected_tools_all: ["linkedomics::overall_survival_per_cancer", "linkedomics::tcga_survival_analysis"] },
    { id: "followup_pronoun_tcga", session_key: "tp53_followup", query: "What about methylation in TCGA?", expected_tools_all: ["linkedomics::tcga_survival_analysis"], forbidden_tools: ["linkedomics::overall_survival_per_cancer"], notes: "Should reuse active-gene context from the previous turn." },

    // ── 2-tool cases ────────────────────────────────────────────────────────

    {
        id: "expression_and_target",
        query: "Is EGFR overexpressed in lung cancer and is it a validated drug target?",
        expected_tools_all: ["linkedomics::cancer_gene_expression", "linkedomics::get_target"],
        forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::overall_survival_per_cancer"],
        notes: "Expression + druggability check — two independent lookups for one gene.",
    },
    {
        id: "expression_and_funmap",
        query: "Show BRCA1 expression in breast cancer and find its functional network neighbors in FunMap.",
        expected_tools_all: ["linkedomics::cancer_gene_expression", "linkedomics::funmap_neighborhood"],
        forbidden_tools: ["linkedomics::clinical_trial_information"],
        notes: "Expression + network neighborhood — common two-part gene profile.",
    },
    {
        id: "cis_and_enrichment",
        query: "Find the top cis-correlated genes for MYC and run pathway enrichment on them.",
        expected_tools_all: ["linkedomics::get_cis_correlations", "linkedomics::webgestalt"],
        forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::clinical_trial_information"],
        notes: "Correlation discovery followed by enrichment — natural two-step workflow.",
    },
    {
        id: "survival_and_literature",
        query: "What is the survival impact of KRAS in pancreatic cancer and what does recent literature say about it?",
        expected_tools_all: ["linkedomics::overall_survival_per_cancer", "literature::search_pubmed"],
        forbidden_tools: ["linkedomics::clinical_trial_information"],
        notes: "Survival data + PubMed literature — data-backed then literature context.",
    },

    // ── 3-tool cases ────────────────────────────────────────────────────────

    {
        id: "expression_survival_target_erbb2",
        query: "Analyze ERBB2 in breast cancer: show tumor vs normal expression, overall survival impact, and whether it is a drug target.",
        expected_tools_all: [
            "linkedomics::cancer_gene_expression",
            "linkedomics::overall_survival_per_cancer",
            "linkedomics::get_target",
        ],
        forbidden_tools: ["linkedomics::clinical_trial_information", "linkedomics::tcga_survival_analysis"],
        notes: "Classic three-part gene profile: expression + prognosis + druggability.",
    },
    {
        id: "expression_tcga_survival_literature",
        query: "For PIK3CA in breast cancer: show tumor vs normal expression, TCGA methylation survival, and find recent papers on PIK3CA and breast cancer.",
        expected_tools_all: [
            "linkedomics::cancer_gene_expression",
            "linkedomics::tcga_survival_analysis",
            "literature::search_pubmed",
        ],
        forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::clinical_trial_information"],
        notes: "Expression + epigenetic survival + literature — three independent knowledge sources.",
    },
    {
        id: "funmap_enrichment_target",
        query: "Find functional neighbors of PTEN in FunMap, run pathway enrichment on those neighbors, and tell me if PTEN is a druggable target.",
        expected_tools_all: [
            "linkedomics::funmap_neighborhood",
            "linkedomics::webgestalt",
            "linkedomics::get_target",
        ],
        forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::clinical_trial_information"],
        notes: "Network → enrichment → druggability: a three-step analytical chain.",
    },
    {
        id: "expression_cis_survival",
        query: "Profile BRCA1: show tumor vs normal expression in breast cancer, cis-correlations across CPTAC cohorts, and overall survival.",
        expected_tools_all: [
            "linkedomics::cancer_gene_expression",
            "linkedomics::get_cis_correlations",
            "linkedomics::overall_survival_per_cancer",
        ],
        forbidden_tools: ["linkedomics::clinical_trial_information"],
        notes: "Expression + regulatory landscape + prognosis — three complementary omics views.",
    },

    // ── 4-tool cases ────────────────────────────────────────────────────────

    {
        id: "egfr_expression_dual_survival_target",
        query: "Give me a complete EGFR profile in LUAD: tumor vs normal expression, overall survival, TCGA methylation survival, and drug target information.",
        expected_tools_all: [
            "linkedomics::cancer_gene_expression",
            "linkedomics::overall_survival_per_cancer",
            "linkedomics::tcga_survival_analysis",
            "linkedomics::get_target",
        ],
        forbidden_tools: ["linkedomics::clinical_trial_information"],
        notes: "Four-part profile: expression + two survival datasets + druggability.",
    },
    {
        id: "kras_expression_funmap_enrichment_target",
        query: "Analyze KRAS in colorectal cancer: tumor vs normal expression, its functional neighbors in FunMap, pathway enrichment of those neighbors, and whether KRAS is druggable.",
        expected_tools_all: [
            "linkedomics::cancer_gene_expression",
            "linkedomics::funmap_neighborhood",
            "linkedomics::webgestalt",
            "linkedomics::get_target",
        ],
        forbidden_tools: ["linkedomics::overall_survival_per_cancer", "linkedomics::clinical_trial_information"],
        notes: "Expression → network → enrichment → druggability: four-step chain for an oncogene.",
    },
    {
        id: "expression_survival_cis_literature",
        query: "Profile MYC: show tumor vs normal expression, overall survival in LUAD, cis-correlations, and find recent literature on MYC in lung cancer.",
        expected_tools_all: [
            "linkedomics::cancer_gene_expression",
            "linkedomics::overall_survival_per_cancer",
            "linkedomics::get_cis_correlations",
            "literature::search_pubmed",
        ],
        forbidden_tools: ["linkedomics::clinical_trial_information"],
        notes: "Four data sources covering omics, prognosis, regulation, and literature.",
    },
    {
        id: "vhl_expression_survival_trials_target",
        query: "For VHL in kidney cancer: show expression, overall survival, drug resistance associations from clinical trials, and whether VHL is a drug target.",
        expected_tools_all: [
            "linkedomics::cancer_gene_expression",
            "linkedomics::overall_survival_per_cancer",
            "linkedomics::clinical_trial_information",
            "linkedomics::get_target",
        ],
        forbidden_tools: ["linkedomics::tcga_survival_analysis"],
        notes: "Tumor suppressor four-part profile combining expression, survival, trials, and target status.",
    },

    // ── 5-tool cases ────────────────────────────────────────────────────────

    {
        id: "tp53_five_tool_comprehensive",
        query: "Give me a comprehensive TP53 analysis: tumor vs normal expression, overall survival in BRCA, TCGA methylation survival, drug target status, and functional network neighbors in FunMap.",
        expected_tools_all: [
            "linkedomics::cancer_gene_expression",
            "linkedomics::overall_survival_per_cancer",
            "linkedomics::tcga_survival_analysis",
            "linkedomics::get_target",
            "linkedomics::funmap_neighborhood",
        ],
        forbidden_tools: ["linkedomics::clinical_trial_information"],
        notes: "Five independent analysis dimensions for TP53 — expression, dual survival, target, network.",
    },
    {
        id: "egfr_five_tool_oncology_report",
        query: "Full EGFR oncology report for LUAD: tumor vs normal expression, overall survival, drug resistance associations from clinical trials, drug target info, and recent PubMed literature.",
        expected_tools_all: [
            "linkedomics::cancer_gene_expression",
            "linkedomics::overall_survival_per_cancer",
            "linkedomics::clinical_trial_information",
            "linkedomics::get_target",
            "literature::search_pubmed",
        ],
        forbidden_tools: ["linkedomics::tcga_survival_analysis"],
        notes: "Five-tool clinical actionability report: omics, prognosis, trials, targets, literature.",
    },
    {
        id: "identifier_then_five_tools",
        query: "Analyze ENSG00000141510 comprehensively: resolve the identifier, show tumor vs normal expression, overall survival in BRCA, TCGA methylation survival, and drug target status.",
        expected_tools_all: [
            "gene_utils::resolve_gene_identifier",
            "linkedomics::cancer_gene_expression",
            "linkedomics::overall_survival_per_cancer",
            "linkedomics::tcga_survival_analysis",
            "linkedomics::get_target",
        ],
        notes: "Identifier resolution as first step, then four-part TP53 profile.",
    },

    // ── 6-tool cases ────────────────────────────────────────────────────────

    {
        id: "brca1_six_tool_full_profile",
        query: "Complete BRCA1 profile: tumor vs normal expression in breast cancer, overall survival, cis-correlations across CPTAC, pathway enrichment of top cis-correlated genes, drug target status, and recent literature.",
        expected_tools_all: [
            "linkedomics::cancer_gene_expression",
            "linkedomics::overall_survival_per_cancer",
            "linkedomics::get_cis_correlations",
            "linkedomics::webgestalt",
            "linkedomics::get_target",
            "literature::search_pubmed",
        ],
        forbidden_tools: ["linkedomics::clinical_trial_information"],
        notes: "Six-tool deep dive: expression, survival, regulatory correlations, enrichment, druggability, literature.",
    },
    {
        id: "erbb2_six_tool_clinical_deep_dive",
        query: "Deep clinical analysis of ERBB2: tumor vs normal expression, overall survival in BRCA, TCGA methylation survival, drug resistance from clinical trials, drug target details, and recent PubMed papers.",
        expected_tools_all: [
            "linkedomics::cancer_gene_expression",
            "linkedomics::overall_survival_per_cancer",
            "linkedomics::tcga_survival_analysis",
            "linkedomics::clinical_trial_information",
            "linkedomics::get_target",
            "literature::search_pubmed",
        ],
        notes: "Six-tool clinical deep dive covering the full translational pipeline for ERBB2/HER2.",
    },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function bareName(tool: string): string {
    // Strip instance index suffix (e.g. "linkedomics::cancer_gene_expression#0" → "...cancer_gene_expression")
    const base = tool.replace(/#\d+$/, "")
    if (base.includes("::")) return base.split("::").pop()!
    if (base.includes("__")) return base.split("__").pop()!
    return base
}

function normalise(tools: string[]): Set<string> {
    return new Set(tools.flatMap((t) => {
        const base = t.replace(/#\d+$/, "")
        return [t, base, bareName(t)]
    }))
}

function evaluate(gc: GoldenCase, resp: ChatResponse): { pass: boolean; details: string[] } {
    const used: string[] = resp.tools_used ?? []
    const usedNorm = normalise(used)
    const details: string[] = []
    let pass = true

    if (gc.expect_no_tools && used.length > 0) {
        pass = false
        details.push(`Expected no tools but got: ${used.join(", ")}`)
    }
    for (const expected of gc.expected_tools_all ?? []) {
        if (![...normalise([expected])].some((e) => usedNorm.has(e))) {
            pass = false
            details.push(`Missing expected tool: ${expected}`)
        }
    }
    for (const forbidden of gc.forbidden_tools ?? []) {
        if ([...normalise([forbidden])].some((f) => usedNorm.has(f))) {
            pass = false
            details.push(`Forbidden tool was called: ${forbidden}`)
        }
    }
    if (gc.expect_general_knowledge && !resp.is_general_knowledge) {
        pass = false
        details.push("Expected is_general_knowledge=true but got false")
    }
    if (pass && details.length === 0) details.push("All checks passed")
    return { pass, details }
}

// ---------------------------------------------------------------------------
// Visualization rendering
// ---------------------------------------------------------------------------

const PLOT_RE = /^\[PLOT:([^\]]+)\]$/
const NETWORK_RE = /^\[NETWORK:([^\]]+)\]$/
const TABLE_RE = /^\[TABLE:([^\]]+)\]$/

function ResponseRenderer({ text, vizs }: { text: string; vizs: AnyVisualization[] }) {
    const vizMap = useMemo(() => {
        const m: Record<string, AnyVisualization> = {}
        for (const v of vizs) m[v.id] = v
        return m
    }, [vizs])

    const parts = useMemo(() => {
        type Seg = { type: "text" | "plot" | "network" | "table"; value: string }
        const segments: Seg[] = []
        let buf: string[] = []
        for (const line of text.split("\n")) {
            const t = line.trim()
            const pm = t.match(PLOT_RE)
            const nm = t.match(NETWORK_RE)
            const tm = t.match(TABLE_RE)
            if (pm || nm || tm) {
                if (buf.length) { segments.push({ type: "text", value: buf.join("\n") }); buf = [] }
                if (pm) segments.push({ type: "plot", value: pm[1] })
                else if (nm) segments.push({ type: "network", value: nm[1] })
                else if (tm) segments.push({ type: "table", value: tm[1] })
            } else {
                buf.push(line)
            }
        }
        if (buf.length) segments.push({ type: "text", value: buf.join("\n") })
        return segments
    }, [text])

    return (
        <div className="space-y-4">
            {parts.map((part, i) => {
                if (part.type === "plot") {
                    const viz = vizMap[part.value]
                    if (!viz) return null
                    if (viz.type === "static_plot") return <StaticPlot key={i} visualization={viz} />
                    if (viz.type === "drug_target_grid") return <DrugTargetGrid key={i} visualization={viz} />
                    if (viz.type === "target_search_table") return <TargetSearchTable key={i} visualization={viz} />
                    return null
                }
                if (part.type === "network") {
                    const viz = vizMap[part.value]
                    return viz?.type === "network_plot" ? <NetworkPlot key={i} visualization={viz} /> : null
                }
                if (part.type === "table") {
                    const viz = vizMap[part.value]
                    if (!viz) return null
                    if (viz.type === "predictive_results_table") return <PredictiveResultsTable key={i} visualization={viz} />
                    if (viz.type === "tcga_cis_results_table") return <TCGACisResultsTable key={i} visualization={viz} />
                    return null
                }
                return (
                    <ReactMarkdown key={i} remarkPlugins={[remarkGfm]}
                        components={{
                            p: ({ children }) => <p className="mb-2 text-sm text-gray-800 leading-relaxed">{children}</p>,
                            ul: ({ children }) => <ul className="list-disc pl-5 mb-2 text-sm text-gray-800">{children}</ul>,
                            ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 text-sm text-gray-800">{children}</ol>,
                            li: ({ children }) => <li className="mb-0.5">{children}</li>,
                            h1: ({ children }) => <h1 className="text-base font-bold mt-3 mb-1">{children}</h1>,
                            h2: ({ children }) => <h2 className="text-sm font-bold mt-3 mb-1">{children}</h2>,
                            h3: ({ children }) => <h3 className="text-sm font-semibold mt-2 mb-1">{children}</h3>,
                            strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                            code: ({ children }) => <code className="bg-gray-100 px-1 py-0.5 rounded text-xs font-mono">{children}</code>,
                            a: ({ href, children }) => <a href={href} className="text-blue-600 underline" target="_blank" rel="noreferrer">{children}</a>,
                        }}
                    >
                        {part.value}
                    </ReactMarkdown>
                )
            })}

            {/* Render any visualizations that were NOT inlined via markers */}
            {vizs
                .filter((v) => {
                    const inlined = new Set([
                        ...(text.match(/\[PLOT:([^\]]+)\]/g)?.map((m) => m.slice(6, -1)) ?? []),
                        ...(text.match(/\[NETWORK:([^\]]+)\]/g)?.map((m) => m.slice(9, -1)) ?? []),
                        ...(text.match(/\[TABLE:([^\]]+)\]/g)?.map((m) => m.slice(7, -1)) ?? []),
                    ])
                    return !inlined.has(v.id)
                })
                .map((v, i) => {
                    if (v.type === "static_plot") return <StaticPlot key={i} visualization={v} />
                    if (v.type === "network_plot") return <NetworkPlot key={i} visualization={v} />
                    if (v.type === "drug_target_grid") return <DrugTargetGrid key={i} visualization={v} />
                    if (v.type === "target_search_table") return <TargetSearchTable key={i} visualization={v} />
                    if (v.type === "predictive_results_table") return <PredictiveResultsTable key={i} visualization={v} />
                    if (v.type === "tcga_cis_results_table") return <TCGACisResultsTable key={i} visualization={v} />
                    return null
                })}
        </div>
    )
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RunResult {
    status: "idle" | "running" | "done" | "error"
    statusText: string
    response: ChatResponse | null
    streamedText: string
    errorMsg?: string
    pass?: boolean
    evalDetails?: string[]
    toolsUsed?: string[]
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function GoldenQueriesPage() {
    const [results, setResults] = useState<Record<string, RunResult>>({})
    const [selected, setSelected] = useState<string | null>(null)
    const sessionIds = useRef<Record<string, string>>({})

    function updateResult(id: string, patch: Partial<RunResult>) {
        setResults((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }))
    }

    async function runCase(gc: GoldenCase) {
        setSelected(gc.id)
        let sessionId: string | undefined
        if (gc.session_key) sessionId = sessionIds.current[gc.session_key]

        updateResult(gc.id, { status: "running", statusText: "Sending…", streamedText: "", response: null, errorMsg: undefined, pass: undefined, evalDetails: undefined, toolsUsed: undefined })

        try {
            const resp = await chatAPI.streamMessage(
                { message: gc.query, session_id: sessionId },
                (s) => updateResult(gc.id, { statusText: s }),
                (delta) => setResults((prev) => ({ ...prev, [gc.id]: { ...prev[gc.id], streamedText: (prev[gc.id]?.streamedText ?? "") + delta } }))
            )
            if (gc.session_key) sessionIds.current[gc.session_key] = resp.session_id
            const { pass, details } = evaluate(gc, resp)
            updateResult(gc.id, { status: "done", statusText: "Done", response: resp, pass, evalDetails: details, toolsUsed: resp.tools_used ?? [] })
        } catch (err: unknown) {
            updateResult(gc.id, { status: "error", statusText: "Error", errorMsg: err instanceof Error ? err.message : String(err) })
        }
    }

    const selectedCase = CASES.find((c) => c.id === selected)
    const selectedResult = selected ? results[selected] : undefined

    function sessionLabel(gc: GoldenCase): string | null {
        if (!gc.session_key) return null
        const siblings = CASES.filter((c) => c.session_key === gc.session_key)
        return `Turn ${siblings.findIndex((c) => c.id === gc.id) + 1}/${siblings.length}`
    }

    const vizs = (selectedResult?.response?.visualizations ?? []) as AnyVisualization[]
    const responseText = selectedResult?.response?.message ?? selectedResult?.streamedText ?? ""

    return (
        <div className="flex h-screen bg-white text-gray-900 text-sm">
            {/* ── Left panel ── */}
            <div className="w-[360px] flex-shrink-0 border-r border-gray-200 flex flex-col">
                <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
                    <h1 className="text-sm font-semibold text-gray-800">Golden Query Tester</h1>
                    <p className="text-xs text-gray-500 mt-0.5">{CASES.length} cases · click to run</p>
                </div>

                <div className="overflow-y-auto flex-1">
                    {CASES.map((gc) => {
                        const r = results[gc.id]
                        const isSelected = selected === gc.id
                        const lbl = sessionLabel(gc)
                        return (
                            <button
                                key={gc.id}
                                onClick={() => runCase(gc)}
                                className={[
                                    "w-full text-left px-3 py-2.5 border-b border-gray-100 transition-colors",
                                    isSelected ? "bg-blue-50" : "hover:bg-gray-50",
                                ].join(" ")}
                            >
                                <div className="flex items-start gap-2">
                                    <span className={[
                                        "mt-1 w-2 h-2 rounded-full flex-shrink-0",
                                        !r || r.status === "idle" ? "bg-gray-300"
                                            : r.status === "running" ? "bg-yellow-400 animate-pulse"
                                            : r.pass === true ? "bg-green-500"
                                            : r.pass === false ? "bg-red-500"
                                            : "bg-red-400",
                                    ].join(" ")} />
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-1.5 flex-wrap">
                                            <span className="text-xs text-gray-400 font-mono">{gc.id}</span>
                                            {lbl && <span className="text-xs bg-indigo-100 text-indigo-600 px-1 rounded">{lbl}</span>}
                                            {gc.expect_no_tools
                                                ? <span className="text-xs bg-gray-100 text-gray-500 px-1 rounded">0 tools</span>
                                                : gc.expected_tools_all?.length
                                                ? <span className="text-xs bg-blue-50 text-blue-600 px-1 rounded">{gc.expected_tools_all.length} tool{gc.expected_tools_all.length > 1 ? "s" : ""}</span>
                                                : null}
                                        </div>
                                        <p className="text-gray-700 mt-0.5 text-xs leading-snug line-clamp-2">{gc.query}</p>
                                    </div>
                                </div>
                            </button>
                        )
                    })}
                </div>
            </div>

            {/* ── Right panel ── */}
            <div className="flex-1 overflow-y-auto p-6 bg-white">
                {!selectedCase ? (
                    <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                        Select a case on the left to run it.
                    </div>
                ) : (
                    <div className="max-w-3xl space-y-5">
                        {/* Header */}
                        <div>
                            <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-xs text-gray-400 font-mono">{selectedCase.id}</span>
                                {selectedResult?.status === "running" && (
                                    <span className="text-xs text-yellow-600 animate-pulse">⏳ {selectedResult.statusText}</span>
                                )}
                                {selectedResult?.status === "done" && (
                                    <span className={`text-xs font-semibold px-2 py-0.5 rounded ${selectedResult.pass ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                                        {selectedResult.pass ? "PASS" : "FAIL"}
                                    </span>
                                )}
                                {selectedResult?.status === "error" && (
                                    <span className="text-xs font-semibold px-2 py-0.5 rounded bg-red-100 text-red-700">ERROR</span>
                                )}
                            </div>
                            <p className="text-base font-medium text-gray-900 mt-1">{selectedCase.query}</p>
                            {selectedCase.notes && <p className="text-xs text-gray-400 mt-1 italic">{selectedCase.notes}</p>}
                        </div>

                        {/* Expectations grid */}
                        <div className="grid grid-cols-2 gap-4">
                            <Section title="Expected tools">
                                {selectedCase.expect_no_tools ? (
                                    <Chip color="gray">none (no-tools)</Chip>
                                ) : selectedCase.expected_tools_all?.length ? (
                                    selectedCase.expected_tools_all.map((t) => <Chip key={t} color="blue">{t}</Chip>)
                                ) : (
                                    <span className="text-gray-300 text-xs">—</span>
                                )}
                            </Section>
                            <Section title="Forbidden tools">
                                {selectedCase.forbidden_tools?.length ? (
                                    selectedCase.forbidden_tools.map((t) => <Chip key={t} color="red">{t}</Chip>)
                                ) : (
                                    <span className="text-gray-300 text-xs">—</span>
                                )}
                            </Section>
                        </div>

                        {/* Eval details */}
                        {selectedResult?.evalDetails && (
                            <Section title="Eval result">
                                <ul className="space-y-1 w-full">
                                    {selectedResult.evalDetails.map((d, i) => (
                                        <li key={i} className="text-xs text-gray-600">{d}</li>
                                    ))}
                                </ul>
                            </Section>
                        )}

                        {/* Tools called */}
                        {selectedResult?.toolsUsed !== undefined && (
                            <Section title="Tools actually called">
                                {selectedResult.toolsUsed.length === 0 ? (
                                    <Chip color="gray">none</Chip>
                                ) : (
                                    selectedResult.toolsUsed.map((t) => {
                                        const expNorm = normalise(selectedCase.expected_tools_all ?? [])
                                        const frbNorm = normalise(selectedCase.forbidden_tools ?? [])
                                        const bn = bareName(t)
                                        const isExp = expNorm.has(t) || expNorm.has(bn)
                                        const isFrb = frbNorm.has(t) || frbNorm.has(bn)
                                        return <Chip key={t} color={isFrb ? "red" : isExp ? "green" : "gray"}>{t}</Chip>
                                    })
                                )}
                            </Section>
                        )}

                        {/* Error */}
                        {selectedResult?.status === "error" && (
                            <Section title="Error">
                                <p className="text-xs text-red-500">{selectedResult.errorMsg}</p>
                            </Section>
                        )}

                        {/* Response */}
                        {responseText && (
                            <Section title="Response">
                                <div className="w-full">
                                    <ResponseRenderer text={responseText} vizs={vizs} />
                                </div>
                            </Section>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function Section({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <div>
            <h3 className="text-xs uppercase tracking-widest text-gray-400 mb-1.5">{title}</h3>
            <div className="flex flex-wrap gap-1.5">{children}</div>
        </div>
    )
}

function Chip({ children, color }: { children: React.ReactNode; color: "blue" | "red" | "green" | "gray" }) {
    const cls = {
        blue: "bg-blue-50 text-blue-700 border border-blue-200",
        red: "bg-red-50 text-red-700 border border-red-200",
        green: "bg-green-50 text-green-700 border border-green-200",
        gray: "bg-gray-50 text-gray-500 border border-gray-200",
    }[color]
    return <span className={`text-xs px-2 py-0.5 rounded font-mono ${cls}`}>{children}</span>
}
