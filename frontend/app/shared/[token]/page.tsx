"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { chatAPI, resolveDataSources, type AnyVisualization } from "@/lib/api"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import "katex/dist/katex.min.css"
import { AppIcon } from "@/components/AppLogo"
import { AssistantMarkdown } from "@/components/ChatInterface"
import { StaticPlot } from "@/components/StaticPlot"
import { NetworkPlot } from "@/components/NetworkPlot"
import { DrugTargetGrid } from "@/components/DrugTargetGrid"
import { TargetSearchTable } from "@/components/TargetSearchTable"
import { PredictiveResultsTable } from "@/components/PredictiveResultsTable"
import { TCGACisResultsTable } from "@/components/TCGACisResultsTable"

interface HistoryEntry {
    id: number
    query: string
    response: {
        message?: string
        summary?: string
        visualizations?: AnyVisualization[]
        tool_sources?: Record<string, string>
        tools_used?: string[]
    }
    timestamp: number
}

interface SharedSession {
    session_id: string
    title: string
    history: HistoryEntry[]
    created_at: number
}

const INLINE_MARKER_RE = /\[(?:PLOT|NETWORK|TABLE):([^\]]+)\]/g

/** Same type-to-component mapping the live chat uses for results not placed inline. */
function VisualizationView({ viz }: { viz: AnyVisualization }) {
    if (viz.type === "network_plot") return <NetworkPlot visualization={viz} />
    if (viz.type === "drug_target_grid") return <DrugTargetGrid visualization={viz} />
    if (viz.type === "target_search_table") return <TargetSearchTable visualization={viz} />
    if (viz.type === "predictive_results_table") return <PredictiveResultsTable visualization={viz} />
    if (viz.type === "tcga_cis_results_table") return <TCGACisResultsTable visualization={viz} />
    return <StaticPlot visualization={viz} />
}

/** Render an answer with the live chat's renderer, so shared results look and behave the same. */
function AssistantContent({ message, summary, visualizations, toolSources, toolsUsed }: {
    message?: string
    summary?: string
    visualizations?: AnyVisualization[]
    toolSources?: Record<string, string>
    toolsUsed?: string[]
}) {
    const content = message || "_(no response)_"
    const inlineIds = new Set(Array.from(content.matchAll(INLINE_MARKER_RE), (m) => m[1]))
    const remaining = (visualizations || []).filter((viz) => !inlineIds.has(viz.id))
    const sources = resolveDataSources(toolsUsed || [])
    const showSummary = summary && summary.trim().length > 0 && summary !== message

    return (
        <div className="space-y-3">
            <AssistantMarkdown content={content} visualizations={visualizations} toolSources={toolSources} />
            {remaining.length > 0 && (
                <div className="space-y-4">
                    {remaining.map((viz) => <VisualizationView key={viz.id} viz={viz} />)}
                </div>
            )}
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
            {sources.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs text-muted-foreground/60">Sources:</span>
                    {sources.map((src) => (
                        <a
                            key={src.label}
                            href={src.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs px-2 py-0.5 rounded-full border border-border bg-muted/50 text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
                        >
                            {src.label}
                        </a>
                    ))}
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
                                toolSources={entry.response?.tool_sources}
                                toolsUsed={entry.response?.tools_used}
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
