"use client"

import { useEffect, useMemo, useState } from "react"
import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react"
import type { PredictiveResultsTableVisualization } from "@/lib/api"
import { useLazyVisible } from "@/hooks/useLazyVisible"
import { getAuthToken } from "@/lib/auth"

const API_URL = process.env.NEXT_PUBLIC_API_URL || ""
const PAGE_SIZE = 15

type SortKey = "rank" | "label" | "studies" | "avg_auroc" | "meta_fdr" | "direction"
type SortDir = "asc" | "desc"

interface Props {
    visualization: PredictiveResultsTableVisualization
}

function formatAuroc(value?: number) {
    return typeof value === "number" ? value.toFixed(3).replace(/\.?0+$/, (m) => (m === ".000" ? "" : m)) : "—"
}

function formatMetaFdr(row: NonNullable<PredictiveResultsTableVisualization["rows"]>[number]) {
    if (row.meta_fdr_sci) return row.meta_fdr_sci
    if (typeof row.meta_fdr === "number") return row.meta_fdr.toExponential(3)
    return "—"
}

function directionText(direction?: string) {
    return direction === "sensitive" ? "↑ Sensitive" : direction === "resistant" ? "↓ Resistant" : "—"
}

export function PredictiveResultsTable({ visualization }: Props) {
    const { ref, isVisible } = useLazyVisible()
    const [resolvedViz, setResolvedViz] = useState<PredictiveResultsTableVisualization>(visualization)
    const [fetchError, setFetchError] = useState(false)
    const [page, setPage] = useState(1)
    const [sortKey, setSortKey] = useState<SortKey>("rank")
    const [sortDir, setSortDir] = useState<SortDir>("asc")

    useEffect(() => {
        if (!isVisible) return
        if (resolvedViz.rows?.length) return
        if (!visualization.id) return
        const token = getAuthToken()
        fetch(`${API_URL}/api/v1/chat/visualizations/${encodeURIComponent(visualization.id)}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
            .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
            .then(data => {
                if (data?.type === "predictive_results_table") {
                    setResolvedViz({ ...visualization, ...(data as PredictiveResultsTableVisualization) })
                } else {
                    setFetchError(true)
                }
            })
            .catch(() => setFetchError(true))
    }, [isVisible, resolvedViz.rows?.length, visualization])

    const rows = resolvedViz.rows ?? []

    const sortedRows = useMemo(() => {
        const numericKeys = new Set<SortKey>(["rank", "studies", "avg_auroc", "meta_fdr"])
        return [...rows].sort((a, b) => {
            if (numericKeys.has(sortKey)) {
                const av = Number((a as Record<string, unknown>)[sortKey] ?? 0)
                const bv = Number((b as Record<string, unknown>)[sortKey] ?? 0)
                return sortDir === "asc" ? av - bv : bv - av
            }
            const av = String((a as Record<string, unknown>)[sortKey] ?? "")
            const bv = String((b as Record<string, unknown>)[sortKey] ?? "")
            const cmp = av.localeCompare(bv)
            return sortDir === "asc" ? cmp : -cmp
        })
    }, [rows, sortDir, sortKey])

    const totalPages = Math.max(1, Math.ceil(sortedRows.length / PAGE_SIZE))
    const currentPage = Math.min(page, totalPages)
    const pageRows = sortedRows.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

    const handleSort = (key: SortKey) => {
        if (sortKey === key) {
            setSortDir((dir) => (dir === "asc" ? "desc" : "asc"))
        } else {
            setSortKey(key)
            setSortDir("asc")
        }
        setPage(1)
    }

    const SortIcon = ({ col }: { col: SortKey }) => {
        if (sortKey !== col) return <ChevronsUpDown className="w-3 h-3 opacity-40" />
        return sortDir === "asc" ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
    }

    const buttonClass = "flex items-center gap-1 hover:text-teal-700 dark:hover:text-teal-400 transition-colors"
    const thCls = "px-3 py-2 text-left font-semibold text-xs text-foreground whitespace-nowrap select-none"

    if (!isVisible) {
        return (
            <div ref={ref} className="rounded-lg border border-border bg-muted/20 my-2 h-28 flex items-center justify-center text-xs text-muted-foreground">
                {visualization.title}
            </div>
        )
    }

    if (!rows.length && !fetchError) {
        return (
            <div ref={ref} className="rounded-lg border border-border bg-muted/20 my-2 h-28 flex items-center justify-center text-xs text-muted-foreground animate-pulse">
                Loading {visualization.title}…
            </div>
        )
    }

    return (
        <div ref={ref} className="rounded-lg border border-border bg-white dark:bg-gray-950 overflow-hidden shadow-sm my-2">
            <div className="overflow-x-auto">
                <table className="w-full text-xs border-collapse">
                    <thead>
                        <tr className="bg-muted/40 border-b border-border">
                            <th className={thCls}>
                                <button type="button" className={buttonClass} onClick={() => handleSort("rank")}>
                                    # <SortIcon col="rank" />
                                </button>
                            </th>
                            <th className={thCls}>
                                <button type="button" className={buttonClass} onClick={() => handleSort("label")}>
                                    {resolvedViz.row_label} <SortIcon col="label" />
                                </button>
                            </th>
                            <th className={thCls}>
                                <button type="button" className={buttonClass} onClick={() => handleSort("studies")}>
                                    Studies <SortIcon col="studies" />
                                </button>
                            </th>
                            <th className={thCls}>
                                <button type="button" className={buttonClass} onClick={() => handleSort("avg_auroc")}>
                                    Avg AUROC <SortIcon col="avg_auroc" />
                                </button>
                            </th>
                            <th className={thCls}>
                                <button type="button" className={buttonClass} onClick={() => handleSort("meta_fdr")}>
                                    Meta-FDR <SortIcon col="meta_fdr" />
                                </button>
                            </th>
                            <th className={thCls}>
                                <button type="button" className={buttonClass} onClick={() => handleSort("direction")}>
                                    Direction <SortIcon col="direction" />
                                </button>
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {pageRows.map((row, i) => (
                            <tr key={`${row.label}-${row.rank}`} className={`border-t border-border/40 hover:bg-muted/20 transition-colors ${i % 2 === 1 ? "bg-muted/10" : ""}`}>
                                <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{row.rank}</td>
                                <td className="px-3 py-1.5 font-medium text-foreground">{row.label}</td>
                                <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{row.studies ?? "—"}</td>
                                <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{formatAuroc(row.avg_auroc)}</td>
                                <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{formatMetaFdr(row)}</td>
                                <td className="px-3 py-1.5 whitespace-nowrap">
                                    {row.direction === "sensitive" ? (
                                        <span className="font-medium text-teal-600 dark:text-teal-400">{directionText(row.direction)}</span>
                                    ) : row.direction === "resistant" ? (
                                        <span className="font-medium text-rose-600 dark:text-rose-400">{directionText(row.direction)}</span>
                                    ) : (
                                        directionText(row.direction)
                                    )}
                                </td>
                            </tr>
                        ))}
                        {pageRows.length === 0 && (
                            <tr>
                                <td colSpan={6} className="px-3 py-6 text-center text-muted-foreground italic">No results.</td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            <div className="flex items-center justify-between px-3 py-2 border-t border-border/50 bg-muted/10 gap-2 flex-wrap">
                <span className="text-xs text-muted-foreground">
                    {rows.length} result{rows.length !== 1 ? "s" : ""}
                </span>
                {totalPages > 1 && (
                    <div className="flex items-center gap-1">
                        <button
                            type="button"
                            onClick={() => setPage((p) => Math.max(1, p - 1))}
                            disabled={currentPage === 1}
                            className="px-2 py-0.5 text-xs rounded border border-border disabled:opacity-40 hover:bg-muted/40 transition-colors"
                        >‹</button>
                        <span className="px-1 text-xs text-muted-foreground">
                            Page {currentPage} / {totalPages}
                        </span>
                        <button
                            type="button"
                            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                            disabled={currentPage === totalPages}
                            className="px-2 py-0.5 text-xs rounded border border-border disabled:opacity-40 hover:bg-muted/40 transition-colors"
                        >›</button>
                    </div>
                )}
            </div>

            {resolvedViz.description && (
                <div className="px-3 py-2 border-t border-border/50 bg-muted/10 text-xs text-muted-foreground leading-relaxed">
                    {resolvedViz.description}
                </div>
            )}
        </div>
    )
}
