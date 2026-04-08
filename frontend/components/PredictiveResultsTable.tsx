"use client"

import { useEffect, useMemo, useState } from "react"
import { createPortal } from "react-dom"
import { ChevronDown, ChevronUp, ChevronsUpDown, X, Download, Maximize2, Minimize2 } from "lucide-react"
import type { PredictiveResultsTableVisualization } from "@/lib/api"
import { useLazyVisible } from "@/hooks/useLazyVisible"
import { getAuthToken } from "@/lib/auth"

const API_URL = process.env.NEXT_PUBLIC_API_URL || ""
const PAGE_SIZE = 15

type SortKey = "rank" | "label" | "studies" | "avg_auroc" | "meta_fdr" | "meta_fdr_signed" | "direction" | "series" | "disease" | "subtype" | "p_value" | "response_evaluation"
type SortDir = "asc" | "desc"

type Row = NonNullable<PredictiveResultsTableVisualization["rows"]>[number]

interface Props {
    visualization: PredictiveResultsTableVisualization
}

function formatAuroc(value?: number) {
    return typeof value === "number" ? value.toFixed(3).replace(/\.?0+$/, (m) => (m === ".000" ? "" : m)) : "—"
}

function formatMetaFdr(row: Row) {
    if (row.meta_fdr_sci) return row.meta_fdr_sci
    if (typeof row.meta_fdr === "number") return row.meta_fdr.toExponential(3)
    return "—"
}

function directionText(direction?: string) {
    return direction === "sensitive" ? "↑ Sensitive" : direction === "resistant" ? "↓ Resistant" : "—"
}

// ── Plot modal ────────────────────────────────────────────────────────────────

interface PlotData {
    png_b64: string
    title: string
}

interface PlotModalProps {
    gene: string
    plotType?: "gene_set" | "treatment_gene" | "treatment_gene_set"
    studyList?: string[]
    row: Row
    onClose: () => void
}

function PlotModal({ gene, plotType, studyList, row, onClose }: PlotModalProps) {
    const [plots, setPlots] = useState<PlotData[] | null>(null)
    const [resolvedStudyId, setResolvedStudyId] = useState<string>("")
    const [error, setError] = useState(false)
    const [fitToWindow, setFitToWindow] = useState(false)

    const study = row.study_id || row.series || ""
    const manyStudies = (studyList?.length ?? 0) > 10

    useEffect(() => {
        const token = getAuthToken()
        const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {}

        if (plotType === "treatment_gene" || plotType === "treatment_gene_set") {
            if (!studyList?.length) { setError(true); return }
            const url = `${API_URL}/api/v1/chat/trial-plot?gene=${encodeURIComponent(gene)}&plot_type=${encodeURIComponent(plotType)}`
            fetch(url, {
                method: "POST",
                headers: { ...headers, "Content-Type": "application/json" },
                body: JSON.stringify({ study_list: studyList }),
            })
                .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
                .then(data => {
                    setPlots(data.plots ?? [])
                    setResolvedStudyId(gene)
                })
                .catch(() => setError(true))
            return
        }

        if (!study) { setError(true); return }
        const treatmentParam = row.label ? `&treatment=${encodeURIComponent(row.label)}` : ""
        const plotTypeParam = plotType ? `&plot_type=${encodeURIComponent(plotType)}` : ""
        const url = `${API_URL}/api/v1/chat/trial-plot?gene=${encodeURIComponent(gene)}&study=${encodeURIComponent(study)}${treatmentParam}${plotTypeParam}`
        fetch(url, { headers })
            .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
            .then(data => {
                setPlots(data.plots ?? [])
                setResolvedStudyId(data.resolved_study_id ?? study)
            })
            .catch(() => setError(true))
    }, [gene, study, plotType, studyList])

    const diseaseStr = [row.disease, row.subtype].filter(Boolean).join(" · ")

    return createPortal(
        <>
            {/* Main modal */}
            <div
                className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
                onClick={onClose}
            >
                <div
                    className="relative bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full flex flex-col"
                    style={{ width: "min(88vw, 1200px)", maxHeight: "85vh" }}
                    onClick={e => e.stopPropagation()}
                >
                    {/* Header */}
                    <div className="flex items-start justify-between px-6 py-4 border-b border-border/60 shrink-0">
                        <div className="min-w-0 pr-4">
                            <div className="flex items-center gap-2 flex-wrap">
                                <span className="font-bold text-base text-foreground">{gene}</span>
                                <span className="text-muted-foreground">·</span>
                                <span className="font-medium text-sm text-foreground/80">
                                    {(plotType === "treatment_gene" || plotType === "treatment_gene_set")
                                        ? `${studyList?.length ?? 0} studies`
                                        : (resolvedStudyId || study)}
                                </span>
                            </div>
                            <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1">
                                {row.label && (
                                    <span className="text-xs text-muted-foreground">{row.label}</span>
                                )}
                                {diseaseStr && (
                                    <span className="text-xs text-muted-foreground/70">{diseaseStr}</span>
                                )}
                            </div>
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                            {plots && plots.length > 0 && (
                                <button
                                    type="button"
                                    onClick={() => setFitToWindow(v => !v)}
                                    className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-muted/50 transition-colors text-muted-foreground hover:text-foreground text-xs"
                                    title={fitToWindow ? "Show actual size" : "Fit to window"}
                                >
                                    {fitToWindow
                                        ? <><Maximize2 className="w-3.5 h-3.5" /><span>Actual size</span></>
                                        : <><Minimize2 className="w-3.5 h-3.5" /><span>Fit to window</span></>}
                                </button>
                            )}
                            <button
                                type="button"
                                onClick={onClose}
                                className="p-1.5 rounded-lg hover:bg-muted/50 transition-colors text-muted-foreground hover:text-foreground"
                            >
                                <X className="w-4 h-4" />
                            </button>
                        </div>
                    </div>

                    {/* Body */}
                    <div className="overflow-y-auto p-6 flex flex-col gap-6">
                        {!plots && !error && (
                            <div className="flex flex-col items-center gap-4 py-10">
                                <svg className="animate-spin w-8 h-8 text-teal-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                                </svg>
                                <span className="text-sm text-muted-foreground">Loading plots…</span>
                            </div>
                        )}

                        {error && (
                            <div className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
                                <span className="text-sm">Plot data not available for this study.</span>
                            </div>
                        )}

                        {plots && plots.length === 0 && (
                            <div className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
                                <span className="text-sm">No plottable data returned for this study.</span>
                            </div>
                        )}

                        {plots && plots.map((p, i) => {
                            const filename = `${gene}_${study}_${p.title?.replace(/\s+/g, "_") ?? i}.png`
                            return (
                                <div key={i} className="flex flex-col gap-2">
                                    <div className="flex items-center gap-2 px-0.5">
                                        {p.title && (
                                            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide flex-1">
                                                {p.title}
                                            </div>
                                        )}
                                        <a
                                            href={`data:image/png;base64,${p.png_b64}`}
                                            download={filename}
                                            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                                            title="Download PNG"
                                        >
                                            <Download className="w-3.5 h-3.5" />
                                        </a>
                                    </div>
                                    <div className={`rounded-xl border border-border/50 shadow-sm bg-white dark:bg-gray-950 ${fitToWindow ? "flex items-center justify-center overflow-hidden" : "overflow-x-auto"}`}>
                                        {/* eslint-disable-next-line @next/next/no-img-element */}
                                        <img
                                            src={`data:image/png;base64,${p.png_b64}`}
                                            alt={p.title}
                                            style={fitToWindow
                                                ? { display: "block", maxWidth: "100%", maxHeight: "calc(85vh - 100px)", width: "auto", height: "auto" }
                                                : { display: "block", maxWidth: "none", height: "auto" }}
                                        />
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </div>
            </div>

        </>,
        document.body
    )
}

// ── Main table ────────────────────────────────────────────────────────────────

export function PredictiveResultsTable({ visualization }: Props) {
    const { ref, isVisible } = useLazyVisible()
    const [resolvedViz, setResolvedViz] = useState<PredictiveResultsTableVisualization>(visualization)
    const [fetchError, setFetchError] = useState(false)
    const [page, setPage] = useState(1)
    const [sortKey, setSortKey] = useState<SortKey>("rank")
    const [sortDir, setSortDir] = useState<SortDir>("asc")
    const [selectedRow, setSelectedRow] = useState<Row | null>(null)

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
        const numericKeys = new Set<SortKey>(["rank", "studies", "avg_auroc", "meta_fdr", "meta_fdr_signed", "p_value"])
        return [...rows].sort((a, b) => {
            if (numericKeys.has(sortKey)) {
                let av = Number((a as Record<string, unknown>)[sortKey] ?? 0)
                let bv = Number((b as Record<string, unknown>)[sortKey] ?? 0)
                // meta_fdr sorts by absolute value (smallest = most significant first)
                if (sortKey === "meta_fdr") {
                    av = Math.abs(Number((a as Record<string, unknown>).meta_fdr_signed ?? av))
                    bv = Math.abs(Number((b as Record<string, unknown>).meta_fdr_signed ?? bv))
                }
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

    const gene = resolvedViz.gene
    const isTreatmentGene = resolvedViz.plot_type === "treatment_gene" || resolvedViz.plot_type === "treatment_gene_set"
    const isClickable = !!gene || isTreatmentGene
    const isClinicalTrial = resolvedViz.variant === "clinical_trial"
    const colStudies = resolvedViz.col_studies ?? "Studies"
    const colAuroc = resolvedViz.col_auroc ?? "Avg AUROC"
    const colFdr = resolvedViz.col_fdr ?? "Meta-FDR"

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
        <>
            <div ref={ref} className="rounded-lg border border-border bg-white dark:bg-gray-950 overflow-hidden shadow-sm my-2">
                {isClickable && (
                    <div className="px-3 py-1.5 bg-muted/20 border-b border-border/40 text-xs text-muted-foreground">
                        Click a row to view expression plots
                    </div>
                )}
                <div className="overflow-x-auto">
                    <table className="w-full text-xs border-collapse">
                        <thead>
                            <tr className="bg-muted/40 border-b border-border">
                                {isClinicalTrial ? (<>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("p_value")}>p value <SortIcon col="p_value" /></button></th>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("meta_fdr")}>FDR <SortIcon col="meta_fdr" /></button></th>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("avg_auroc")}>AUROC <SortIcon col="avg_auroc" /></button></th>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("series")}>Series <SortIcon col="series" /></button></th>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("disease")}>Disease <SortIcon col="disease" /></button></th>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("subtype")}>Subtype <SortIcon col="subtype" /></button></th>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("label")}>Treatment <SortIcon col="label" /></button></th>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("response_evaluation")}>Response Evaluation <SortIcon col="response_evaluation" /></button></th>
                                </>) : (<>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("rank")}># <SortIcon col="rank" /></button></th>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("label")}>{resolvedViz.row_label} <SortIcon col="label" /></button></th>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("studies")}>{colStudies} <SortIcon col="studies" /></button></th>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("avg_auroc")}>{colAuroc} <SortIcon col="avg_auroc" /></button></th>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("meta_fdr")}>{colFdr} <SortIcon col="meta_fdr" /></button></th>
                                    <th className={thCls}><button type="button" className={buttonClass} onClick={() => handleSort("direction")}>Direction <SortIcon col="direction" /></button></th>
                                </>)}
                            </tr>
                        </thead>
                        <tbody>
                            {pageRows.map((row, i) => {
                                const trClass = [
                                    "border-t border-border/40 transition-colors",
                                    i % 2 === 1 ? "bg-muted/10" : "",
                                    isClickable ? "cursor-pointer hover:bg-teal-50 dark:hover:bg-teal-950/30" : "hover:bg-muted/20",
                                ].join(" ")
                                const onClick = isClickable ? () => setSelectedRow(row) : undefined
                                const dirCell = (
                                    <td className="px-3 py-1.5 whitespace-nowrap">
                                        {row.direction === "sensitive" ? (
                                            <span className="font-medium text-teal-600 dark:text-teal-400">{directionText(row.direction)}</span>
                                        ) : row.direction === "resistant" ? (
                                            <span className="font-medium text-rose-600 dark:text-rose-400">{directionText(row.direction)}</span>
                                        ) : directionText(row.direction)}
                                    </td>
                                )
                                if (isClinicalTrial) {
                                    const pVal = typeof row.p_value === "number" ? row.p_value.toExponential(3) : "—"
                                    const fdr = typeof row.meta_fdr === "number" ? row.meta_fdr.toFixed(4) : "—"
                                    return (
                                        <tr key={`${row.series}-${row.rank}`} onClick={onClick} className={trClass}>
                                            <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{pVal}</td>
                                            <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{fdr}</td>
                                            <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{formatAuroc(row.avg_auroc)}</td>
                                            <td className="px-3 py-1.5 whitespace-nowrap font-medium">{row.series ?? "—"}</td>
                                            <td className="px-3 py-1.5 whitespace-nowrap">{row.disease ?? "—"}</td>
                                            <td className="px-3 py-1.5 whitespace-nowrap">{row.subtype || "—"}</td>
                                            <td className="px-3 py-1.5">{row.label}</td>
                                            <td className="px-3 py-1.5 whitespace-nowrap">{row.response_evaluation || "—"}</td>
                                        </tr>
                                    )
                                }
                                return (
                                    <tr key={`${row.label}-${row.rank}`} onClick={onClick} className={trClass}>
                                        <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{row.rank}</td>
                                        <td className="px-3 py-1.5 font-medium text-foreground">
                                            <div>{row.label}</div>
                                            {(row.disease || row.subtype) && (
                                                <div className="text-muted-foreground font-normal text-[10px]">
                                                    {[row.disease, row.subtype].filter(Boolean).join(" · ")}
                                                </div>
                                            )}
                                        </td>
                                        <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{row.studies ?? "—"}</td>
                                        <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{formatAuroc(row.avg_auroc)}</td>
                                        <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{formatMetaFdr(row)}</td>
                                        {dirCell}
                                    </tr>
                                )
                            })}
                            {pageRows.length === 0 && (
                                <tr>
                                    <td colSpan={isClinicalTrial ? 8 : 6} className="px-3 py-6 text-center text-muted-foreground italic">No results.</td>
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

            {selectedRow && (gene || isTreatmentGene) && (
                <PlotModal
                    gene={isTreatmentGene ? (selectedRow.label || gene || "") : (gene || "")}
                    plotType={resolvedViz.plot_type}
                    studyList={resolvedViz.study_list}
                    row={selectedRow}
                    onClose={() => setSelectedRow(null)}
                />
            )}
        </>
    )
}
