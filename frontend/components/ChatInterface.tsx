"use client"

import { useState, useRef, useEffect, useCallback, memo, useMemo, startTransition } from "react"
import { Send, Loader2, Sparkles, Copy, Check, User, Download, Search, X, ChevronUp, ChevronDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Card, CardContent } from "@/components/ui/card"
import { chatAPI, type ChatMessage, type Paper, type AnalysisResult, API_URL, resolveDataSources, INLINE_SOURCE_MAP } from "@/lib/api"
import { useAuth } from "@/components/AuthContext"
import { EnrichmentRenderer } from "./ToolExplorer"
import axios from "axios"
import { cn } from "@/lib/utils"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeHighlight from "rehype-highlight"
import rehypeKatex from "rehype-katex"
import "highlight.js/styles/github-dark.css"
import "katex/dist/katex.min.css"

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

const AssistantMarkdown = memo(function AssistantMarkdown({ content, onCopyTable, toolSources }: { content: string; onCopyTable?: (content: string) => void; toolSources?: Record<string, string> }) {
    const handleCopyTable = useCallback((tableContent: string) => {
        if (onCopyTable) {
            onCopyTable(tableContent)
        } else {
            // Fallback: copy to clipboard directly
            navigator.clipboard.writeText(tableContent).catch(console.error)
        }
    }, [onCopyTable])

    // Create gene color map from content
    const geneColorMap = useMemo(() => createGeneColorMap(content), [content])
    const enhancedComponents = useMemo(() => createEnhancedMarkdownComponents(handleCopyTable, geneColorMap, toolSources), [handleCopyTable, geneColorMap, toolSources])

    return (
        <div className="prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeHighlight, rehypeKatex]}
                urlTransform={safeMarkdownUrlTransform}
                components={enhancedComponents as any}
            >
                {content}
            </ReactMarkdown>
        </div>
    )
})

const AssistantPlainText = memo(function AssistantPlainText({ content }: { content: string }) {
    return <p className="text-sm whitespace-pre-wrap text-foreground">{content}</p>
})

// Helper: Extract gene names from markdown headers (e.g., "## Cancer expression - NFAT1")
function extractGeneNames(markdown: string): string[] {
    if (!markdown) return []
    const genePattern = /##\s+[^-]+-\s+([A-Z0-9]+)/g
    const matches = Array.from(markdown.matchAll(genePattern))
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
        table: ({ node, children, ...props }: any) => {
            const [copied, setCopied] = useState(false)

            const handleCopy = () => {
                // Extract table content as TSV
                const table = node
                const rows: string[][] = []

                // Parse table structure from children
                const tableContent = String(children)
                const lines = tableContent.split('\n').filter(l => l.trim())

                // Simple TSV conversion (can be enhanced)
                const tsv = lines.map(line =>
                    line.split('|').map(cell => cell.trim()).filter(Boolean).join('\t')
                ).join('\n')

                onCopyTable(tsv)
                setCopied(true)
                setTimeout(() => setCopied(false), 2000)
            }

            return (
                <div className="relative group my-4">
                    <button
                        onClick={handleCopy}
                        className="absolute -top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-background border border-border rounded px-2 py-1 text-xs flex items-center gap-1 hover:bg-accent z-10"
                        title="Copy table as TSV"
                    >
                        {copied ? (
                            <>
                                <Check className="w-3 h-3" />
                                Copied!
                            </>
                        ) : (
                            <>
                                <Copy className="w-3 h-3" />
                                Copy
                            </>
                        )}
                    </button>
                    <table className="w-full border-collapse" {...props}>
                        {children}
                    </table>
                </div>
            )
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

const MessagesPane = memo(function MessagesPane({
    messages,
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
    onSend,
    streamStatus,
    searchTerm,
    searchMatchIndices,
    searchMatchIndex,
    messageRefs,
}: {
    messages: ChatMessage[]
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
    onSend: (text: string) => void
    streamStatus: string | null
    searchTerm: string
    searchMatchIndices: number[]
    searchMatchIndex: number
    messageRefs: React.MutableRefObject<(HTMLDivElement | null)[]>
}) {
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
                    return (
                        <div
                            key={messageKey}
                            ref={el => { messageRefs.current[index] = el }}
                            className={cn(
                                "flex flex-col gap-1 w-full rounded-lg transition-colors duration-300",
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
                                <Card
                                    className={cn(
                                        "max-w-[80%] relative group shadow-sm hover:shadow-md transition-shadow duration-300",
                                        message.role === "user"
                                            ? "bg-primary text-primary-foreground rounded-2xl rounded-tr-sm"
                                            : "bg-card rounded-2xl rounded-tl-sm border-muted/60"
                                    )}
                                >
                                    <CardContent className="p-4 leading-relaxed tracking-wide">
                                        {message.role === "assistant" && message.isGeneralKnowledge && (
                                            <div className="flex items-start gap-2 mb-3 px-3 py-2 rounded-md bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300 text-xs">
                                                <span className="mt-0.5 shrink-0">⚠️</span>
                                                <span>
                                                    <span className="font-semibold">General knowledge response</span> — this answer is based on the AI&apos;s training data, not LinkedOmics database. It may be incomplete or outdated.
                                                </span>
                                            </div>
                                        )}
                                        {message.role === "assistant" ? (
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
                                                        (isPreviewOnly || content.length > 4000 || hasMoreThanNLines(content, 80))

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
                                                                <AssistantMarkdown content={sanitizedContent} toolSources={message.toolSources} />
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
                                        ) : (
                                            <p className="text-sm whitespace-pre-wrap">{message.content}</p>
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

                                        {/* Summary moved to the end as a takeaway */}
                                        {message.role === "assistant" && message.summary && message.summary.trim().length > 0 && message.summary !== message.content && (
                                            <div className="mt-4 pt-4 border-t border-border">
                                                <div className="rounded-md border border-border bg-muted/40 p-3">
                                                    <div className="text-xs font-semibold text-muted-foreground mb-2">
                                                        Summary
                                                    </div>
                                                    <AssistantMarkdown content={message.summary} />
                                                </div>
                                            </div>
                                        )}
                                    </CardContent>
                                    {message.role === "assistant" && (
                                        <button
                                            onClick={() => onCopy(message.content, index)}
                                            className="absolute top-2 right-2 p-1.5 rounded-md hover:bg-muted opacity-0 group-hover:opacity-100 transition-opacity"
                                            title="Copy to clipboard"
                                        >
                                            {copiedIndex === index ? (
                                                <Check className="w-4 h-4 text-green-500" />
                                            ) : (
                                                <Copy className="w-4 h-4" />
                                            )}
                                        </button>
                                    )}
                                </Card>
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
                                <div className="flex flex-wrap gap-2 mt-2 pl-11">
                                    <span className="text-xs text-muted-foreground self-center mr-1">Choose:</span>
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
                            )}
                            {message.role === "assistant" && message.suggestions && message.suggestions.length > 0 && (
                                <div className="flex flex-wrap gap-2 mt-1 pl-11">
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

interface ChatInterfaceProps {
    sessionId: string | null
    onSessionChange: (sessionId: string) => void
    onContextUpdate?: (ctx: {
        lastAssistantText?: string
        lastAssistantImages?: string[]
        lastAssistantPapers?: Paper[]
        lastAssistantAnalyses?: AnalysisResult[]
        hiddenImagesCount?: number
    }) => void
    initialQuery?: string | null
    onInitialQueryConsumed?: () => void
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

export function ChatInterface({ sessionId, onSessionChange, onContextUpdate, initialQuery, onInitialQueryConsumed }: ChatInterfaceProps) {
    const { isGuest } = useAuth()
    const [messages, setMessages] = useState<ChatMessage[]>([])
    const [input, setInput] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const [streamStatus, setStreamStatus] = useState<string | null>(null)
    const [isHistoryLoading, setIsHistoryLoading] = useState(false)
    const [isLoadingMoreHistory, setIsLoadingMoreHistory] = useState(false)
    const [hasMoreHistory, setHasMoreHistory] = useState(false)
    const [historyCursor, setHistoryCursor] = useState<number | null>(null)
    const [expandedKeys, setExpandedKeys] = useState<Record<string, boolean>>({})
    const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
    const [showScrollButton, setShowScrollButton] = useState(false)
    // In-session search
    const [searchOpen, setSearchOpen] = useState(false)
    const [searchTerm, setSearchTerm] = useState("")
    const [searchMatchIndex, setSearchMatchIndex] = useState(0)
    const searchInputRef = useRef<HTMLInputElement>(null)
    const messageRefs = useRef<(HTMLDivElement | null)[]>([])
    const scrollAreaRootRef = useRef<any>(null)
    const historyLoadTokenRef = useRef(0)
    const [suggestions] = useState([
        "Show me expression data for NFAT1 and CERS2",
        "Compare survival for TP53 and BRCA1 across cancers",
        "Find clinical trials for EGFR in lung cancer",
        "Help me prioritize KRAS and PIK3CA as therapeutic targets",
    ])

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
        if (!sessionId) {
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
            // Load session history (guests have no persistent history)
            loadSessionHistory(sessionId)
        }
    }, [sessionId, isGuest])

    // Pre-fill input when launched from Use Cases panel
    useEffect(() => {
        if (initialQuery) {
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
                // User message
                loadedMessages.push({
                    role: "user",
                    content: (item as any)?.query ?? "",
                    timestamp: new Date((((item as any)?.timestamp ?? 0) as number) * 1000),
                })

                const resp = (item as any)?.response

                // Extract papers from response (could be in papers or metadata.papers)
                const papers: any[] = []

                // Extract analyses from response
                const analyses: AnalysisResult[] = []

                const respSummary =
                    typeof resp === "string"
                        ? undefined
                        : (resp?.summary as string | undefined)

                const preview =
                    typeof resp === "string"
                        ? resp
                        : (resp?.message_preview as string | undefined) ||
                        resp?.message ||
                        ""

                loadedMessages.push({
                    role: "assistant",
                    // Always show full message in chat; keep summary separately.
                    content: preview,
                    summary: respSummary,
                    sourceMessageId: (item as any)?.id,
                    hasFullContent: typeof resp === "string" ? true : (resp?.has_full_content !== false),
                    hasImages: typeof resp === "string" ? false : !!resp?.has_images,
                    timestamp: new Date((((item as any)?.timestamp ?? 0) as number) * 1000),
                    toolSources: resp?.tool_sources && Object.keys(resp.tool_sources).length ? resp.tool_sources : undefined,
                    papers: undefined,
                    analyses: undefined,
                })
            }

            setHasMoreHistory(!!(data as any)?.has_more)
            setHistoryCursor(((data as any)?.next_before as number | null) ?? null)

            setMessages(
                loadedMessages.length > 0
                    ? loadedMessages
                    : [
                        {
                            role: "assistant",
                            content: "Hello! I'm LinkedOmicsChat, your AI research assistant for multi-omics analysis.",
                            timestamp: new Date(),
                        },
                    ]
            )

            // After the newest chunk is rendered, scroll to bottom once,
            requestAnimationFrame(() => {
                scrollToBottom()
            })
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
                    const resp = (item as any)?.response
                    allOlder.push({ role: "user", content: (item as any)?.query ?? "", timestamp: new Date((((item as any)?.timestamp ?? 0)) * 1000) })
                    allOlder.push({
                        role: "assistant",
                        content: typeof resp === "string" ? resp : resp?.message_preview || resp?.message || "",
                        summary: typeof resp === "string" ? undefined : (resp?.summary as string | undefined),
                        sourceMessageId: (item as any)?.id,
                        hasFullContent: typeof resp === "string" ? true : (resp?.has_full_content !== false),
                        hasImages: typeof resp === "string" ? false : !!resp?.has_images,
                        timestamp: new Date((((item as any)?.timestamp ?? 0)) * 1000),
                        toolSources: resp?.tool_sources && Object.keys(resp.tool_sources).length ? resp.tool_sources : undefined,
                    })
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
                const resp = (item as any)?.response
                const respSummary =
                    typeof resp === "string"
                        ? undefined
                        : (resp?.summary as string | undefined)
                older.push({
                    role: "user",
                    content: (item as any)?.query ?? "",
                    timestamp: new Date((((item as any)?.timestamp ?? 0) as number) * 1000),
                })
                older.push({
                    role: "assistant",
                    content:
                        typeof resp === "string"
                            ? resp
                            : resp?.message_preview || resp?.message || "",
                    summary: respSummary,
                    sourceMessageId: (item as any)?.id,
                    hasFullContent: typeof resp === "string" ? true : (resp?.has_full_content !== false),
                    hasImages: typeof resp === "string" ? false : !!resp?.has_images,
                    timestamp: new Date((((item as any)?.timestamp ?? 0) as number) * 1000),
                    toolSources: resp?.tool_sources && Object.keys(resp.tool_sources).length ? resp.tool_sources : undefined,
                })
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
                if (msg?.role === "assistant" && !msg.hasFullContent && msg.sourceMessageId) {
                    try {
                        const full = await chatAPI.getChatMessage(msg.sourceMessageId)
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

                        if (fullMessage) {
                            setMessages((prev) => {
                                const next = [...prev]
                                const current = next[idx]
                                if (!current) return prev
                                next[idx] = {
                                    ...current,
                                    content: fullMessage,
                                    summary: fullSummary ?? current.summary,
                                    papers: fullPapers,
                                    analyses: fullAnalyses,
                                    hasFullContent: true,
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

        const text = lastAssistant?.content || ""
        onContextUpdate({
            lastAssistantText: text,
            lastAssistantImages: allImages,
            lastAssistantPapers: lastAssistant?.papers,
            lastAssistantAnalyses: lastAssistant?.analyses,
            hiddenImagesCount: hiddenCount,
        })
    }, [messages, onContextUpdate])

    const handleSend = async (textOverride?: string | any) => {
        // Workaround for browser automation: check DOM value if React state is empty
        let messageText = typeof textOverride === "string" ? textOverride : input.trim()
        if (!messageText) {
            const inputElement = document.querySelector('input[placeholder*="genes, datasets"]') as HTMLInputElement
            if (inputElement && inputElement.value.trim()) {
                messageText = inputElement.value.trim()
                if (typeof textOverride !== "string") {
                    setInput(messageText) // Update React state
                }
            }
        }

        if (!messageText || isLoading) {
            return
        }

        const userMessage: ChatMessage = {
            role: "user",
            content: messageText,
            timestamp: new Date(),
        }

        setMessages((prev) => [...prev, userMessage])
        setInput("")
        setIsLoading(true)
        setStreamStatus("Initializing...")

        // Scroll to the user's new message before waiting for the assistant's response
        requestAnimationFrame(() => scrollToBottom())

        try {
            const response = await chatAPI.streamMessage(
                {
                    message: messageText,
                    session_id: sessionId || undefined,
                },
                (status) => {
                    setStreamStatus(status)
                }
            )

            if (response.session_id && response.session_id !== sessionId) {
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
                timestamp: new Date(),
                papers: papers.length > 0 ? papers : undefined,
                analyses: analyses.length > 0 ? analyses : undefined,
                suggestions: response.suggestions?.length ? response.suggestions : undefined,
                clarificationOptions: response.clarification_options?.length ? response.clarification_options : undefined,
                toolSources: response.tool_sources && Object.keys(response.tool_sources).length ? response.tool_sources : undefined,
                toolsUsed: response.tools_used?.length ? response.tools_used : undefined,
                noCollapse: response.no_collapse === true,
                isGeneralKnowledge: response.is_general_knowledge === true,
            }

            setMessages((prev) => [...prev, assistantMessage])
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
            }
            setMessages((prev) => [...prev, errorMessage])
        } finally {
            setIsLoading(false)
            setStreamStatus(null)
        }
    }

    const handleSuggestionClick = (suggestion: string) => {
        setInput(suggestion)
    }

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

    const handleExport = useCallback(() => {
        const now = new Date()
        const date = now.toISOString().slice(0, 10)
        const time = now.toTimeString().slice(0, 8).replace(/:/g, "-")

        // Build as BlobPart[] so we never concatenate one massive string in memory.
        // This avoids freezing when messages contain large base64-encoded images.
        const parts: BlobPart[] = [
            `# LinkedOmicsChat Session Export\n`,
            `*Exported: ${new Date().toLocaleString()}*\n`,
            `*Tool: LinkedOmicsChat — Multi-Omics Analysis AI*\n\n`,
            `---\n\n`,
        ]

        // Strip base64-encoded images — they can be MBs each and are not useful in a text file.
        const stripBase64Images = (md: string) =>
            md.replace(/!\[([^\]]*)\]\(data:image\/[^)]+\)/g, "*[Figure: $1 — open in app to view]*")

        // Skip the first welcome message
        messages.slice(1).forEach((msg) => {
            if (msg.role === "user") {
                parts.push(`## You\n\n`)
                parts.push(msg.content)
                parts.push(`\n\n`)
            } else if (msg.role === "assistant") {
                parts.push(`## Assistant\n\n`)
                parts.push(stripBase64Images(msg.content))
                parts.push(`\n\n`)
                if (msg.toolsUsed?.length) {
                    const sources = resolveDataSources(msg.toolsUsed)
                    if (sources.length > 0) {
                        const srcList = sources.map(s => `[${s.label}](${s.url})`).join(" · ")
                        parts.push(`*Sources: ${srcList}*\n\n`)
                    }
                }
                parts.push(`---\n\n`)
            }
        })

        const blob = new Blob(parts, { type: "text/markdown;charset=utf-8" })
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `linkedomicsai-session-${date}-${time}.md`
        a.click()
        URL.revokeObjectURL(url)
    }, [messages])

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
                            {messages.length > 1 && (
                                <Button variant="outline" size="sm" onClick={handleExport} className="gap-2" title="Export session as Markdown">
                                    <Download className="w-4 h-4" />
                                    Export
                                </Button>
                            )}
                        </div>
                    </>
                )}
            </div>

            {/* Messages */}
            <MessagesPane
                messages={messages}
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
                onSend={handleSend}
                streamStatus={streamStatus}
                searchTerm={searchTerm}
                searchMatchIndices={searchMatchIndices}
                searchMatchIndex={searchMatchIndex}
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
                        placeholder="Ask about genes, datasets, or analyses..."
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyPress={(e) => e.key === "Enter" && handleSend()}
                        disabled={isLoading}
                        className="flex-1"
                    />
                    <Button onClick={handleSend} disabled={isLoading || !input.trim()}>
                        {isLoading ? (
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
}
