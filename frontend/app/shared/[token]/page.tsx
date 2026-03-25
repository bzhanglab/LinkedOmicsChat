"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { chatAPI, API_URL } from "@/lib/api"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import "katex/dist/katex.min.css"
import { AppIcon } from "@/components/AppLogo"

interface AtRiskRow { time: number; [group: string]: number }

function parseAtRiskCsv(csv: string): { rows: AtRiskRow[]; groups: string[] } | null {
    const lines = csv.trim().split("\n")
    if (lines.length < 2) return null
    const headers = lines[0].split(",").map(h => h.trim())
    const groupIdx = headers.indexOf("group")
    const timeIdx = headers.indexOf("time_days")
    const atRiskIdx = headers.indexOf("at_risk")
    if (groupIdx === -1 || timeIdx === -1 || atRiskIdx === -1) return null
    const byTime = new Map<number, Record<string, number>>()
    const groupSet = new Set<string>()
    for (let i = 1; i < lines.length; i++) {
        const cols = lines[i].split(",").map(c => c.trim())
        if (cols.length < headers.length) continue
        const time = parseFloat(cols[timeIdx])
        const group = cols[groupIdx]
        const atRisk = parseInt(cols[atRiskIdx], 10)
        if (isNaN(time) || isNaN(atRisk)) continue
        groupSet.add(group)
        if (!byTime.has(time)) byTime.set(time, {})
        byTime.get(time)![group] = atRisk
    }
    const groups = Array.from(groupSet).sort()
    const rows = Array.from(byTime.entries()).sort(([a], [b]) => a - b).map(([time, vals]) => ({ time, ...vals }))
    return rows.length > 0 ? { rows, groups } : null
}

const PLOT_MARKER_RE = /^\[PLOT:([^\]]+)\]$/

interface Viz { id: string; type: string; title?: string }

interface HistoryEntry {
    id: number
    query: string
    response: {
        message?: string
        summary?: string
        visualizations?: Viz[]
    }
    timestamp: number
}

interface SharedSession {
    session_id: string
    title: string
    history: HistoryEntry[]
    created_at: number
}

/** Split markdown on [PLOT:id] lines and render text + images inline. */
function AssistantContent({ message, summary, visualizations }: {
    message?: string
    summary?: string
    visualizations?: Viz[]
}) {
    const vizMap: Record<string, Viz> = {}
    visualizations?.forEach(v => { vizMap[v.id] = v })

    const text = message || "_(no response)_"

    // Split into text/plot segments
    const segments: { type: "text" | "plot"; value: string }[] = []
    let buf: string[] = []
    for (const line of text.split("\n")) {
        const m = line.trim().match(PLOT_MARKER_RE)
        if (m) {
            if (buf.length) { segments.push({ type: "text", value: buf.join("\n") }); buf = [] }
            segments.push({ type: "plot", value: m[1] })
        } else {
            buf.push(line)
        }
    }
    if (buf.length) segments.push({ type: "text", value: buf.join("\n") })

    // Plots not referenced inline — render after message
    const inlinedIds = new Set(segments.filter(s => s.type === "plot").map(s => s.value))
    const trailingVizs = (visualizations || []).filter(v => !inlinedIds.has(v.id))

    const showSummary = summary && summary.trim().length > 0 && summary !== message

    return (
        <div className="space-y-3">
            <div className="prose prose-sm dark:prose-invert max-w-none">
                {segments.map((seg, i) =>
                    seg.type === "plot" ? (
                        vizMap[seg.value] ? <PlotImage key={i} viz={vizMap[seg.value]} /> : null
                    ) : (
                        <ReactMarkdown key={i} remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                            {seg.value}
                        </ReactMarkdown>
                    )
                )}
            </div>
            {trailingVizs.map(viz => <PlotImage key={viz.id} viz={viz} />)}
            {showSummary && (
                <div className="mt-2 pt-3 border-t border-border">
                    <div className="rounded-md border border-border bg-muted/40 p-3">
                        <div className="text-xs font-semibold text-muted-foreground mb-2">Summary</div>
                        <div className="prose prose-sm dark:prose-invert max-w-none">
                            <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                                {summary}
                            </ReactMarkdown>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

function PlotImage({ viz }: { viz: Viz }) {
    const [atRiskData, setAtRiskData] = useState<{ rows: AtRiskRow[]; groups: string[] } | null>(null)
    const [showAtRisk, setShowAtRisk] = useState(false)

    useEffect(() => {
        fetch(`${API_URL}/api/v1/chat/visualizations/${encodeURIComponent(viz.id)}`)
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (data?.csv) {
                    const parsed = parseAtRiskCsv(data.csv)
                    if (parsed) setAtRiskData(parsed)
                }
            })
            .catch(() => {})
    }, [viz.id])

    return (
        <div className="my-3 rounded border border-border overflow-hidden">
            {viz.title && <p className="text-xs font-medium text-muted-foreground px-3 pt-2">{viz.title}</p>}
            <div className="p-2 flex justify-center">
                <img
                    src={`${API_URL}/api/v1/chat/visualizations/${viz.id}/png`}
                    alt={viz.title || "Plot"}
                    className="max-w-full h-auto"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none" }}
                />
            </div>
            {atRiskData && (
                <div className="border-t border-border px-3 py-2 bg-muted/20">
                    <button
                        className="text-xs text-primary hover:underline mb-1.5"
                        onClick={() => setShowAtRisk(v => !v)}
                    >
                        {showAtRisk ? "Hide at-risk table" : "Show at-risk table"}
                    </button>
                    {showAtRisk && (
                        <div className="max-h-48 overflow-y-auto rounded border border-border text-xs">
                            <table className="w-full border-collapse">
                                <thead className="sticky top-0 bg-muted/80">
                                    <tr>
                                        <th className="text-left px-2 py-1 font-medium text-muted-foreground border-b border-border">Time (days)</th>
                                        {atRiskData.groups.map(g => (
                                            <th key={g} className="text-right px-2 py-1 font-medium text-muted-foreground border-b border-border">{g}</th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {atRiskData.rows.map((row, i) => (
                                        <tr key={row.time} className={i % 2 === 0 ? "bg-background" : "bg-muted/20"}>
                                            <td className="px-2 py-0.5 tabular-nums">{row.time}</td>
                                            {atRiskData.groups.map(g => (
                                                <td key={g} className="px-2 py-0.5 text-right tabular-nums">{row[g] ?? "—"}</td>
                                            ))}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

export default function SharedSessionPage() {
    const params = useParams()
    const token = params.token as string
    const [session, setSession] = useState<SharedSession | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        if (!token) return
        chatAPI.getSharedSession(token)
            .then(setSession)
            .catch(() => setError("This shared session could not be found or has been removed."))
            .finally(() => setLoading(false))
    }, [token])

    if (loading) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-background">
                <div className="text-muted-foreground animate-pulse">Loading shared session…</div>
            </div>
        )
    }

    if (error || !session) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-background">
                <div className="text-center space-y-3">
                    <p className="text-destructive font-medium">{error ?? "Session not found."}</p>
                    <a href="/" className="text-sm text-primary underline">Go to LinkedOmicsChat</a>
                </div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-background">
            {/* Header */}
            <div className="border-b border-border px-6 py-4 flex items-center gap-4">
                <AppIcon className="h-7 w-auto" />
                <div className="flex-1 min-w-0">
                    <h1 className="text-lg font-semibold truncate">{session.title}</h1>
                    <p className="text-xs text-muted-foreground">
                        Shared read-only session · {session.history.length} exchange{session.history.length !== 1 ? "s" : ""}
                    </p>
                </div>
                <a
                    href="/"
                    className="shrink-0 text-sm px-3 py-1.5 rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
                >
                    Try LinkedOmicsChat
                </a>
            </div>

            {/* Messages */}
            <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
                {session.history.map((entry) => (
                    <div key={entry.id} className="space-y-3">
                        {/* User query */}
                        <div className="flex justify-end">
                            <div className="bg-primary text-primary-foreground rounded-2xl px-4 py-2.5 max-w-[80%] text-sm">
                                {entry.query}
                            </div>
                        </div>
                        {/* Assistant response */}
                        <div className="bg-card border border-border rounded-2xl px-4 py-3 text-sm">
                            <AssistantContent
                                message={entry.response?.message}
                                summary={entry.response?.summary}
                                visualizations={entry.response?.visualizations}
                            />
                        </div>
                        <p className="text-xs text-muted-foreground text-right">
                            {new Date(entry.timestamp * 1000).toLocaleString()}
                        </p>
                    </div>
                ))}
            </div>
        </div>
    )
}
