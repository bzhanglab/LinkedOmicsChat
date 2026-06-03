"use client"

import { useState, useEffect, useContext, createContext, useCallback } from "react"
import { toolsAPI } from "@/lib/api"
import type { NetworkVisualization } from "@/lib/api"
import { NetworkPlot } from "@/components/NetworkPlot"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
    Beaker,
    Play,
    AlertCircle,
    ArrowLeft,
    Table as TableIcon,
    Code,
    ChevronDown,
    ChevronRight,
    Image as ImageIcon,
    Search,
    Lightbulb,
    BookOpen,
    Zap,
    Package,
    FileText,
    Dna,
    BarChart2,
    HeartPulse,
    Pill,
    Network,
    FlaskConical,
    Library,
    Copy,
    Check,
    ClipboardList,
} from "lucide-react"
import { ToolCategoryGuide, getToolCategoryGuideKeyFromLabel } from "@/components/ToolCategoryGuide"

interface ToolParameter {
    type?: string
    description?: string
    default?: any
    enum?: any[]
    anyOf?: Array<{ type?: string; enum?: any[] }>
}

interface ToolSchema {
    description: string
    inputSchema: {
        type: string
        properties: Record<string, ToolParameter>
        required?: string[]
    }
}

interface ToolExplorerProps {
    className?: string
    resetKey?: number
}

/** Strip markdown syntax for plain-text card previews */
const stripMarkdown = (text: string) =>
    text
        .replace(/\*\*(.+?)\*\*/g, '$1')
        .replace(/\*(.+?)\*/g, '$1')
        .replace(/^#{1,6}\s+/gm, '')
        .replace(/^[-*+]\s+/gm, '')
        .replace(/`(.+?)`/g, '$1')
        .replace(/\n{2,}/g, ' ')
        .trim()

/** Inline-render markdown bold/code/italic within a string */
const InlineText = ({ text }: { text: string }) => {
    // Replace **bold**, `code`, and *italic* with spans
    const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g)
    return (
        <>
            {parts.map((part, i) => {
                if (part.startsWith('**') && part.endsWith('**'))
                    return <strong key={i} className="font-semibold text-gray-900 dark:text-gray-100">{part.slice(2, -2)}</strong>
                if (part.startsWith('`') && part.endsWith('`'))
                    return <code key={i} className="font-mono text-xs bg-teal-50 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300 px-1.5 py-0.5 rounded">{part.slice(1, -1)}</code>
                if (part.startsWith('*') && part.endsWith('*'))
                    return <em key={i} className="italic text-gray-600 dark:text-gray-400">{part.slice(1, -1)}</em>
                return <span key={i}>{part}</span>
            })}
        </>
    )
}

interface ParsedDoc {
    summary: string
    summaryItems: string[]
    whenToUse: string[]
    useCases: string[]
    args: { name: string; type: string; desc: string }[]
    returns: { name: string; type: string; desc: string }[]
    returnsIntro: string
    notes: string[]
}

const appendDocLine = (existing: string, next: string) => (
    existing ? `${existing}\n${next}` : next
)

function parseDocstring(raw: string): ParsedDoc {
    const lines = raw.split('\n')
    const result: ParsedDoc = { summary: '', summaryItems: [], whenToUse: [], useCases: [], args: [], returns: [], returnsIntro: '', notes: [] }

    let section = 'summary'
    const summaryLines: string[] = []
    const summaryItemLines: string[] = []
    let currentArg: { name: string; type: string; desc: string } | null = null
    let currentReturn: { name: string; type: string; desc: string } | null = null
    let currentSummaryItemIndex: number | null = null
    let currentWhenItemIndex: number | null = null
    let currentCaseItemIndex: number | null = null
    let currentNoteItemIndex: number | null = null

    for (const line of lines) {
        const trimmed = line.trim()

        // Detect section headers
        if (/^use this tool when/i.test(trimmed) || /^use when/i.test(trimmed)) { section = 'when'; continue }
        if (/^use cases?:/i.test(trimmed) || /^triggers?:/i.test(trimmed) || /^this tool answers/i.test(trimmed)) { section = 'cases'; continue }
        if (/^args?:/i.test(trimmed) || /^parameters?[:\s-]+$/i.test(trimmed)) { section = 'args'; continue }
        if (/^returns?:/i.test(trimmed)) { section = 'returns'; continue }
        if (/^notes?:/i.test(trimmed) || /^available (omic|cancer|cohort)/i.test(trimmed) || /^cancer cohorts?:/i.test(trimmed) || /^interpretation/i.test(trimmed) || /^best used/i.test(trimmed) || /^example usage/i.test(trimmed) || /^supported query modes/i.test(trimmed)) { section = 'notes'; continue }
        // Skip NumPy-style underline separators (e.g., "----------")
        if (/^[-=]{4,}$/.test(trimmed)) continue

        if (!trimmed) {
            currentSummaryItemIndex = null
            currentWhenItemIndex = null
            currentCaseItemIndex = null
            currentNoteItemIndex = null
            if (section === 'returns' && !currentReturn && result.returnsIntro) {
                result.returnsIntro = appendDocLine(result.returnsIntro, '')
            }
            continue
        }

        if (section === 'summary') {
            if (/^[-*]\s+/.test(trimmed)) {
                summaryItemLines.push(trimmed.replace(/^[-*]\s+/, ''))
                currentSummaryItemIndex = summaryItemLines.length - 1
            } else if (currentSummaryItemIndex !== null) {
                summaryItemLines[currentSummaryItemIndex] += ' ' + trimmed
            } else {
                summaryLines.push(trimmed)
            }
        } else if (section === 'when') {
            const bullet = trimmed.replace(/^[-*]\s*/, '')
            if (/^[-*]\s*/.test(trimmed)) {
                if (bullet) {
                    result.whenToUse.push(bullet)
                    currentWhenItemIndex = result.whenToUse.length - 1
                }
            } else if (currentWhenItemIndex !== null) {
                result.whenToUse[currentWhenItemIndex] += ' ' + trimmed
            } else if (bullet) {
                result.whenToUse.push(bullet)
                currentWhenItemIndex = result.whenToUse.length - 1
            }
        } else if (section === 'cases') {
            const bullet = trimmed.replace(/^[-*"']\s*/, '').replace(/["']$/, '')
            if (/^[-*"']\s*/.test(trimmed)) {
                if (bullet) {
                    result.useCases.push(bullet)
                    currentCaseItemIndex = result.useCases.length - 1
                }
            } else if (currentCaseItemIndex !== null) {
                result.useCases[currentCaseItemIndex] += ' ' + bullet
            } else if (bullet) {
                result.useCases.push(bullet)
                currentCaseItemIndex = result.useCases.length - 1
            }
        } else if (section === 'args') {
            // Standard: `param (type): desc`  or NumPy: `param` on its own line then desc indented
            const argMatch = trimmed.match(/^(\w+)\s*\(([^)]+)\):\s*(.*)/)
            if (argMatch) {
                if (currentArg) result.args.push(currentArg)
                currentArg = { name: argMatch[1], type: argMatch[2], desc: argMatch[3] }
            } else if (currentArg && trimmed) {
                currentArg.desc += ' ' + trimmed
            }
        } else if (section === 'returns') {
            const retMatch = trimmed.match(/^[-*]?\s*["']?(\w+)["']?\s*\(([^)]+)\):\s*(.*)/)
            if (retMatch) {
                if (currentReturn) result.returns.push(currentReturn)
                currentReturn = { name: retMatch[1], type: retMatch[2], desc: retMatch[3] }
            } else if (currentReturn && trimmed.startsWith('-')) {
                currentReturn.desc += ' ' + trimmed.replace(/^-\s*/, '')
            } else if (currentReturn && trimmed) {
                currentReturn.desc += ' ' + trimmed
            } else if (!currentReturn && trimmed) {
                result.returnsIntro = appendDocLine(result.returnsIntro, trimmed)
            }
        } else if (section === 'notes') {
            const bullet = trimmed.replace(/^[-*]\s*/, '')
            if (/^[-*]\s*/.test(trimmed)) {
                if (bullet) {
                    result.notes.push(bullet)
                    currentNoteItemIndex = result.notes.length - 1
                }
            } else if (currentNoteItemIndex !== null) {
                result.notes[currentNoteItemIndex] += ' ' + trimmed
            } else if (bullet) {
                result.notes.push(bullet)
                currentNoteItemIndex = result.notes.length - 1
            }
        }
    }

    if (currentArg) result.args.push(currentArg)
    if (currentReturn) result.returns.push(currentReturn)
    result.summary = summaryLines.join(' ')
    result.summaryItems = summaryItemLines
    return result
}

const ToolDocumentation = ({ description }: { description: string }) => {
    const doc = parseDocstring(description)

    return (
        <div className="space-y-4">
            {/* Summary */}
            {(doc.summary || doc.summaryItems.length > 0) && (
                <div className="bg-gradient-to-r from-teal-50 to-emerald-50 dark:from-teal-900/20 dark:to-emerald-900/20 border border-teal-200 dark:border-teal-800 rounded-xl p-4">
                    <div className="flex items-start gap-3">
                        <div className="mt-0.5 h-7 w-7 rounded-lg bg-teal-100 dark:bg-teal-900/50 flex items-center justify-center flex-shrink-0">
                            <FileText className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                        </div>
                        <div className="flex-1">
                            {doc.summary && (
                                <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
                                    <InlineText text={doc.summary} />
                                </p>
                            )}
                            {doc.summaryItems.length > 0 && (
                                <ul className="mt-2 space-y-1">
                                    {doc.summaryItems.map((item, i) => (
                                        <li key={i} className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300">
                                            <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-teal-500 flex-shrink-0" />
                                            <InlineText text={item} />
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* When to use */}
            {doc.whenToUse.length > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-3">
                        <div className="h-6 w-6 rounded-md bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                            <Lightbulb className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400" />
                        </div>
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-amber-700 dark:text-amber-400">When to use</h4>
                    </div>
                    <ul className="space-y-1.5">
                        {doc.whenToUse.map((item, i) => (
                            <li key={i} className="flex items-start gap-2 text-sm text-gray-600 dark:text-gray-400">
                                <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-amber-400 dark:bg-amber-500 flex-shrink-0" />
                                <InlineText text={item} />
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Use cases */}
            {doc.useCases.length > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-3">
                        <div className="h-6 w-6 rounded-md bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                            <Zap className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
                        </div>
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">Example queries</h4>
                    </div>
                    <ul className="space-y-2">
                        {doc.useCases.map((item, i) => (
                            <li key={i} className="text-sm text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-700/50 rounded-lg px-3 py-2 border-l-2 border-emerald-400 dark:border-emerald-500">
                                <InlineText text={item.replace(/^["']|["']$/g, '')} />
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Args */}
            {doc.args.length > 0 && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-3">
                        <div className="h-6 w-6 rounded-md bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center">
                            <Package className="h-3.5 w-3.5 text-purple-600 dark:text-purple-400" />
                        </div>
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-purple-700 dark:text-purple-400">Parameters</h4>
                    </div>
                    <div className="space-y-3">
                        {doc.args.map((arg, i) => (
                            <div key={i} className="flex items-start gap-3">
                                <div className="flex-shrink-0 mt-0.5">
                                    <code className="text-xs font-mono font-semibold bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 px-2 py-0.5 rounded-md border border-purple-200 dark:border-purple-700">
                                        {arg.name}
                                    </code>
                                </div>
                                <div className="flex-1 min-w-0">
                                    <span className="text-xs text-gray-400 dark:text-gray-500 italic mr-2">{arg.type}</span>
                                    <span className="text-sm text-gray-600 dark:text-gray-400">
                                        <InlineText text={arg.desc} />
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Returns */}
            {(doc.returns.length > 0 || doc.returnsIntro) && (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-3">
                        <div className="h-6 w-6 rounded-md bg-teal-100 dark:bg-teal-900/30 flex items-center justify-center">
                            <BookOpen className="h-3.5 w-3.5 text-teal-600 dark:text-teal-400" />
                        </div>
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-teal-700 dark:text-teal-400">Returns</h4>
                    </div>
                    {doc.returnsIntro && (
                        <p className="text-xs text-gray-400 dark:text-gray-500 mb-3 italic">
                            <InlineText text={doc.returnsIntro} />
                        </p>
                    )}
                    {doc.returns.length > 0 ? (
                        <div className="space-y-2.5">
                            {doc.returns.map((field, i) => (
                                <div key={i} className="flex items-start gap-3">
                                    <div className="flex-shrink-0 mt-0.5">
                                        <code className="text-xs font-mono font-semibold bg-teal-50 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300 px-2 py-0.5 rounded-md border border-teal-200 dark:border-teal-700">
                                            {field.name}
                                        </code>
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <span className="text-xs text-gray-400 dark:text-gray-500 italic mr-2">{field.type}</span>
                                        <span className="text-sm text-gray-600 dark:text-gray-400">
                                            <InlineText text={field.desc} />
                                        </span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : null}
                </div>
            )}

            {/* Notes */}
            {doc.notes.length > 0 && (
                <div className="bg-gray-50 dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-3">
                        <div className="h-6 w-6 rounded-md bg-gray-200 dark:bg-gray-700 flex items-center justify-center">
                            <FileText className="h-3.5 w-3.5 text-gray-500 dark:text-gray-400" />
                        </div>
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Notes</h4>
                    </div>
                    <ul className="space-y-1.5">
                        {doc.notes.map((note, i) => (
                            <li key={i} className="flex items-start gap-2 text-xs text-gray-500 dark:text-gray-400">
                                <span className="mt-1.5 h-1 w-1 rounded-full bg-gray-400 dark:bg-gray-500 flex-shrink-0" />
                                <InlineText text={note} />
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}

const TableRenderer = ({ data, title }: { data: any[], title?: string }) => {
    // ... existing TableRenderer code (unchanged) ...
    if (!data || data.length === 0) return null
    const headers = Object.keys(data[0])

    return (
        <div className="mb-6">
            {title && (
                <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                    <TableIcon className="h-4 w-4" />
                    {title}
                </h5>
            )}
            <div className="overflow-x-auto border border-gray-200 dark:border-gray-700 rounded-lg">
                <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                    <thead className="bg-gray-50 dark:bg-gray-800">
                        <tr>
                            {headers.map((header) => (
                                <th
                                    key={header}
                                    className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
                                >
                                    {header}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                        {data.map((row, i) => (
                            <tr key={i} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                                {headers.map((header) => (
                                    <td
                                        key={`${i}-${header}`}
                                        className="px-3 py-2 text-sm text-gray-900 dark:text-gray-100 whitespace-nowrap"
                                    >
                                        {typeof row[header] === 'object'
                                            ? JSON.stringify(row[header])
                                            : String(row[header])
                                        }
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

const ImageRenderer = ({ data, mimeType }: { data: string, mimeType: string }) => {
    return (
        <div className="mb-4">
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-2 bg-white dark:bg-gray-800 inline-block">
                <img
                    src={`data:${mimeType};base64,${data}`}
                    alt="Tool Output"
                    className="max-w-full h-auto rounded"
                />
            </div>
        </div>
    )
}

/** Renders GO enrichment results from webgestalt as visual cards */
export const EnrichmentRenderer = ({ data }: { data: any[] }) => {
    const maxRatio = Math.max(...data.map(d => d.enrichmentRatio || 0))

    const getFDRColor = (fdr: number) => {
        if (fdr < 0.001) return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300 border-red-200 dark:border-red-700'
        if (fdr < 0.01) return 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300 border-orange-200 dark:border-orange-700'
        if (fdr < 0.05) return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 border-amber-200 dark:border-amber-700'
        return 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400 border-gray-200 dark:border-gray-600'
    }

    const formatNum = (n: number, digits = 2) =>
        n < 0.001 ? n.toExponential(1) : n.toFixed(digits)

    return (
        <div className="space-y-3">
            <ToolCategoryGuide category="pathway-enrichment" compact collapsible defaultExpanded={false} />
            <p className="text-xs text-gray-400 dark:text-gray-500 mb-1">
                {data.length} enriched GO term{data.length !== 1 ? 's' : ''} · sorted by FDR
            </p>
            {data.map((term, i) => {
                const ratio = term.enrichmentRatio || 0
                const barWidth = maxRatio > 0 ? Math.round((ratio / maxRatio) * 100) : 0
                const fdr = parseFloat(term.FDR)
                const goId = term.geneSet?.replace(':', '_')

                return (
                    <div key={i} className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 hover:border-teal-300 dark:hover:border-teal-600 transition-colors">
                        <div className="flex items-start justify-between gap-3 mb-2">
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-xs font-mono text-gray-400 dark:text-gray-500">{term.geneSet}</span>
                                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${getFDRColor(fdr)}`}>
                                        FDR {formatNum(fdr, 3)}
                                    </span>
                                </div>
                                <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mt-1 leading-snug">
                                    {term.description}
                                </h4>
                            </div>
                            {term.link && (
                                <a
                                    href={term.link}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="flex-shrink-0 text-xs text-teal-500 hover:text-teal-600 dark:text-teal-400 underline"
                                >
                                    AmiGO ↗
                                </a>
                            )}
                        </div>

                        {/* Enrichment ratio bar */}
                        <div className="mt-3">
                            <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400 mb-1">
                                <span>Enrichment ratio</span>
                                <span className="font-semibold text-teal-600 dark:text-teal-400">{ratio.toFixed(1)}×</span>
                            </div>
                            <div className="h-2 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                                <div
                                    className="h-full bg-gradient-to-r from-teal-400 to-emerald-500 dark:from-teal-500 dark:to-emerald-400 rounded-full transition-all"
                                    style={{ width: `${barWidth}%` }}
                                />
                            </div>
                        </div>

                        {/* Stats row */}
                        <div className="flex gap-4 mt-2.5 text-xs text-gray-500 dark:text-gray-400">
                            <span><span className="font-medium text-gray-700 dark:text-gray-300">{term.overlap}</span> / {term.size} genes overlap</span>
                            <span>p = {formatNum(parseFloat(term.pValue), 3)}</span>
                        </div>
                    </div>
                )
            })}
        </div>
    )
}

// ── Interactive JSON tree viewer ─────────────────────────────────────────────
// Context carries a "generation" counter + forced expansion state so that
// "Expand all" / "Collapse all" buttons can override every node at once.
const JsonExpandCtx = createContext<{ gen: number; forced: boolean | null }>({ gen: 0, forced: null })

const JsonNode = ({ value, depth = 0, defaultExpanded = true }: {
    value: unknown
    depth?: number
    defaultExpanded?: boolean
}) => {
    const { gen, forced } = useContext(JsonExpandCtx)
    const [expanded, setExpanded] = useState(defaultExpanded)

    // Sync with forced expand/collapse from parent
    useEffect(() => {
        if (forced !== null) setExpanded(forced)
    }, [gen]) // eslint-disable-line react-hooks/exhaustive-deps

    if (value === null) return <span className="text-gray-400">null</span>
    if (typeof value === "boolean") return <span className="text-purple-500 dark:text-purple-400">{String(value)}</span>
    if (typeof value === "number") return <span className="text-blue-600 dark:text-blue-400">{value}</span>
    if (typeof value === "string") {
        const MAX = 120
        const short = value.length > MAX
        const [showFull, setShowFull] = useState(false)
        const display = short && !showFull ? value.slice(0, MAX) + "…" : value
        return (
            <span className="text-green-700 dark:text-green-400">
                &quot;{display}&quot;
                {short && (
                    <button
                        className="ml-1 text-xs text-teal-500 hover:underline"
                        onClick={(e) => { e.stopPropagation(); setShowFull(v => !v) }}
                    >
                        {showFull ? "less" : "more"}
                    </button>
                )}
            </span>
        )
    }

    const isArray = Array.isArray(value)
    const entries = isArray
        ? (value as unknown[]).map((v, i) => [String(i), v] as [string, unknown])
        : Object.entries(value as Record<string, unknown>)
    const count = entries.length
    const bracket = isArray ? ["[", "]"] : ["{", "}"]

    if (count === 0) return <span className="text-gray-500">{bracket[0]}{bracket[1]}</span>

    return (
        <span>
            <button
                className="inline-flex items-center gap-0.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded px-0.5"
                onClick={() => setExpanded(e => !e)}
            >
                {expanded
                    ? <ChevronDown className="w-3 h-3 text-gray-400 flex-shrink-0" />
                    : <ChevronRight className="w-3 h-3 text-gray-400 flex-shrink-0" />
                }
                <span className="text-gray-500">{bracket[0]}</span>
                {!expanded && (
                    <span className="text-xs text-gray-400 mx-1">
                        {isArray ? `${count} items` : `${count} keys`}
                    </span>
                )}
                {!expanded && <span className="text-gray-500">{bracket[1]}</span>}
            </button>
            {expanded && (
                <span>
                    <br />
                    {entries.map(([k, v]) => (
                        <span key={k} style={{ display: "block", paddingLeft: `${(depth + 1) * 14}px` }}>
                            {!isArray && (
                                <span className="text-teal-700 dark:text-teal-400 font-medium">&quot;{k}&quot;</span>
                            )}
                            {!isArray && <span className="text-gray-500">: </span>}
                            <JsonNode value={v} depth={depth + 1} defaultExpanded={depth < 1} />
                            <span className="text-gray-400">,</span>
                        </span>
                    ))}
                    <span style={{ display: "block", paddingLeft: `${depth * 14}px` }} className="text-gray-500">
                        {bracket[1]}
                    </span>
                </span>
            )}
        </span>
    )
}

const JsonTreeViewer = ({ data }: { data: unknown }) => {
    const parsed = typeof data === "string" ? (() => {
        try { return JSON.parse(data) } catch { return data }
    })() : data

    const [expandCtx, setExpandCtx] = useState<{ gen: number; forced: boolean | null }>({ gen: 0, forced: null })
    const [copied, setCopied] = useState(false)

    const expandAll   = () => setExpandCtx(c => ({ gen: c.gen + 1, forced: true }))
    const collapseAll = () => setExpandCtx(c => ({ gen: c.gen + 1, forced: false }))

    const handleCopy = useCallback(() => {
        const text = JSON.stringify(parsed, null, 2)
        navigator.clipboard.writeText(text).then(() => {
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
        })
    }, [parsed])

    return (
        <div className="bg-gray-50 dark:bg-gray-900 border border-border rounded-lg overflow-hidden text-xs font-mono">
            <div className="flex items-center justify-between gap-1 px-3 py-1.5 border-b border-border bg-muted/40">
                <div className="flex items-center gap-1">
                    <button
                        onClick={expandAll}
                        className="px-2 py-0.5 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                    >
                        Expand all
                    </button>
                    <span className="text-border">|</span>
                    <button
                        onClick={collapseAll}
                        className="px-2 py-0.5 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                    >
                        Collapse all
                    </button>
                </div>
                <button
                    onClick={handleCopy}
                    className="flex items-center gap-1 px-2 py-0.5 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                    title="Copy JSON"
                >
                    {copied
                        ? <><Check className="h-3 w-3 text-green-500" /><span className="text-green-500">Copied</span></>
                        : <><Copy className="h-3 w-3" />Copy</>
                    }
                </button>
            </div>
            <div className="p-4 overflow-x-auto leading-relaxed">
                <JsonExpandCtx.Provider value={expandCtx}>
                    <JsonNode value={parsed} depth={0} defaultExpanded={true} />
                </JsonExpandCtx.Provider>
            </div>
        </div>
    )
}

const ResultRenderer = ({ result }: { result: any }) => {
    const [viewMode, setViewMode] = useState<'table' | 'json' | 'image' | 'enrichment' | 'network'>('table')

    // Detect GO enrichment data (webgestalt output)
    const isEnrichmentData = Array.isArray(result) && result.length > 0 &&
        result[0] && typeof result[0] === 'object' &&
        'geneSet' in result[0] && 'FDR' in result[0] && 'enrichmentRatio' in result[0]

    // Detect funmap network data (nodes + edges)
    const isFunmapData = result && typeof result === 'object' && !Array.isArray(result) &&
        Array.isArray(result.nodes) && Array.isArray(result.edges) &&
        (result.nodes.length === 0 || (typeof result.nodes[0] === 'object' && 'name' in result.nodes[0])) &&
        (result.edges.length === 0 || (typeof result.edges[0] === 'object' && 'source' in result.edges[0]))

    // Detect if valid table data
    const isTableData = !isEnrichmentData && !isFunmapData && Array.isArray(result) && result.length > 0 && typeof result[0] === 'object'
    const isMultiTableData = !isFunmapData && result && typeof result === 'object' && !Array.isArray(result) &&
        Object.values(result).every(val => Array.isArray(val) && (val.length === 0 || typeof val[0] === 'object'))

    // Detect if flat Key-Value object (e.g. get_drug_target_profile result)
    // Must be object, not array, not image parts, and values are primitives
    const isKeyValueData = result && typeof result === 'object' && !Array.isArray(result) && !result.parts &&
        Object.values(result).every(val => typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean')

    // Detect if object with array values (e.g. get_funmap_functional_neighborhood)
    const isListDictData = !isFunmapData && result && typeof result === 'object' && !Array.isArray(result) && !result.parts &&
        Object.values(result).every(val => Array.isArray(val) && (val.length === 0 || typeof val[0] === 'string' || typeof val[0] === 'number'))

    // Detect if image data (Standard MCP format with parts)
    const isImageData = result && typeof result === 'object' && result.parts && Array.isArray(result.parts) &&
        result.parts.some((p: any) => p.type === 'image')

    const hasData = isEnrichmentData || isFunmapData || isTableData || isMultiTableData || isImageData || isKeyValueData || isListDictData

    // Auto-switch to best view mode
    useEffect(() => {
        if (isImageData) setViewMode('image')
        else if (isEnrichmentData) setViewMode('enrichment')
        else if (isFunmapData) setViewMode('network')
        else if (isTableData || isMultiTableData || isKeyValueData || isListDictData) setViewMode('table')
    }, [isImageData, isEnrichmentData, isFunmapData, isTableData, isMultiTableData, isKeyValueData, isListDictData])


    if (!hasData) {
        return <JsonTreeViewer data={result} />
    }

    return (
        <div>
            <div className="flex justify-end mb-2">
                <div className="flex bg-gray-100 dark:bg-gray-800 rounded-lg p-1">
                    {isEnrichmentData && (
                        <button
                            onClick={() => setViewMode('enrichment')}
                            className={`px-3 py-1 text-xs font-medium rounded-md flex items-center gap-1 ${viewMode === 'enrichment'
                                ? 'bg-white dark:bg-gray-700 text-teal-600 dark:text-teal-400 shadow-sm'
                                : 'text-gray-500 dark:text-gray-400 hover:text-gray-900'
                                }`}
                        >
                            <Zap className="h-3 w-3" />
                            Enrichment
                        </button>
                    )}
                    {isFunmapData && (
                        <button
                            onClick={() => setViewMode('network')}
                            className={`px-3 py-1 text-xs font-medium rounded-md flex items-center gap-1 ${viewMode === 'network'
                                ? 'bg-white dark:bg-gray-700 text-teal-600 dark:text-teal-400 shadow-sm'
                                : 'text-gray-500 dark:text-gray-400 hover:text-gray-900'
                                }`}
                        >
                            <Network className="h-3 w-3" />
                            Network
                        </button>
                    )}
                    {(isTableData || isMultiTableData || isKeyValueData || isListDictData) && (
                        <button
                            onClick={() => setViewMode('table')}
                            className={`px-3 py-1 text-xs font-medium rounded-md flex items-center gap-1 ${viewMode === 'table'
                                ? 'bg-white dark:bg-gray-700 text-teal-600 dark:text-teal-400 shadow-sm'
                                : 'text-gray-500 dark:text-gray-400 hover:text-gray-900'
                                }`}
                        >
                            <TableIcon className="h-3 w-3" />
                            Table
                        </button>
                    )}
                    {isImageData && (
                        <button
                            onClick={() => setViewMode('image')}
                            className={`px-3 py-1 text-xs font-medium rounded-md flex items-center gap-1 ${viewMode === 'image'
                                ? 'bg-white dark:bg-gray-700 text-teal-600 dark:text-teal-400 shadow-sm'
                                : 'text-gray-500 dark:text-gray-400 hover:text-gray-900'
                                }`}
                        >
                            <ImageIcon className="h-3 w-3" />
                            Image
                        </button>
                    )}
                    <button
                        onClick={() => setViewMode('json')}
                        className={`px-3 py-1 text-xs font-medium rounded-md flex items-center gap-1 ${viewMode === 'json'
                            ? 'bg-white dark:bg-gray-700 text-teal-600 dark:text-teal-400 shadow-sm'
                            : 'text-gray-500 dark:text-gray-400 hover:text-gray-900'
                            }`}
                    >
                        <Code className="h-3 w-3" />
                        JSON
                    </button>
                </div>
            </div>

            {viewMode === 'json' ? (
                <JsonTreeViewer data={result} />
            ) : viewMode === 'enrichment' && isEnrichmentData ? (
                <EnrichmentRenderer data={result} />
            ) : viewMode === 'network' && isFunmapData ? (
                <NetworkPlot
                    visualization={{
                        type: "network_plot",
                        id: "__tool_explorer_preview__",
                        title: result.nodes.find((n: any) => parseFloat(n.value) === 0)?.name
                            ? `FunMap neighborhood \u2014 ${result.nodes.find((n: any) => parseFloat(n.value) === 0).name}`
                            : "FunMap Network",
                        nodes: result.nodes,
                        edges: result.edges,
                    } as NetworkVisualization}
                />
            ) : viewMode === 'image' ? (
                <div>
                    {result.parts.filter((p: any) => p.type === 'image').map((part: any, i: number) => (
                        <ImageRenderer key={i} data={part.data} mimeType={part.mimeType} />
                    ))}
                    {/* Also show text parts if any */}
                    {result.text && (
                        <div className="prose dark:prose-invert max-w-none text-sm mt-4">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.text}</ReactMarkdown>
                        </div>
                    )}
                </div>
            ) : (
                <div>
                    {isTableData && <TableRenderer data={result} />}
                    {isMultiTableData && Object.entries(result).map(([key, val]: [string, any]) => (
                        <TableRenderer key={key} title={key} data={val} />
                    ))}
                    {isKeyValueData && (
                        <TableRenderer
                            data={Object.entries(result).map(([k, v]) => ({ "Key": k, "Value": v }))}
                        />
                    )}
                    {isListDictData && Object.entries(result).map(([key, val]: [string, any]) => (
                        <TableRenderer
                            key={key}
                            title={key}
                            data={val.map((item: any) => ({ "Value": item }))}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

const ToolCard = ({ id, toolName, schema, Icon, color, onSelect }: {
    id: string
    toolName: string
    schema: ToolSchema
    Icon: React.ElementType
    color: string
    onSelect: (id: string) => void
}) => (
    <button
        onClick={() => onSelect(id)}
        className="group flex flex-col items-start text-left p-4 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:border-teal-300 dark:hover:border-teal-700 hover:bg-teal-50/50 dark:hover:bg-teal-900/20 hover:shadow-md transition-all duration-200"
    >
        <div className="flex items-center gap-3 w-full mb-2">
            <div className={`h-9 w-9 rounded-lg flex items-center justify-center flex-shrink-0 ${color}`}>
                <Icon className="h-4.5 w-4.5" />
            </div>
            <h3 className="font-semibold text-gray-900 dark:text-gray-100 group-hover:text-teal-600 dark:group-hover:text-teal-400 transition-colors truncate text-sm">
                {toolName}
            </h3>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2 leading-relaxed">
            {stripMarkdown(parseDocstring(schema.description).summary) || stripMarkdown(schema.description)}
        </p>
    </button>
)

interface CategoryDef {
    label: string
    icon: React.ElementType
    color: string        // Tailwind classes for icon bg + text
    borderColor: string  // active pill border
    tools: string[]      // tool name suffixes (after ::)
    serverPrefix?: string // match all tools from a server
}

const CATEGORIES: CategoryDef[] = [
    {
        label: "Expression Analysis",
        icon: BarChart2,
        color: "bg-teal-100 text-teal-600 dark:bg-teal-900/30 dark:text-teal-400",
        borderColor: "border-teal-400 dark:border-teal-500",
        tools: ["compare_cptac_tumor_normal_expression", "batch_compare_cptac_tumor_normal_expression", "analyze_cptac_cis_associations", "batch_analyze_cptac_cis_associations", "analyze_tcga_cis_associations"],
    },
    {
        label: "Survival Analysis",
        icon: HeartPulse,
        color: "bg-rose-100 text-rose-600 dark:bg-rose-900/30 dark:text-rose-400",
        borderColor: "border-rose-400 dark:border-rose-500",
        tools: ["analyze_cptac_gene_survival_associations", "batch_analyze_cptac_gene_survival_associations", "analyze_tcga_survival_associations"],
    },
    {
        label: "Drug Targets",
        icon: Pill,
        color: "bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400",
        borderColor: "border-amber-400 dark:border-amber-500",
        tools: ["get_drug_target_profile", "batch_get_drug_target_profiles", "search_drug_target_index", "rank_drug_targets"],
    },
    {
        label: "Clinical Trials",
        icon: ClipboardList,
        color: "bg-rose-100 text-rose-600 dark:bg-rose-900/30 dark:text-rose-400",
        borderColor: "border-rose-400 dark:border-rose-500",
        tools: ["search_gene_response_trials", "batch_search_gene_response_trials", "get_trial_study_details", "search_gene_set_response_trials", "search_trial_studies", "meta_analyze_response_genes", "meta_analyze_response_gene_sets", "rank_study_response_genes", "rank_study_response_gene_sets"],
    },
    {
        label: "Functional Networks",
        icon: Network,
        color: "bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400",
        borderColor: "border-blue-400 dark:border-blue-500",
        tools: ["get_funmap_functional_neighborhood"],
    },
    {
        label: "Pathway Enrichment",
        icon: FlaskConical,
        color: "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400",
        borderColor: "border-emerald-400 dark:border-emerald-500",
        tools: ["run_webgestalt_go_enrichment"],
    },
    {
        label: "Literature",
        icon: Library,
        color: "bg-indigo-100 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400",
        borderColor: "border-indigo-400 dark:border-indigo-500",
        tools: [],
        serverPrefix: "literature",
    },
    {
        label: "Gene Utilities",
        icon: Dna,
        color: "bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400",
        borderColor: "border-violet-400 dark:border-violet-500",
        tools: ["resolve_gene_identifier"],
    },
]

function getCategoryForTool(toolId: string): CategoryDef | null {
    const toolName = toolId.split("::").pop() || toolId
    const serverPrefix = toolId.split("::")[0]
    return CATEGORIES.find(cat =>
        (cat.serverPrefix && serverPrefix === cat.serverPrefix) ||
        cat.tools.includes(toolName)
    ) ?? null
}

// Full names for TCGA cohort abbreviations (display-only, value passed is the abbreviation)
const TCGA_COHORT_NAMES: Record<string, string> = {
    ACC: "Adrenocortical Carcinoma", BLCA: "Bladder Urothelial Carcinoma",
    BRCA: "Breast Invasive Carcinoma", CESC: "Cervical Squamous Cell Carcinoma",
    CHOL: "Cholangiocarcinoma", COAD: "Colon Adenocarcinoma",
    COADREAD: "Colorectal Adenocarcinoma", DLBC: "Diffuse Large B-Cell Lymphoma",
    ESCA: "Esophageal Carcinoma", GBM: "Glioblastoma Multiforme",
    GBMLGG: "Glioma", HNSC: "Head and Neck Squamous Cell Carcinoma",
    KICH: "Kidney Chromophobe", KIPAN: "Pan-Kidney",
    KIRC: "Kidney Renal Clear Cell Carcinoma", KIRP: "Kidney Renal Papillary Cell Carcinoma",
    LAML: "Acute Myeloid Leukemia", LGG: "Brain Lower Grade Glioma",
    LIHC: "Liver Hepatocellular Carcinoma", LUAD: "Lung Adenocarcinoma",
    LUSC: "Lung Squamous Cell Carcinoma", MESO: "Mesothelioma",
    OV: "Ovarian Serous Cystadenocarcinoma", PAAD: "Pancreatic Adenocarcinoma",
    PCPG: "Pheochromocytoma and Paraganglioma", PRAD: "Prostate Adenocarcinoma",
    SARC: "Sarcoma", SKCM: "Skin Cutaneous Melanoma",
    STAD: "Stomach Adenocarcinoma", STES: "Stomach and Esophageal Carcinoma",
    TGCT: "Testicular Germ Cell Tumors", THCA: "Thyroid Carcinoma",
    THYM: "Thymoma", UCEC: "Uterine Corpus Endometrial Carcinoma",
    UCS: "Uterine Carcinosarcoma", UVM: "Uveal Melanoma",
}

const CIS_PAIR_OPTIONS = [
    "RNA vs Protein",
    "RNA vs SCNV",
    "RNA vs Methylation",
    "Protein vs SCNV",
    "Protein vs Methylation",
    "SCNV vs Methylation",
]

const CPTAC_COHORT_OPTIONS = [
    "BRCA",
    "COAD",
    "CCRCC",
    "GBM",
    "HNSCC",
    "LSCC",
    "LUAD",
    "OV",
    "PDAC",
    "UCEC",
]

const CPTAC_COHORT_NAMES: Record<string, string> = {
    BRCA: "Breast cancer",
    COAD: "Colon adenocarcinoma",
    CCRCC: "Clear cell renal cell carcinoma",
    GBM: "Glioblastoma",
    HNSCC: "Head and neck squamous cell carcinoma",
    LSCC: "Lung squamous cell carcinoma",
    LUAD: "Lung adenocarcinoma",
    OV: "Ovarian serous carcinoma",
    PDAC: "Pancreatic ductal adenocarcinoma",
    UCEC: "Uterine corpus endometrial carcinoma",
}

function getCisCorrelationMultiSelectConfig(toolId: string | null, name: string) {
    const toolName = toolId?.split("::").pop()
    if (toolName !== "analyze_cptac_cis_associations" && toolName !== "batch_analyze_cptac_cis_associations") return null
    if (name === "pairs") {
        return {
            options: CIS_PAIR_OPTIONS,
            placeholder: "All molecular pairs",
        }
    }
    if (name === "cancers") {
        return {
            options: CPTAC_COHORT_OPTIONS,
            placeholder: "All CPTAC cohorts",
            getLabel: (opt: string) => CPTAC_COHORT_NAMES[opt],
        }
    }
    return null
}

function getToolSpecificEnumOptions(toolId: string | null, name: string, options: string[]): string[] {
    if (
        toolId?.endsWith("analyze_tcga_cis_associations") &&
        (name === "source_omics" || name === "target_omics")
    ) {
        return options.filter(option => option !== "miRNASeq")
    }
    return options
}

// ── Searchable enum select ────────────────────────────────────────────────────
function EnumSelect({ name, description, required, options, value, onChange, getLabel }: {
    name: string
    description?: string
    required: boolean
    options: string[]
    value: string
    onChange: (v: string) => void
    getLabel?: (opt: string) => string | undefined
}) {
    const [open, setOpen] = useState(false)
    const [query, setQuery] = useState("")
    const [dropUp, setDropUp] = useState(false)
    const ref = useState(() => ({ current: null as HTMLDivElement | null }))[0]

    const label = (opt: string) => getLabel?.(opt) || opt
    const displayValue = value ? `${value}${getLabel?.(value) ? ` — ${getLabel!(value)}` : ""}` : ""

    const filtered = query
        ? options.filter(o =>
            o.toLowerCase().includes(query.toLowerCase()) ||
            label(o).toLowerCase().includes(query.toLowerCase())
          )
        : options

    const select = (opt: string) => {
        onChange(opt)
        setQuery("")
        setOpen(false)
    }

    const clear = (e: React.MouseEvent) => {
        e.stopPropagation()
        onChange("")
        setQuery("")
    }

    // Decide open direction and close on outside click
    useEffect(() => {
        if (!open) return
        // Check if there's enough space below
        if (ref.current) {
            const rect = ref.current.getBoundingClientRect()
            const spaceBelow = window.innerHeight - rect.bottom
            setDropUp(spaceBelow < 240)
        }
        const handler = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) {
                setOpen(false)
                setQuery("")
            }
        }
        document.addEventListener("mousedown", handler)
        return () => document.removeEventListener("mousedown", handler)
    }, [open, ref])

    return (
        <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {name} {required && <span className="text-red-500">*</span>}
                <span className="ml-1.5 text-xs font-normal text-teal-600 dark:text-teal-400 bg-teal-50 dark:bg-teal-900/30 px-1.5 py-0.5 rounded">
                    {options.length} options
                </span>
            </label>
            {description && (
                <div className="text-xs text-gray-500 dark:text-gray-400 mb-1.5">{description}</div>
            )}
            <div className="relative" ref={(el) => { ref.current = el }}>
                {/* Trigger */}
                <button
                    type="button"
                    onClick={() => { setOpen(o => !o); setQuery("") }}
                    className={`w-full flex items-center justify-between rounded-lg border px-3 py-2 text-sm transition-colors
                        ${value
                            ? "border-teal-400 dark:border-teal-600 bg-teal-50/50 dark:bg-teal-900/20 text-gray-900 dark:text-gray-100"
                            : "border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-400 dark:text-gray-500"}
                        hover:border-teal-400 dark:hover:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500/40`}
                >
                    <span className="truncate">{displayValue || `Select ${name}…`}</span>
                    <span className="flex items-center gap-1 ml-2 flex-shrink-0">
                        {value && (
                            <span
                                onClick={clear}
                                className="w-4 h-4 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-200 dark:hover:bg-gray-600 cursor-pointer text-xs leading-none"
                                title="Clear"
                            >✕</span>
                        )}
                        <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`} />
                    </span>
                </button>

                {/* Dropdown */}
                {open && (
                    <div className={`absolute z-50 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg overflow-hidden ${dropUp ? "bottom-full mb-1" : "mt-1"}`}>
                        {/* Search */}
                        {options.length > 6 && (
                            <div className="p-2 border-b border-gray-100 dark:border-gray-700">
                                <input
                                    autoFocus
                                    type="text"
                                    placeholder="Search…"
                                    value={query}
                                    onChange={e => setQuery(e.target.value)}
                                    className="w-full text-sm px-2 py-1 rounded border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-teal-500"
                                />
                            </div>
                        )}
                        {/* Options */}
                        <ul className="max-h-52 overflow-y-auto py-1">
                            {filtered.length === 0 ? (
                                <li className="px-3 py-2 text-xs text-gray-400">No matches</li>
                            ) : filtered.map(opt => (
                                <li
                                    key={opt}
                                    onClick={() => select(opt)}
                                    className={`px-3 py-1.5 text-sm cursor-pointer flex items-center justify-between gap-2
                                        ${opt === value
                                            ? "bg-teal-50 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300 font-medium"
                                            : "text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/60"}`}
                                >
                                    <span className="flex items-center gap-2 min-w-0">
                                        <span className="font-medium flex-shrink-0">{opt}</span>
                                        {getLabel?.(opt) && (
                                            <span className="text-xs text-gray-400 dark:text-gray-500 truncate">{getLabel(opt)}</span>
                                        )}
                                    </span>
                                    {opt === value && <span className="text-teal-500 text-xs flex-shrink-0">✓</span>}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>
        </div>
    )
}

// ── Searchable multi-select for optional list parameters ─────────────────────
function MultiSelect({ name, description, required, options, value, onChange, placeholder, getLabel }: {
    name: string
    description?: string
    required: boolean
    options: string[]
    value: string[]
    onChange: (v: string[]) => void
    placeholder: string
    getLabel?: (opt: string) => string | undefined
}) {
    const [open, setOpen] = useState(false)
    const [query, setQuery] = useState("")
    const [dropUp, setDropUp] = useState(false)
    const ref = useState(() => ({ current: null as HTMLDivElement | null }))[0]

    const selected = new Set(value)
    const label = (opt: string) => getLabel?.(opt) || opt
    const displayValue = value.length ? value.join(", ") : placeholder
    const filtered = query
        ? options.filter(o =>
            o.toLowerCase().includes(query.toLowerCase()) ||
            label(o).toLowerCase().includes(query.toLowerCase())
          )
        : options

    const toggle = (opt: string) => {
        if (selected.has(opt)) onChange(value.filter(v => v !== opt))
        else onChange([...value, opt])
    }

    const clear = (e: React.MouseEvent) => {
        e.stopPropagation()
        onChange([])
        setQuery("")
    }

    useEffect(() => {
        if (!open) return
        if (ref.current) {
            const rect = ref.current.getBoundingClientRect()
            const spaceBelow = window.innerHeight - rect.bottom
            setDropUp(spaceBelow < 280)
        }
        const handler = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) {
                setOpen(false)
                setQuery("")
            }
        }
        document.addEventListener("mousedown", handler)
        return () => document.removeEventListener("mousedown", handler)
    }, [open, ref])

    return (
        <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {name} {required && <span className="text-red-500">*</span>}
                <span className="ml-1.5 text-xs font-normal text-teal-600 dark:text-teal-400 bg-teal-50 dark:bg-teal-900/30 px-1.5 py-0.5 rounded">
                    optional multi-select
                </span>
            </label>
            {description && (
                <div className="text-xs text-gray-500 dark:text-gray-400 mb-1.5">{description}</div>
            )}
            <div className="relative" ref={(el) => { ref.current = el }}>
                <button
                    type="button"
                    onClick={() => { setOpen(o => !o); setQuery("") }}
                    className={`w-full flex items-center justify-between rounded-lg border px-3 py-2 text-sm transition-colors
                        ${value.length
                            ? "border-teal-400 dark:border-teal-600 bg-teal-50/50 dark:bg-teal-900/20 text-gray-900 dark:text-gray-100"
                            : "border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400"}
                        hover:border-teal-400 dark:hover:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500/40`}
                >
                    <span className="truncate">{displayValue}</span>
                    <span className="flex items-center gap-1 ml-2 flex-shrink-0">
                        {value.length > 0 && (
                            <span
                                onClick={clear}
                                className="w-4 h-4 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-200 dark:hover:bg-gray-600 cursor-pointer text-xs leading-none"
                                title="Clear"
                            >✕</span>
                        )}
                        <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`} />
                    </span>
                </button>

                {open && (
                    <div className={`absolute z-50 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg overflow-hidden ${dropUp ? "bottom-full mb-1" : "mt-1"}`}>
                        <div className="p-2 border-b border-gray-100 dark:border-gray-700 space-y-2">
                            {options.length > 6 && (
                                <input
                                    autoFocus
                                    type="text"
                                    placeholder="Search…"
                                    value={query}
                                    onChange={e => setQuery(e.target.value)}
                                    className="w-full text-sm px-2 py-1 rounded border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-teal-500"
                                />
                            )}
                            <button
                                type="button"
                                onClick={() => { onChange([]); setQuery("") }}
                                className={`w-full text-left px-2 py-1.5 rounded text-sm transition-colors ${
                                    value.length === 0
                                        ? "bg-teal-50 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300 font-medium"
                                        : "text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/60"
                                }`}
                            >
                                {placeholder}
                            </button>
                        </div>
                        <ul className="max-h-56 overflow-y-auto py-1">
                            {filtered.length === 0 ? (
                                <li className="px-3 py-2 text-xs text-gray-400">No matches</li>
                            ) : filtered.map(opt => {
                                const isSelected = selected.has(opt)
                                return (
                                    <li
                                        key={opt}
                                        onClick={() => toggle(opt)}
                                        className={`px-3 py-1.5 text-sm cursor-pointer flex items-center justify-between gap-2
                                            ${isSelected
                                                ? "bg-teal-50 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300 font-medium"
                                                : "text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/60"}`}
                                    >
                                        <span className="flex items-center gap-2 min-w-0">
                                            <span className={`h-4 w-4 rounded border flex items-center justify-center flex-shrink-0 ${
                                                isSelected
                                                    ? "border-teal-500 bg-teal-500 text-white"
                                                    : "border-gray-300 dark:border-gray-600"
                                            }`}>
                                                {isSelected && <Check className="h-3 w-3" />}
                                            </span>
                                            <span className="font-medium flex-shrink-0">{opt}</span>
                                            {getLabel?.(opt) && (
                                                <span className="text-xs text-gray-400 dark:text-gray-500 truncate">{getLabel(opt)}</span>
                                            )}
                                        </span>
                                    </li>
                                )
                            })}
                        </ul>
                    </div>
                )}
            </div>
        </div>
    )
}

// Module-level cache — survives re-mounts so Tools tab is instant after first load
let _toolsCache: Record<string, ToolSchema> | null = null

export default function ToolExplorer({ className = "", resetKey }: ToolExplorerProps) {
    const [tools, setTools] = useState<Record<string, ToolSchema> | null>(_toolsCache)
    const [selectedToolId, setSelectedToolId] = useState<string | null>(null)

    useEffect(() => {
        if (resetKey !== undefined) {
            setSelectedToolId(null)
            setResult(null)
            setArgs({})
            setError(null)
        }
    }, [resetKey])

    const [args, setArgs] = useState<Record<string, any>>({})
    const [result, setResult] = useState<any>(null)
    const [loading, setLoading] = useState(false)
    const [executing, setExecuting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [searchQuery, setSearchQuery] = useState("")
    const [activeCategory, setActiveCategory] = useState<string | null>(null)
    const selectedCategory = selectedToolId ? getCategoryForTool(selectedToolId) : null
    const activeGuideKey = getToolCategoryGuideKeyFromLabel(activeCategory)
    const selectedGuideKey = getToolCategoryGuideKeyFromLabel(selectedCategory?.label)

    useEffect(() => {
        if (!_toolsCache) loadTools()
    }, [])

    const loadTools = async () => {
        try {
            setLoading(true)
            const data = await toolsAPI.list()
            _toolsCache = data.tools
            setTools(data.tools)
        } catch (err: any) {
            setError(err.message || "Failed to load tools")
        } finally {
            setLoading(false)
        }
    }

    const handleToolSelect = (toolId: string) => {
        setSelectedToolId(toolId)
        setResult(null)
        setArgs({})
        setError(null)
    }

    const handleExecute = async () => {
        if (!selectedToolId) return

        try {
            setExecuting(true)
            setError(null)
            // Strip empty strings so Optional params are sent as absent (None) not ""
            const cleanArgs = Object.fromEntries(
                Object.entries(args).filter(([, v]) =>
                    v !== "" && v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0)
                )
            )
            const res = await toolsAPI.execute(selectedToolId, cleanArgs)

            // Extract the actual data payload
            let cleanResult = res.result

            // If result is a string, try to parse it as JSON first
            if (typeof cleanResult === 'string') {
                try {
                    cleanResult = JSON.parse(cleanResult)
                } catch (e) {
                    // Not valid JSON, keep as is
                }
            }

            // If it's the LinkedOmics specific wrapper {"status": "available", "data": ...}, unwrap it
            if (cleanResult && typeof cleanResult === 'object') {
                if (['available', 'success'].includes(cleanResult.status) && cleanResult.data) {
                    cleanResult = cleanResult.data
                } else {
                    // Check for nested wrappers (e.g. { protein: {status:..., data:...}, rna: {status:..., data:...} })
                    // This happens in tools like analyze_cptac_gene_survival_associations
                    const newResult: any = {}
                    let modified = false

                    for (const [key, val] of Object.entries(cleanResult)) {
                        if (val && typeof val === 'object' && ['available', 'success'].includes((val as any).status) && (val as any).data) {
                            // Check if the data is a simple key-value object (cancer -> string)
                            // If so, transform it to an array of objects for table rendering
                            let data = (val as any).data
                            if (data && typeof data === 'object' && !Array.isArray(data)) {
                                // Transform { "BRCA": "High risk", ... } -> [ { "Cancer": "BRCA", "Result": "High risk" }, ... ]
                                data = Object.entries(data).map(([k, v]) => ({
                                    "Key": k,
                                    "Value": v
                                }))
                            }
                            newResult[key] = data
                            modified = true
                        } else {
                            newResult[key] = val
                        }
                    }
                    if (modified) cleanResult = newResult
                }
            }

            // If it's a standard MCP TextContent list, verify content
            if (Array.isArray(cleanResult) && cleanResult[0]?.type === 'text') {
                // Try to parse JSON from the text block if possible, otherwise use string
                try {
                    cleanResult = JSON.parse(cleanResult[0].text)
                    // If it has the wrapper inside the parsed JSON
                    if (cleanResult && typeof cleanResult === 'object' && cleanResult.status === 'available' && cleanResult.data) {
                        cleanResult = cleanResult.data
                    }
                } catch {
                    cleanResult = cleanResult.map((c: any) => c.text).join("\n")
                }
            }

            setResult(cleanResult)
        } catch (err: any) {
            setError(err.message || "Execution failed")
        } finally {
            setExecuting(false)
        }
    }

    const renderFormInput = (name: string, param: ToolParameter, required: boolean) => {
        const cisMultiSelectConfig = getCisCorrelationMultiSelectConfig(selectedToolId, name)
        if (cisMultiSelectConfig) {
            return (
                <MultiSelect
                    key={name}
                    name={name}
                    description={param.description}
                    required={required}
                    options={cisMultiSelectConfig.options}
                    value={Array.isArray(args[name]) ? args[name] : []}
                    onChange={(v) => setArgs({ ...args, [name]: v })}
                    placeholder={cisMultiSelectConfig.placeholder}
                    getLabel={cisMultiSelectConfig.getLabel}
                />
            )
        }

        // FastMCP wraps Optional[Literal[...]] as anyOf: [{enum:[...]}, {type:"null"}]
        // so we extract enum from either location
        const rawEnumValues = param.enum ?? param.anyOf?.find(s => Array.isArray(s.enum))?.enum
        const enumValues = rawEnumValues
            ? getToolSpecificEnumOptions(selectedToolId, name, rawEnumValues.map(String))
            : undefined
        if (enumValues) {
            // Detect if this is a TCGA cohort parameter to show full names
            const isCohortParam = name === "cohort" ||
                enumValues.some((v: any) => String(v) in TCGA_COHORT_NAMES)
            return (
                <EnumSelect
                    key={name}
                    name={name}
                    description={param.description}
                    required={required}
                    options={enumValues}
                    value={args[name] || ""}
                    onChange={(v) => setArgs({ ...args, [name]: v })}
                    getLabel={isCohortParam ? (opt) => TCGA_COHORT_NAMES[opt] : undefined}
                />
            )
        }

        return (
            <div key={name} className="mb-4">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {name} {required && <span className="text-red-500">*</span>}
                </label>
                <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">
                    {param.description}
                </div>
                <input
                    type="text"
                    className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
                    placeholder={`Enter ${name}...`}
                    value={args[name] || ""}
                    onChange={(e) => setArgs({ ...args, [name]: e.target.value })}
                />
            </div>
        )
    }

    if (loading) return <div className="p-4 text-center">Loading tools...</div>

    return (
        <div className={`flex flex-col h-full bg-gray-50 dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700 ${className}`}>
            <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
                <Beaker className="h-5 w-5 text-teal-500" />
                <h2 className="font-semibold text-gray-900 dark:text-white">Tool Explorer</h2>
            </div>

            {/* Sticky search + pills — only shown on list view */}
            {!selectedToolId && (
                <div className="shrink-0 px-4 pt-4 pb-3 bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 space-y-3">
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
                        <input
                            type="text"
                            placeholder="Search tools..."
                            className="w-full pl-9 pr-4 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 transition-all"
                            value={searchQuery}
                            onChange={(e) => { setSearchQuery(e.target.value); setActiveCategory(null) }}
                        />
                    </div>
                    {!searchQuery && (
                        <div className="flex flex-wrap gap-2">
                            <button
                                onClick={() => setActiveCategory(null)}
                                className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                                    activeCategory === null
                                        ? "bg-gray-800 dark:bg-gray-100 text-white dark:text-gray-900 border-gray-800 dark:border-gray-100"
                                        : "bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700 hover:border-gray-400"
                                }`}
                            >
                                All
                            </button>
                            {CATEGORIES.filter(cat => {
                                if (!tools) return false
                                return Object.keys(tools).some(id => getCategoryForTool(id)?.label === cat.label)
                            }).map(cat => {
                                const Icon = cat.icon
                                const isActive = activeCategory === cat.label
                                return (
                                    <button
                                        key={cat.label}
                                        onClick={() => setActiveCategory(isActive ? null : cat.label)}
                                        className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                                            isActive
                                                ? `${cat.color} ${cat.borderColor}`
                                                : "bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700 hover:border-gray-400"
                                        }`}
                                    >
                                        <Icon className="h-3 w-3" />
                                        {cat.label}
                                    </button>
                                )
                            })}
                        </div>
                    )}
                </div>
            )}

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {error && (
                    <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-3 rounded-md text-sm flex items-center gap-2">
                        <AlertCircle className="h-4 w-4" />
                        {error}
                    </div>
                )}

                {!selectedToolId && activeGuideKey && (
                    <ToolCategoryGuide category={activeGuideKey} compact />
                )}

                {/* Tool Grid */}
                {!selectedToolId && tools && (() => {
                    const filtered = Object.entries(tools).filter(([id, schema]) => {
                        const matchesSearch = !searchQuery ||
                            id.toLowerCase().includes(searchQuery.toLowerCase()) ||
                            schema.description.toLowerCase().includes(searchQuery.toLowerCase())
                        const matchesCategory = !activeCategory ||
                            getCategoryForTool(id)?.label === activeCategory
                        return matchesSearch && matchesCategory
                    })

                    // When searching or a category is active, show flat grid
                    if (searchQuery || activeCategory) {
                        return (
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                {filtered.map(([id, schema]) => {
                                    const toolName = id.split("::").pop() || id
                                    const cat = getCategoryForTool(id)
                                    const Icon = cat?.icon ?? Beaker
                                    const color = cat?.color ?? "bg-teal-100 text-teal-600 dark:bg-teal-900/30 dark:text-teal-400"
                                    return (
                                        <ToolCard key={id} id={id} toolName={toolName} schema={schema} Icon={Icon} color={color} onSelect={handleToolSelect} />
                                    )
                                })}
                                {filtered.length === 0 && (
                                    <p className="col-span-2 text-sm text-gray-400 text-center py-8">No tools match your search.</p>
                                )}
                            </div>
                        )
                    }

                    // Default: group by category
                    const grouped: { cat: CategoryDef; entries: [string, ToolSchema][] }[] = []
                    const uncategorized: [string, ToolSchema][] = []

                    for (const cat of CATEGORIES) {
                        const entries = filtered.filter(([id]) => getCategoryForTool(id)?.label === cat.label)
                        if (entries.length > 0) grouped.push({ cat, entries })
                    }
                    for (const entry of filtered) {
                        if (!getCategoryForTool(entry[0])) uncategorized.push(entry)
                    }

                    return (
                        <div className="space-y-6">
                            {grouped.map(({ cat, entries }) => {
                                const Icon = cat.icon
                                return (
                                    <div key={cat.label}>
                                        <div className="flex items-center gap-2 mb-3">
                                            <div className={`h-6 w-6 rounded-md flex items-center justify-center ${cat.color}`}>
                                                <Icon className="h-3.5 w-3.5" />
                                            </div>
                                            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">{cat.label}</h3>
                                            <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
                                            <span className="text-xs text-gray-400">{entries.length}</span>
                                        </div>
                                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                            {entries.map(([id, schema]) => {
                                                const toolName = id.split("::").pop() || id
                                                return (
                                                    <ToolCard key={id} id={id} toolName={toolName} schema={schema} Icon={Icon} color={cat.color} onSelect={handleToolSelect} />
                                                )
                                            })}
                                        </div>
                                    </div>
                                )
                            })}
                            {uncategorized.length > 0 && (
                                <div>
                                    <div className="flex items-center gap-2 mb-3">
                                        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Other</h3>
                                        <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
                                    </div>
                                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                        {uncategorized.map(([id, schema]) => (
                                            <ToolCard key={id} id={id} toolName={id.split("::").pop() || id} schema={schema} Icon={Beaker} color="bg-teal-100 text-teal-600 dark:bg-teal-900/30 dark:text-teal-400" onSelect={handleToolSelect} />
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    )
                })()}

                {/* Selected Tool Form */}
                {selectedToolId && tools && tools[selectedToolId] && (
                    <div className="space-y-6">
                        <button
                            onClick={() => {
                                setSelectedToolId(null)
                                setResult(null)
                                setArgs({})
                            }}
                            className="text-sm text-teal-500 hover:text-teal-600 flex items-center gap-1"
                        >
                            <ArrowLeft className="h-4 w-4" />
                            Back to list
                        </button>

                        <div>
                            <div className="flex items-center gap-3 mb-4">
                                <div className="h-10 w-10 rounded-xl bg-teal-100 dark:bg-teal-900/40 flex items-center justify-center flex-shrink-0">
                                    <Beaker className="h-5 w-5 text-teal-600 dark:text-teal-400" />
                                </div>
                                <div>
                                    <h3 className="text-lg font-bold text-gray-900 dark:text-white font-mono">
                                        {selectedToolId.split("::").pop()}
                                    </h3>
                                    <p className="text-xs text-gray-400 dark:text-gray-500">
                                        {selectedToolId.split("::")[0]} MCP Tool
                                    </p>
                                </div>
                            </div>
                            <ToolDocumentation description={tools[selectedToolId].description} />
                        </div>

                        {selectedGuideKey && (
                            <ToolCategoryGuide category={selectedGuideKey} compact />
                        )}

                        {/* Literature tool note */}
                        {selectedToolId.startsWith("literature::") && (
                            <div className="flex gap-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-lg p-3 text-xs text-amber-800 dark:text-amber-300">
                                <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                                <div>
                                    <span className="font-semibold">PubMed syntax required.</span> The <code className="bg-amber-100 dark:bg-amber-800/40 px-1 rounded">query</code> field is sent directly to NCBI — use keywords, not natural language sentences.
                                    <br />
                                    <span className="text-amber-700 dark:text-amber-400">Examples: </span>
                                    <code className="bg-amber-100 dark:bg-amber-800/40 px-1 rounded">ESR1 breast cancer survival</code>
                                    {" · "}
                                    <code className="bg-amber-100 dark:bg-amber-800/40 px-1 rounded">KRAS pancreatic cancer 2022:2025[dp]</code>
                                    <br />
                                    In the <span className="font-medium">Chat</span>, you can ask in plain language — the AI reformulates the query automatically.
                                </div>
                            </div>
                        )}

                        <div className="bg-white dark:bg-gray-800 p-4 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm">
                            {Object.entries(tools[selectedToolId].inputSchema.properties).map(([name, param]) =>
                                renderFormInput(
                                    name,
                                    param,
                                    tools[selectedToolId].inputSchema.required?.includes(name) || false
                                )
                            )}

                            <button
                                onClick={handleExecute}
                                disabled={executing}
                                className="w-full mt-4 bg-teal-600 hover:bg-teal-700 text-white font-medium py-2 px-4 rounded-md flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                            >
                                {executing ? (
                                    <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                ) : (
                                    <Play className="h-4 w-4" />
                                )}
                                Execute Tool
                            </button>
                        </div>
                    </div>
                )}

                {/* Results Area */}
                {result && (
                    <div className="mt-6 border-t border-gray-200 dark:border-gray-700 pt-6">
                        <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">Result Output</h4>
                        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
                            <ResultRenderer result={result} />
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
