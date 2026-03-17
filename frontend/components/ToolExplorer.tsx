"use client"

import { useState, useEffect } from "react"
import { toolsAPI } from "@/lib/api"
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
    FileText
} from "lucide-react"

interface ToolParameter {
    type: string
    description?: string
    default?: any
    enum?: any[]
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
    whenToUse: string[]
    useCases: string[]
    args: { name: string; type: string; desc: string }[]
    returns: { name: string; type: string; desc: string }[]
    returnsIntro: string
    extra: string[]
}

function parseDocstring(raw: string): ParsedDoc {
    const lines = raw.split('\n')
    const result: ParsedDoc = { summary: '', whenToUse: [], useCases: [], args: [], returns: [], returnsIntro: '', extra: [] }

    let section = 'summary'
    const summaryLines: string[] = []
    let currentArg: { name: string; type: string; desc: string } | null = null
    let currentReturn: { name: string; type: string; desc: string } | null = null

    for (const line of lines) {
        const trimmed = line.trim()

        // Detect section headers
        if (/^use this tool when/i.test(trimmed) || /^use when/i.test(trimmed)) { section = 'when'; continue }
        if (/^use cases?:/i.test(trimmed)) { section = 'cases'; continue }
        if (/^args?:/i.test(trimmed)) { section = 'args'; continue }
        if (/^returns?:/i.test(trimmed)) { section = 'returns'; continue }
        if (/^available (omic|cancer)/i.test(trimmed)) { section = 'extra'; }
        if (/^interpretation tips/i.test(trimmed)) { section = 'extra'; }
        if (/^example usage/i.test(trimmed)) { section = 'extra'; }
        if (/^best used after/i.test(trimmed)) { section = 'extra'; }

        if (!trimmed) continue

        if (section === 'summary') {
            summaryLines.push(trimmed)
        } else if (section === 'when') {
            const bullet = trimmed.replace(/^[-*]\s*/, '')
            if (bullet) result.whenToUse.push(bullet)
        } else if (section === 'cases') {
            const bullet = trimmed.replace(/^[-*]\s*/, '')
            if (bullet) result.useCases.push(bullet)
        } else if (section === 'args') {
            const argMatch = trimmed.match(/^(\w+)\s*\(([^)]+)\):\s*(.*)/)
            if (argMatch) {
                if (currentArg) result.args.push(currentArg)
                currentArg = { name: argMatch[1], type: argMatch[2], desc: argMatch[3] }
            } else if (currentArg && trimmed) {
                currentArg.desc += ' ' + trimmed
            }
        } else if (section === 'returns') {
            // Match: `"key" (type): desc`  or  `- "key" (type): desc`  or  `key (type): desc`
            const retMatch = trimmed.match(/^[-*]?\s*["']?(\w+)["']?\s*\(([^)]+)\):\s*(.*)/)
            if (retMatch) {
                if (currentReturn) result.returns.push(currentReturn)
                currentReturn = { name: retMatch[1], type: retMatch[2], desc: retMatch[3] }
            } else if (currentReturn && trimmed.startsWith('-')) {
                // nested bullet under a return field — append to desc
                currentReturn.desc += ' ' + trimmed.replace(/^-\s*/, '')
            } else if (currentReturn && trimmed) {
                currentReturn.desc += ' ' + trimmed
            } else if (!currentReturn && trimmed) {
                // intro line like "dict with keys:"
                result.returnsIntro = trimmed
            }
        } else if (section === 'extra') {
            result.extra.push(trimmed)
        }
    }

    if (currentArg) result.args.push(currentArg)
    if (currentReturn) result.returns.push(currentReturn)
    result.summary = summaryLines.join(' ')
    return result
}

const ToolDocumentation = ({ description }: { description: string }) => {
    const doc = parseDocstring(description)

    return (
        <div className="space-y-4">
            {/* Summary */}
            {doc.summary && (
                <div className="bg-gradient-to-r from-teal-50 to-emerald-50 dark:from-teal-900/20 dark:to-emerald-900/20 border border-teal-200 dark:border-teal-800 rounded-xl p-4">
                    <div className="flex items-start gap-3">
                        <div className="mt-0.5 h-7 w-7 rounded-lg bg-teal-100 dark:bg-teal-900/50 flex items-center justify-center flex-shrink-0">
                            <FileText className="h-4 w-4 text-teal-600 dark:text-teal-400" />
                        </div>
                        <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
                            <InlineText text={doc.summary} />
                        </p>
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
                        <p className="text-xs text-gray-400 dark:text-gray-500 mb-3 italic">{doc.returnsIntro}</p>
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

const ResultRenderer = ({ result }: { result: any }) => {
    const [viewMode, setViewMode] = useState<'table' | 'json' | 'image' | 'enrichment'>('table')

    // Detect GO enrichment data (webgestalt output)
    const isEnrichmentData = Array.isArray(result) && result.length > 0 &&
        result[0] && typeof result[0] === 'object' &&
        'geneSet' in result[0] && 'FDR' in result[0] && 'enrichmentRatio' in result[0]

    // Detect if valid table data
    const isTableData = !isEnrichmentData && Array.isArray(result) && result.length > 0 && typeof result[0] === 'object'
    const isMultiTableData = result && typeof result === 'object' && !Array.isArray(result) &&
        Object.values(result).every(val => Array.isArray(val) && (val.length === 0 || typeof val[0] === 'object'))

    // Detect if flat Key-Value object (e.g. get_target result)
    // Must be object, not array, not image parts, and values are primitives
    const isKeyValueData = result && typeof result === 'object' && !Array.isArray(result) && !result.parts &&
        Object.values(result).every(val => typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean')

    // Detect if object with array values (e.g. funmap_neighborhood)
    const isListDictData = result && typeof result === 'object' && !Array.isArray(result) && !result.parts &&
        Object.values(result).every(val => Array.isArray(val) && (val.length === 0 || typeof val[0] === 'string' || typeof val[0] === 'number'))

    // Detect if image data (Standard MCP format with parts)
    const isImageData = result && typeof result === 'object' && result.parts && Array.isArray(result.parts) &&
        result.parts.some((p: any) => p.type === 'image')

    const hasData = isEnrichmentData || isTableData || isMultiTableData || isImageData || isKeyValueData || isListDictData

    // Auto-switch to best view mode
    useEffect(() => {
        if (isImageData) setViewMode('image')
        else if (isEnrichmentData) setViewMode('enrichment')
        else if (isTableData || isMultiTableData || isKeyValueData || isListDictData) setViewMode('table')
    }, [isImageData, isEnrichmentData, isTableData, isMultiTableData, isKeyValueData, isListDictData])


    if (!hasData) {
        // Fallback to markdown/json for non-tabular data
        const content = typeof result === 'string' ? result :
            "```json\n" + JSON.stringify(result, null, 2) + "\n```"

        return (
            <div className="prose dark:prose-invert max-w-none text-sm">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
        )
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
                <div className="bg-gray-50 dark:bg-gray-900 p-4 rounded-lg overflow-x-auto text-xs font-mono">
                    <pre>{JSON.stringify(result, null, 2)}</pre>
                </div>
            ) : viewMode === 'enrichment' && isEnrichmentData ? (
                <EnrichmentRenderer data={result} />
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

export default function ToolExplorer({ className = "" }: ToolExplorerProps) {
    const [tools, setTools] = useState<Record<string, ToolSchema> | null>(null)
    const [selectedToolId, setSelectedToolId] = useState<string | null>(null)
    const [args, setArgs] = useState<Record<string, any>>({})
    const [result, setResult] = useState<any>(null)
    const [loading, setLoading] = useState(false)
    const [executing, setExecuting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [searchQuery, setSearchQuery] = useState("")

    useEffect(() => {
        loadTools()
    }, [])

    const loadTools = async () => {
        try {
            setLoading(true)
            const data = await toolsAPI.list()
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
            const res = await toolsAPI.execute(selectedToolId, args)

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
                    // This happens in tools like overall_survival_per_cancer
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
        if (param.enum) {
            return (
                <div key={name} className="mb-4">
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        {name} {required && <span className="text-red-500">*</span>}
                    </label>
                    <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">
                        {param.description}
                    </div>
                    <select
                        className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
                        value={args[name] || ""}
                        onChange={(e) => setArgs({ ...args, [name]: e.target.value })}
                    >
                        <option value="" disabled>Select {name}...</option>
                        {param.enum.map((opt: any) => (
                            <option key={String(opt)} value={opt}>
                                {String(opt)}
                            </option>
                        ))}
                    </select>
                </div>
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

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {error && (
                    <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-3 rounded-md text-sm flex items-center gap-2">
                        <AlertCircle className="h-4 w-4" />
                        {error}
                    </div>
                )}

                {/* Search Bar */}
                {!selectedToolId && (
                    <div className="mb-6 relative">
                        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
                        <input
                            type="text"
                            placeholder="Search tools..."
                            className="w-full pl-9 pr-4 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 transition-all"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                    </div>
                )}

                {/* Tool Grid */}
                {!selectedToolId && tools && (
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        {Object.entries(tools)
                            .filter(([id, schema]) =>
                                id.toLowerCase().includes(searchQuery.toLowerCase()) ||
                                schema.description.toLowerCase().includes(searchQuery.toLowerCase())
                            )
                            .map(([id, schema]) => {
                                const toolName = id.split("::").pop() || id
                                const iconColor = "bg-teal-100 text-teal-600 dark:bg-teal-900/30 dark:text-teal-400"

                                return (
                                    <button
                                        key={id}
                                        onClick={() => handleToolSelect(id)}
                                        className="group flex flex-col items-start text-left p-4 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:border-teal-300 dark:hover:border-teal-700 hover:bg-teal-50/50 dark:hover:bg-teal-900/20 hover:shadow-md transition-all duration-200"
                                    >
                                        <div className="flex items-center gap-3 w-full mb-3">
                                            <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${iconColor}`}>
                                                <Beaker className="h-5 w-5" />
                                            </div>
                                            <div className="flex-1 min-w-0">
                                                <h3 className="font-semibold text-gray-900 dark:text-gray-100 group-hover:text-teal-600 dark:group-hover:text-teal-400 transition-colors truncate">
                                                    {toolName}
                                                </h3>
                                            </div>
                                        </div>
                                        <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2 leading-relaxed">
                                            {stripMarkdown(schema.description)}
                                        </p>
                                    </button>
                                )
                            })}
                    </div>
                )}

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
