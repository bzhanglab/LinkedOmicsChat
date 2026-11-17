"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { useAuth } from "@/components/AuthContext"
import { Zap } from "lucide-react"

type Category = "survival" | "expression" | "network" | "proteomics" | "drug_targets" | "clinical_trials"

const CAT_ROW_STYLE: Record<Category, string> = {
    survival:        "bg-rose-50/60    border-rose-100    text-rose-700    hover:bg-rose-100/80",
    expression:      "bg-teal-50/60    border-teal-100    text-teal-700    hover:bg-teal-100/80",
    network:         "bg-emerald-50/60 border-emerald-100 text-emerald-700 hover:bg-emerald-100/80",
    proteomics:      "bg-indigo-50/60  border-indigo-100  text-indigo-700  hover:bg-indigo-100/80",
    drug_targets:    "bg-violet-50/60  border-violet-100  text-violet-700  hover:bg-violet-100/80",
    clinical_trials: "bg-amber-50/60   border-amber-100   text-amber-700   hover:bg-amber-100/80",
}

const CAT_LABEL: Record<Category, string> = {
    survival:        "Survival analysis",
    expression:      "Gene expression",
    network:         "Network & pathway",
    proteomics:      "Proteomics",
    drug_targets:    "Drug targets",
    clinical_trials: "Clinical trials",
}

// `label` is shown on the chip when the full query (`text`) is too long, e.g. sample data
interface Chip { text: string; cat: Category; label?: string }

// One example per analysis type; clicking a chip fills the question box
const EXAMPLES: Chip[] = [
    { label: "Pathway enrichment for a sample gene list", text: "Run pathway enrichment on my gene list: CDK1, CCNB1, CCNA2, AURKA, AURKB, PLK1, BUB1, BUB1B, TOP2A, KIF11, BIRC5, MKI67, CDC20, CENPF, TTK", cat: "network" },
    { text: "Is ESR1 associated with survival in BRCA?",            cat: "survival"        },
    { text: "EGFR expression in LUAD vs normal tissue",             cat: "expression"      },
    { text: "Compare KRAS RNA vs protein in PDAC",                  cat: "proteomics"      },
    { text: "Which genes best predict immunotherapy response?",      cat: "clinical_trials" },
    { text: "Is EGFR a druggable oncology target?",                 cat: "drug_targets"    },
]

// ── Page ───────────────────────────────────────────────────────────────────
export default function WelcomePage() {
    const { isAuthenticated, isGuest, loading, enterGuestMode } = useAuth()
    const router = useRouter()
    const [question, setQuestion] = useState("")

    if (loading) return null

    // Visitors who are not signed in go straight in as guests; no separate guest step
    const ask = () => {
        const query = question.trim()
        if (!query) return
        if (!isAuthenticated) enterGuestMode()
        sessionStorage.setItem("linkedomicsai-prefill-query", query)
        router.push("/")
    }

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
                    <Link href="/about" className="text-sm text-slate-500 hover:text-slate-800 transition-colors font-medium">
                        About
                    </Link>
                    <Link href="/docs" className="text-sm text-slate-500 hover:text-slate-800 transition-colors font-medium">
                        Documentation
                    </Link>
                    <Link href="/login" className="text-sm text-slate-500 hover:text-slate-800 transition-colors font-medium">
                        Sign in
                    </Link>
                </div>

                {/* Mobile sign-in */}
                <Link href="/login" className="sm:hidden text-sm text-slate-500 hover:text-slate-800 transition-colors font-medium">
                    Sign in
                </Link>
            </nav>

            {/* Content sits slightly above center (optical center) on tall screens */}
            <main className="flex-1 flex flex-col justify-center pb-[12vh]">
            {/* ── Hero section ──────────────────────────────────────── */}
            <div className="relative z-10 pt-6 sm:pt-10 pb-2 px-6 text-center">

                {/* Badge */}
                <div className="inline-flex items-center gap-2 bg-white/80 border border-teal-100 text-teal-700 text-xs font-semibold text-center px-3.5 py-1.5 rounded-2xl sm:rounded-full shadow-sm mb-6">
                    <Zap className="w-3.5 h-3.5 fill-amber-400 text-amber-400" />
                    TCGA · CPTAC · LinkedOmics · ClinicalOmicsDB · FunMap · WebGestalt · PubMed
                </div>

                <h1 className="text-3xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-slate-900 leading-[1.1]">
                    Cancer multi-omics research,
                    <br />
                    <span className="text-teal-600">powered by agentic AI.</span>
                </h1>

                <p className="mt-4 text-base sm:text-lg text-slate-500 font-normal max-w-xl mx-auto leading-relaxed">
                    Ask survival, expression, proteomics, and pathway questions in plain English.
                    LinkedOmicsChat queries real databases and returns structured, cited answers.
                </p>

                {/* Question box */}
                <form
                    onSubmit={(e) => { e.preventDefault(); ask() }}
                    className="mt-8 mx-auto max-w-2xl flex items-end gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-sm focus-within:border-teal-400"
                >
                    <textarea
                        value={question}
                        onChange={(e) => setQuestion(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask() } }}
                        rows={2}
                        aria-label="Your question"
                        placeholder="Ask a question, e.g. Is ESR1 associated with survival in breast cancer?"
                        className="flex-1 resize-none bg-transparent px-3 py-2 text-left text-base text-slate-800 placeholder:text-slate-400 focus:outline-none"
                    />
                    <button type="submit" className="bg-teal-600 hover:bg-teal-700 text-white font-semibold px-5 py-2.5 rounded-xl text-sm transition-colors">
                        Ask
                    </button>
                </form>
                <p className="mt-2 text-sm text-slate-500">
                    Free to use · No account needed
                </p>

            </div>

            {/* ── Example questions ─────────────────────────────────── */}
            <div className="relative z-0 flex flex-col items-center gap-4 pt-12 pb-16 px-6">
                <p className="text-sm font-semibold text-slate-500">Or start from an example</p>
                <div className="flex flex-wrap justify-center gap-2.5 max-w-3xl">
                    {EXAMPLES.map((chip) => (
                        <button
                            key={chip.text}
                            type="button"
                            title={`Ask: "${chip.text}" — ${CAT_LABEL[chip.cat]}`}
                            onClick={() => setQuestion(chip.text)}
                            className={`chip-row-item ${CAT_ROW_STYLE[chip.cat]} transition-colors duration-150`}
                        >
                            {chip.label ?? chip.text}
                        </button>
                    ))}
                </div>
            </div>

            </main>

            {/* ── Footer ────────────────────────────────────────────── */}
            <div className="relative z-10 mt-auto flex items-center justify-between px-6 lg:px-10 py-4">
                <p className="text-xs text-slate-400">
                    © 2026 Zhang Lab · Free to use · Source code under the{" "}
                    <a href="https://github.com/bzhanglab/LinkedOmicsChat/blob/main/LICENSE" target="_blank" rel="noopener noreferrer" className="underline hover:text-slate-600 transition-colors">MIT License</a>
                </p>
                <div className="hidden sm:flex items-center gap-4 text-xs text-slate-400">
                    <Link href="/about" className="hover:text-slate-600 transition-colors">About</Link>
                    <Link href="/docs" className="hover:text-slate-600 transition-colors">Documentation</Link>
                </div>
            </div>
        </div>
    )
}
