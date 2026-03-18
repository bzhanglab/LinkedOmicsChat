"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { useAuth } from "@/components/AuthContext"
import { MessageCircle, DatabaseZap, FileCheck2, Zap, MousePointerClick, ChevronDown } from "lucide-react"

type Category = "survival" | "expression" | "network" | "proteomics" | "mutation"

const CAT_STYLE: Record<Category, string> = {
    survival:   "bg-rose-100    border-rose-400   text-slate-700 hover:bg-rose-200",
    expression: "bg-teal-100    border-teal-400   text-slate-700 hover:bg-teal-200",
    network:    "bg-emerald-100 border-emerald-400 text-slate-700 hover:bg-emerald-200",
    proteomics: "bg-indigo-100  border-indigo-400 text-slate-700 hover:bg-indigo-200",
    mutation:   "bg-orange-100  border-orange-400 text-slate-700 hover:bg-orange-200",
}

const CAT_ROW_STYLE: Record<Category, string> = {
    survival:   "bg-rose-50/60    border-rose-100   text-rose-700    hover:bg-rose-100/80",
    expression: "bg-teal-50/60    border-teal-100   text-teal-700    hover:bg-teal-100/80",
    network:    "bg-emerald-50/60 border-emerald-100 text-emerald-700 hover:bg-emerald-100/80",
    proteomics: "bg-indigo-50/60  border-indigo-100  text-indigo-700  hover:bg-indigo-100/80",
    mutation:   "bg-orange-50/60  border-orange-100  text-orange-700  hover:bg-orange-100/80",
}

const CAT_LABEL: Record<Category, string> = {
    survival:   "Survival analysis",
    expression: "Gene expression",
    network:    "Network & pathway",
    proteomics: "Proteomics",
    mutation:   "Mutation analysis",
}

interface Chip { text: string; cat: Category }

const ROW1: Chip[] = [
    { text: "Is ESR1 associated with survival in BRCA?",  cat: "survival"   },
    { text: "EGFR expression across TCGA LUAD",           cat: "expression" },
    { text: "Survival analysis for PIK3CA in LUAD",       cat: "survival"   },
    { text: "RB1 co-expression partners in OV",           cat: "expression" },
    { text: "BRCA1 drug targets + survival analysis",     cat: "survival"   },
    { text: "Overall survival in KIRC with VHL mutation", cat: "survival"   },
    { text: "VEGFA expression in clear cell RCC",         cat: "expression" },
]

const ROW2: Chip[] = [
    { text: "LinkedOmics network for MYC in BRCA",        cat: "network"    },
    { text: "Compare KRAS RNA vs protein in PDAC",        cat: "proteomics" },
    { text: "Find TP53 functional neighbors",             cat: "network"    },
    { text: "Phosphoproteomics of EGFR in LUAD",          cat: "proteomics" },
    { text: "WebGestalt enrichment for PTEN targets",     cat: "network"    },
    { text: "AKT1 phosphosite changes in LUAD",           cat: "proteomics" },
]

const ROW3: Chip[] = [
    { text: "TP53 mutation frequency in breast cancer",   cat: "mutation"   },
    { text: "Differential expression GBM vs normal",      cat: "expression" },
    { text: "MET amplification frequency in LUSC",        cat: "mutation"   },
    { text: "CDH1 methylation in gastric cancer",         cat: "mutation"   },
    { text: "Pathway enrichment for DNA repair genes",    cat: "network"    },
    { text: "SMAD4 loss and TGF-β pathway in PDAC",      cat: "mutation"   },
]

const ROW4: Chip[] = [
    { text: "Proteogenomic correlation for CDKN2A",       cat: "proteomics" },
    { text: "PTEN loss and immune infiltration in GBM",   cat: "mutation"   },
    { text: "HIF1A targets in hypoxic KIRC",              cat: "network"    },
    { text: "Immune subtype differences in COAD",         cat: "expression" },
    { text: "RB1 loss frequency in SCLC",                 cat: "mutation"   },
    { text: "FunMap neighborhood of BRCA1",               cat: "network"    },
]

const ROW5: Chip[] = [
    { text: "Survival by TP53 status in OV",              cat: "survival"   },
    { text: "KRAS G12D mutation in colorectal cancer",    cat: "mutation"   },
    { text: "mRNA–protein correlation for MYC",           cat: "proteomics" },
    { text: "LinkedOmics survival module for LUAD",       cat: "survival"   },
    { text: "Enrichment analysis for EMT pathway",        cat: "network"    },
    { text: "PIK3CA hotspot mutations in BRCA",           cat: "mutation"   },
]


function ChipRow({
    chips,
    duration,
    onChipClick,
}: {
    chips: Chip[]
    duration: string
    onChipClick: (text: string, cat: Category) => void
}) {
    const doubled = [...chips, ...chips]
    return (
        <div className="chip-row w-full">
            <div
                className="chip-row-track"
                style={{ animationDuration: duration }}
            >
                {doubled.map((chip, i) => (
                    <button
                        key={i}
                        title={`Ask: "${chip.text}" — ${CAT_LABEL[chip.cat]}`}
                        onClick={(e) => { e.stopPropagation(); onChipClick(chip.text, chip.cat) }}
                        className={`chip-row-item ${CAT_ROW_STYLE[chip.cat]} transition-colors duration-150`}
                    >
                        {chip.text}
                    </button>
                ))}
            </div>
        </div>
    )
}

function QueryModal({
    query,
    cat,
    isLoggedIn,
    onClose,
    onGuest,
    onSignIn,
    onSubmit,
}: {
    query: string
    cat: Category
    isLoggedIn: boolean
    onClose: () => void
    onGuest: () => void
    onSignIn: () => void
    onSubmit: () => void
}) {
    return (
        <div
            className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/25 backdrop-blur-sm"
            onClick={onClose}
        >
            <div
                className="bg-white rounded-2xl shadow-2xl border border-slate-200/80 p-6 w-full max-w-sm text-left"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Category badge */}
                <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border ${CAT_STYLE[cat]}`}>
                    <span className="w-1.5 h-1.5 rounded-full bg-current opacity-60" />
                    {CAT_LABEL[cat]}
                </span>

                {/* Query preview */}
                <p className="mt-3 text-[15px] font-semibold text-slate-900 leading-snug">
                    "{query}"
                </p>
                <p className="mt-1 text-xs text-slate-400">
                    This question will be sent directly to the research assistant.
                </p>

                <div className="mt-5 flex flex-col gap-2">
                    {isLoggedIn ? (
                        <button
                            onClick={onSubmit}
                            className="w-full bg-teal-600 hover:bg-teal-700 active:scale-[0.98] text-white font-semibold py-2.5 rounded-xl text-sm transition-all shadow-md shadow-teal-200 inline-flex items-center justify-center gap-2"
                        >
                            Open in workspace
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
                            </svg>
                        </button>
                    ) : (
                        <>
                            <button
                                onClick={onGuest}
                                className="w-full bg-teal-600 hover:bg-teal-700 active:scale-[0.98] text-white font-semibold py-2.5 rounded-xl text-sm transition-all shadow-md shadow-teal-200 inline-flex items-center justify-center gap-2"
                            >
                                Try as guest
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
                                </svg>
                            </button>
                            <button
                                onClick={onSignIn}
                                className="w-full border border-slate-200 hover:border-slate-300 hover:bg-slate-50 text-slate-700 font-semibold py-2.5 rounded-xl text-sm transition-colors"
                            >
                                Sign in to save history
                            </button>
                        </>
                    )}
                    <button onClick={onClose} className="w-full text-xs text-slate-400 hover:text-slate-600 py-1 transition-colors">
                        Cancel
                    </button>
                </div>
            </div>
        </div>
    )
}

// ── Page ───────────────────────────────────────────────────────────────────
export default function WelcomePage() {
    const { isAuthenticated, isGuest, loading, enterGuestMode } = useAuth()
    const router = useRouter()
    const [selected, setSelected] = useState<{ text: string; cat: Category } | null>(null)

    useEffect(() => {
        if (!loading && isAuthenticated && !isGuest) {
            router.replace("/")
        }
    }, [isAuthenticated, isGuest, loading, router])

    if (loading) return null

    const handleChipClick = (text: string, cat: Category) => setSelected({ text, cat })

    const submitQuery = (query: string) => {
        sessionStorage.setItem("linkedomicsai-prefill-query", query)
        router.push("/")
    }

    const handleGuest = () => {
        if (selected) { enterGuestMode(); submitQuery(selected.text) }
    }

    const handleSignIn = () => {
        if (selected) {
            sessionStorage.setItem("linkedomicsai-prefill-query", selected.text)
            router.push("/login")
        }
    }

    const handleSubmit = () => {
        if (selected) submitQuery(selected.text)
    }

    const rows = [ROW1, ROW2, ROW3, ROW4, ROW5]
    const durations = ["64s", "78s", "70s", "84s", "58s"]

    return (
        <div className="relative min-h-screen overflow-x-hidden flex flex-col bg-slate-50">

            {/* ── Nav bar ───────────────────────────────────────────── */}
            <nav className="relative z-20 flex items-center justify-between px-6 py-4 lg:px-10">
                {/* Logo */}
                <div className="flex items-center gap-2.5">
                    <img src="/logo.png" alt="LinkedOmicsChat" className="h-8 w-auto" />
                    <span className="text-2xl font-bold tracking-tight text-slate-800">LinkedOmics<span className="text-teal-600">Chat</span></span>
                </div>

                {/* Nav links */}
                <div className="hidden sm:flex items-center gap-6">
                    <Link href="/docs" className="text-sm text-slate-500 hover:text-slate-800 transition-colors font-medium">
                        Docs
                    </Link>
                    <Link href="/login" className="text-sm text-slate-500 hover:text-slate-800 transition-colors font-medium">
                        Sign in
                    </Link>
                    <Link
                        href="/register"
                        className="bg-teal-600 hover:bg-teal-700 text-white text-sm font-semibold px-4 py-1.5 rounded-lg transition-colors shadow-sm shadow-teal-200"
                    >
                        Get started
                    </Link>
                </div>

                {/* Mobile sign-in */}
                <Link href="/login" className="sm:hidden text-sm font-semibold text-teal-600">
                    Sign in
                </Link>
            </nav>

            {/* ── Hero section ──────────────────────────────────────── */}
            <div className="relative z-10 pt-6 sm:pt-10 pb-2 px-6 text-center">

                {/* Badge */}
                <div className="inline-flex items-center gap-2 bg-white/80 border border-teal-100 text-teal-700 text-xs font-semibold px-3.5 py-1.5 rounded-full shadow-sm mb-6">
                    <Zap className="w-3.5 h-3.5 fill-amber-400 text-amber-400" />
                    AI-powered · TCGA · CPTAC · LinkedOmics
                </div>

                <h1 className="text-3xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-slate-900 leading-[1.1]">
                    Cancer multi-omics research,
                    <br />
                    <span className="text-teal-600">powered by conversation.</span>
                </h1>

                <p className="mt-4 text-base sm:text-lg text-slate-500 font-normal max-w-xl mx-auto leading-relaxed">
                    Ask survival, expression, proteomics, and pathway questions in plain English.
                    LinkedOmicsChat queries real databases and returns structured, cited answers.
                </p>

            </div>

            {/* ── Chip rows ─────────────────────────────────────────── */}
            <div className="relative z-0 flex flex-col gap-2.5 sm:gap-2 pt-16 sm:pt-14 pb-2 overflow-x-hidden select-none">
                <div className="flex flex-col items-center gap-2 mb-3">
                    <div className="inline-flex items-center gap-2.5 rounded-2xl border-2 border-teal-400 bg-teal-50 px-5 py-2.5 text-base font-bold text-teal-700 shadow-md shadow-teal-100 ring-4 ring-teal-100/60">
                        <MousePointerClick className="w-5 h-5 text-teal-500 shrink-0" />
                        Click any question below to try it
                    </div>
                    <ChevronDown className="w-5 h-5 text-teal-400 animate-bounce" />
                </div>
                {rows.map((row, i) => (
                    <div key={i} className={i >= 3 ? "hidden sm:block" : ""}>
                        <ChipRow chips={row} duration={durations[i]} onChipClick={handleChipClick} />
                    </div>
                ))}
            </div>

            {/* ── How it works ──────────────────────────────────────── */}
            <div className="relative z-10 flex-1 px-6 pt-20 flex flex-col justify-center gap-5">
                <p className="text-center text-sm font-bold uppercase tracking-widest text-slate-500">How it works</p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-10 max-w-4xl mx-auto w-full">
                    <div className="relative flex flex-col items-center text-center gap-3 glass-card-light rounded-2xl px-6 py-6 sm:py-8">
                        <span className="absolute top-3 right-4 text-2xl sm:text-3xl font-black text-teal-300">01</span>
                        <div className="w-16 h-16 rounded-2xl bg-teal-50 flex items-center justify-center">
                            <MessageCircle className="w-8 h-8 sm:w-9 sm:h-9 text-teal-500 stroke-2" />
                        </div>
                        <p className="text-base sm:text-lg font-semibold text-slate-800">Ask a research question</p>
                        <p className="text-sm sm:text-base text-slate-400 leading-relaxed">Type your question in plain English — no special syntax or database knowledge required.</p>
                    </div>
                    <div className="relative flex flex-col items-center text-center gap-3 glass-card-light rounded-2xl px-6 py-6 sm:py-8">
                        <span className="absolute top-3 right-4 text-2xl sm:text-3xl font-black text-violet-300">02</span>
                        <div className="w-16 h-16 rounded-2xl bg-violet-50 flex items-center justify-center">
                            <DatabaseZap className="w-8 h-8 sm:w-9 sm:h-9 text-violet-500 stroke-2" />
                        </div>
                        <p className="text-base sm:text-lg font-semibold text-slate-800">We search the data for you</p>
                        <p className="text-sm sm:text-base text-slate-400 leading-relaxed">The assistant automatically searches cancer databases — survival records, gene expression, proteomics, and literature.</p>
                    </div>
                    <div className="relative flex flex-col items-center text-center gap-3 glass-card-light rounded-2xl px-6 py-6 sm:py-8">
                        <span className="absolute top-3 right-4 text-2xl sm:text-3xl font-black text-emerald-300">03</span>
                        <div className="w-16 h-16 rounded-2xl bg-emerald-50 flex items-center justify-center">
                            <FileCheck2 className="w-8 h-8 sm:w-9 sm:h-9 text-emerald-500 stroke-2" />
                        </div>
                        <p className="text-base sm:text-lg font-semibold text-slate-800">Get a structured answer</p>
                        <p className="text-sm sm:text-base text-slate-400 leading-relaxed">Results are returned with source links so you can verify every data point and dig deeper.</p>
                    </div>
                </div>
            </div>

            {/* ── Footer ────────────────────────────────────────────── */}
            <div className="relative z-10 flex items-center justify-between px-6 lg:px-10 py-4">
                <p className="text-xs text-slate-400">© 2026 Zhang Lab</p>
                <div className="hidden sm:flex items-center gap-4 text-xs text-slate-400">
                    <Link href="/docs" className="hover:text-slate-600 transition-colors">Docs</Link>
                    <Link href="/login" className="hover:text-slate-600 transition-colors">Sign in</Link>
                    <Link href="/register" className="hover:text-slate-600 transition-colors">Register</Link>
                </div>
            </div>

            {/* ── Modal ─────────────────────────────────────────────── */}
            {selected && (
                <QueryModal
                    query={selected.text}
                    cat={selected.cat}
                    isLoggedIn={isAuthenticated && !isGuest}
                    onClose={() => setSelected(null)}
                    onGuest={handleGuest}
                    onSignIn={handleSignIn}
                    onSubmit={handleSubmit}
                />
            )}
        </div>
    )
}
