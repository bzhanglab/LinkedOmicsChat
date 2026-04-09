"use client"

import React, { useState, useRef, useEffect, useCallback, memo, useMemo, startTransition } from "react"
import { Send, Loader2, Sparkles, Copy, Check, User, Download, Search, X, ChevronUp, ChevronDown, Share2, Pencil, ThumbsUp, ThumbsDown, AlertCircle, RefreshCw, HelpCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Card, CardContent } from "@/components/ui/card"
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { chatAPI, type ChatMessage, type Paper, type AnalysisResult, type AnyVisualization, API_URL, resolveDataSources, INLINE_SOURCE_MAP } from "@/lib/api"
import { StaticPlot } from "@/components/StaticPlot"
import { NetworkPlot } from "@/components/NetworkPlot"
import { DrugTargetGrid } from "@/components/DrugTargetGrid"
import { TargetSearchTable } from "@/components/TargetSearchTable"
import { PredictiveResultsTable } from "@/components/PredictiveResultsTable"
import { useAuth } from "@/components/AuthContext"
import { EnrichmentRenderer } from "./ToolExplorer"
import ExecutionTrace from "./ExecutionTrace"
import axios from "axios"
import { cn } from "@/lib/utils"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeHighlight from "rehype-highlight"
import rehypeKatex from "rehype-katex"
import { flushSync } from "react-dom"
import "highlight.js/styles/github-dark.css"
import "katex/dist/katex.min.css"

// Lazy wrapper: renders children only once the element scrolls within 400px of the viewport.
// Once rendered, stays rendered (no unmounting) to avoid layout shift.
// A height placeholder keeps scroll position stable while content is off-screen.
function LazyMessageContent({ estimatedHeight, children }: { estimatedHeight: number; children: React.ReactNode }) {
    const ref = useRef<HTMLDivElement>(null)
    const [visible, setVisible] = useState(false)
    useEffect(() => {
        const el = ref.current
        if (!el) return
        const observer = new IntersectionObserver(
            ([entry]) => { if (entry.isIntersecting) { setVisible(true); observer.disconnect() } },
            { rootMargin: "400px" }
        )
        observer.observe(el)
        return () => observer.disconnect()
    }, [])
    return (
        <div ref={ref} style={visible ? undefined : { minHeight: estimatedHeight }}>
            {visible && children}
        </div>
    )
}

// react-markdown v10 blocks `data:` URLs by default; allow only safe image data URLs.
function safeMarkdownUrlTransform(url: string) {
    if (!url) return url
    const lower = url.toLowerCase()
    if (lower.startsWith("http://") || lower.startsWith("https://")) return url
    // Allow relative links (e.g., in-app)
    if (lower.startsWith("/") || lower.startsWith("#")) return url
    // Allow only data:image/* for plot rendering
    if (lower.startsWith("data:image/")) return url
    // Block everything else (e.g., javascript:)
    return "#"
}

const markdownComponents = {
    img: ({ node, ...props }: any) => {
        return (
            <img
                {...props}
                className={cn(
                    "max-w-full h-auto rounded-md border border-border",
                    props.className
                )}
                loading="lazy"
            />
        )
    },
    code: ({ node, className, children, ...props }: any) => {
        const match = /language-(\w+)/.exec(className || "")
        const isInline = !match

        if (isInline) {
            return (
                <code className="bg-muted px-1 py-0.5 rounded text-sm font-mono" {...props}>
                    {children}
                </code>
            )
        }
        return (
            <code className={className} {...props}>
                {children}
            </code>
        )
    },
}

// Strip large binary fields from visualizations before storing in React state.
// png_b64 / svg / csv are served on-demand by StaticPlot's lazy fetch; no need to keep them in memory.
const STRIP_VIZ_KEYS = new Set(["png_b64", "svg", "csv", "nodes", "edges"])
function stripVizBinary(vizs: AnyVisualization[] | undefined): AnyVisualization[] | undefined {
    if (!vizs?.length) return vizs
    return vizs.map(v => {
        const stripped = { ...v } as any
        for (const k of STRIP_VIZ_KEYS) delete stripped[k]
        return stripped as AnyVisualization
    })
}

const PLOT_MARKER_RE = /^\[PLOT:([^\]]+)\]$/
const NETWORK_MARKER_RE = /^\[NETWORK:([^\]]+)\]$/
const TABLE_MARKER_RE = /^\[TABLE:([^\]]+)\]$/

const AssistantMarkdown = memo(function AssistantMarkdown({ content, onCopyTable, toolSources, visualizations }: { content: string; onCopyTable?: (content: string) => void; toolSources?: Record<string, string>; visualizations?: AnyVisualization[] }) {
    const handleCopyTable = useCallback((tableContent: string) => {
        if (onCopyTable) {
            onCopyTable(tableContent)
        } else {
            navigator.clipboard.writeText(tableContent).catch(console.error)
        }
    }, [onCopyTable])

    // Strip inline source blockquotes — shown as consolidated footer instead.
    const processedContent = useMemo(() =>
        content.replace(/^>[ \t]*.*(Source:|source:).*$/gm, "").replace(/\n{3,}/g, "\n\n").trim()
    , [content])

    // Split content on [PLOT:id] and [NETWORK:id] markers so they render inline.
    const parts = useMemo(() => {
        const segments: { type: "text" | "plot" | "network" | "table"; value: string }[] = []
        let buf: string[] = []
        for (const line of processedContent.split("\n")) {
            const trimmed = line.trim()
            const pm = trimmed.match(PLOT_MARKER_RE)
            const nm = trimmed.match(NETWORK_MARKER_RE)
            const tm = trimmed.match(TABLE_MARKER_RE)
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
    }, [processedContent])

    const geneColorMap = useMemo(() => createGeneColorMap(processedContent), [processedContent])
    const enhancedComponents = useMemo(() => createEnhancedMarkdownComponents(handleCopyTable, geneColorMap, toolSources), [handleCopyTable, geneColorMap, toolSources])

    const vizMap = useMemo(() => {
        const m: Record<string, AnyVisualization> = {}
        visualizations?.forEach(v => { m[v.id] = v })
        return m
    }, [visualizations])

    return (
        <div className="prose prose-sm dark:prose-invert max-w-none">
            {parts.map((part, i) => {
                if (part.type === "plot") {
                    const viz = vizMap[part.value]
                    if (viz?.type === "static_plot") return <StaticPlot key={i} visualization={viz} />
                    if (viz?.type === "drug_target_grid") return <DrugTargetGrid key={i} visualization={viz} />
                    if (viz?.type === "target_search_table") return <TargetSearchTable key={i} visualization={viz} />
                    return null
                }
                if (part.type === "network") {
                    const viz = vizMap[part.value]
                    return viz?.type === "network_plot" ? <NetworkPlot key={i} visualization={viz} /> : null
                }
                if (part.type === "table") {
                    const viz = vizMap[part.value]
                    return viz?.type === "predictive_results_table"
                        ? <PredictiveResultsTable key={i} visualization={viz} />
                        : null
                }
                return (
                    <ReactMarkdown
                        key={i}
                        remarkPlugins={[remarkGfm, remarkMath]}
                        rehypePlugins={[rehypeHighlight, rehypeKatex]}
                        urlTransform={safeMarkdownUrlTransform}
                        components={enhancedComponents as any}
                    >
                        {part.value}
                    </ReactMarkdown>
                )
            })}
        </div>
    )
})

const AssistantPlainText = memo(function AssistantPlainText({ content }: { content: string }) {
    return <p className="text-sm whitespace-pre-wrap text-foreground">{content}</p>
})

// Helper: Extract gene names from our tool-output section headers only.
// Matches patterns like "## Cancer expression - TP53" or "## Survival association — BRCA1".
// Restricted to known section prefixes to avoid picking up LLM-generated prose headers
// that mention partner genes (e.g. "## Immune function - HACD4").
const TOOL_SECTION_RE = /##\s+(?:Cancer expression|Overall survival|Survival association|Cis.correlations?|Trans.correlations?|TCGA survival|Clinical trial|FunMap neighborhood)\s*[-—]\s*([A-Z][A-Z0-9]{1,9})\b/gi

function extractGeneNames(markdown: string): string[] {
    if (!markdown) return []
    const matches = Array.from(markdown.matchAll(TOOL_SECTION_RE))
    const genes = matches.map(m => m[1]).filter(Boolean)
    return [...new Set(genes)] // unique
}

// Gene Badge Component
const GeneBadge = memo(function GeneBadge({ gene, index }: { gene: string; index: number }) {
    const colors = [
        "bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300",
        "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
        "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300",
        "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300",
        "bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-300",
    ]
    const colorClass = colors[index % colors.length]

    return (
        <span className={cn("inline-flex items-center px-2 py-0.5 rounded text-xs font-medium", colorClass)}>
            {gene}
        </span>
    )
})

// Helper: Get border color for a gene based on its index
function getGeneBorderColor(index: number): string {
    const borderColors = [
        "border-l-teal-500",
        "border-l-purple-500",
        "border-l-green-500",
        "border-l-orange-500",
        "border-l-pink-500",
    ]
    return borderColors[index % borderColors.length]
}

// Helper: Create gene-to-color mapping from content
function createGeneColorMap(markdown: string): Map<string, number> {
    const genes = extractGeneNames(markdown)
    const map = new Map<string, number>()
    genes.forEach((gene, index) => {
        map.set(gene, index)
    })
    return map
}

// Extract plain text from a HAST cell node (handles text and nested inline nodes)
function hastCellText(cell: any): string {
    const walk = (n: any): string => {
        if (!n) return ""
        if (n.type === "text") return n.value ?? ""
        if (n.children) return n.children.map(walk).join("")
        return ""
    }
    return walk(cell)
}

function reactCellText(node: React.ReactNode): string {
    const walk = (value: React.ReactNode): string => {
        if (value == null || typeof value === "boolean") return ""
        if (typeof value === "string" || typeof value === "number") return String(value)
        if (Array.isArray(value)) return value.map(walk).join("")
        if (React.isValidElement(value)) return walk(value.props.children)
        return ""
    }
    return walk(node).trim()
}

function reactElementTag(element: React.ReactElement<any>): string | undefined {
    if (typeof element.type === "string") return element.type
    return element.props?.node?.tagName
}

function reactElementsByTag(children: React.ReactNode, tag: string): React.ReactElement<any>[] {
    const matches: React.ReactElement<any>[] = []

    const walk = (value: React.ReactNode) => {
        React.Children.forEach(value, (child) => {
            if (!React.isValidElement(child)) return
            if (reactElementTag(child) === tag) matches.push(child)
            if (child.props?.children) walk(child.props.children)
        })
    }

    walk(children)
    return matches
}

function tableDataFromReactChildren(children: React.ReactNode): { headers: string[]; rows: string[][] } {
    const thead = reactElementsByTag(children, "thead")[0]
    const tbody = reactElementsByTag(children, "tbody")[0]

    const headerRow = thead ? reactElementsByTag(thead.props.children, "tr")[0] : undefined
    const headers = headerRow
        ? reactElementsByTag(headerRow.props.children, "th").map((cell) => reactCellText(cell.props.children))
        : []

    const bodyRowsSource = tbody ? reactElementsByTag(tbody.props.children, "tr") : reactElementsByTag(children, "tr").slice(headers.length ? 1 : 0)
    const rows = bodyRowsSource.map((row) =>
        reactElementsByTag(row.props.children, "td").map((cell) => reactCellText(cell.props.children))
    ).filter((row) => row.length > 0)

    return { headers, rows }
}

// Standalone named component so React always sees the same component type
// regardless of `createEnhancedMarkdownComponents` re-invocations.
function SortableTable({ node, children, onCopyTable }: { node: any; children?: React.ReactNode; onCopyTable: (s: string) => void }) {
    const [copied, setCopied] = useState(false)
    const [sortCol, setSortCol] = useState<number | null>(null)
    const [sortDir, setSortDir] = useState<"asc" | "desc">("asc")
    const PAGE_SIZE = 10
    const [page, setPage] = useState(0)

    const { headers, rows } = useMemo(() => {
        const astHeaders: string[] = []
        const astRows: string[][] = []

        if (node) {
            const theadSection = node.children?.find((s: any) => s.tagName === "thead")
            const tbodySection = node.children?.find((s: any) => s.tagName === "tbody")
            const headerRow = theadSection?.children?.find((r: any) => r.tagName === "tr")
            astHeaders.push(...(headerRow?.children ?? []).filter((c: any) => c.tagName === "th").map(hastCellText))
            astRows.push(...(tbodySection?.children ?? [])
                .filter((r: any) => r.tagName === "tr")
                .map((r: any) => (r.children ?? []).filter((c: any) => c.tagName === "td").map(hastCellText)))
        }

        if (astHeaders.length || astRows.length) {
            return { headers: astHeaders, rows: astRows }
        }

        return tableDataFromReactChildren(children)
    }, [children, node])

    const sortedRows = useMemo(() => {
        if (sortCol === null) return rows
        return [...rows].sort((a, b) => {
            const va = a[sortCol] ?? "", vb = b[sortCol] ?? ""
            const na = parseFloat(va.replace(/[^0-9.\-e+]/g, "")), nb = parseFloat(vb.replace(/[^0-9.\-e+]/g, ""))
            const cmp = (!isNaN(na) && !isNaN(nb)) ? na - nb : va.localeCompare(vb)
            return sortDir === "asc" ? cmp : -cmp
        })
    }, [rows, sortCol, sortDir])

    useEffect(() => { setPage(0) }, [sortCol, sortDir])

    const totalRows = sortedRows.length
    const needsPagination = totalRows > PAGE_SIZE
    const pageCount = Math.ceil(totalRows / PAGE_SIZE)
    const visibleRows = needsPagination ? sortedRows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE) : sortedRows

    const handleSort = (col: number) => {
        if (sortCol === col) { setSortDir(d => d === "asc" ? "desc" : "asc") }
        else { setSortCol(col); setSortDir("asc") }
    }
    const handleCopy = () => {
        const allRows = headers.length ? [headers, ...rows] : rows
        onCopyTable(allRows.map(r => r.join('\t')).join('\n'))
        setCopied(true); setTimeout(() => setCopied(false), 2000)
    }
    const renderCell = (text: string) => {
        if (text.startsWith("↑")) return <span className="font-medium text-teal-600 dark:text-teal-400">{text}</span>
        if (text.startsWith("↓")) return <span className="font-medium text-rose-600 dark:text-rose-400">{text}</span>
        return text
    }
    const btnClass = "px-1.5 py-0.5 rounded border border-border hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors text-xs"

    // If neither the markdown AST nor rendered children yielded table data, fall back.
    if (headers.length === 0 && rows.length === 0) {
        return (
            <div className="relative group my-4 rounded-lg border border-border overflow-hidden overflow-x-auto">
                <table className="w-full border-collapse text-sm">{children}</table>
            </div>
        )
    }

    return (
        <div className="relative group my-4 rounded-lg border border-border overflow-hidden">
            <button onClick={handleCopy}
                className="absolute top-1.5 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-background border border-border rounded px-2 py-1 text-xs flex items-center gap-1 hover:bg-accent z-10"
                title="Copy table as TSV">
                {copied ? <><Check className="w-3 h-3" />Copied!</> : <><Copy className="w-3 h-3" />Copy</>}
            </button>
            <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                    {headers.length > 0 && (
                        <thead className="bg-muted/60 border-b border-border">
                            <tr>
                                {headers.map((h, i) => {
                                    const active = sortCol === i
                                    return (
                                        <th key={i}
                                            className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:text-foreground transition-colors"
                                            onClick={() => handleSort(i)}>
                                            <span className="inline-flex items-center gap-1">
                                                {h}
                                                {active ? (sortDir === "asc" ? <ChevronUp className="w-3 h-3 text-foreground" /> : <ChevronDown className="w-3 h-3 text-foreground" />) : <ChevronUp className="w-3 h-3 opacity-20" />}
                                            </span>
                                        </th>
                                    )
                                })}
                            </tr>
                        </thead>
                    )}
                    <tbody className="divide-y divide-border">
                        {visibleRows.map((row, ri) => (
                            <tr key={ri} className="hover:bg-muted/30 transition-colors">
                                {row.map((cell, ci) => (
                                    <td key={ci} className="px-3 py-2 text-xs text-foreground align-top">{renderCell(cell)}</td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                    {needsPagination && (
                        <tfoot className="border-t border-border bg-muted/30">
                            <tr><td colSpan={999} className="px-3 py-2">
                                <div className="flex items-center justify-between text-xs text-muted-foreground select-none">
                                    <span>Rows {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, totalRows)} of {totalRows}</span>
                                    <div className="flex items-center gap-1">
                                        <button onClick={() => setPage(0)} disabled={page === 0} className={btnClass}>«</button>
                                        <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className={btnClass}>‹ Prev</button>
                                        <span className="px-2">Page {page + 1} / {pageCount}</span>
                                        <button onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))} disabled={page === pageCount - 1} className={btnClass}>Next ›</button>
                                        <button onClick={() => setPage(pageCount - 1)} disabled={page === pageCount - 1} className={btnClass}>»</button>
                                    </div>
                                </div>
                            </td></tr>
                        </tfoot>
                    )}
                </table>
            </div>
        </div>
    )
}

// Enhanced markdown components with copy table functionality
function createEnhancedMarkdownComponents(onCopyTable: (content: string) => void, geneColorMap?: Map<string, number>, toolSources?: Record<string, string>) {
    return {
        img: ({ node, ...props }: any) => {
            return (
                <img
                    {...props}
                    className={cn(
                        "max-w-full h-auto rounded-md border border-border",
                        props.className
                    )}
                    loading="lazy"
                />
            )
        },
        code: ({ node, className, children, ...props }: any) => {
            const match = /language-(\w+)/.exec(className || "")
            const isInline = !match

            if (isInline) {
                return (
                    <code className="bg-muted px-1 py-0.5 rounded text-sm font-mono" {...props}>
                        {children}
                    </code>
                )
            }
            return (
                <code className={className} {...props}>
                    {children}
                </code>
            )
        },
        table: ({ node, children }: any) => <SortableTable node={node} children={children} onCopyTable={onCopyTable} />,
        // Fallback styled sub-components (used only in non-passNode ReactMarkdown instances)
        thead: ({ children, ...props }: any) => <thead className="bg-muted/60 border-b border-border" {...props}>{children}</thead>,
        tbody: ({ children, ...props }: any) => <tbody className="divide-y divide-border" {...props}>{children}</tbody>,
        tr: ({ children, ...props }: any) => <tr className="hover:bg-muted/30 transition-colors" {...props}>{children}</tr>,
        th: ({ children, ...props }: any) => <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wide whitespace-nowrap" {...props}>{children}</th>,
        td: ({ children, ...props }: any) => {
            const text = typeof children === "string" ? children : Array.isArray(children) && typeof children[0] === "string" ? children[0] : null
            const isSensitive = text?.startsWith("↑"); const isResistant = text?.startsWith("↓")
            return (
                <td className="px-3 py-2 text-xs text-foreground align-top" {...props}>
                    {(isSensitive || isResistant) ? <span className={isSensitive ? "font-medium text-teal-600 dark:text-teal-400" : "font-medium text-rose-600 dark:text-rose-400"}>{children}</span> : children}
                </td>
            )
        },
        blockquote: ({ node, children, ...props }: any) => {
            // Suppress inline source attribution blockquotes — sources are shown
            // as a consolidated footer below the message instead.
            const text = String(children?.props?.children ?? children ?? "")
            if (text.includes("Source:")) return null
            return <blockquote {...props}>{children}</blockquote>
        },
        a: ({ href, children, ...props }: any) => {
            if (href?.startsWith("#source:")) {
                const key = href.replace("#source:", "")
                const src = INLINE_SOURCE_MAP[key]
                const label = src?.label || String(children)
                // Use the specific API endpoint URL if available, otherwise fall back to root
                const url = toolSources?.[key] ?? src?.url ?? "#"
                return (
                    <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={`Source: ${label}`}
                        className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium border border-border bg-muted/50 text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors no-underline mx-0.5 align-middle"
                    >
                        {label}
                    </a>
                )
            }
            return <a href={href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>
        },
        h2: ({ node, children, ...props }: any) => {
            // Check if this is a synthesis section (starts with "Direct Answer" or contains key synthesis keywords)
            const text = String(children)
            const isSynthesis = text.includes("Direct Answer") || text.includes("Key Findings") || text.includes("Analytical Synthesis")

            if (isSynthesis) {
                return (
                    <div className="bg-gradient-to-r from-primary/10 to-primary/5 dark:from-primary/20 dark:to-primary/10 border-l-4 border-primary rounded-r-lg p-4 my-6">
                        <h2 className="text-lg font-semibold mb-0 flex items-center gap-2" {...props}>
                            <Sparkles className="w-5 h-5 text-primary" />
                            {children}
                        </h2>
                    </div>
                )
            }

            // Check if this header contains a gene name (pattern: "Header text - GENENAME")
            if (geneColorMap) {
                const geneMatch = text.match(/[-–]\s*([A-Z0-9]+)\s*$/)
                const geneName = geneMatch ? geneMatch[1] : null

                if (geneName && geneColorMap.has(geneName)) {
                    const geneIndex = geneColorMap.get(geneName)!
                    const borderColor = getGeneBorderColor(geneIndex)
                    return (
                        <h2 className={cn("text-lg font-semibold mt-6 mb-3 pl-3 border-l-4", borderColor)} {...props}>
                            {children}
                        </h2>
                    )
                }
            }

            return <h2 className="text-lg font-semibold mt-6 mb-3" {...props}>{children}</h2>
        },
    }
}


function hasMoreThanNLines(text: string, n: number): boolean {
    if (!text) return false
    let count = 0
    for (let i = 0; i < text.length; i++) {
        if (text.charCodeAt(i) === 10) {
            count++
            if (count > n) return true
        }
    }
    return false
}

function stripInlineImageDataUrls(markdown: string): string {
    if (!markdown) return ""
    // Replace inline base64 images with a friendly placeholder in previews.
    return markdown.replace(
        /!\[[^\]]*\]\(data:image\/[^)]+\)/gi,
        "_(Plot attached — load details to view.)_"
    )
}

function stripExportBase64Images(markdown: string): string {
    if (!markdown) return ""
    return markdown.replace(
        /!\[([^\]]*)\]\(data:image\/[^)]+\)/gi,
        (_match, alt) => `<em>[Figure${alt ? `: ${alt}` : ""} — open in app to view]</em>`
    )
}

function rewriteExportInlineSourceLinks(markdown: string, toolSources?: Record<string, string>): string {
    if (!markdown) return ""

    return markdown.replace(/\[([^\]]+)\]\(#source:([^)]+)\)/g, (_match, label, key) => {
        const resolvedUrl = toolSources?.[key] || INLINE_SOURCE_MAP[key]?.url
        return resolvedUrl ? `[${label}](${resolvedUrl})` : label
    })
}

async function renderMarkdownForExport(markdown: string, toolSources?: Record<string, string>): Promise<string> {
    const { renderToStaticMarkup } = await import("react-dom/server.browser")
    const prepared = rewriteExportInlineSourceLinks(stripExportBase64Images(markdown), toolSources)

    return renderToStaticMarkup(
        <div className="export-markdown">
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeHighlight, rehypeKatex]}
                urlTransform={safeMarkdownUrlTransform}
                components={{
                    a: ({ href, children, ...props }) => (
                        <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
                            {children}
                        </a>
                    ),
                    img: ({ ...props }) => (
                        <img
                            {...props}
                            className={cn("export-image", props.className)}
                            loading="lazy"
                        />
                    ),
                }}
            >
                {prepared}
            </ReactMarkdown>
        </div>
    )
}

const MessagesPane = memo(function MessagesPane({
    messages,
    isGuest,
    isLoading,
    isHistoryLoading,
    isLoadingMoreHistory,
    hasMoreHistory,
    onLoadMoreHistory,
    scrollAreaRootRef,
    expandedKeys,
    onToggleExpand,
    copiedIndex,
    onCopy,
    editingTurnId,
    editDraft,
    onStartEdit,
    onCancelEdit,
    onChangeEditDraft,
    onRequestResubmitEdit,
    isEditingBusy,
    onSend,
    lastUserQuery,
    streamStatus,
    searchTerm,
    searchMatchIndices,
    searchMatchIndex,
    jumpHighlightTurnId,
    messageRefs,
}: {
    messages: ChatMessage[]
    isGuest: boolean
    isLoading: boolean
    isHistoryLoading: boolean
    isLoadingMoreHistory: boolean
    hasMoreHistory: boolean
    onLoadMoreHistory: () => void
    scrollAreaRootRef: React.RefObject<any>
    expandedKeys: Record<string, boolean>
    onToggleExpand: (key: string) => void
    copiedIndex: number | null
    onCopy: (content: string, index: number) => void
    editingTurnId: number | null
    editDraft: string
    onStartEdit: (message: ChatMessage) => void
    onCancelEdit: () => void
    onChangeEditDraft: (value: string) => void
    onRequestResubmitEdit: () => void
    isEditingBusy: boolean
    onSend: (text: string) => void
    lastUserQuery: string
    streamStatus: string | null
    searchTerm: string
    searchMatchIndices: number[]
    searchMatchIndex: number
    jumpHighlightTurnId: number | null
    messageRefs: React.MutableRefObject<(HTMLDivElement | null)[]>
}) {
    const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
    const [feedbackState, setFeedbackState] = useState<Record<number, 1 | -1>>({})

    const handleFeedback = async (message: ChatMessage, index: number, rating: 1 | -1) => {
        const key = message.turnId ?? index
        if (feedbackState[key] != null) return
        setFeedbackState(prev => ({ ...prev, [key]: rating }))
        try {
            await chatAPI.submitFeedback({
                turn_id: message.turnId,
                rating,
            })
        } catch {
            // Silently ignore — feedback is best-effort
        }
    }

    return (
        <ScrollArea ref={scrollAreaRootRef} className="flex-1 p-6">
            <div className="space-y-4 max-w-4xl mx-auto">
                {isHistoryLoading && (
                    <div className="text-center text-xs text-muted-foreground py-2">
                        Loading history...
                    </div>
                )}
                {!isHistoryLoading && hasMoreHistory && (
                    <div className="flex justify-center py-2">
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={onLoadMoreHistory}
                            disabled={isLoadingMoreHistory}
                        >
                            {isLoadingMoreHistory ? "Loading earlier messages..." : "Load earlier messages"}
                        </Button>
                    </div>
                )}
                {messages.map((message, index) => {
                    // Use stable key based on timestamp + role to prevent re-renders when prepending
                    const messageKey = `${message.role}-${message.timestamp?.getTime?.() ?? index}-${index}`
                    const isEditingUserMessage =
                        message.role === "user" &&
                        message.turnId != null &&
                        message.turnId === editingTurnId
                    const canEditMessage =
                        message.role === "user" &&
                        !isGuest &&
                        message.turnId != null
                    const userBubbleWrapperClass = message.role === "user"
                        ? isEditingUserMessage
                            ? "flex w-full max-w-[min(44rem,calc(100%-3rem))] self-end flex-col items-end gap-2"
                            : "flex w-fit max-w-[80%] self-end flex-col items-end"
                        : "flex flex-col items-start"

                    return (
                        <div
                            key={messageKey}
                            id={messageKey}
                            ref={el => { messageRefs.current[index] = el }}
                            onMouseEnter={() => setHoveredIndex(index)}
                            onMouseLeave={() => setHoveredIndex(null)}
                            style={{ contentVisibility: "auto", containIntrinsicSize: "0 200px" }}
                            className={cn(
                                "flex flex-col gap-1 w-full rounded-lg transition-colors duration-300",
                                jumpHighlightTurnId != null && message.turnId === jumpHighlightTurnId
                                    ? "ring-2 ring-teal-400 ring-offset-2 ring-offset-background"
                                    : "",
                                searchTerm && searchMatchIndices.includes(index) && searchMatchIndices[searchMatchIndex] === index
                                    ? "ring-2 ring-amber-400 ring-offset-1"
                                    : searchTerm && searchMatchIndices.includes(index)
                                    ? "ring-1 ring-amber-200"
                                    : ""
                            )}
                        >
                            <div className={cn(
                                "flex gap-3",
                                message.role === "user" ? "justify-end" : "justify-start"
                            )}>
                                {message.role === "assistant" && (
                                    <div className="flex-shrink-0">
                                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-teal-500 to-emerald-500 flex items-center justify-center">
                                            <Sparkles className="w-4 h-4 text-white" />
                                        </div>
                                    </div>
                                )}
                                <div className={userBubbleWrapperClass}>
                                    {message.isError ? (
                                        <div className="max-w-[80%] rounded-2xl rounded-tl-sm border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/40 p-4 text-sm text-red-800 dark:text-red-300 shadow-sm">
                                            <div className="flex items-start gap-2.5">
                                                <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                                                <div className="flex-1 min-w-0">
                                                    <p className="font-semibold mb-1">Something went wrong</p>
                                                    <p className="text-xs text-red-700 dark:text-red-400 leading-relaxed">{message.content}</p>
                                                </div>
                                            </div>
                                            <button
                                                type="button"
                                                onClick={() => onSend(lastUserQuery)}
                                                disabled={isLoading || !lastUserQuery}
                                                className="mt-3 flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md bg-red-100 dark:bg-red-900/40 hover:bg-red-200 dark:hover:bg-red-900/70 text-red-800 dark:text-red-300 border border-red-200 dark:border-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                            >
                                                <RefreshCw className="h-3 w-3" />
                                                Retry
                                            </button>
                                        </div>
                                    ) : (
                                    <Card
                                        className={cn(
                                            "relative shadow-sm hover:shadow-md transition-shadow duration-300",
                                            message.role === "user"
                                                ? cn(
                                                    "bg-primary text-primary-foreground rounded-2xl rounded-tr-sm",
                                                    isEditingUserMessage ? "w-full" : ""
                                                )
                                                : "max-w-[80%] bg-card rounded-2xl rounded-tl-sm border-muted/60"
                                        )}
                                    >
                                        <CardContent className="p-4 leading-relaxed tracking-wide">
                                            {message.role === "assistant" && (message.isGeneralKnowledge || message.confidence === "general_knowledge") && (
                                                <div className="flex items-start gap-2 mb-3 px-3 py-2 rounded-md bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300 text-xs">
                                                    <span className="mt-0.5 shrink-0">⚠️</span>
                                                    <span>
                                                        <span className="font-semibold">General knowledge response</span> — this answer is based on the AI&apos;s training data, not LinkedOmics database. It may be incomplete or outdated.
                                                    </span>
                                                </div>
                                            )}
                                            {message.role === "assistant" && message.confidence === "low" && !message.isGeneralKnowledge && (
                                                <div className="flex items-start gap-2 mb-3 px-3 py-2 rounded-md bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300 text-xs">
                                                    <span className="mt-0.5 shrink-0">⚠️</span>
                                                    <span>
                                                        <span className="font-semibold">Limited data</span> — the queried tools returned no usable results. This response may rely on general knowledge.
                                                    </span>
                                                </div>
                                            )}
                                            {message.role === "assistant" && message.confidence === "partial" && (
                                                <div className="flex items-start gap-2 mb-3 px-3 py-2 rounded-md bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 text-blue-800 dark:text-blue-300 text-xs">
                                                    <span className="mt-0.5 shrink-0">ℹ️</span>
                                                    <span>
                                                        <span className="font-semibold">Partial data</span> — some tools returned results while others found no data. Conclusions are based on available evidence only.
                                                    </span>
                                                </div>
                                            )}
                                            {/* Summary shown at the top before the detailed response */}
                                            {message.role === "assistant" && message.summary && message.summary.trim().length > 0 && message.summary !== message.content && (
                                                <div className="mb-4 pb-4 border-b border-border">
                                                    <div className="rounded-md border border-border bg-muted/40 p-3">
                                                        <AssistantMarkdown content={message.summary} />
                                                    </div>
                                                </div>
                                            )}

                                            {message.role === "assistant" ? (
                                                <LazyMessageContent estimatedHeight={Math.min(800, Math.max(80, Math.ceil((message.content || "").length / 80) * 22))}>
                                                <div className="space-y-3">
                                                    {(() => {
                                                        const key =
                                                            `${message.role}-` +
                                                            `${message.timestamp?.getTime?.() ?? "no-ts"}-` +
                                                            `${index}`
                                                        const expanded = !!expandedKeys[key]
                                                        const content = message.content || ""
                                                        const fullAvailable = message.hasFullContent === true
                                                        const hasImages = message.hasImages === true
                                                        const isPreviewOnly = message.hasFullContent === false
                                                        const isLarge =
                                                            !message.noCollapse &&
                                                            (isPreviewOnly || message.wasPreview || content.length > 4000 || hasMoreThanNLines(content, 80))

                                                        let enrichmentData = null
                                                        // Regex to find ```json ... ``` blocks or just raw arrays [ ... ]
                                                        // We look for a pattern that looks like an array of objects
                                                        const jsonBlockRegex = /```json\s*(\[\s*\{[\s\S]*?\}\s*\])\s*```/
                                                        const rawArrayRegex = /(\[\s*\{[\s\S]*?\}\s*\])/

                                                        let match = content.match(jsonBlockRegex)
                                                        if (!match) match = content.match(rawArrayRegex)

                                                        // Sanitized content: strip the JSON block if it's rendered by EnrichmentRenderer
                                                        let sanitizedContent = content

                                                        if (match && match[1]) {
                                                            try {
                                                                const parsed = JSON.parse(match[1])
                                                                if (Array.isArray(parsed) && parsed.length > 0 &&
                                                                    parsed[0].geneSet && parsed[0].enrichmentRatio && parsed[0].FDR) {
                                                                    enrichmentData = parsed
                                                                    // Strip the matched block so AssistantMarkdown doesn't render it again
                                                                    sanitizedContent = content.replace(match[0], "").trim()
                                                                }
                                                            } catch (e) {
                                                                // Not valid JSON or not enrichment data
                                                            }
                                                        }

                                                        const renderEnrichment = () => (
                                                            enrichmentData ? (
                                                                <div className="mt-2 mb-6 border-b border-border pb-4">
                                                                    <div className="flex items-center gap-2 mb-3 text-sm font-medium text-teal-600 dark:text-teal-400">
                                                                        <Sparkles className="w-4 h-4" />
                                                                        Enrichment Analysis Results
                                                                    </div>
                                                                    <EnrichmentRenderer data={enrichmentData} />
                                                                </div>
                                                            ) : null
                                                        )

                                                        if (!isLarge || expanded) {
                                                            // Extract gene names for badges
                                                            const genes = extractGeneNames(content)

                                                            return (
                                                                <div className="space-y-2">
                                                                    {renderEnrichment()}

                                                                    {genes.length > 0 && (
                                                                        <div className="flex flex-wrap gap-1.5 mb-3">
                                                                            {genes.map((gene, idx) => (
                                                                                <GeneBadge key={gene} gene={gene} index={idx} />
                                                                            ))}
                                                                        </div>
                                                                    )}
                                                                    {isLarge && (
                                                                        <div className="flex justify-end">
                                                                            <button
                                                                                className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-4"
                                                                                onClick={() => onToggleExpand(key)}
                                                                            >
                                                                                Hide details
                                                                            </button>
                                                                        </div>
                                                                    )}
                                                                    {/* Render markdown content (JSON block stripped when shown via EnrichmentRenderer) */}
                                                                    <AssistantMarkdown content={sanitizedContent} toolSources={message.toolSources} visualizations={message.visualizations} />
                                                                </div>
                                                            )
                                                        }

                                                        return (
                                                            <div className="rounded-md border border-border bg-background p-3">
                                                                <div className="flex justify-center">
                                                                    <button
                                                                        className="text-xs font-medium text-primary hover:underline underline-offset-4"
                                                                        onClick={() => onToggleExpand(key)}
                                                                    >
                                                                        {fullAvailable
                                                                            ? hasImages
                                                                                ? "Load details (show plot)"
                                                                                : "Load details"
                                                                            : "Show details"}
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        )
                                                    })()}
                                                </div>
                                                </LazyMessageContent>
                                            ) : (
                                                isEditingUserMessage ? (
                                                    <div className="space-y-4">
                                                        <textarea
                                                            value={editDraft}
                                                            onChange={(event) => onChangeEditDraft(event.target.value)}
                                                            onKeyDown={(event) => {
                                                                if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                                                                    event.preventDefault()
                                                                    onRequestResubmitEdit()
                                                                }
                                                                if (event.key === "Escape") {
                                                                    event.preventDefault()
                                                                    onCancelEdit()
                                                                }
                                                            }}
                                                            disabled={isEditingBusy}
                                                            autoFocus
                                                            rows={5}
                                                            className="w-full min-h-[144px] resize-y rounded-lg border border-border bg-background/95 px-4 py-3 text-sm leading-relaxed text-foreground outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
                                                        />
                                                        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                                                            <Button
                                                                type="button"
                                                                size="sm"
                                                                variant="outline"
                                                                className="w-full min-w-[8.5rem] bg-background text-foreground hover:bg-accent sm:w-auto"
                                                                onClick={onCancelEdit}
                                                                disabled={isEditingBusy}
                                                            >
                                                                Cancel
                                                            </Button>
                                                            <Button
                                                                type="button"
                                                                size="sm"
                                                                className="w-full min-w-[8.5rem] bg-slate-900 text-white hover:bg-slate-800 sm:w-auto"
                                                                onClick={onRequestResubmitEdit}
                                                                disabled={isEditingBusy || !editDraft.trim()}
                                                            >
                                                                Send
                                                            </Button>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <p className="text-sm whitespace-pre-wrap">{message.content}</p>
                                                )
                                            )}
                                            {(() => {
                                                const content = message.content || ""
                                                const inlined = new Set([
                                                    ...(content.match(/\[PLOT:([^\]]+)\]/g)?.map(m => m.slice(6, -1)) ?? []),
                                                    ...(content.match(/\[NETWORK:([^\]]+)\]/g)?.map(m => m.slice(9, -1)) ?? []),
                                                    ...(content.match(/\[TABLE:([^\]]+)\]/g)?.map(m => m.slice(7, -1)) ?? []),
                                                ])
                                                const remaining = (message.visualizations || []).filter(v => !inlined.has(v.id))
                                                return remaining.length > 0 ? (
                                                    <div className="mt-4 space-y-4">
                                                        {remaining.map((viz) =>
                                                            viz.type === "network_plot"
                                                                ? <NetworkPlot key={viz.id} visualization={viz} />
                                                                : viz.type === "drug_target_grid"
                                                                ? <DrugTargetGrid key={viz.id} visualization={viz} />
                                                                : viz.type === "target_search_table"
                                                                ? <TargetSearchTable key={viz.id} visualization={viz} />
                                                                : viz.type === "predictive_results_table"
                                                                ? <PredictiveResultsTable key={viz.id} visualization={viz} />
                                                                : <StaticPlot key={viz.id} visualization={viz} />
                                                        )}
                                                    </div>
                                                ) : null
                                            })()}

                                            {/* Consolidated data sources footer */}
                                            {message.toolSources && Object.keys(message.toolSources).length > 0 && (
                                                <div className="flex flex-wrap items-center gap-1.5 mt-3 pt-2 border-t border-border/40">
                                                    {Object.entries(message.toolSources).map(([key, url]) => {
                                                        const src = INLINE_SOURCE_MAP[key]
                                                        if (!src) return null
                                                        return (
                                                            <a
                                                                key={key}
                                                                href={(url as string) || src.url}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium border border-border bg-muted/50 text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors no-underline"
                                                            >
                                                                {src.label}
                                                            </a>
                                                        )
                                                    })}
                                                </div>
                                            )}

                                            {message.timestamp && (
                                                <p className="text-xs opacity-70 mt-2">
                                                    {message.timestamp.toLocaleTimeString()}
                                                </p>
                                            )}


                                            {/* Display analysis results if available */}
                                            {message.analyses && message.analyses.length > 0 && (
                                                <div className="mt-4 pt-4 border-t border-border">
                                                    <h4 className="text-sm font-semibold mb-3 flex items-center gap-2">
                                                        <Sparkles className="w-4 h-4" />
                                                        Analysis Results
                                                    </h4>
                                                    {message.analyses.map((analysis, idx) => (
                                                        <div key={idx} className="mb-4 last:mb-0">
                                                            <div className="p-4 rounded-lg bg-muted/50 border border-border">
                                                                {/* existing analysis rendering continues below (unchanged) */}
                                                                {/* NOTE: This component only wraps the messages list; analysis rendering is unchanged. */}
                                                                {/* The rest of the analysis UI is rendered by existing JSX in the file. */}
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}

                                            {/* Display papers if available */}
                                            {message.papers && message.papers.length > 0 && (
                                                <div className="mt-4 pt-4 border-t border-border">
                                                    <h4 className="text-sm font-semibold mb-3 flex items-center gap-2">
                                                        <Sparkles className="w-4 h-4" />
                                                        Sources ({message.papers.length} papers found)
                                                    </h4>
                                                    <div className="space-y-2">
                                                        {message.papers.map((paper, idx) => (
                                                            <div
                                                                key={idx}
                                                                className="p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                                                            >
                                                                <div className="flex items-start gap-2">
                                                                    <span className="text-xs font-medium text-muted-foreground mt-0.5">
                                                                        {idx + 1}.
                                                                    </span>
                                                                    <div className="flex-1 min-w-0">
                                                                        {paper.link ? (
                                                                            <a
                                                                                href={paper.link}
                                                                                target="_blank"
                                                                                rel="noopener noreferrer"
                                                                                className="text-sm font-medium text-primary hover:underline break-words"
                                                                            >
                                                                                {paper.title}
                                                                            </a>
                                                                        ) : (
                                                                            <p className="text-sm font-medium break-words">
                                                                                {paper.title}
                                                                            </p>
                                                                        )}
                                                                        {paper.snippet && (
                                                                            <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                                                                                {paper.snippet}
                                                                            </p>
                                                                        )}
                                                                        {(paper.authors || paper.journal || paper.year || paper.source) && (
                                                                            <p className="text-xs text-muted-foreground mt-1">
                                                                                {paper.authors && <span>{paper.authors}</span>}
                                                                                {paper.journal && <span> • {paper.journal}</span>}
                                                                                {paper.year && <span> ({paper.year})</span>}
                                                                                {paper.source && <span> • {paper.source}</span>}
                                                                            </p>
                                                                        )}
                                                                    </div>
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}

                                        </CardContent>
                                    </Card>
                                    )}
                                    {message.role === "user" && !isEditingUserMessage && (
                                        <div className={cn("flex items-center gap-1 mt-1 transition-opacity duration-150 opacity-60 md:opacity-0 md:pointer-events-none", hoveredIndex === index ? "md:opacity-100 md:pointer-events-auto" : "")}>
                                            <Button
                                                type="button"
                                                size="sm"
                                                variant="ghost"
                                                className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                                                onClick={() => onCopy(message.content, index)}
                                                title="Copy"
                                            >
                                                {copiedIndex === index ? (
                                                    <Check className="h-3.5 w-3.5" />
                                                ) : (
                                                    <Copy className="h-3.5 w-3.5" />
                                                )}
                                            </Button>
                                            {canEditMessage && (
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="ghost"
                                                    className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                                                    onClick={() => onStartEdit(message)}
                                                    disabled={isEditingBusy}
                                                    title="Edit"
                                                >
                                                    <Pencil className="h-3.5 w-3.5" />
                                                </Button>
                                            )}
                                        </div>
                                    )}
                                    {message.role === "assistant" && !message.isError && (
                                        <div className={cn("flex items-center gap-0.5 mt-1 transition-opacity duration-150 opacity-60 md:opacity-0 md:pointer-events-none", hoveredIndex === index ? "md:opacity-100 md:pointer-events-auto" : "")}>
                                            <button
                                                type="button"
                                                onClick={() => onCopy(message.content, index)}
                                                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted"
                                                title="Copy to clipboard"
                                            >
                                                {copiedIndex === index ? (
                                                    <Check className="w-3.5 h-3.5 text-green-500" />
                                                ) : (
                                                    <Copy className="w-3.5 h-3.5" />
                                                )}
                                            </button>
                                        </div>
                                    )}
                                </div>
                                {message.role === "user" && (
                                    <div className="flex-shrink-0">
                                        <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center">
                                            <User className="w-4 h-4 text-muted-foreground" aria-label="User" />
                                        </div>
                                    </div>
                                )}
                            </div>
                            {message.role === "assistant" && message.toolsUsed && message.toolsUsed.length > 0 && (() => {
                                const sources = resolveDataSources(message.toolsUsed)
                                if (sources.length === 0) return null
                                return (
                                    <div className="flex flex-wrap items-center gap-1.5 mt-2 pl-11">
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
                                )
                            })()}
                            {message.role === "assistant" && message.clarificationOptions && message.clarificationOptions.length > 0 && (
                                <div className="mt-2 pl-11 border-l-2 border-amber-400 dark:border-amber-600 ml-11 pl-3">
                                    <div className="flex items-center gap-1 mb-1.5 text-xs font-semibold text-amber-700 dark:text-amber-400">
                                        <HelpCircle className="w-3.5 h-3.5" />
                                        Choose one:
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                        {message.clarificationOptions.map((opt, oi) => (
                                            <button
                                                key={oi}
                                                onClick={() => onSend(opt)}
                                                className="text-xs px-3 py-1.5 rounded-full border border-amber-400 dark:border-amber-600 bg-amber-50 dark:bg-amber-950/50 text-amber-800 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/60 font-medium transition-all duration-200 hover:scale-[1.02] shadow-sm hover:shadow"
                                            >
                                                {opt}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {message.role === "assistant" && message.suggestions && message.suggestions.length > 0 && (
                                <div className="mt-1 pl-11">
                                    <div className="flex items-center gap-1 mb-1.5 text-xs font-medium text-teal-600 dark:text-teal-400">
                                        <Sparkles className="w-3.5 h-3.5" />
                                        Try next:
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                        {message.suggestions.map((s, si) => (
                                            <button
                                                key={si}
                                                onClick={() => onSend(s)}
                                                className="text-xs px-3 py-1.5 rounded-full border border-teal-300 dark:border-teal-700 bg-teal-50 dark:bg-teal-950/40 text-teal-700 dark:text-teal-300 hover:bg-teal-100 dark:hover:bg-teal-900/60 transition-all duration-200 hover:scale-[1.02] shadow-sm hover:shadow text-left"
                                            >
                                                {s}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {message.role === "assistant" && message.executionTrace && (
                                <ExecutionTrace trace={message.executionTrace} />
                            )}
                            {message.role === "assistant" && message.turnId != null && (
                                <div className="flex items-center gap-1 ml-11 mt-1">
                                    <span className="text-xs text-muted-foreground/50 mr-0.5">Helpful?</span>
                                    <button
                                        type="button"
                                        onClick={() => handleFeedback(message, index, 1)}
                                        className={cn(
                                            "p-1 rounded-md text-xs transition-colors",
                                            feedbackState[message.turnId] === 1
                                                ? "text-emerald-500"
                                                : feedbackState[message.turnId] != null
                                                ? "text-muted-foreground/30 cursor-default"
                                                : "text-muted-foreground hover:text-emerald-500 hover:bg-muted",
                                        )}
                                        title="Helpful"
                                        disabled={feedbackState[message.turnId] != null}
                                    >
                                        <ThumbsUp className="w-3.5 h-3.5" />
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => handleFeedback(message, index, -1)}
                                        className={cn(
                                            "p-1 rounded-md text-xs transition-colors",
                                            feedbackState[message.turnId] === -1
                                                ? "text-rose-500"
                                                : feedbackState[message.turnId] != null
                                                ? "text-muted-foreground/30 cursor-default"
                                                : "text-muted-foreground hover:text-rose-500 hover:bg-muted",
                                        )}
                                        title="Not helpful"
                                        disabled={feedbackState[message.turnId] != null}
                                    >
                                        <ThumbsDown className="w-3.5 h-3.5" />
                                    </button>
                                </div>
                            )}
                        </div>
                    )
                })}

                {
                    isLoading && (
                        <div className="flex gap-3">
                            <div className="flex-shrink-0">
                                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-teal-500 to-emerald-500 flex items-center justify-center">
                                    <Loader2 className="w-4 h-4 text-white animate-spin" />
                                </div>
                            </div>
                            <Card className="bg-card rounded-2xl rounded-tl-sm border-muted/60 shadow-sm">
                                <CardContent className="p-4">
                                    <div className="flex items-center gap-2">
                                        <div className="flex space-x-1">
                                            <div className="w-2 h-2 rounded-full bg-teal-500 animate-bounce" />
                                            <div className="w-2 h-2 rounded-full bg-violet-500 animate-bounce" style={{ animationDelay: "0.2s" }} />
                                            <div className="w-2 h-2 rounded-full bg-pink-500 animate-bounce" style={{ animationDelay: "0.4s" }} />
                                        </div>
                                        <span className="text-sm text-muted-foreground ml-2">
                                            {streamStatus || "Analyzing your request..."}
                                        </span>
                                    </div>
                                </CardContent>
                            </Card>
                        </div>
                    )
                }
            </div >
        </ScrollArea >
    )
})

function mapHistoryItemToMessages(item: { id: number; query: string; response: any; timestamp: number }): ChatMessage[] {
    const resp = item.response
    const timestamp = new Date(((item.timestamp ?? 0) as number) * 1000)
    const summary = typeof resp === "string" ? undefined : (resp?.summary as string | undefined)
    const content =
        typeof resp === "string"
            ? resp
            : (resp?.message_preview as string | undefined) || resp?.message || ""

    return [
        {
            role: "user",
            content: item.query ?? "",
            turnId: item.id,
            timestamp,
        },
        {
            role: "assistant",
            content,
            summary,
            turnId: item.id,
            sourceMessageId: item.id,
            hasFullContent: typeof resp === "string" ? true : (resp?.has_full_content !== false),
            hasImages: typeof resp === "string" ? false : !!resp?.has_images,
            hasVisualizations: typeof resp === "string" ? false : !!resp?.has_visualizations,
            timestamp,
            clarificationOptions: typeof resp === "string" ? undefined : (resp?.clarification_options?.length ? resp.clarification_options : undefined),
            noCollapse: typeof resp === "string" ? undefined : (resp?.no_collapse === true),
            isGeneralKnowledge: typeof resp === "string" ? undefined : (resp?.is_general_knowledge === true),
            confidence: typeof resp === "string" ? undefined : resp?.confidence,
            toolSources: resp?.tool_sources && Object.keys(resp.tool_sources).length ? resp.tool_sources : undefined,
            toolsUsed: typeof resp === "string" ? undefined : (resp?.tools_used?.length ? resp.tools_used : undefined),
            visualizations: typeof resp === "string" ? undefined : stripVizBinary(resp?.visualizations?.length ? resp.visualizations as AnyVisualization[] : undefined),
            executionTrace: typeof resp === "string" ? undefined : (resp?.execution_trace?.length ? resp.execution_trace : undefined),
        },
    ]
}

async function fetchExportMessages(sessionId: string): Promise<ChatMessage[]> {
    const messages: ChatMessage[] = []
    let before: number | undefined
    let hasMore = true

    while (hasMore) {
        const page = await chatAPI.getSessionHistory(sessionId, before == null ? { limit: 100 } : { limit: 100, before })
        page.history.forEach((item) => {
            messages.push(...mapHistoryItemToMessages(item))
        })
        hasMore = page.has_more
        before = page.next_before ?? undefined
        if (!hasMore || before == null) break
    }

    // Only hydrate messages with truncated text — viz binary data is no longer stored
    // in the DB so there's nothing extra to fetch for visualization-only messages.
    const assistantsToHydrate = messages.filter(
        (msg) => msg.role === "assistant" && msg.sourceMessageId && !msg.hasFullContent
    )

    await Promise.all(
        assistantsToHydrate.map(async (msg) => {
            const full = await chatAPI.getChatMessage(msg.sourceMessageId!)
            const resp = full?.response
            if (typeof resp === "string") {
                msg.content = resp
                msg.hasFullContent = true
                return
            }

            msg.content = (resp?.message as string | undefined) || msg.content
            msg.summary = (resp?.summary as string | undefined) ?? msg.summary
            msg.papers = Array.isArray(resp?.papers) && resp.papers.length > 0 ? resp.papers as Paper[] : msg.papers
            msg.analyses = Array.isArray(resp?.analyses) && resp.analyses.length > 0 ? resp.analyses as AnalysisResult[] : msg.analyses
            msg.clarificationOptions = resp?.clarification_options?.length ? resp.clarification_options : msg.clarificationOptions
            msg.noCollapse = resp?.no_collapse === true ? true : msg.noCollapse
            msg.isGeneralKnowledge = resp?.is_general_knowledge === true ? true : msg.isGeneralKnowledge
            msg.confidence = resp?.confidence ?? msg.confidence
            msg.toolsUsed = resp?.tools_used?.length ? resp.tools_used : msg.toolsUsed
            msg.toolSources = resp?.tool_sources && Object.keys(resp.tool_sources).length ? resp.tool_sources : msg.toolSources
            msg.visualizations = Array.isArray(resp?.visualizations) && resp.visualizations.length > 0
                ? stripVizBinary(resp.visualizations as AnyVisualization[])
                : msg.visualizations
            msg.executionTrace = Array.isArray(resp?.execution_trace) && resp.execution_trace.length > 0
                ? resp.execution_trace
                : msg.executionTrace
            msg.hasFullContent = true
            msg.hasVisualizations = Array.isArray(resp?.visualizations) && resp.visualizations.length > 0
            msg.hasImages = !!resp?.has_images || msg.hasImages
        })
    )

    return messages
}

async function downloadSessionExport(messages: ChatMessage[]) {
    const now = new Date()
    const date = now.toISOString().slice(0, 10)
    const time = now.toTimeString().slice(0, 8).replace(/:/g, "-")

    const escapeHtml = (text: string) =>
        text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")

    const messageParts: string[] = []

    for (const msg of messages) {
        if (msg.role === "user") {
            messageParts.push(
                `<div class="message user">` +
                `<strong>You</strong><br><br>` +
                `${escapeHtml(msg.content)}` +
                (msg.timestamp ? `<div class="timestamp">${msg.timestamp.toLocaleString()}</div>` : "") +
                `</div>`
            )
            continue
        }

        if (msg.role !== "assistant") continue

        // Fetch full data for all viz types that were stripped before DB save
        if (msg.visualizations && msg.visualizations.length > 0) {
            await Promise.all(
                msg.visualizations.map(async (viz) => {
                    if (viz.type === "static_plot" && viz.id) {
                        try {
                            const data = await chatAPI.getVisualization(viz.id)
                            viz.png_b64 = typeof data.png_b64 === "string" ? data.png_b64 : undefined
                            ;(viz as any)._csv = typeof data.csv === "string" ? data.csv : ""
                        } catch {
                            // leave png_b64 empty — plot will be skipped
                        }
                    } else if ((viz.type === "drug_target_grid" && !(viz as any).features) ||
                               (viz.type === "target_search_table" && !(viz as any).genes?.length) ||
                               (viz.type === "predictive_results_table" && !(viz as any).rows?.length)) {
                        if (viz.id) {
                            try {
                                const data = await chatAPI.getVisualization(viz.id)
                                Object.assign(viz, data)
                            } catch { /* leave as-is */ }
                        }
                    }
                })
            )
        }

        const vizMap: Record<string, AnyVisualization> = {}
        msg.visualizations?.forEach(v => { vizMap[v.id] = v })

        const buildAtRiskTableHtml = (csv: string): string => {
            const lines = csv.trim().split("\n")
            if (lines.length < 2) return ""
            const headers = lines[0].split(",").map(h => h.trim())
            const groupIdx = headers.indexOf("group")
            const timeIdx = headers.indexOf("time_days")
            const atRiskIdx = headers.indexOf("at_risk")
            if (groupIdx === -1 || timeIdx === -1 || atRiskIdx === -1) return ""
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
            const rows = Array.from(byTime.entries()).sort(([a], [b]) => a - b)
            if (!rows.length) return ""
            const thStyle = `style="text-align:left;padding:4px 8px;font-size:12px;font-weight:600;background:hsl(var(--muted));color:hsl(var(--muted-foreground));border-bottom:1px solid hsl(var(--border));white-space:nowrap;text-transform:uppercase;letter-spacing:0.04em;"`
            const tdStyle = (right = false) => `style="padding:3px 8px;font-size:14px;color:hsl(var(--foreground));${right ? "text-align:right;" : ""}font-variant-numeric:tabular-nums;"`
            const headerCells = [`<th ${thStyle}>Time (days)</th>`, ...groups.map(g => `<th ${thStyle} style="text-align:right;">${escapeHtml(g)}</th>`)]
            const bodyRows = rows.map(([time, vals], i) => {
                const bg = i % 2 === 0 ? "hsl(var(--card))" : "hsl(var(--muted) / 0.4)"
                const cells = [`<td ${tdStyle()}>${time}</td>`, ...groups.map(g => `<td ${tdStyle(true)}>${vals[g] ?? "—"}</td>`)]
                return `<tr style="background:${bg};">${cells.join("")}</tr>`
            })
            return `<div style="margin-top:8px;"><div style="font-size:11px;font-weight:600;color:hsl(var(--muted-foreground));margin-bottom:4px;">At-risk counts by time (days)</div><div style="max-height:180px;overflow-y:auto;border:1px solid hsl(var(--border));border-radius:4px;"><table style="width:100%;border-collapse:collapse;"><thead><tr>${headerCells.join("")}</tr></thead><tbody>${bodyRows.join("")}</tbody></table></div></div>`
        }

        const plotImgHtml = (viz: AnyVisualization) => {
            if (viz.type !== "static_plot" || !(viz as any).png_b64) return ""
            const v = viz as any
            const atRiskHtml = v._csv ? buildAtRiskTableHtml(v._csv) : ""
            return `<div style="margin:16px 0;border:1px solid #e5e7eb;border-radius:6px;overflow:hidden;">${v.title ? `<p style="font-size:12px;color:#888;margin:8px 12px 4px;">${escapeHtml(v.title)}</p>` : ""}<div style="padding:8px;text-align:center;"><img src="data:image/png;base64,${v.png_b64}" alt="${escapeHtml(v.title || "")}" style="max-width:100%;height:auto;" /></div>${atRiskHtml ? `<div style="padding:8px 12px 12px;border-top:1px solid #e5e7eb;background:#fafafa;">${atRiskHtml}</div>` : ""}</div>`
        }

        const TIER_LABELS_EXP: Record<string, string> = {
            T1: "Approved oncology", T2: "Approved non-oncology",
            T3: "Investigational", T4: "Pre-clinical", T5: "Surface protein",
        }
        const TIER_BADGE_BG: Record<string, string> = {
            T1: "#dcfce7", T2: "#dbeafe", T3: "#fef9c3", T4: "#ffedd5", T5: "#f3f4f6",
        }
        const TIER_BADGE_COLOR: Record<string, string> = {
            T1: "#166534", T2: "#1e40af", T3: "#854d0e", T4: "#7c2d12", T5: "#374151",
        }
        const thS = `padding:6px 10px;text-align:left;font-size:12px;font-weight:600;background:hsl(var(--muted));color:hsl(var(--muted-foreground));border-bottom:2px solid hsl(var(--border));white-space:nowrap;text-transform:uppercase;letter-spacing:0.04em;`
        const tdS = `padding:5px 10px;font-size:14px;color:hsl(var(--foreground));border-bottom:1px solid hsl(var(--border));vertical-align:top;`
        const tdCS = `padding:5px 10px;font-size:14px;color:hsl(var(--foreground));border-bottom:1px solid hsl(var(--border));text-align:center;vertical-align:top;`
        const rowEven = `background:hsl(var(--card));`
        const rowOdd = `background:hsl(var(--muted) / 0.4);`

        const drugTargetGridHtml = (viz: AnyVisualization): string => {
            if (viz.type !== "drug_target_grid") return ""
            const v = viz as any
            if (!v.gene) return ""
            const tierBg = v.tier ? (TIER_BADGE_BG[v.tier] ?? "#f3f4f6") : ""
            const tierFg = v.tier ? (TIER_BADGE_COLOR[v.tier] ?? "#374151") : ""
            const tierBadge = v.tier && v.tier !== "NA"
                ? `<span style="display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:600;background:${tierBg};color:${tierFg};margin-left:6px;">${v.tier} · ${TIER_LABELS_EXP[v.tier] ?? v.tier}</span>`
                : ""
            const familyBadge = v.family && v.family !== "NA" && v.family !== "Other"
                ? `<span style="display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;background:hsl(var(--muted));color:hsl(var(--muted-foreground));margin-left:4px;">${escapeHtml(v.family)}</span>`
                : ""
            let html = `<div style="margin:16px 0;border:1px solid hsl(var(--border));border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06);">`
            html += `<div style="padding:10px 14px;background:hsl(var(--accent));border-bottom:1px solid hsl(var(--border));display:flex;align-items:center;gap:4px;flex-wrap:wrap;"><span style="font-size:15px;font-weight:700;color:hsl(var(--primary));">${escapeHtml(v.gene)}</span>${tierBadge}${familyBadge}</div>`

            // Drug details tables
            const drugDetails: any[] = v.drug_details || []
            const grouped: Record<string, any[]> = {}
            for (const d of drugDetails) {
                if (!d.name || d.name === "NA") continue
                if (!grouped[d.tier]) grouped[d.tier] = []
                grouped[d.tier].push(d)
            }
            for (const tier of ["T1","T2","T3","T4","T5"]) {
                const drugs = grouped[tier]
                if (!drugs?.length) continue
                const tLabel = TIER_LABELS_EXP[tier] ?? tier
                const hBg = TIER_BADGE_BG[tier] ?? "#f3f4f6"
                const hFg = TIER_BADGE_COLOR[tier] ?? "#374151"
                html += `<div style="padding:10px 14px;">`
                html += `<div style="display:inline-block;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:600;background:${hBg};color:${hFg};margin-bottom:6px;">${tier} · ${escapeHtml(tLabel)}</div>`
                html += `<table style="width:100%;border-collapse:collapse;border:1px solid hsl(var(--border));border-radius:6px;overflow:hidden;">`
                html += `<thead><tr><th style="${thS}">Name</th><th style="${thS}">Database</th><th style="${thS}">Indication</th></tr></thead><tbody>`
                drugs.forEach((d, i) => {
                    const rowBg = i % 2 === 0 ? rowEven : rowOdd
                    const dbLinks = (d.databases || []).map((db: any) => db.url ? `<a href="${escapeHtml(db.url)}" style="color:hsl(var(--primary));text-decoration:none;">${escapeHtml(db.name)}</a>` : escapeHtml(db.name)).join(", ") || "—"
                    const indLink = d.indication ? (d.indication.url ? `<a href="${escapeHtml(d.indication.url)}" style="color:hsl(var(--primary));text-decoration:none;">${escapeHtml(d.indication.name)}</a>` : escapeHtml(d.indication.name)) : "—"
                    html += `<tr style="${rowBg}"><td style="${tdS}font-weight:500;">${escapeHtml(d.name)}</td><td style="${tdS}">${dbLinks}</td><td style="${tdS}">${indLink}</td></tr>`
                })
                html += `</tbody></table></div>`
            }

            // Presence matrix
            if (v.features?.length && v.cohorts?.length && v.presence?.length) {
                html += `<div style="padding:10px 14px;border-top:1px solid hsl(var(--border));overflow-x:auto;">`
                html += `<div style="font-size:11px;font-weight:600;color:hsl(var(--muted-foreground));margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em;">Omics Presence</div>`
                html += `<table style="border-collapse:collapse;font-size:11px;">`
                html += `<thead><tr><th style="${thS}min-width:160px;"></th>${(v.cohorts as string[]).map((c: string) => `<th style="${thS}text-align:center;min-width:36px;">${escapeHtml(c)}</th>`).join("")}</tr></thead><tbody>`
                for (let ri = 0; ri < v.features.length; ri++) {
                    const feat = v.features[ri]
                    if (feat.parent_field) continue
                    const rowBg = ri % 2 === 0 ? rowEven : rowOdd
                    html += `<tr style="${rowBg}"><td style="${tdS}white-space:nowrap;font-weight:500;">${escapeHtml(feat.label)}</td>`
                    for (let ci = 0; ci < v.cohorts.length; ci++) {
                        const present = v.presence[ri]?.[ci]
                        html += `<td style="${tdCS}background:${present ? "hsl(var(--primary))" : "transparent"};color:${present ? "hsl(var(--primary-foreground))" : "hsl(var(--border))"};">${present ? "✓" : "·"}</td>`
                    }
                    html += `</tr>`
                }
                html += `</tbody></table></div>`
            }
            html += `</div>`
            return html
        }

        const targetSearchTableHtml = (viz: AnyVisualization): string => {
            if (viz.type !== "target_search_table") return ""
            const v = viz as any
            const genes: any[] = v.genes || []
            if (!genes.length) return ""
            const hasLoScore = genes.some((g: any) => g.lo_score != null)
            let html = `<div style="margin:16px 0;border:1px solid hsl(var(--border));border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06);">`
            html += `<div style="padding:10px 14px;background:hsl(var(--muted));border-bottom:2px solid hsl(var(--border));font-weight:700;font-size:13px;color:hsl(var(--foreground));">${escapeHtml(v.title || "Target search results")}</div>`
            html += `<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;">`
            html += `<thead><tr>`
            html += `<th style="${thS}">Gene</th>`
            html += `<th style="${thS}">Tier</th>`
            html += `<th style="${thS}">Family</th>`
            html += `<th style="${thS}">Drugs</th>`
            html += `<th style="${thS}">Antigen</th>`
            if (hasLoScore) html += `<th style="${thS}text-align:center;">Evidence Score</th>`
            html += `<th style="${thS}text-align:center;">${escapeHtml(v.score_label || "Score")}</th>`
            html += `</tr></thead><tbody>`
            genes.forEach((g, i) => {
                const rowBg = i % 2 === 0 ? rowEven : rowOdd
                const tb = g.tier && g.tier !== "NA" ? TIER_BADGE_BG[g.tier] ?? "#f3f4f6" : ""
                const tf = g.tier && g.tier !== "NA" ? TIER_BADGE_COLOR[g.tier] ?? "#374151" : ""
                const tierCell = g.tier && g.tier !== "NA"
                    ? `<span style="display:inline-block;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:600;background:${tb};color:${tf};">${g.tier} · ${TIER_LABELS_EXP[g.tier] ?? g.tier}</span>`
                    : "—"
                html += `<tr style="${rowBg}">`
                html += `<td style="${tdS}font-weight:600;color:hsl(var(--primary));">${escapeHtml(g.gene)}</td>`
                html += `<td style="${tdS}">${tierCell}</td>`
                html += `<td style="${tdS}">${escapeHtml(g.family || "—")}</td>`
                html += `<td style="${tdS}max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(g.drugs || "")}">${escapeHtml(g.drugs || "—")}</td>`
                html += `<td style="${tdCS}">${escapeHtml(g.antigen || "—")}</td>`
                if (hasLoScore) html += `<td style="${tdCS}font-variant-numeric:tabular-nums;">${g.lo_score ?? "—"}</td>`
                html += `<td style="${tdCS}font-variant-numeric:tabular-nums;font-weight:600;">${g.count ?? "—"}</td>`
                html += `</tr>`
            })
            html += `</tbody></table></div>`
            if (v.description) html += `<div style="padding:8px 14px;font-size:11px;color:hsl(var(--muted-foreground));border-top:1px solid hsl(var(--border));background:hsl(var(--muted));">${escapeHtml(v.description)}</div>`
            html += `</div>`
            return html
        }

        const predictiveResultsTableHtml = (viz: AnyVisualization): string => {
            if (viz.type !== "predictive_results_table") return ""
            const v = viz as any
            const rows: any[] = v.rows || []
            if (!rows.length) return ""
            let html = `<div style="margin:16px 0;border:1px solid hsl(var(--border));border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06);">`
            html += `<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;">`
            html += `<thead><tr>`
            html += `<th style="${thS}">#</th>`
            html += `<th style="${thS}">${escapeHtml(v.row_label || "Item")}</th>`
            html += `<th style="${thS}">Studies</th>`
            html += `<th style="${thS}">Avg AUROC</th>`
            html += `<th style="${thS}">Meta-FDR</th>`
            html += `<th style="${thS}">Direction</th>`
            html += `</tr></thead><tbody>`
            rows.forEach((row, i) => {
                const rowBg = i % 2 === 0 ? rowEven : rowOdd
                const dir = row.direction === "sensitive"
                    ? `<span style="color:#0f766e;font-weight:600;">↑ Sensitive</span>`
                    : row.direction === "resistant"
                    ? `<span style="color:#e11d48;font-weight:600;">↓ Resistant</span>`
                    : "—"
                html += `<tr style="${rowBg}">`
                html += `<td style="${tdCS}font-variant-numeric:tabular-nums;">${row.rank ?? "—"}</td>`
                html += `<td style="${tdS}font-weight:600;color:hsl(var(--foreground));">${escapeHtml(row.label || "—")}</td>`
                html += `<td style="${tdCS}font-variant-numeric:tabular-nums;">${row.studies ?? "—"}</td>`
                html += `<td style="${tdCS}font-variant-numeric:tabular-nums;">${row.avg_auroc ?? "—"}</td>`
                html += `<td style="${tdCS}font-variant-numeric:tabular-nums;">${escapeHtml(row.meta_fdr_sci || "—")}</td>`
                html += `<td style="${tdS}white-space:nowrap;">${dir}</td>`
                html += `</tr>`
            })
            html += `</tbody></table></div>`
            if (v.description) html += `<div style="padding:8px 14px;font-size:11px;color:hsl(var(--muted-foreground));border-top:1px solid hsl(var(--border));background:hsl(var(--muted));">${escapeHtml(v.description)}</div>`
            html += `</div>`
            return html
        }

        const vizHtml = (viz: AnyVisualization): string => {
            if (viz.type === "static_plot") return plotImgHtml(viz)
            if (viz.type === "drug_target_grid") return drugTargetGridHtml(viz)
            if (viz.type === "target_search_table") return targetSearchTableHtml(viz)
            if (viz.type === "predictive_results_table") return predictiveResultsTableHtml(viz)
            return ""
        }

        // Split content on inline visualization markers for export HTML rendering.
        const PLOT_RE = /^\[PLOT:([^\]]+)\]$/
        const NETWORK_RE = /^\[NETWORK:([^\]]+)\]$/
        const TABLE_RE = /^\[TABLE:([^\]]+)\]$/
        const inlinedIds = new Set<string>()
        const contentSegments: string[] = []
        let textBuf: string[] = []
        for (const line of (msg.content || "").split("\n")) {
            const trimmed = line.trim()
            const plotMatch = trimmed.match(PLOT_RE)
            const networkMatch = trimmed.match(NETWORK_RE)
            const tableMatch = trimmed.match(TABLE_RE)
            const markerMatch = plotMatch || networkMatch || tableMatch
            if (markerMatch) {
                if (textBuf.length) {
                    try { contentSegments.push(await renderMarkdownForExport(textBuf.join("\n"), msg.toolSources)) }
                    catch { contentSegments.push(`<div class="export-markdown">${escapeHtml(textBuf.join("\n")).replace(/\n/g, "<br>")}</div>`) }
                    textBuf = []
                }
                inlinedIds.add(markerMatch[1])
                contentSegments.push(vizMap[markerMatch[1]] ? vizHtml(vizMap[markerMatch[1]]) : "")
            } else {
                textBuf.push(line)
            }
        }
        if (textBuf.length) {
            try { contentSegments.push(await renderMarkdownForExport(textBuf.join("\n"), msg.toolSources)) }
            catch { contentSegments.push(`<div class="export-markdown">${escapeHtml(textBuf.join("\n")).replace(/\n/g, "<br>")}</div>`) }
        }
        const textContent = contentSegments.join("\n")

        // Trailing plots not referenced inline
        const trailingVizHtml = (msg.visualizations || [])
            .filter(v => !inlinedIds.has(v.id))
            .map(vizHtml)
            .join("\n")

        // Summary rendered as formatted markdown at the bottom
        let summaryHtml = ""
        if (msg.summary && msg.summary.trim() && msg.summary !== msg.content) {
            let renderedSummary = ""
            try { renderedSummary = await renderMarkdownForExport(msg.summary, msg.toolSources) }
            catch { renderedSummary = `<div class="export-markdown">${escapeHtml(msg.summary).replace(/\n/g, "<br>")}</div>` }
            summaryHtml = `<div style="margin-top:16px;padding-top:16px;border-top:1px solid #e5e7eb;"><div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:12px;"><div style="font-size:11px;font-weight:600;color:#888;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.05em;">Summary</div>${renderedSummary}</div></div>`
        }

        const sources = msg.toolSources
            ? Object.entries(msg.toolSources)
                .map(([key, url]) => {
                    const source = INLINE_SOURCE_MAP[key]
                    if (!source) return null  // skip internal tool keys, same as chat UI
                    return {
                        label: source.label,
                        url: (url as string) || source.url || "",
                    }
                })
                .filter((source): source is { label: string; url: string } => source != null && !!source.url)
            : resolveDataSources(msg.toolsUsed || [])

        const uniqueSources = sources.filter((source, index, arr) =>
            arr.findIndex((candidate) => candidate.label === source.label && candidate.url === source.url) === index
        )

        const sourcesHtml = uniqueSources.length > 0
            ? `<p style="font-size:12px;color:#888;margin-top:12px;">Sources: ${uniqueSources.map((source) => `<a href="${source.url}" target="_blank">${escapeHtml(source.label)}</a>`).join(" &middot; ")}</p>`
            : ""

        messageParts.push(
            `<div class="message assistant">` +
            `<strong>LinkedOmicsChat</strong><br><br>` +
            textContent +
            trailingVizHtml +
            summaryHtml +
            sourcesHtml +
            (msg.timestamp ? `<div class="timestamp">${msg.timestamp.toLocaleString()}</div>` : "") +
            `</div>`
        )
    }

    const exportDate = now.toLocaleString()
    const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>LinkedOmicsChat Session Export</title>

  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.38/dist/katex.min.css">
  <style>
    body { font-family: Inter, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; background: #f9fafb; }
    .message { margin: 16px 0; padding: 16px; border-radius: 8px; }
    .user { background: #5f958b; color: white; margin-left: 20%; }
    .assistant { background: white; border: 1px solid #e5e7eb; }
    .timestamp { font-size: 11px; opacity: 0.6; margin-top: 8px; }
    h1 { color: #5f958b; border-bottom: 2px solid #5f958b; padding-bottom: 8px; }
    .export-markdown { color: #111827; line-height: 1.65; }
    .export-markdown > :first-child { margin-top: 0; }
    .export-markdown > :last-child { margin-bottom: 0; }
    .export-markdown h1, .export-markdown h2, .export-markdown h3, .export-markdown h4 { color: #0f172a; margin: 1.25em 0 0.65em; }
    .export-markdown p, .export-markdown ul, .export-markdown ol, .export-markdown blockquote, .export-markdown pre, .export-markdown table { margin: 0 0 1em; }
    .export-markdown ul, .export-markdown ol { padding-left: 1.5rem; }
    .export-markdown a { color: #0f766e; }
    .export-markdown blockquote { border-left: 4px solid #cbd5e1; margin-left: 0; padding: 0.25rem 0 0.25rem 1rem; color: #475569; background: #f8fafc; }
    .export-markdown pre { background: #0f172a; color: #e2e8f0; padding: 12px; border-radius: 8px; overflow-x: auto; }
    .export-markdown code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    .export-markdown :not(pre) > code { background: #f1f5f9; color: #0f172a; padding: 0.15rem 0.35rem; border-radius: 4px; }
    .export-markdown table { width: 100%; border-collapse: collapse; display: block; overflow-x: auto; background: white; }
    .export-markdown thead { background: #f8fafc; }
    .export-markdown th, .export-markdown td { border: 1px solid #dbe4ee; padding: 10px 12px; text-align: left; vertical-align: top; }
    .export-markdown th { font-weight: 600; color: #0f172a; }
    .export-markdown tbody tr:nth-child(even) { background: #fcfdff; }
    .export-markdown hr { border: 0; border-top: 1px solid #e5e7eb; margin: 1.25rem 0; }
    .export-image { max-width: 100%; height: auto; border-radius: 8px; border: 1px solid #e5e7eb; }
  </style>
</head>
<body>
  <h1>LinkedOmicsChat Session Export</h1>
  <p style="color:#666">Exported on ${exportDate}</p>
  ${messageParts.join("\n")}
</body>
</html>`

    const blob = new Blob([html], { type: "text/html;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `linkedomicschat-session-${date}-${time}.html`
    a.click()
    URL.revokeObjectURL(url)
}

const ShareSessionControl = memo(function ShareSessionControl({
    sessionId,
    isGuest,
}: {
    sessionId: string | null
    isGuest: boolean
}) {
    const [shareDialogOpen, setShareDialogOpen] = useState(false)
    const [shareUrl, setShareUrl] = useState("")
    const [shareCopied, setShareCopied] = useState(false)
    const [isSharing, setIsSharing] = useState(false)
    const [shareError, setShareError] = useState<string | null>(null)
    const [shareSessionId, setShareSessionId] = useState<string | null>(null)
    const shareInputRef = useRef<HTMLInputElement>(null)
    const shareRequestIdRef = useRef(0)

    useEffect(() => {
        if (!shareDialogOpen || !shareUrl) return
        shareInputRef.current?.focus()
        shareInputRef.current?.select()
    }, [shareDialogOpen, shareUrl])

    useEffect(() => {
        shareRequestIdRef.current += 1
        setShareDialogOpen(false)
        setShareUrl("")
        setShareCopied(false)
        setIsSharing(false)
        setShareError(null)
        setShareSessionId(null)
    }, [sessionId])

    const handleCopyShareLink = useCallback(async () => {
        if (!shareUrl) return
        try {
            await navigator.clipboard.writeText(shareUrl)
            setShareCopied(true)
            setTimeout(() => setShareCopied(false), 2000)
        } catch (error) {
            console.error("Failed to copy share link:", error)
            shareInputRef.current?.focus()
            shareInputRef.current?.select()
        }
    }, [shareUrl])

    const handleShare = useCallback(() => {
        if (!sessionId || isGuest || isSharing) return
        if (shareUrl && shareSessionId === sessionId) {
            flushSync(() => {
                setShareCopied(false)
                setShareError(null)
                setShareDialogOpen(true)
            })
            return
        }

        const requestId = shareRequestIdRef.current + 1
        shareRequestIdRef.current = requestId

        flushSync(() => {
            setShareDialogOpen(true)
            setShareUrl("")
            setShareCopied(false)
            setShareError(null)
            setIsSharing(true)
            setShareSessionId(null)
        })

        requestAnimationFrame(() => {
            void (async () => {
                try {
                    const data = await chatAPI.shareSession(sessionId)
                    if (shareRequestIdRef.current !== requestId) return

                    const url = `${window.location.origin}/shared/${data.shared_token}`
                    setShareUrl(url)
                    setShareSessionId(sessionId)

                    let copied = false
                    try {
                        await navigator.clipboard.writeText(url)
                        copied = true
                    } catch {
                        // Clipboard unavailable (non-HTTPS) — allow manual copy from the dialog
                    }

                    if (shareRequestIdRef.current !== requestId) return
                    setShareCopied(copied)
                    if (copied) {
                        setTimeout(() => setShareCopied(false), 2000)
                    }
                } catch (e) {
                    if (shareRequestIdRef.current !== requestId) return
                    setShareError("Failed to generate share link.")
                } finally {
                    if (shareRequestIdRef.current === requestId) {
                        setIsSharing(false)
                    }
                }
            })()
        })
    }, [sessionId, isGuest, isSharing, shareUrl, shareSessionId])

    return (
        <>
            <Button
                variant="outline"
                size="sm"
                onClick={handleShare}
                className="gap-2"
                title="Copy shareable link"
                disabled={!sessionId || isSharing}
            >
                {isSharing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Share2 className="w-4 h-4" />}
                {isSharing ? "Sharing..." : "Share"}
            </Button>

            <AlertDialog open={shareDialogOpen} onOpenChange={setShareDialogOpen}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Share Session</AlertDialogTitle>
                        <AlertDialogDescription>
                            {shareError ? shareError : isSharing || !shareUrl ? "Generating share link..." : "Copy this share link:"}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <div className="space-y-3">
                        <Input
                            ref={shareInputRef}
                            value={shareUrl}
                            placeholder={shareError ? "Unable to generate share link" : "Generating share link..."}
                            readOnly
                            onFocus={(event) => event.target.select()}
                            className="font-mono text-xs sm:text-sm"
                        />
                        <p className="text-xs text-muted-foreground">
                            Anyone with this link can open a read-only version of this session.
                        </p>
                    </div>
                    <AlertDialogFooter>
                        <Button variant="outline" onClick={() => setShareDialogOpen(false)}>
                            Close
                        </Button>
                        <Button onClick={handleCopyShareLink} className="gap-2" disabled={!shareUrl || isSharing}>
                            {isSharing ? <Loader2 className="w-4 h-4 animate-spin" /> : shareCopied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                            {isSharing ? "Preparing..." : shareCopied ? "Copied" : "Copy link"}
                        </Button>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    )
})

const ExportSessionControl = memo(function ExportSessionControl({
    sessionId,
}: {
    sessionId: string | null
}) {
    const [isExporting, setIsExporting] = useState(false)

    const handleExport = useCallback(async () => {
        if (!sessionId || isExporting) return
        try {
            setIsExporting(true)
            const messages = await fetchExportMessages(sessionId)
            await downloadSessionExport(messages)
        } catch (error) {
            console.error("Failed to export session:", error)
            alert("Failed to export session.")
        } finally {
            setIsExporting(false)
        }
    }, [sessionId, isExporting])

    return (
        <Button
            variant="outline"
            size="sm"
            onClick={handleExport}
            className="gap-2"
            title="Export session"
            disabled={!sessionId || isExporting}
        >
            {isExporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            {isExporting ? "Exporting..." : "Export"}
        </Button>
    )
})

interface ChatInterfaceProps {
    sessionId: string | null
    onSessionChange: (sessionId: string) => void
    onContextUpdate?: (ctx: import("@/components/RightPanel").RightPanelContext) => void
    initialQuery?: string | null
    onInitialQueryConsumed?: () => void
    pendingSearchTarget?: { sessionId: string; messageId: number; requestKey: string } | null
    onSearchTargetHandled?: (requestKey: string) => void
    focusKey?: number
}

function extractMarkdownImages(markdown: string): string[] {
    if (!markdown) return []
    const matches = Array.from(markdown.matchAll(/!\[[^\]]*\]\(([^)]+)\)/g))
    const urls = matches.map((m) => (m[1] || "").trim()).filter(Boolean)
    const seen = new Set<string>()
    const out: string[] = []
    for (const u of urls) {
        if (!seen.has(u)) {
            seen.add(u)
            out.push(u)
        }
    }
    return out
}

export const ChatInterface = memo(function ChatInterface({
    sessionId,
    onSessionChange,
    onContextUpdate,
    initialQuery,
    onInitialQueryConsumed,
    pendingSearchTarget,
    onSearchTargetHandled,
    focusKey,
}: ChatInterfaceProps) {
    const { isGuest } = useAuth()
    const [messages, setMessages] = useState<ChatMessage[]>([])
    const [input, setInput] = useState("")
    const inputRef = useRef("")
    const chatInputRef = useRef<HTMLInputElement>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [streamStatus, setStreamStatus] = useState<string | null>(null)
    const [isHistoryLoading, setIsHistoryLoading] = useState(false)
    const [isLoadingMoreHistory, setIsLoadingMoreHistory] = useState(false)
    const [hasMoreHistory, setHasMoreHistory] = useState(false)
    const [historyCursor, setHistoryCursor] = useState<number | null>(null)
    const [expandedKeys, setExpandedKeys] = useState<Record<string, boolean>>({})
    const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
    const [editingTurnId, setEditingTurnId] = useState<number | null>(null)
    const [editDraft, setEditDraft] = useState("")
    const [isTruncating, setIsTruncating] = useState(false)
    const [showScrollButton, setShowScrollButton] = useState(false)
    const [jumpHighlightTurnId, setJumpHighlightTurnId] = useState<number | null>(null)
    // In-session search
    const [searchOpen, setSearchOpen] = useState(false)
    const [searchTerm, setSearchTerm] = useState("")
    const [searchMatchIndex, setSearchMatchIndex] = useState(0)
    const searchInputRef = useRef<HTMLInputElement>(null)
    const messageRefs = useRef<(HTMLDivElement | null)[]>([])
    const scrollAreaRootRef = useRef<any>(null)
    const lastUserQueryRef = useRef<string>("")
    const historyLoadTokenRef = useRef(0)
    const adoptedSessionIdRef = useRef<string | null>(null)
    const activeSearchJumpKeyRef = useRef<string | null>(null)
    const jumpHighlightTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const [suggestions] = useState([
        "Show me expression data for NFAT1 and CERS2",
        "Compare survival for TP53 and BRCA1 across cancers",
        "Find clinical trials for EGFR in lung cancer",
        "Help me prioritize KRAS and PIK3CA as therapeutic targets",
    ])
    const showSessionActions = !isGuest && !!sessionId

    useEffect(() => {
        if (!pendingSearchTarget) {
            activeSearchJumpKeyRef.current = null
        }
    }, [pendingSearchTarget])

    useEffect(() => {
        return () => {
            if (jumpHighlightTimeoutRef.current) {
                clearTimeout(jumpHighlightTimeoutRef.current)
            }
        }
    }, [])

    const handleCopy = useCallback(async (content: string, index: number) => {
        try {
            await navigator.clipboard.writeText(content)
            setCopiedIndex(index)
            setTimeout(() => setCopiedIndex(null), 2000)
        } catch (error) {
            console.error("Failed to copy:", error)
        }
    }, [])

    // Initialize welcome message on client side only to avoid hydration mismatch
    useEffect(() => {
        setMessages([
            {
                role: "assistant",
                content: "Hello! I'm LinkedOmicsChat, your AI research assistant for multi-omics analysis. Ask me anything about gene expression, correlations, survival analysis, or help finding relevant datasets.",
                timestamp: new Date(),
            },
        ])
    }, [])

    // Reset messages when session changes
    useEffect(() => {
        historyLoadTokenRef.current += 1
        setExpandedKeys({})
        setHasMoreHistory(false)
        setHistoryCursor(null)
        setJumpHighlightTurnId(null)
        if (jumpHighlightTimeoutRef.current) {
            clearTimeout(jumpHighlightTimeoutRef.current)
            jumpHighlightTimeoutRef.current = null
        }
        setSearchOpen(false)
        setSearchTerm("")
        setSearchMatchIndex(0)
        setEditingTurnId(null)
        setEditDraft("")
        setIsTruncating(false)
        if (!sessionId) {
            adoptedSessionIdRef.current = null
            // New chat - show welcome message and create session
            setMessages([
                {
                    role: "assistant",
                    content: "Hello! I'm LinkedOmicsChat, your AI research assistant for multi-omics analysis. Ask me anything about gene expression, correlations, survival analysis, or help finding relevant datasets.",
                    timestamp: new Date(),
                },
            ])
            // Create a new session immediately so it appears in sidebar
            createNewSession()
        } else if (!isGuest) {
            if (adoptedSessionIdRef.current === sessionId) {
                adoptedSessionIdRef.current = null
                return
            }
            setMessages([])
            setIsHistoryLoading(true)
            // Load session history (guests have no persistent history)
            loadSessionHistory(sessionId)
        }
    }, [sessionId, isGuest])

    // Focus input when the Chat nav item is clicked
    useEffect(() => {
        if (focusKey !== undefined) chatInputRef.current?.focus()
    }, [focusKey])

    // Pre-fill input when launched from Use Cases panel
    useEffect(() => {
        if (initialQuery) {
            inputRef.current = initialQuery
            setInput(initialQuery)
            onInitialQueryConsumed?.()
        }
    }, [initialQuery])

    // Reset match index when search term changes
    useEffect(() => { setSearchMatchIndex(0) }, [searchTerm])

    const createNewSession = async () => {
        try {
            // Make a dummy request to create the session
            // The backend will create a session when we send our first real message
            // For now, we'll let it happen naturally with the first message
        } catch (error) {
            console.error("Failed to create session:", error)
        }
    }

    const loadSessionHistory = async (sid: string) => {
        const token = historyLoadTokenRef.current
        try {
            setIsHistoryLoading(true)
            // Load only the newest chunk for fast initial render
            const data = await chatAPI.getSessionHistory(sid, { limit: 10 })
            if (token !== historyLoadTokenRef.current) return
            const history = Array.isArray((data as any)?.history) ? (data as any).history : []
            const loadedMessages: ChatMessage[] = []

            for (const item of history) {
                loadedMessages.push(...mapHistoryItemToMessages(item as any))
            }

            setHasMoreHistory(!!(data as any)?.has_more)
            setHistoryCursor(((data as any)?.next_before as number | null) ?? null)

            const finalMessages = loadedMessages.length > 0
                ? loadedMessages
                : [
                    {
                        role: "assistant" as const,
                        content: "Hello! I'm LinkedOmicsChat, your AI research assistant for multi-omics analysis.",
                        timestamp: new Date(),
                    },
                ]
            setMessages(finalMessages)
        } catch (error) {
            console.error("Failed to load session history:", error)
            if (token !== historyLoadTokenRef.current) return
            setMessages([
                {
                    role: "assistant",
                    content:
                        "I couldn't load this chat history. Please refresh and try again.\n\n" +
                        (error instanceof Error ? `Error: ${error.message}` : ""),
                    timestamp: new Date(),
                },
            ])
        } finally {
            if (token === historyLoadTokenRef.current) {
                setIsHistoryLoading(false)
            }
        }
    }

    useEffect(() => {
        const target = pendingSearchTarget
        if (!target || !sessionId || target.sessionId !== sessionId || isGuest || isHistoryLoading) {
            return
        }
        if (activeSearchJumpKeyRef.current === target.requestKey) {
            return
        }

        activeSearchJumpKeyRef.current = target.requestKey
        let cancelled = false
        const historyToken = historyLoadTokenRef.current

        const waitForPaint = () =>
            new Promise<void>((resolve) => {
                requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
            })

        const run = async () => {
            let workingMessages = messages
            let cursor = historyCursor
            let more = hasMoreHistory
            let changed = false

            while (!workingMessages.some((message) => message.turnId === target.messageId) && more && cursor != null) {
                const data = await chatAPI.getSessionHistory(sessionId, { limit: 50, before: cursor })
                if (cancelled || historyToken !== historyLoadTokenRef.current) return

                const history = Array.isArray((data as any)?.history) ? (data as any).history : []
                if (history.length === 0) {
                    more = false
                    cursor = null
                    break
                }

                const older: ChatMessage[] = []
                for (const item of history) {
                    older.push(...mapHistoryItemToMessages(item as any))
                }

                workingMessages = [...older, ...workingMessages]
                more = !!(data as any)?.has_more
                cursor = ((data as any)?.next_before as number | null) ?? null
                changed = true
            }

            if (cancelled || historyToken !== historyLoadTokenRef.current) return

            if (changed) {
                setHasMoreHistory(more)
                setHistoryCursor(cursor)
                flushSync(() => setMessages(workingMessages))
                await waitForPaint()
            }

            const turnIndex = workingMessages.findIndex((message) => message.turnId === target.messageId)
            if (turnIndex === -1) {
                onSearchTargetHandled?.(target.requestKey)
                return
            }

            const assistantIndex = workingMessages.findIndex(
                (message) => message.role === "assistant" && message.turnId === target.messageId
            )
            if (assistantIndex !== -1) {
                const assistantMessage = workingMessages[assistantIndex]
                const assistantKey =
                    `${assistantMessage.role}-` +
                    `${assistantMessage.timestamp?.getTime?.() ?? "no-ts"}-` +
                    `${assistantIndex}`

                setExpandedKeys((prev) => ({ ...prev, [assistantKey]: true }))
                await waitForPaint()

                const needsHydration =
                    assistantMessage.sourceMessageId &&
                    (
                        !assistantMessage.hasFullContent ||
                        (
                            assistantMessage.hasVisualizations === true &&
                            (!assistantMessage.visualizations || assistantMessage.visualizations.length === 0)
                        )
                    )

                if (needsHydration) {
                    try {
                        const full = await chatAPI.getChatMessage(assistantMessage.sourceMessageId!)
                        if (cancelled || historyToken !== historyLoadTokenRef.current) return

                        const resp = full?.response
                        const fullMessage =
                            typeof resp === "string" ? resp : resp?.message || ""
                        const fullSummary =
                            typeof resp === "string" ? undefined : (resp?.summary as string | undefined)
                        const fullPapers =
                            typeof resp === "string"
                                ? undefined
                                : (resp?.papers || resp?.metadata?.papers || undefined)
                        const fullAnalyses =
                            typeof resp === "string" ? undefined : ((resp?.analyses || undefined) as AnalysisResult[] | undefined)
                        const fullVisualizations = stripVizBinary(
                            typeof resp === "string" ? undefined : (resp?.visualizations || undefined)
                        )

                        if (fullMessage || fullVisualizations) {
                            workingMessages = workingMessages.map((message, index) =>
                                index !== assistantIndex
                                    ? message
                                    : {
                                        ...message,
                                        ...(fullMessage ? { content: fullMessage } : {}),
                                        summary: fullSummary ?? message.summary,
                                        papers: fullPapers,
                                        analyses: fullAnalyses,
                                        clarificationOptions: resp?.clarification_options?.length ? resp.clarification_options : message.clarificationOptions,
                                        noCollapse: resp?.no_collapse === true ? true : message.noCollapse,
                                        isGeneralKnowledge: resp?.is_general_knowledge === true ? true : message.isGeneralKnowledge,
                                        confidence: resp?.confidence ?? message.confidence,
                                        executionTrace: Array.isArray(resp?.execution_trace) && resp.execution_trace.length > 0
                                            ? resp.execution_trace
                                            : message.executionTrace,
                                        ...(fullVisualizations ? { visualizations: fullVisualizations } : {}),
                                        hasFullContent: true,
                                        wasPreview: true,
                                    }
                            )

                            flushSync(() => setMessages(workingMessages))
                            await waitForPaint()
                        }
                    } catch (error) {
                        console.error("Failed to hydrate search target message:", error)
                    }
                }
            }

            if (jumpHighlightTimeoutRef.current) {
                clearTimeout(jumpHighlightTimeoutRef.current)
            }
            setJumpHighlightTurnId(target.messageId)
            messageRefs.current[turnIndex]?.scrollIntoView({ behavior: "smooth", block: "center" })
            jumpHighlightTimeoutRef.current = setTimeout(() => {
                setJumpHighlightTurnId((current) => current === target.messageId ? null : current)
            }, 2500)

            onSearchTargetHandled?.(target.requestKey)
        }

        void run()

        return () => {
            cancelled = true
        }
    }, [
        pendingSearchTarget,
        sessionId,
        isGuest,
        isHistoryLoading,
        messages,
        historyCursor,
        hasMoreHistory,
        onSearchTargetHandled,
    ])

    const getViewport = useCallback((): HTMLElement | null => {
        const root = scrollAreaRootRef.current as HTMLElement | null
        if (!root) return null
        return root.querySelector("[data-radix-scroll-area-viewport]") as HTMLElement | null
    }, [])

    const scrollToBottom = useCallback(() => {
        const vp = getViewport()
        if (!vp) return
        vp.scrollTop = vp.scrollHeight
    }, [getViewport])

    // Scroll to bottom after history finishes loading.
    // Observes the scroll *content* element (first child of viewport) with ResizeObserver
    // for 2 seconds so lazy messages and images that expand after initial render re-trigger scroll.
    const prevHistoryLoadingRef = useRef(false)
    useEffect(() => {
        if (prevHistoryLoadingRef.current && !isHistoryLoading) {
            requestAnimationFrame(() => requestAnimationFrame(() => {
                scrollToBottom()
                const vp = getViewport()
                if (!vp) return
                // The scroll content div is the direct child of the viewport
                const content = vp.firstElementChild as HTMLElement | null
                if (!content) return
                const deadline = Date.now() + 2000
                const ro = new ResizeObserver(() => {
                    if (Date.now() > deadline) { ro.disconnect(); return }
                    scrollToBottom()
                })
                ro.observe(content)
                setTimeout(() => ro.disconnect(), 2000)
            }))
        }
        prevHistoryLoadingRef.current = isHistoryLoading
    }, [isHistoryLoading, scrollToBottom, getViewport])

    // Load ALL remaining history pages at once (used when opening in-session search)
    const loadAllHistory = useCallback(async () => {
        if (!sessionId || isGuest) return
        let cursor = historyCursor
        let more = hasMoreHistory
        if (!more || cursor == null) return

        const allOlder: ChatMessage[] = []
        while (more && cursor != null) {
            try {
                const data = await chatAPI.getSessionHistory(sessionId, { limit: 50, before: cursor })
                const history = Array.isArray((data as any)?.history) ? (data as any).history : []
                if (history.length === 0) break
                for (const item of history) {
                    allOlder.push(...mapHistoryItemToMessages(item as any))
                }
                more = !!(data as any)?.has_more
                cursor = ((data as any)?.next_before as number | null) ?? null
            } catch { break }
        }

        if (allOlder.length > 0) {
            setHasMoreHistory(false)
            setHistoryCursor(null)
            startTransition(() => setMessages(prev => [...allOlder, ...prev]))
        }
    }, [sessionId, isGuest, historyCursor, hasMoreHistory])

    const openSearch = useCallback(() => {
        setSearchOpen(true)
        loadAllHistory()
        setTimeout(() => searchInputRef.current?.focus(), 50)
    }, [loadAllHistory])

    // Cmd+F / Ctrl+F → open in-session search
    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "f") {
                e.preventDefault()
                openSearch()
            }
            if (e.key === "Escape" && searchOpen) {
                setSearchOpen(false)
                setSearchTerm("")
            }
        }
        window.addEventListener("keydown", handler)
        return () => window.removeEventListener("keydown", handler)
    }, [searchOpen, openSearch])

    const loadMoreHistory = useCallback(async () => {
        if (!sessionId) return
        if (!hasMoreHistory) return
        if (isHistoryLoading || isLoadingMoreHistory) return
        if (historyCursor == null) return

        const vp = getViewport()
        const prevHeight = vp?.scrollHeight ?? 0
        const prevTop = vp?.scrollTop ?? 0

        try {
            setIsLoadingMoreHistory(true)
            const data = await chatAPI.getSessionHistory(sessionId, {
                limit: 10,
                before: historyCursor,
            })
            const history = Array.isArray((data as any)?.history) ? (data as any).history : []
            if (history.length === 0) {
                setHasMoreHistory(false)
                return
            }

            const older: ChatMessage[] = []
            for (const item of history) {
                older.push(...mapHistoryItemToMessages(item as any))
            }

            // Batch state updates to prevent multiple re-renders
            const hasMore = !!(data as any)?.has_more
            const nextBefore = ((data as any)?.next_before as number | null) ?? null

            setHasMoreHistory(hasMore)
            setHistoryCursor(nextBefore)

            // Use startTransition to make the update non-blocking
            startTransition(() => {
                setMessages((prev) => [...older, ...prev])
            })

            // Preserve scroll position after prepending
            requestAnimationFrame(() => {
                const vp2 = getViewport()
                if (!vp2) return
                const newHeight = vp2.scrollHeight
                vp2.scrollTop = newHeight - prevHeight + prevTop
            })
        } catch (e) {
            console.error("Failed to load more history:", e)
        } finally {
            setIsLoadingMoreHistory(false)
        }
    }, [sessionId, hasMoreHistory, isHistoryLoading, isLoadingMoreHistory, historyCursor, getViewport])

    const toggleExpand = useCallback(
        async (key: string) => {
            // If we're expanding, and this message is a lazy placeholder, fetch full content first.
            const isExpanding = !expandedKeys[key]
            if (isExpanding) {
                const idx = messages.findIndex((m, i) => {
                    const k = `${m.role}-${m.timestamp?.getTime?.() ?? "no-ts"}-${i}`
                    return k === key
                })
                const msg = idx >= 0 ? messages[idx] : null
                const needsHydration =
                    msg?.role === "assistant" &&
                    msg.sourceMessageId &&
                    (
                        !msg.hasFullContent ||
                        (msg.hasVisualizations === true && (!msg.visualizations || msg.visualizations.length === 0))
                    )

                if (needsHydration) {
                    try {
                        const sourceMessageId = msg.sourceMessageId!
                        const full = await chatAPI.getChatMessage(sourceMessageId)
                        const resp = full?.response
                        const fullMessage =
                            typeof resp === "string" ? resp : resp?.message || ""
                        const fullSummary =
                            typeof resp === "string" ? undefined : (resp?.summary as string | undefined)
                        const fullPapers =
                            typeof resp === "string"
                                ? undefined
                                : (resp?.papers || resp?.metadata?.papers || undefined)
                        const fullAnalyses =
                            typeof resp === "string" ? undefined : ((resp?.analyses || undefined) as AnalysisResult[] | undefined)
                        const fullVisualizations = stripVizBinary(
                            typeof resp === "string" ? undefined : (resp?.visualizations || undefined)
                        )

                        if (fullMessage || fullVisualizations) {
                            setMessages((prev) => {
                                const next = [...prev]
                                const current = next[idx]
                                if (!current) return prev
                                next[idx] = {
                                    ...current,
                                    ...(fullMessage ? { content: fullMessage } : {}),
                                    summary: fullSummary ?? current.summary,
                                    papers: fullPapers,
                                    analyses: fullAnalyses,
                                    clarificationOptions: resp?.clarification_options?.length ? resp.clarification_options : current.clarificationOptions,
                                    noCollapse: resp?.no_collapse === true ? true : current.noCollapse,
                                    isGeneralKnowledge: resp?.is_general_knowledge === true ? true : current.isGeneralKnowledge,
                                    confidence: resp?.confidence ?? current.confidence,
                                    executionTrace: Array.isArray(resp?.execution_trace) && resp.execution_trace.length > 0
                                        ? resp.execution_trace
                                        : current.executionTrace,
                                    ...(fullVisualizations ? { visualizations: fullVisualizations } : {}),
                                    hasFullContent: true,
                                    wasPreview: true,
                                }
                                return next
                            })
                        }
                    } catch (e) {
                        console.error("Failed to fetch full message:", e)
                    }
                }
            }

            setExpandedKeys((prev) => ({ ...prev, [key]: !prev[key] }))
        },
        [expandedKeys, messages]
    )

    // Push lightweight “context” to the parent for the right panel.
    useEffect(() => {
        if (!onContextUpdate) return
        const reversedMessages = [...messages].reverse()
        const lastAssistant = reversedMessages.find((m) => m.role === "assistant")

        // Collect images from all loaded messages (newest first)
        const allImages: string[] = []
        const seenImages = new Set<string>()
        let hiddenCount = 0

        for (const m of reversedMessages) {
            if (m.role !== "assistant") continue

            const imgs = m.content ? extractMarkdownImages(m.content) : []
            if (imgs.length > 0) {
                for (const img of imgs) {
                    if (!seenImages.has(img)) {
                        seenImages.add(img)
                        allImages.push(img)
                    }
                }
            } else if (m.hasImages) {
                // If backend says it has images, but we found none in content,
                // it means they are hidden (sanitized history).
                hiddenCount++
            }
        }

        // Collect all Plotly visualizations across all messages (newest first), tagged with messageKey
        const allVisualizations: Array<AnyVisualization & { messageKey: string }> = []
        messages.forEach((m, index) => {
            if (m.role !== "assistant") return
            if (!m.visualizations || m.visualizations.length === 0) return
            const key = `${m.role}-${m.timestamp?.getTime?.() ?? index}-${index}`
            m.visualizations.forEach(viz => allVisualizations.push({ ...viz, messageKey: key }))
        })
        // Oldest first — matches chat message flow

        const text = lastAssistant?.content || ""
        onContextUpdate({
            lastAssistantText: text,
            lastAssistantImages: allImages,
            lastAssistantPapers: lastAssistant?.papers,
            lastAssistantAnalyses: lastAssistant?.analyses,
            hiddenImagesCount: hiddenCount,
            allVisualizations: allVisualizations.length > 0 ? allVisualizations : undefined,
            onNavigateToViz: (messageKey: string) => {
                const el = document.getElementById(messageKey)
                el?.scrollIntoView({ behavior: "smooth", block: "center" })
            },
        })
    }, [messages, onContextUpdate])

    const sendMessageText = useCallback(async (messageText: string) => {
        if (!messageText || isLoading) {
            return
        }

        lastUserQueryRef.current = messageText

        const userMessage: ChatMessage = {
            role: "user",
            content: messageText,
            timestamp: new Date(),
        }

        setMessages((prev) => [...prev, userMessage])
        inputRef.current = ""
        setInput("")
        setIsLoading(true)
        setStreamStatus("Initializing...")

        // Scroll to the user's new message before waiting for the assistant's response
        requestAnimationFrame(() => scrollToBottom())

        // Unique marker so we can find and replace the streaming placeholder
        const STREAM_PLACEHOLDER = "__streaming__"

        try {
            const response = await chatAPI.streamMessage(
                {
                    message: messageText,
                    session_id: sessionId || undefined,
                },
                (status) => {
                    setStreamStatus(status)
                },
                (delta) => {
                    // Append text deltas to a streaming placeholder message
                    setMessages((prev) => {
                        const last = prev[prev.length - 1]
                        if (last?.role === "assistant" && last.content === STREAM_PLACEHOLDER) {
                            // First delta — replace the sentinel with actual text
                            return [...prev.slice(0, -1), { ...last, content: delta }]
                        }
                        if (last?.role === "assistant" && last.turnId === undefined && !last.isGeneralKnowledge) {
                            // Subsequent deltas — accumulate
                            return [...prev.slice(0, -1), { ...last, content: last.content + delta }]
                        }
                        // No placeholder yet — create one
                        return [...prev, { role: "assistant", content: delta, timestamp: new Date() }]
                    })
                    requestAnimationFrame(() => scrollToBottom())
                },
                (delta) => {
                    // Append summary deltas — populates the summary box incrementally
                    setMessages((prev) => {
                        const last = prev[prev.length - 1]
                        if (last?.role === "assistant" && last.turnId === undefined && !last.isGeneralKnowledge) {
                            const current = last.summary || ""
                            return [...prev.slice(0, -1), { ...last, summary: current + delta }]
                        }
                        return prev
                    })
                    requestAnimationFrame(() => scrollToBottom())
                }
            )

            if (response.session_id && response.session_id !== sessionId) {
                adoptedSessionIdRef.current = response.session_id
                onSessionChange(response.session_id)
            }

            // Extract papers from metadata
            const papers = response.metadata?.papers as Paper[] || []

            // Extract analyses from response - ensure proper typing
            const analyses = (response.analyses || []) as AnalysisResult[]

            // Debug logging
            console.log("Received response:", {
                messageLength: response.message?.length || 0,
                analysesCount: analyses.length,
                hasAnalyses: analyses.length > 0,
                tools_used: response.tools_used,
            })

            if (analyses.length > 0) {
                const firstAnalysis = analyses[0]
                console.log("First analysis details:", {
                    type: firstAnalysis.analysis_type,
                    has_upregulated: !!firstAnalysis.top_upregulated,
                    upregulated_count: firstAnalysis.top_upregulated?.length || 0,
                    has_downregulated: !!firstAnalysis.top_downregulated,
                    downregulated_count: firstAnalysis.top_downregulated?.length || 0,
                    total_results: firstAnalysis.total_results,
                    significant_results: firstAnalysis.significant_results
                })

                // Log first upregulated gene if available
                if (firstAnalysis.top_upregulated && firstAnalysis.top_upregulated.length > 0) {
                    console.log("First upregulated gene:", firstAnalysis.top_upregulated[0])
                }
            }

            const assistantMessage: ChatMessage = {
                role: "assistant",
                content: response.message || ((response.tools_used?.length ?? 0) > 0 ? `Tools executed: ${response.tools_used!.map(t => t.replace("::", " › ")).join(", ")}. No summary was generated — the tool may have returned no data.` : "I've processed your request."),
                summary: response.summary || undefined,
                turnId: response.turn_id,
                sourceMessageId: response.turn_id,
                timestamp: new Date(),
                papers: papers.length > 0 ? papers : undefined,
                analyses: analyses.length > 0 ? analyses : undefined,
                suggestions: response.suggestions?.length ? response.suggestions : undefined,
                clarificationOptions: response.clarification_options?.length ? response.clarification_options : undefined,
                toolSources: response.tool_sources && Object.keys(response.tool_sources).length ? response.tool_sources : undefined,
                toolsUsed: response.tools_used?.length ? response.tools_used : undefined,
                noCollapse: response.no_collapse === true,
                isGeneralKnowledge: response.is_general_knowledge === true,
                confidence: response.confidence,
                visualizations: (response.visualizations || []) as unknown as AnyVisualization[],
                executionTrace: response.execution_trace?.length ? response.execution_trace : undefined,
            }

            setMessages((prev) => {
                const next = [...prev]
                if (response.turn_id != null) {
                    for (let i = next.length - 1; i >= 0; i -= 1) {
                        const candidate = next[i]
                        if (candidate.role === "user" && candidate.turnId == null) {
                            next[i] = { ...candidate, turnId: response.turn_id }
                            break
                        }
                    }
                }
                // Replace streaming placeholder (if any) with the fully-formatted message
                const lastIdx = next.length - 1
                if (lastIdx >= 0 && next[lastIdx].role === "assistant" && next[lastIdx].turnId == null) {
                    next[lastIdx] = assistantMessage
                } else {
                    next.push(assistantMessage)
                }
                return next
            })
        } catch (error) {
            console.error("Error sending message:", error)

            // Determine the error message based on error type
            let errorContent = "I apologize, but I encountered an error processing your request."

            if (axios.isAxiosError(error)) {
                if (error.code === 'ECONNREFUSED' || error.code === 'ERR_NETWORK' || !error.response) {
                    errorContent = "Unable to connect to the backend server. Please make sure the backend is running on " + API_URL + ". You can start it by running `./start_backend.sh` or `python backend/main.py`."
                } else if (error.response) {
                    // Server responded with error status
                    const status = error.response.status
                    const detail = error.response.data?.detail || error.response.data?.error || error.message
                    errorContent = `Server error (${status}): ${detail}. Please try again.`
                } else if (error.request) {
                    // Request was made but no response received
                    errorContent = "The request was sent but no response was received. The backend may be taking too long to respond or may be unavailable."
                } else {
                    errorContent = `Request error: ${error.message}. Please try again.`
                }
            } else if (error instanceof Error) {
                errorContent = `Error: ${error.message}. Please try again.`
            } else {
                errorContent = `An unexpected error occurred: ${String(error)}. Please try again.`
            }

            const errorMessage: ChatMessage = {
                role: "assistant",
                content: errorContent,
                timestamp: new Date(),
                isError: true,
            }
            setMessages((prev) => [...prev, errorMessage])
        } finally {
            setIsLoading(false)
            setStreamStatus(null)
        }
    }, [isLoading, sessionId, scrollToBottom, onSessionChange])

    const handleSend = useCallback(async (textOverride?: string | any) => {
        // Workaround for browser automation: check DOM value if React state is empty
        let messageText = typeof textOverride === "string" ? textOverride : inputRef.current.trim()
        if (!messageText) {
            const inputElement = chatInputRef.current
            if (inputElement && inputElement.value.trim()) {
                messageText = inputElement.value.trim()
                if (typeof textOverride !== "string") {
                    inputRef.current = messageText
                    setInput(messageText) // Update React state
                }
            }
        }

        if (!messageText) {
            return
        }

        await sendMessageText(messageText)
    }, [sendMessageText])

    const handleStartEdit = useCallback((message: ChatMessage) => {
        if (message.turnId == null || isGuest || isLoading || isTruncating) return
        setEditingTurnId(message.turnId)
        setEditDraft(message.content)
    }, [isGuest, isLoading, isTruncating])

    const handleCancelEdit = useCallback(() => {
        if (isTruncating) return
        setEditingTurnId(null)
        setEditDraft("")
    }, [isTruncating])

    const handleRequestResubmitEdit = useCallback(async () => {
        if (editingTurnId == null || !sessionId) return
        const nextText = editDraft.trim()
        if (!nextText) return

        const cutoffIndex = messages.findIndex(
            (message) => message.role === "user" && message.turnId === editingTurnId
        )
        if (cutoffIndex === -1) {
            window.alert("I couldn't find that message in the current chat anymore. Please refresh and try again.")
            return
        }

        try {
            setIsTruncating(true)
            await chatAPI.truncateSessionFromMessage(sessionId, editingTurnId)

            flushSync(() => {
                setMessages((prev) => prev.slice(0, cutoffIndex))
                setEditingTurnId(null)
                setEditDraft("")
                setExpandedKeys({})
            })

            setIsTruncating(false)
            await sendMessageText(nextText)
        } catch (error) {
            console.error("Failed to send edited message:", error)
            const detail =
                axios.isAxiosError(error)
                    ? error.response?.data?.detail || error.message
                    : error instanceof Error
                    ? error.message
                    : String(error)
            window.alert(`Failed to send the edited message: ${detail}`)
            setIsTruncating(false)
        }
    }, [editDraft, editingTurnId, messages, sendMessageText, sessionId])

    const handleSuggestionClick = useCallback((suggestion: string) => {
        inputRef.current = suggestion
        setInput(suggestion)
    }, [])

    // Scroll detection for showing/hiding scroll-to-bottom button
    useEffect(() => {
        const scrollArea = scrollAreaRootRef.current
        if (!scrollArea) return

        const handleScroll = () => {
            const viewport = scrollArea.querySelector('[data-radix-scroll-area-viewport]')
            if (!viewport) return

            const { scrollTop, scrollHeight, clientHeight } = viewport
            const isNearBottom = scrollHeight - scrollTop - clientHeight < 200
            setShowScrollButton(!isNearBottom && messages.length > 1)
        }

        const viewport = scrollArea.querySelector('[data-radix-scroll-area-viewport]')
        if (viewport) {
            viewport.addEventListener('scroll', handleScroll)
            handleScroll() // Initial check
            return () => viewport.removeEventListener('scroll', handleScroll)
        }
    }, [messages.length])

    // In-session search helpers
    const searchMatchIndices = useMemo(() => {
        if (!searchTerm.trim()) return []
        const lower = searchTerm.toLowerCase()
        return messages
            .map((m, i) => ({ i, text: (m.content + " " + (m.summary || "")).toLowerCase() }))
            .filter(({ text }) => text.includes(lower))
            .map(({ i }) => i)
    }, [searchTerm, messages])

    const navigateSearch = useCallback((dir: 1 | -1) => {
        if (!searchMatchIndices.length) return
        const next = (searchMatchIndex + dir + searchMatchIndices.length) % searchMatchIndices.length
        setSearchMatchIndex(next)
        const msgIndex = searchMatchIndices[next]
        messageRefs.current[msgIndex]?.scrollIntoView({ behavior: "smooth", block: "center" })
    }, [searchMatchIndices, searchMatchIndex])

    // Auto-scroll to first match when results first appear
    useEffect(() => {
        if (searchMatchIndices.length > 0) {
            messageRefs.current[searchMatchIndices[0]]?.scrollIntoView({ behavior: "smooth", block: "center" })
        }
    }, [searchMatchIndices])

    // Scroll to bottom handler
    const scrollToBottomSmooth = () => {
        const scrollArea = scrollAreaRootRef.current
        if (!scrollArea) return

        const viewport = scrollArea.querySelector('[data-radix-scroll-area-viewport]')
        if (viewport) {
            viewport.scrollTo({
                top: viewport.scrollHeight,
                behavior: 'smooth'
            })
        }
    }

    return (
        <div className="h-full flex flex-col bg-background">
            {/* Header */}
            <div className="border-b border-border px-4 py-3 md:px-6 md:py-4 flex items-center justify-between gap-3">
                {searchOpen ? (
                    <div className="flex items-center gap-2 flex-1 pr-10 md:pr-12">
                        <Search className="w-4 h-4 text-muted-foreground shrink-0" />
                        <input
                            ref={searchInputRef}
                            value={searchTerm}
                            onChange={e => setSearchTerm(e.target.value)}
                            onKeyDown={e => {
                                if (e.key === "Enter") navigateSearch(e.shiftKey ? -1 : 1)
                                if (e.key === "Escape") { setSearchOpen(false); setSearchTerm("") }
                            }}
                            placeholder="Search in this chat…"
                            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                        />
                        {searchTerm && (
                            <span className="text-xs text-muted-foreground shrink-0">
                                {searchMatchIndices.length === 0 ? "No matches" : `${searchMatchIndex + 1} / ${searchMatchIndices.length}`}
                            </span>
                        )}
                        <button onClick={() => navigateSearch(-1)} disabled={!searchMatchIndices.length} className="p-1 hover:bg-muted rounded disabled:opacity-30"><ChevronUp className="w-4 h-4" /></button>
                        <button onClick={() => navigateSearch(1)} disabled={!searchMatchIndices.length} className="p-1 hover:bg-muted rounded disabled:opacity-30"><ChevronDown className="w-4 h-4" /></button>
                        <button onClick={() => { setSearchOpen(false); setSearchTerm("") }} className="p-1 hover:bg-muted rounded mr-1"><X className="w-4 h-4" /></button>
                    </div>
                ) : (
                    <>
                        <div className="flex-1 min-w-0">
                            <h2 className="text-lg md:text-2xl font-semibold">Research Assistant</h2>
                            <p className="hidden sm:block text-sm text-muted-foreground mt-1">
                                Query cancer multi-omics data across CPTAC, LinkedOmics, and PubMed
                            </p>
                        </div>
                        <div className="flex items-center gap-2 shrink-0 pr-10 md:pr-12">
                            {messages.length > 1 && (
                                <Button variant="ghost" size="sm" onClick={openSearch} title="Search in this chat (⌘F)">
                                    <Search className="w-4 h-4" />
                                </Button>
                            )}
                            {showSessionActions && (
                                <ShareSessionControl sessionId={sessionId} isGuest={isGuest} />
                            )}
                            {showSessionActions && (
                                <ExportSessionControl sessionId={sessionId} />
                            )}
                        </div>
                    </>
                )}
            </div>

            {/* Messages */}
            <MessagesPane
                messages={messages}
                isGuest={isGuest}
                isLoading={isLoading}
                isHistoryLoading={isHistoryLoading}
                isLoadingMoreHistory={isLoadingMoreHistory}
                hasMoreHistory={hasMoreHistory}
                onLoadMoreHistory={loadMoreHistory}
                scrollAreaRootRef={scrollAreaRootRef}
                expandedKeys={expandedKeys}
                onToggleExpand={toggleExpand}
                copiedIndex={copiedIndex}
                onCopy={handleCopy}
                editingTurnId={editingTurnId}
                editDraft={editDraft}
                onStartEdit={handleStartEdit}
                onCancelEdit={handleCancelEdit}
                onChangeEditDraft={setEditDraft}
                onRequestResubmitEdit={handleRequestResubmitEdit}
                isEditingBusy={isLoading || isTruncating}
                onSend={handleSend}
                lastUserQuery={lastUserQueryRef.current}
                streamStatus={streamStatus}
                searchTerm={searchTerm}
                searchMatchIndices={searchMatchIndices}
                searchMatchIndex={searchMatchIndex}
                jumpHighlightTurnId={jumpHighlightTurnId}
                messageRefs={messageRefs}
            />

            {/* Suggestions */}
            {messages.length === 1 && !isLoading && (
                <div className="px-4 pb-4 md:px-6">
                    <div className="max-w-4xl mx-auto">
                        <p className="text-sm text-muted-foreground mb-3">Try asking:</p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {suggestions.map((suggestion, index) => (
                                <button
                                    key={index}
                                    onClick={() => handleSuggestionClick(suggestion)}
                                    className="text-left text-sm p-3 rounded-lg border border-border hover:bg-accent hover:border-primary transition-all"
                                >
                                    {suggestion}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* Input */}
            <div className="border-t border-border p-3 md:p-6">
                <div className="max-w-4xl mx-auto flex gap-2 relative">
                    <Input
                        ref={chatInputRef}
                        placeholder="Ask about genes, expression, survival, drug targets, trials, pathways, networks, or literature..."
                        value={input}
                        onChange={(e) => { setInput(e.target.value); inputRef.current = e.target.value }}
                        onKeyPress={(e) => e.key === "Enter" && handleSend()}
                        disabled={isLoading || isTruncating}
                        className="flex-1"
                    />
                    <Button onClick={handleSend} disabled={isLoading || isTruncating || !input.trim()}>
                        {isLoading || isTruncating ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                            <Send className="w-4 h-4" />
                        )}
                    </Button>

                    {/* Scroll to Bottom Button - Right side of center panel */}
                    {showScrollButton && (
                        <button
                            onClick={scrollToBottomSmooth}
                            className="absolute -top-16 right-0 bg-primary text-primary-foreground rounded-full p-3 shadow-lg hover:shadow-xl transition-all hover:scale-110 z-50"
                            title="Scroll to bottom"
                        >
                            <svg
                                xmlns="http://www.w3.org/2000/svg"
                                width="20"
                                height="20"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                            >
                                <path d="M12 5v14" />
                                <path d="m19 12-7 7-7-7" />
                            </svg>
                        </button>
                    )}
                </div>
            </div>
        </div>
    )
})
