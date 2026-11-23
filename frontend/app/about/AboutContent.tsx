"use client"
import { useState } from "react"
import Link from "next/link"
import { OmicsCohorts } from "./OmicsCohorts"
import { DrugTargetsPrimer } from "@/components/DrugTargetsPrimer"
import { ClinicalTrialsPrimer } from "@/components/ClinicalTrialsPrimer"
import { ToolCategoryGuide } from "@/components/ToolCategoryGuide"

const TABS = [
    { id: "overview", label: "Overview" },
    { id: "data",     label: "Data" },
    { id: "analyses", label: "Analyses" },
    { id: "cite",     label: "Cite & contact" },
] as const

type TabId = typeof TABS[number]["id"]

// Papers to cite for the resources behind the analyses (PubMed entries confirmed by the lab, 2026-11-18).
const REFERENCES = [
    { resource: "LinkedOmics (TCGA analyses)", pmid: "29136207", citation: "Vasaikar SV, Straub P, Wang J, Zhang B. LinkedOmics: analyzing multi-omics data within and across 32 cancer types. Nucleic Acids Res. 2018;46(D1):D956-D963." },
    { resource: "LinkedOmicsKB (CPTAC analyses)", pmid: "37619559", citation: "Liao Y, Savage SR, Dou Y, et al. A proteogenomics data-driven knowledge base of human cancer. Cell Syst. 2023;14(9):777-787.e5." },
    { resource: "CPTAC data", pmid: "37582339", citation: "Li Y, Dou Y, Da Veiga Leprevost F, et al. Proteogenomic data and resources for pan-cancer analysis. Cancer Cell. 2023;41(8):1397-1406." },
    { resource: "TCGA data", pmid: "24071849", citation: "Weinstein JN, Collisson EA, Mills GB, et al. The Cancer Genome Atlas Pan-Cancer analysis project. Nat Genet. 2013;45(10):1113-1120." },
    { resource: "ClinicalOmicsDB (treatment response)", pmid: "37811874", citation: "Moon CI, Elizarraras JM, Lei JT, Jia B, Zhang B. ClinicalOmicsDB: exploring molecular associations of oncology drug responses in clinical trials. Nucleic Acids Res. 2024;52(D1):D1201-D1209." },
    { resource: "LinkedOmics Targets (drug targets)", pmid: "38917788", citation: "Savage SR, Yi X, Lei JT, et al. Pan-cancer proteogenomics expands the landscape of therapeutic targets. Cell. 2024;187(16):4389-4407.e15." },
    { resource: "FunMap (functional network)", pmid: "39663389", citation: "Shi Z, Lei JT, Elizarraras JM, Zhang B. Mapping the functional network of human cancer through machine learning and pan-cancer proteogenomics. Nat Cancer. 2025;6(1):205-222." },
    { resource: "WebGestalt (pathway enrichment)", pmid: "38808672", citation: "Elizarraras JM, Liao Y, Shi Z, Zhu Q, Pico AR, Zhang B. WebGestalt 2024: faster gene set analysis and new support for metabolomics and multi-omics. Nucleic Acids Res. 2024;52(W1):W415-W421." },
    { resource: "MyGene.info (gene ID conversion)", pmid: "27154141", citation: "Xin J, Mark A, Afrasiabi C, et al. High-performance web services for querying gene and variant annotation. Genome Biol. 2016;17:91." },
]

// Example questions are from the golden test set (backend/examples/langgraph_golden_queries.json).
const ANALYSES = [
    {
        name: "Survival",
        desc: "CPTAC survival by RNA or protein in 10 cohorts, and TCGA survival by RNA, methylation, copy number, or miRNA in 35 cohorts (TCGA protein, RPPA, is left out because its source files give some genes identical or misaligned values). TCGA also supports pan-cancer comparisons and genome-wide scans within a cohort. TCGA results include Kaplan-Meier plots with at-risk tables; in pan-cancer comparisons, for up to five cohorts with p < 0.05.",
        example: "Show TP53 overall survival in BRCA.",
    },
    {
        name: "Tumor vs. normal",
        desc: "RNA and protein in tumors compared with adjacent normal tissue, per CPTAC cohort.",
        example: "How is EGFR expressed tumor vs normal in LUAD?",
    },
    {
        name: "Same-gene correlations",
        desc: "Correlations between layers of one gene (copy number vs. RNA, methylation vs. RNA, RNA vs. protein) in CPTAC or TCGA, including genome-wide TCGA scans for the strongest associations.",
        example: "Show cis-correlations for MYC.",
    },
    {
        name: "Drug targets",
        desc: "Per-gene target profiles from LinkedOmics Targets (tier, drugs, dependency, overexpression, phosphosite activation, driver and antigen evidence), plus target search and ranking.",
        example: "Is EGFR a validated oncology target?",
    },
    {
        name: "Treatment response",
        desc: "Genes and gene sets associated with response or resistance in ClinicalOmicsDB studies, study lookup by drug or cancer type, and cross-study meta-analysis.",
        example: "Which genes best predict paclitaxel response in breast cancer?",
    },
    {
        name: "Functional networks",
        desc: "A gene's top-50 FunMap neighborhood, shown as an interactive network.",
        example: "Find functional neighbors of TP53 in the FunMap network.",
    },
    {
        name: "Pathway enrichment",
        desc: "Gene Ontology biological-process over-representation analysis in WebGestalt, for your own gene list or genes from an earlier step.",
        example: "What pathways are enriched in this gene set: EGFR, MET, ERBB2, ALK, RET?",
    },
    {
        name: "Literature",
        desc: "PubMed search and article details.",
        example: "Find recent papers on ESR1 and breast cancer survival.",
    },
]

const OVERVIEW_EXAMPLES = [
    "Is EGFR overexpressed in lung cancer and is it a validated drug target?",
    "Which genes best predict paclitaxel response in breast cancer?",
    "Show TP53 overall survival in BRCA.",
    "Find functional neighbors of TP53 in the FunMap network.",
]

function QuestionLink({ q }: { q: string }) {
    return (
        <a
            href={`/?q=${encodeURIComponent(q)}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline"
        >
            &ldquo;{q}&rdquo;
        </a>
    )
}

export function AboutContent() {
    const [active, setActive] = useState<TabId>("overview")

    return (
        <div className="min-h-screen bg-slate-50 dark:bg-background text-foreground flex flex-col">
            {/* Header */}
            <header className="sticky top-0 z-20 bg-white/80 dark:bg-background/80 backdrop-blur border-b border-border shrink-0">
                <div className="max-w-4xl mx-auto px-6 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <Link href="/" className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors text-sm font-medium">
                            <img src="/logo.png" alt="" className="h-5 w-auto" />
                            LinkedOmicsChat
                        </Link>
                        <span className="text-border">/</span>
                        <span className="text-sm font-semibold text-foreground">About</span>
                    </div>
                    <Link href="/docs" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
                        Documentation
                    </Link>
                </div>
            </header>

            {/* Tab bar */}
            <div className="border-b border-border shrink-0">
                <div className="max-w-4xl mx-auto px-6 flex gap-1 overflow-x-auto pt-2">
                    {TABS.map(({ id, label }) => (
                        <button
                            key={id}
                            onClick={() => setActive(id)}
                            className={`px-4 py-2.5 text-base font-medium whitespace-nowrap border-b-2 transition-colors ${
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
                    <div className="space-y-6 max-w-2xl">
                        <h1 className="text-3xl font-bold">
                            LinkedOmicsChat
                            {process.env.NEXT_PUBLIC_APP_VERSION && (
                                <span className="ml-3 text-base font-normal text-muted-foreground align-middle">
                                    v{process.env.NEXT_PUBLIC_APP_VERSION}
                                </span>
                            )}
                        </h1>
                        <p className="text-base text-muted-foreground leading-relaxed">
                            LinkedOmicsChat is a chat interface to LinkedOmics and related cancer resources. A question in
                            plain English is turned into analyses on TCGA and CPTAC multi-omics data, clinical-trial
                            expression studies, drug-target annotations, the FunMap network, and WebGestalt, and the answer
                            comes back as the plots and tables those analyses produce, with a short written summary.
                        </p>
                        <p className="text-base text-muted-foreground leading-relaxed">
                            It covers 35 TCGA cohorts and 10 CPTAC cohorts through 26 analysis tools. It is free and needs
                            no account; signing in adds saved history, sharing, HTML export, and higher hourly limits.
                        </p>
                        <div>
                            <h2 className="text-lg font-semibold mb-3">Try an example</h2>
                            <ul className="space-y-2 text-base">
                                {OVERVIEW_EXAMPLES.map((q) => <li key={q}><QuestionLink q={q} /></li>)}
                            </ul>
                            <p className="mt-4 text-sm text-muted-foreground">
                                Each opens a new chat with the question filled in, ready to send. The{" "}
                                <Link href="/docs" className="text-primary hover:underline">documentation</Link>{" "}
                                has more examples, explains how to read the results, and describes how the app works.
                            </p>
                        </div>
                    </div>
                )}

                {active === "data" && (
                    <div className="space-y-8">
                        <div className="max-w-3xl space-y-4">
                            <h2 className="text-xl font-semibold">Datasets</h2>
                            <p className="text-base text-muted-foreground leading-relaxed">
                                <a href="https://www.cancer.gov/tcga" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">TCGA</a>{" "}
                                data come from{" "}
                                <a href="https://www.linkedomics.org" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">LinkedOmics</a>:
                                more than 11,000 tumors from 32 primary cancer types, organized as 35 cohort codes (four of
                                them combine related types, such as COADREAD). The app uses RNA-seq, miRNA-seq, methylation,
                                copy number, and overall survival. It leaves out RPPA protein, whose source files give
                                some genes identical or misaligned values.
                            </p>
                            <p className="text-base text-muted-foreground leading-relaxed">
                                <a href="https://proteomics.cancer.gov/programs/cptac" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">CPTAC</a>{" "}
                                data come from{" "}
                                <a href="https://kb.linkedomics.org" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">LinkedOmicsKB</a>:
                                10 proteogenomic cohorts with mass-spectrometry proteomics alongside RNA, methylation, and copy
                                number. Phosphoproteomics appears only as phosphosite activation in drug-target profiles.
                            </p>
                            <p className="text-base text-muted-foreground leading-relaxed">
                                The other resources (ClinicalOmicsDB, LinkedOmics Targets, FunMap, WebGestalt, PubMed, and
                                MyGene.info) are described under{" "}
                                <Link href="/docs#data-sources" className="text-primary hover:underline">Data sources</Link>{" "}
                                in the documentation. LinkedOmicsChat keeps no copy of any of these datasets; each analysis
                                queries the service when you ask.
                            </p>
                        </div>

                        <div>
                            <h2 className="text-xl font-semibold mb-4">Omics data and cohorts</h2>
                            <OmicsCohorts />
                        </div>
                    </div>
                )}

                {active === "analyses" && (
                    <div className="space-y-10">
                        <div>
                            <h2 className="text-xl font-semibold mb-2">Analyses</h2>
                            <p className="text-base text-muted-foreground mb-4">
                                One example question per analysis; clicking one opens a new chat with the question filled in, ready to send.
                            </p>
                            <dl className="divide-y divide-border rounded-lg border border-border bg-white/70 dark:bg-transparent">
                                {ANALYSES.map((a) => (
                                    <div key={a.name} className="px-4 py-3.5 sm:grid sm:grid-cols-[11rem_1fr] sm:gap-6">
                                        <dt className="font-semibold text-base">{a.name}</dt>
                                        <dd className="mt-1 sm:mt-0 text-sm text-muted-foreground leading-relaxed">
                                            {a.desc}
                                            <span className="block mt-1.5"><QuestionLink q={a.example} /></span>
                                        </dd>
                                    </div>
                                ))}
                            </dl>
                        </div>

                        <div>
                            <h2 className="text-xl font-semibold mb-4">Interpretation guides</h2>
                            <div className="space-y-4">
                                <DrugTargetsPrimer />
                                <ClinicalTrialsPrimer />
                                <ToolCategoryGuide category="functional-networks" />
                                <ToolCategoryGuide category="pathway-enrichment" />
                                <ToolCategoryGuide category="survival-analysis" />
                                <ToolCategoryGuide category="expression-analysis" />
                            </div>
                        </div>
                    </div>
                )}

                {active === "cite" && (
                    <div className="space-y-8 max-w-2xl">
                        <div>
                            <h2 className="text-xl font-semibold mb-3">Citing</h2>
                            <p className="text-base text-muted-foreground leading-relaxed">
                                There is no LinkedOmicsChat paper yet. If you use it in published work, please cite the
                                resources behind the analyses you used:
                            </p>
                            <ul className="mt-4 space-y-3">
                                {REFERENCES.map((ref) => (
                                    <li key={ref.pmid} className="text-sm leading-relaxed">
                                        <span className="font-medium text-foreground">{ref.resource}</span>
                                        <span className="block text-muted-foreground">
                                            {ref.citation}{" "}
                                            <a href={`https://pubmed.ncbi.nlm.nih.gov/${ref.pmid}/`} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                                                PMID {ref.pmid}
                                            </a>
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        </div>

                        <div>
                            <h2 className="text-xl font-semibold mb-3">Contact</h2>
                            <p className="text-base text-muted-foreground leading-relaxed">
                                LinkedOmicsChat is developed and maintained by the{" "}
                                <a href="https://www.zhang-lab.org" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">Zhang Lab</a>.
                                Report bugs and request features on{" "}
                                <a href="https://github.com/bzhanglab/LinkedOmicsChat/issues" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">GitHub</a>.
                                Questions about the underlying data are best directed to{" "}
                                <a href="https://www.linkedomics.org" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">LinkedOmics</a>.
                            </p>
                        </div>
                    </div>
                )}

            </main>

            <footer className="border-t border-border px-6 py-6 text-center text-xs text-muted-foreground shrink-0">
                &copy; {new Date().getFullYear()} Zhang Lab &middot; Free to use &middot; Source code under the{" "}
                <a href="https://github.com/bzhanglab/LinkedOmicsChat/blob/main/LICENSE" target="_blank" rel="noopener noreferrer" className="underline hover:text-foreground">MIT License</a>
            </footer>
        </div>
    )
}
