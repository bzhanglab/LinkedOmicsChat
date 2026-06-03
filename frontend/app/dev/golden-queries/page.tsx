"use client"

import { useState, useRef, useMemo, useEffect } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { chatAPI, INLINE_SOURCE_MAP, type ChatResponse, type AnyVisualization, type GoldenQueryCase } from "@/lib/api"
import { StaticPlot } from "@/components/StaticPlot"
import { NetworkPlot } from "@/components/NetworkPlot"
import { DrugTargetGrid } from "@/components/DrugTargetGrid"
import { TargetSearchTable } from "@/components/TargetSearchTable"
import { PredictiveResultsTable } from "@/components/PredictiveResultsTable"
import { TCGACisResultsTable } from "@/components/TCGACisResultsTable"

// ---------------------------------------------------------------------------
// Golden query test cases are loaded from backend/examples/langgraph_golden_queries.json.
// ---------------------------------------------------------------------------

type GoldenCase = GoldenQueryCase

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function bareName(tool: string): string {
    // Strip instance index suffix (e.g. "linkedomics::compare_cptac_tumor_normal_expression#0" → "...compare_cptac_tumor_normal_expression")
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
                    if (viz.type === "static_plot") return <StaticPlot key={viz.id} visualization={viz} />
                    if (viz.type === "drug_target_grid") return <DrugTargetGrid key={viz.id} visualization={viz} />
                    if (viz.type === "target_search_table") return <TargetSearchTable key={viz.id} visualization={viz} />
                    return null
                }
                if (part.type === "network") {
                    const viz = vizMap[part.value]
                    return viz?.type === "network_plot" ? <NetworkPlot key={viz.id} visualization={viz} /> : null
                }
                if (part.type === "table") {
                    const viz = vizMap[part.value]
                    if (!viz) return null
                    if (viz.type === "predictive_results_table") return <PredictiveResultsTable key={viz.id} visualization={viz} />
                    if (viz.type === "tcga_cis_results_table") return <TCGACisResultsTable key={viz.id} visualization={viz} />
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
                            a: ({ href, children }) => {
                                const sourceKey = href?.startsWith("#source:") ? href.replace("#source:", "") : null
                                const source = sourceKey ? INLINE_SOURCE_MAP[sourceKey] : undefined
                                const label = source?.label ?? children
                                return <a href={source?.url ?? href} className="text-blue-600 underline" target="_blank" rel="noreferrer">{label}</a>
                            },
                        }}
                    >
                        {part.value}
                    </ReactMarkdown>
                )
            })}

            {/* Render any visualizations that were NOT inlined via markers */}
            {(() => {
                const inlined = new Set([
                    ...(text.match(/\[PLOT:([^\]]+)\]/g)?.map((m) => m.slice(6, -1)) ?? []),
                    ...(text.match(/\[NETWORK:([^\]]+)\]/g)?.map((m) => m.slice(9, -1)) ?? []),
                    ...(text.match(/\[TABLE:([^\]]+)\]/g)?.map((m) => m.slice(7, -1)) ?? []),
                ])
                const remaining = vizs.filter((v) => !inlined.has(v.id))
                return remaining.map((v) => {
                    // Use stable viz.id as key so StaticPlot is not remounted on re-render
                    if (v.type === "static_plot") return <StaticPlot key={v.id} visualization={v} />
                    if (v.type === "network_plot") return <NetworkPlot key={v.id} visualization={v} />
                    if (v.type === "drug_target_grid") return <DrugTargetGrid key={v.id} visualization={v} />
                    if (v.type === "target_search_table") return <TargetSearchTable key={v.id} visualization={v} />
                    if (v.type === "predictive_results_table") return <PredictiveResultsTable key={v.id} visualization={v} />
                    if (v.type === "tcga_cis_results_table") return <TCGACisResultsTable key={v.id} visualization={v} />
                    return null
                })
            })()}
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
    const [cases, setCases] = useState<GoldenCase[]>([])
    const [casesStatus, setCasesStatus] = useState<"loading" | "ready" | "error">("loading")
    const [casesError, setCasesError] = useState<string | null>(null)
    const [results, setResults] = useState<Record<string, RunResult>>({})
    const [selected, setSelected] = useState<string | null>(null)
    const sessionIds = useRef<Record<string, string>>({})

    useEffect(() => {
        let cancelled = false
        setCasesStatus("loading")
        chatAPI.getGoldenQueries()
            .then((payload) => {
                if (cancelled) return
                setCases(payload.cases ?? [])
                setCasesError(null)
                setCasesStatus("ready")
            })
            .catch((err: unknown) => {
                if (cancelled) return
                setCases([])
                setCasesError(err instanceof Error ? err.message : String(err))
                setCasesStatus("error")
            })
        return () => { cancelled = true }
    }, [])

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

    const selectedCase = cases.find((c) => c.id === selected)
    const selectedResult = selected ? results[selected] : undefined

    function sessionLabel(gc: GoldenCase): string | null {
        if (!gc.session_key) return null
        const siblings = cases.filter((c) => c.session_key === gc.session_key)
        return `Turn ${siblings.findIndex((c) => c.id === gc.id) + 1}/${siblings.length}`
    }

    const vizs = (selectedResult?.response?.visualizations ?? []) as unknown as AnyVisualization[]
    const responseText = selectedResult?.response?.message ?? selectedResult?.streamedText ?? ""

    return (
        <div className="flex h-screen bg-white text-gray-900 text-sm">
            {/* ── Left panel ── */}
            <div className="w-[360px] flex-shrink-0 border-r border-gray-200 flex flex-col">
                <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
                    <h1 className="text-sm font-semibold text-gray-800">Golden Query Tester</h1>
                    <p className="text-xs text-gray-500 mt-0.5">
                        {casesStatus === "loading" ? "Loading cases…" : `${cases.length} cases · loaded from JSON`}
                    </p>
                </div>

                <div className="overflow-y-auto flex-1">
                    {casesStatus === "error" && (
                        <div className="px-4 py-3 text-xs text-red-600">
                            Could not load golden queries: {casesError}
                        </div>
                    )}
                    {cases.map((gc) => {
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
                {casesStatus === "loading" ? (
                    <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                        Loading golden queries…
                    </div>
                ) : casesStatus === "error" ? (
                    <div className="flex items-center justify-center h-full text-red-500 text-sm">
                        Could not load golden queries: {casesError}
                    </div>
                ) : !selectedCase ? (
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
                            <Section title={`Response${vizs.length > 0 ? ` · ${vizs.length} visualization${vizs.length > 1 ? "s" : ""}` : ""}`}>
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
