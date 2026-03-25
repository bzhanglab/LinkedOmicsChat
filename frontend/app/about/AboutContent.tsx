"use client"
import { useState } from "react"
import Link from "next/link"
import { OmicsCohorts } from "./OmicsCohorts"

const TABS = [
    { id: "overview",     label: "Overview" },
    { id: "data",         label: "Data & Omics" },
    { id: "analyses",     label: "Analyses" },
    { id: "architecture", label: "How It Works" },
    { id: "cite",         label: "Cite & Contact" },
] as const

type TabId = typeof TABS[number]["id"]

const ANALYSES = [
    {
        name: "Survival analysis",
        desc: "Kaplan-Meier overall survival curves stratified by high/low expression or other molecular features. Returns the plot, log-rank p-value, hazard ratio, and a scrollable at-risk table for all event time points.",
    },
    {
        name: "Differential expression",
        desc: "Volcano plot of tumor vs. normal differential expression with user-configurable fold-change and significance thresholds. Highlights up- and down-regulated genes.",
    },
    {
        name: "Correlation analysis",
        desc: "Gene-level Spearman/Pearson correlation across omics layers within a cohort, returned as ranked tables with statistical significance.",
    },
    {
        name: "Multi-omics query",
        desc: "Natural-language retrieval of molecular profiles, co-expression partners, drug targets, and pathway-level summaries across all TCGA and CPTAC cohorts.",
    },
    {
        name: "Network & pathway",
        desc: "FunMap functional neighborhood analysis and WebGestalt pathway enrichment for gene sets of interest.",
    },
    {
        name: "Proteogenomics",
        desc: "Integration of CPTAC mass spectrometry proteomics and phosphoproteomics with matched TCGA genomic data for mRNA–protein and SCNA–protein correlation.",
    },
]

const EXAMPLE_QUERIES = [
    { q: "Is ESR1 associated with survival in BRCA?",    cat: "Survival" },
    { q: "Survival analysis for PIK3CA in LUAD",          cat: "Survival" },
    { q: "EGFR expression across TCGA LUAD",              cat: "Expression" },
    { q: "RB1 co-expression partners in OV",              cat: "Correlation" },
    { q: "Compare KRAS RNA vs protein in PDAC",           cat: "Proteogenomics" },
    { q: "Differential expression GBM vs normal",         cat: "Expression" },
    { q: "LinkedOmics network for MYC in BRCA",           cat: "Network" },
    { q: "Phosphoproteomics of EGFR in LUAD",             cat: "Proteogenomics" },
]

const CAT_STYLE: Record<string, string> = {
    "Survival":        "bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400",
    "Expression":      "bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400",
    "Correlation":     "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
    "Proteogenomics":  "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400",
    "Network":         "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
}

export function AboutContent() {
    const [active, setActive] = useState<TabId>("overview")

    return (
        <div className="min-h-screen bg-background text-foreground flex flex-col">
            {/* Header */}
            <header className="border-b border-border px-6 py-4 flex items-center justify-between shrink-0">
                <Link href="/" className="flex items-center gap-2.5 hover:opacity-80 transition-opacity">
                    <img src="/logo.png" alt="LinkedOmicsChat" className="h-7 w-auto" />
                    <span className="text-lg font-bold tracking-tight">
                        LinkedOmics<span className="text-teal-600 dark:text-teal-400">Chat</span>
                    </span>
                </Link>
                <div className="flex items-center gap-4">
                    <Link href="/welcome" className="text-sm text-muted-foreground hover:underline">Examples</Link>
                    <Link href="/" className="text-sm text-primary hover:underline">Launch app →</Link>
                </div>
            </header>

            {/* Tab bar */}
            <div className="border-b border-border shrink-0">
                <div className="max-w-4xl mx-auto px-6 flex gap-1 overflow-x-auto pt-2">
                    {TABS.map(({ id, label }) => (
                        <button
                            key={id}
                            onClick={() => setActive(id)}
                            className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                                active === id
                                    ? "border-primary text-primary"
                                    : "border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground"
                            }`}
                        >
                            {label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Content */}
            <main className="flex-1 max-w-4xl mx-auto w-full px-6 py-10">

                {active === "overview" && (
                    <div className="space-y-8">
                        <div>
                            <h1 className="text-3xl font-bold mb-3">
                                LinkedOmicsChat
                                {process.env.NEXT_PUBLIC_APP_VERSION && (
                                    <span className="ml-3 text-base font-normal text-muted-foreground align-middle">
                                        v{process.env.NEXT_PUBLIC_APP_VERSION}
                                    </span>
                                )}
                            </h1>
                            <p className="text-muted-foreground text-base leading-relaxed max-w-2xl">
                                An AI-powered conversational interface for multi-omics cancer research.
                                Ask natural-language questions about gene expression, survival, methylation,
                                copy number, and protein abundance across TCGA and CPTAC cohorts — and receive
                                publication-ready plots, ranked tables, and LLM-generated summaries in a single chat turn.
                            </p>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                            {[
                                { title: "32+ cancer types", sub: "TCGA & CPTAC cohorts via LinkedOmics" },
                                { title: "5 omics platforms", sub: "RNA · protein · methylation · CNV · miRNA" },
                                { title: "No coding required", sub: "Plain-English questions, structured results" },
                            ].map(({ title, sub }) => (
                                <div key={title} className="rounded-lg border border-border p-4 bg-muted/20 text-center">
                                    <p className="font-semibold text-sm mb-1">{title}</p>
                                    <p className="text-xs text-muted-foreground">{sub}</p>
                                </div>
                            ))}
                        </div>

                        <div>
                            <h2 className="text-base font-semibold mb-3">Try an example</h2>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                {EXAMPLE_QUERIES.slice(0, 4).map(({ q, cat }) => (
                                    <a
                                        key={q}
                                        href={`/?q=${encodeURIComponent(q)}`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/20 px-3 py-2 hover:bg-muted/50 hover:text-foreground transition-colors group"
                                    >
                                        <span className="text-xs text-muted-foreground group-hover:text-foreground">"{q}"</span>
                                        <span className={`text-xs px-1.5 py-0.5 rounded font-medium shrink-0 ${CAT_STYLE[cat] ?? ""}`}>{cat}</span>
                                    </a>
                                ))}
                            </div>
                            <p className="mt-3 text-xs text-muted-foreground">
                                More examples on the{" "}
                                <a href="/welcome" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">landing page</a>
                                {" "}— try as guest, no account required.
                            </p>
                        </div>
                    </div>
                )}

                {active === "data" && (
                    <div className="space-y-8">
                        <div>
                            <h2 className="text-xl font-semibold mb-4">Data Sources</h2>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
                                <div className="rounded-lg border border-border p-4 bg-muted/20">
                                    <div className="flex items-center justify-between mb-2">
                                        <h3 className="font-semibold text-sm">
                                            <a href="https://www.cancer.gov/tcga" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                                                TCGA — The Cancer Genome Atlas ↗
                                            </a>
                                        </h3>
                                        <span className="text-xs px-2 py-0.5 rounded-full bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-400 font-medium">NCI</span>
                                    </div>
                                    <p className="text-xs text-muted-foreground leading-relaxed">
                                        Multi-omics profiling of 11,000+ tumor samples across 32 cancer types. Includes mRNA, miRNA, methylation, copy number, protein (RPPA), and clinical data.
                                    </p>
                                    <a href="https://www.linkedomics.org/login.php#dataSource" target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-xs text-primary hover:underline">
                                        View cohorts on LinkedOmics ↗
                                    </a>
                                </div>
                                <div className="rounded-lg border border-border p-4 bg-muted/20">
                                    <div className="flex items-center justify-between mb-2">
                                        <h3 className="font-semibold text-sm">
                                            <a href="https://proteomics.cancer.gov/programs/cptac" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                                                CPTAC — Clinical Proteomic Tumor Analysis Consortium ↗
                                            </a>
                                        </h3>
                                        <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-400 font-medium">NCI</span>
                                    </div>
                                    <p className="text-xs text-muted-foreground leading-relaxed">
                                        Mass spectrometry-based global proteomics and phosphoproteomics on 10 tumor cohorts, integrated with matched TCGA genomic data for proteogenomic analysis.
                                    </p>
                                    <a href="https://www.linkedomics.org/login.php#dataSource" target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-xs text-primary hover:underline">
                                        View cohorts on LinkedOmics ↗
                                    </a>
                                </div>
                            </div>
                            <p className="text-xs text-muted-foreground">
                                All data are accessed in real time via{" "}
                                <a href="https://www.linkedomics.org" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">LinkedOmics</a>
                                {" "}(linkedomics.org). LinkedOmicsChat does not store or redistribute raw omics data.
                            </p>
                        </div>

                        <div>
                            <h2 className="text-xl font-semibold mb-4">Omics Platforms & Cohorts</h2>
                            <OmicsCohorts />
                        </div>
                    </div>
                )}

                {active === "analyses" && (
                    <div className="space-y-8">
                        <div>
                            <h2 className="text-xl font-semibold mb-4">Supported Analyses</h2>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                {ANALYSES.map((a) => (
                                    <div key={a.name} className="rounded-lg border border-border p-4 bg-muted/20">
                                        <h3 className="font-semibold text-sm mb-1">{a.name}</h3>
                                        <p className="text-xs text-muted-foreground leading-relaxed">{a.desc}</p>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div>
                            <h2 className="text-xl font-semibold mb-4">Example Queries</h2>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                {EXAMPLE_QUERIES.map(({ q, cat }) => (
                                    <a
                                        key={q}
                                        href={`/?q=${encodeURIComponent(q)}`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/20 px-3 py-2 hover:bg-muted/50 transition-colors group"
                                    >
                                        <span className="text-xs text-muted-foreground group-hover:text-foreground">"{q}"</span>
                                        <span className={`text-xs px-1.5 py-0.5 rounded font-medium shrink-0 ${CAT_STYLE[cat] ?? ""}`}>{cat}</span>
                                    </a>
                                ))}
                            </div>
                        </div>
                    </div>
                )}

                {active === "architecture" && (
                    <div className="space-y-8">
                        <div>
                            <h2 className="text-xl font-semibold mb-4">How It Works</h2>
                            <p className="text-sm text-muted-foreground leading-relaxed mb-6">
                                LinkedOmicsChat uses a large language model (LLM) orchestrated via the{" "}
                                <a href="https://modelcontextprotocol.io" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                                    Model Context Protocol (MCP)
                                </a>{" "}
                                to route user queries to specialized tools — each responsible for a distinct analysis.
                                The LLM selects and calls the appropriate tool, interprets the results, generates plots,
                                and synthesizes a plain-language summary. Session history is persisted per user for reproducibility.
                            </p>

                            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                                {[
                                    { step: "01", title: "User query", desc: "Ask a natural-language research question in the chat interface." },
                                    { step: "02", title: "LLM routing", desc: "The LLM identifies the appropriate analysis tool and parameters via MCP." },
                                    { step: "03", title: "Live data fetch", desc: "The tool queries LinkedOmics in real time and returns structured results." },
                                    { step: "04", title: "Plot generation", desc: "Publication-ready plots (KM curves, volcano plots) are generated server-side." },
                                    { step: "05", title: "Summary", desc: "The LLM synthesizes a plain-language interpretation of the results." },
                                    { step: "06", title: "Export & share", desc: "Sessions can be exported as HTML or shared via a public link." },
                                ].map(({ step, title, desc }) => (
                                    <div key={step} className="rounded-lg border border-border p-4 bg-muted/20 relative">
                                        <span className="absolute top-3 right-3 text-2xl font-black text-muted-foreground/20">{step}</span>
                                        <p className="font-semibold text-sm mb-1">{title}</p>
                                        <p className="text-xs text-muted-foreground leading-relaxed">{desc}</p>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                )}

                {active === "cite" && (
                    <div className="space-y-8">
                        <div>
                            <h2 className="text-xl font-semibold mb-4">How to Cite</h2>
                            <div className="rounded-lg border border-border bg-muted/30 p-4 text-sm text-muted-foreground mb-4">
                                Citation information will be available upon publication.
                            </div>
                            <p className="text-xs text-muted-foreground leading-relaxed">
                                Please also cite the LinkedOmics resource:{" "}
                                <span className="italic">
                                    Vasaikar SV, Straub P, Wang J, Zhang B. LinkedOmics: analyzing multi-omics data within and across 32 cancer types.
                                    Nucleic Acids Research, 2018.
                                </span>
                            </p>
                        </div>

                        <div>
                            <h2 className="text-xl font-semibold mb-4">Contact & Support</h2>
                            <div className="space-y-3 text-sm text-muted-foreground">
                                <p>
                                    LinkedOmicsChat is developed and maintained by the{" "}
                                    <a href="https://www.zhang-lab.org" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">Zhang Lab</a>.
                                </p>
                                <p>
                                    For bug reports and feature requests, please open an issue on{" "}
                                    <a href="https://github.com/bzhanglab/LinkedOmicsChat" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                                        GitHub ↗
                                    </a>.
                                </p>
                                <p>
                                    For general questions about LinkedOmics data, visit{" "}
                                    <a href="https://www.linkedomics.org" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                                        linkedomics.org ↗
                                    </a>.
                                </p>
                            </div>
                        </div>
                    </div>
                )}

            </main>

            <footer className="border-t border-border px-6 py-6 text-center text-xs text-muted-foreground shrink-0">
                &copy; {new Date().getFullYear()} Zhang Lab &middot;{" "}
                <Link href="/" className="hover:underline">Launch app</Link>
            </footer>
        </div>
    )
}
