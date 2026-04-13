"use client"

import Link from "next/link"
import { ArrowLeft, ArrowUpRight, Database, MessageSquare, Cpu, HelpCircle, BookOpen } from "lucide-react"

// ── Shared primitives ──────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
    return (
        <p className="text-xs font-bold uppercase tracking-widest text-teal-600 mb-3">
            {children}
        </p>
    )
}

function SectionTitle({ children, icon }: { children: React.ReactNode; icon?: React.ReactNode }) {
    return (
        <h2 className="text-2xl font-bold tracking-tight text-slate-900 mb-2 flex items-center gap-3">
            {icon && <span className="text-teal-500">{icon}</span>}
            {children}
        </h2>
    )
}

function SectionDesc({ children }: { children: React.ReactNode }) {
    return (
        <p className="text-slate-500 leading-relaxed mb-8">
            {children}
        </p>
    )
}

function Divider() {
    return <hr className="border-slate-100 my-12" />
}

// ── Data ──────────────────────────────────────────────────────────────────

const DATA_SOURCES = [
    {
        name: "LinkedOmics",
        url: "https://www.linkedomics.org",
        color: "bg-teal-50 border-teal-100",
        dot: "bg-teal-500",
        description: "Core multi-omics and analysis services used by the app, including TCGA survival, CPTAC-integrated expression and correlation analyses, drug target annotations, and treatment-response studies served through LinkedOmics-hosted APIs.",
        tools: ["TCGA survival", "CPTAC-integrated expression", "Drug target lookup", "Clinical trial studies"],
    },
    {
        name: "FunMap",
        url: "https://funmap.linkedomics.org",
        color: "bg-emerald-50 border-emerald-100",
        dot: "bg-emerald-500",
        description: "Functional proteogenomic interaction network for discovering gene co-functional neighborhoods and pathway modules.",
        tools: ["Gene functional neighborhood", "Protein interaction graph", "Module-level enrichment"],
    },
    {
        name: "WebGestalt",
        url: "https://www.webgestalt.org",
        color: "bg-violet-50 border-violet-100",
        dot: "bg-violet-500",
        description: "Gene set enrichment analysis across GO, KEGG, WikiPathways, and other ontology databases.",
        tools: ["Pathway enrichment (ORA)", "GSEA enrichment", "Network topology-based analysis"],
    },
    {
        name: "CPTAC",
        url: "https://proteomics.cancer.gov/programs/cptac",
        color: "bg-rose-50 border-rose-100",
        dot: "bg-rose-500",
        description: "Underlying proteomics and phosphoproteomics datasets used in LinkedOmics-supported proteogenomic analyses across 10 cohorts.",
        tools: ["Protein abundance", "Phosphorylation sites", "mRNA-protein correlation", "Clinical metadata"],
    },
    {
        name: "PubMed",
        url: "https://pubmed.ncbi.nlm.nih.gov",
        color: "bg-amber-50 border-amber-100",
        dot: "bg-amber-500",
        description: "NCBI literature search integrated into the research workflow for evidence-backed answers.",
        tools: ["Keyword and gene searches", "Recent publication summaries", "Abstract-level evidence"],
    },
    {
        name: "MyGene.info",
        url: "https://mygene.info",
        color: "bg-sky-50 border-sky-100",
        dot: "bg-sky-500",
        description: "Identifier normalization service used to resolve Ensembl and UniProt identifiers to HGNC gene symbols before analysis.",
        tools: ["Gene ID normalization", "Ensembl to HGNC", "UniProt to HGNC"],
    },
]

const EXAMPLE_CATEGORIES = [
    {
        label: "Survival Analysis",
        color: "text-rose-700 bg-rose-50 border-rose-100",
        queries: [
            "Is ESR1 associated with overall survival in breast cancer?",
            "Compare survival outcomes for high vs low MYC expression in LUAD",
            "Show me survival analysis for PIK3CA across all TCGA cancer types",
        ],
    },
    {
        label: "Gene Expression",
        color: "text-teal-700 bg-teal-50 border-teal-100",
        queries: [
            "What is the expression profile of EGFR across TCGA cancer types?",
            "Show tumor vs normal expression for TP53 in colorectal cancer",
            "Find genes co-expressed with BRCA1 in ovarian cancer",
        ],
    },
    {
        label: "Proteomics",
        color: "text-violet-700 bg-violet-50 border-violet-100",
        queries: [
            "Compare KRAS RNA and protein levels in pancreatic cancer",
            "Show EGFR phosphorylation sites in LUAD from CPTAC",
            "What is the mRNA–protein correlation for MYC in breast cancer?",
        ],
    },
    {
        label: "Network & Pathway",
        color: "text-emerald-700 bg-emerald-50 border-emerald-100",
        queries: [
            "Find functional neighbors of TP53 in the FunMap network",
            "Run pathway enrichment for BRCA1 FunMap partners",
            "What pathways are enriched in PTEN-low tumors?",
        ],
    },
    {
        label: "Multi-step",
        color: "text-slate-700 bg-slate-50 border-slate-200",
        queries: [
            "Find BRCA1 drug targets, then show their survival associations in BRCA",
            "Get TP53 functional neighbors, then run WebGestalt enrichment on them",
            "Show KRAS expression in PDAC and find relevant clinical trials",
        ],
    },
]

const ARCH_STEPS = [
    {
        step: "1",
        title: "You type a question",
        desc: "Natural language query with no required syntax — gene name, cancer type, and analysis type are inferred from context.",
    },
    {
        step: "2",
        title: "LangGraph plans the steps",
        desc: "A LangGraph agent decides which tools to call, in what order, and with what parameters — including multi-step chains.",
    },
    {
        step: "3",
        title: "MCP tools query real APIs",
        desc: "Each tool calls the relevant live endpoint or service layer, including LinkedOmics-hosted APIs, FunMap, WebGestalt, PubMed, and MyGene.info.",
    },
    {
        step: "4",
        title: "LLM synthesizes the answer",
        desc: "Results are formatted into a cited markdown response with visualizations, tables, and literature references.",
    },
]

const FAQS = [
    {
        q: "Do I need an account to use LinkedOmicsChat?",
        a: "No. You can try the platform as a guest — click any chip on the welcome page or use the 'Try as guest' button. Create an account to save session history and export results.",
    },
    {
        q: "What cancer types are supported?",
        a: "TCGA survival analysis supports 35 cohort codes, including aggregate cohorts such as COADREAD, GBMLGG, KIPAN, and STES. CPTAC-integrated expression, survival, and correlation analyses currently cover 10 cohorts: BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, and UCEC.",
    },
    {
        q: "Can it run multi-step analyses automatically?",
        a: "Yes. The LangGraph agent can chain tools without you specifying the steps. For example: 'Find BRCA1 neighbors and run enrichment' automatically calls FunMap, collects the gene list, then calls WebGestalt with those genes.",
    },
    {
        q: "What if my question is ambiguous?",
        a: "The assistant will ask a focused clarification question rather than guessing. For finite choices (like analysis type), it shows quick-select option chips. For open-ended inputs like gene names, it asks directly.",
    },
    {
        q: "Is the data real or simulated?",
        a: "Production responses use live API calls to LinkedOmics-hosted services, FunMap, WebGestalt, PubMed, and MyGene.info as needed.",
    },
]

// ── Page ──────────────────────────────────────────────────────────────────

export default function DocsPage() {
    return (
        <div className="min-h-screen bg-slate-50">

            {/* Nav */}
            <nav className="sticky top-0 z-20 bg-white/80 backdrop-blur border-b border-slate-100">
                <div className="max-w-4xl mx-auto px-6 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <Link href="/" className="flex items-center gap-1.5 text-slate-500 hover:text-slate-900 transition-colors text-sm">
                            <ArrowLeft className="w-4 h-4" />
                            Back
                        </Link>
                        <span className="text-slate-200">/</span>
                        <span className="text-sm font-semibold text-slate-700">Documentation</span>
                    </div>
                    <Link
                        href="/register"
                        className="bg-teal-600 hover:bg-teal-700 text-white text-xs font-semibold px-4 py-1.5 rounded-lg transition-colors"
                    >
                        Get started
                    </Link>
                </div>
            </nav>

            <div className="max-w-4xl mx-auto px-6 py-14">

                {/* Hero */}
                <div className="mb-14">
                    <div className="inline-flex items-center gap-2 bg-white/80 border border-teal-100 text-teal-700 text-xs font-semibold px-3 py-1.5 rounded-full mb-6">
                        <span className="w-1.5 h-1.5 rounded-full bg-teal-500" />
                        LinkedOmicsChat · Documentation
                    </div>
                    <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-slate-900 leading-tight flex items-center gap-4">
                        <BookOpen className="w-10 h-10 text-teal-500 stroke-[1.5] flex-shrink-0" />
                        Everything you need to know
                    </h1>
                    <p className="mt-4 text-lg text-slate-500 max-w-2xl leading-relaxed">
                        LinkedOmicsChat is a natural language interface to cancer multi-omics databases.
                        Ask research questions in plain English and get structured, cited answers from
                        real data sources.
                    </p>
                </div>

                <Divider />

                {/* Data Sources */}
                <section id="data-sources">
                    <SectionLabel>Data Sources</SectionLabel>
                    <SectionTitle icon={<Database className="w-6 h-6" />}>Where the data comes from</SectionTitle>
                    <SectionDesc>
                        Results are grounded in live API calls to these datasets and services.
                        Different workflows query different sources in real time depending on the question.
                    </SectionDesc>

                    <div className="grid sm:grid-cols-2 gap-4">
                        {DATA_SOURCES.map((src) => (
                            <div key={src.name} className={`rounded-2xl border p-5 ${src.color}`}>
                                <div className="flex items-center justify-between mb-3">
                                    <div className="flex items-center gap-2">
                                        <span className={`w-2 h-2 rounded-full ${src.dot}`} />
                                        <span className="text-sm font-bold text-slate-900">{src.name}</span>
                                    </div>
                                    <a
                                        href={src.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-xs text-slate-400 hover:text-slate-700 transition-colors flex items-center gap-0.5"
                                    >
                                        Visit <ArrowUpRight className="w-3 h-3" />
                                    </a>
                                </div>
                                <p className="text-xs text-slate-600 leading-relaxed mb-3">
                                    {src.description}
                                </p>
                                <div className="flex flex-wrap gap-1.5">
                                    {src.tools.map((t) => (
                                        <span key={t} className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-white/70 border border-white text-slate-600">
                                            {t}
                                        </span>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>
                </section>

                <Divider />

                {/* Example Queries */}
                <section id="examples">
                    <SectionLabel>Example Queries</SectionLabel>
                    <SectionTitle icon={<MessageSquare className="w-6 h-6" />}>What you can ask</SectionTitle>
                    <SectionDesc>
                        These are representative questions across analysis types. You can also click
                        example chips on the welcome page to launch them directly.
                    </SectionDesc>

                    <div className="space-y-4">
                        {EXAMPLE_CATEGORIES.map((cat) => (
                            <div key={cat.label} className="rounded-2xl border border-slate-200/80 bg-white/70 overflow-hidden">
                                <div className={`px-5 py-3 border-b border-inherit flex items-center gap-2`}>
                                    <span className={`text-xs font-bold px-2.5 py-1 rounded-full border ${cat.color}`}>
                                        {cat.label}
                                    </span>
                                </div>
                                <ul className="divide-y divide-slate-100">
                                    {cat.queries.map((q) => (
                                        <li key={q} className="px-5 py-3 text-sm text-slate-700 flex items-start gap-2">
                                            <span className="text-slate-300 mt-0.5 select-none">"</span>
                                            <span>{q}</span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        ))}
                    </div>
                </section>

                <Divider />

                {/* How it works */}
                <section id="architecture">
                    <SectionLabel>Architecture</SectionLabel>
                    <SectionTitle icon={<Cpu className="w-6 h-6" />}>How a query becomes an answer</SectionTitle>
                    <SectionDesc>
                        LinkedOmicsChat uses a LangGraph agent loop with MCP-connected tool servers.
                        The LLM autonomously decides which tools to call and in what order — enabling
                        multi-step analyses without manual workflow configuration.
                    </SectionDesc>

                    <div className="grid sm:grid-cols-2 gap-4">
                        {ARCH_STEPS.map((s) => (
                            <div key={s.step} className="rounded-2xl border border-slate-200/80 bg-white/70 p-5 flex gap-4">
                                <span className="flex-shrink-0 w-8 h-8 rounded-full bg-teal-600 text-white text-sm font-bold flex items-center justify-center shadow-sm shadow-teal-200">
                                    {s.step}
                                </span>
                                <div>
                                    <p className="text-sm font-semibold text-slate-900 mb-1">{s.title}</p>
                                    <p className="text-sm text-slate-500 leading-relaxed">{s.desc}</p>
                                </div>
                            </div>
                        ))}
                    </div>

                    <div className="mt-6 rounded-2xl border border-slate-200/80 bg-slate-50/80 p-5">
                        <p className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-3">Tech stack</p>
                        <div className="flex flex-wrap gap-2">
                            {["FastAPI", "LangGraph", "Model Context Protocol (MCP)", "Next.js", "FastMCP", "LangChain"].map((t) => (
                                <span key={t} className="text-xs font-medium px-2.5 py-1 rounded-full border border-slate-200 bg-white text-slate-600">
                                    {t}
                                </span>
                            ))}
                        </div>
                    </div>
                </section>

                <Divider />

                {/* FAQ */}
                <section id="faq">
                    <SectionLabel>FAQ</SectionLabel>
                    <SectionTitle icon={<HelpCircle className="w-6 h-6" />}>Common questions</SectionTitle>

                    <div className="space-y-4">
                        {FAQS.map((faq) => (
                            <div key={faq.q} className="rounded-2xl border border-slate-200/80 bg-white/70 p-5">
                                <p className="text-sm font-semibold text-slate-900 mb-2">{faq.q}</p>
                                <p className="text-sm text-slate-500 leading-relaxed">{faq.a}</p>
                            </div>
                        ))}
                    </div>
                </section>

                <Divider />

                {/* CTA */}
                <div className="text-center pb-4">
                    <p className="text-slate-500 text-sm mb-4">Ready to start exploring your research questions?</p>
                    <div className="flex justify-center gap-3">
                        <Link
                            href="/register"
                            className="bg-teal-600 hover:bg-teal-700 text-white font-semibold px-6 py-2.5 rounded-xl text-sm transition-colors shadow-md shadow-teal-200 inline-flex items-center gap-2"
                        >
                            Create free account
                            <ArrowUpRight className="w-4 h-4" />
                        </Link>
                        <Link
                            href="/"
                            className="border border-slate-200 hover:border-slate-300 bg-white/80 hover:bg-white text-slate-700 font-semibold px-6 py-2.5 rounded-xl text-sm transition-colors"
                        >
                            Open workspace
                        </Link>
                    </div>
                    <p className="mt-6 text-xs text-slate-400">
                        Built by Zhang Lab · Data and services from LinkedOmics, TCGA, CPTAC, PubMed, and related research resources
                    </p>
                </div>

            </div>
        </div>
    )
}
