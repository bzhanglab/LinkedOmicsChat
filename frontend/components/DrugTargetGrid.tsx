"use client"
import { useState, useCallback, useEffect, Fragment } from "react"
import { createPortal } from "react-dom"
import { X, ChevronDown, ChevronRight, Maximize2, Minimize2 } from "lucide-react"
import type { DrugTargetVisualization, DrugDetail } from "@/lib/api"
import { useLazyVisible } from "@/hooks/useLazyVisible"
import { getAuthToken } from "@/lib/auth"

const API_URL = process.env.NEXT_PUBLIC_API_URL || ""

function TierBadge({ tier }: { tier: string }) {
    const colors: Record<string, string> = {
        T1: "bg-green-100 text-green-800 border-green-300",
        T2: "bg-blue-100 text-blue-800 border-blue-300",
        T3: "bg-yellow-100 text-yellow-800 border-yellow-300",
        T4: "bg-orange-100 text-orange-800 border-orange-300",
        T5: "bg-gray-100 text-gray-700 border-gray-300",
    }
    return (
        <span className={`text-xs px-1.5 py-0.5 rounded border font-medium ${colors[tier] ?? "bg-gray-100 text-gray-700 border-gray-300"}`}>
            {tier}
        </span>
    )
}

const TIER_LABELS: Record<string, string> = {
    T1: "Approved oncology drugs",
    T2: "Approved non-oncology drugs",
    T3: "Investigational drugs",
    T4: "Pre-clinical / druggable",
    T5: "Surface proteins",
}

const TIER_STYLES: Record<string, { header: string; row: string }> = {
    T1: { header: "bg-green-50 text-green-900 dark:bg-green-950 dark:text-green-200", row: "hover:bg-green-50 dark:hover:bg-green-950/40" },
    T2: { header: "bg-blue-50 text-blue-900 dark:bg-blue-950 dark:text-blue-200", row: "hover:bg-blue-50 dark:hover:bg-blue-950/40" },
    T3: { header: "bg-yellow-50 text-yellow-900 dark:bg-yellow-950 dark:text-yellow-200", row: "hover:bg-yellow-50 dark:hover:bg-yellow-950/40" },
    T4: { header: "bg-orange-50 text-orange-900 dark:bg-orange-950 dark:text-orange-200", row: "hover:bg-orange-50 dark:hover:bg-orange-950/40" },
    T5: { header: "bg-gray-50 text-gray-700 dark:bg-gray-800 dark:text-gray-300", row: "hover:bg-gray-50 dark:hover:bg-gray-800/40" },
}

const SUMMARY_FIELD = "tumor_increase_summary"

interface Props {
    visualization: DrugTargetVisualization
}

export function DrugTargetGrid({ visualization }: Props) {
    const { ref, isVisible } = useLazyVisible()

    // For historical messages, the DB only stores slim metadata (gene, tier, family).
    // Fetch the full viz from disk when scrolled into view.
    const [resolvedViz, setResolvedViz] = useState<DrugTargetVisualization>(
        visualization.features ? visualization : visualization
    )
    const [fetchError, setFetchError] = useState(false)

    useEffect(() => {
        if (!isVisible) return
        if (resolvedViz.features) return  // already have full data
        if (!visualization.id) return
        const token = getAuthToken()
        fetch(`${API_URL}/api/v1/chat/visualizations/${encodeURIComponent(visualization.id)}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
            .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
            .then(data => {
                if (data?.type === "drug_target_grid") setResolvedViz({ ...visualization, ...data })
                else setFetchError(true)
            })
            .catch(() => setFetchError(true))
    }, [isVisible, resolvedViz.features, visualization])

    const { gene, tier, family, drugs, drug_tiers, drug_details, features, cohorts, presence, plot_map, table_map, hyper_sites, protein_cohorts } = resolvedViz

    // Whether the "Increased in tumor, summary" sub-rows are expanded
    const [summaryExpanded, setSummaryExpanded] = useState(false)

    // Single active cell for red highlight — persists after modal closes
    const [activeCell, setActiveCell] = useState<{ field: string; cohort: string } | null>(null)

    // Currently open modal
    const [selected, setSelected] = useState<{
        field: string
        label: string
        cohort: string
        plot_ids?: string[]
        table_rows?: Record<string, string | number | null>[]
    } | null>(null)

    const handleCellClick = useCallback((feat_label: string, feat_field: string, cohort: string) => {
        setActiveCell(prev => {
            if (prev?.field === feat_field && prev?.cohort === cohort) return null  // deselect, no modal
            // Select and open modal
            const pids = plot_map?.[feat_field]?.[cohort]
            if (pids?.length) setSelected({ field: feat_field, label: feat_label, cohort, plot_ids: pids })
            else {
                const rows = table_map?.[feat_field]?.[cohort]
                if (rows?.length) setSelected({ field: feat_field, label: feat_label, cohort, table_rows: rows })
            }
            return { field: feat_field, cohort }
        })
    }, [plot_map, table_map])

    const closeModal = useCallback(() => { setSelected(null); setModalFit(false) }, [])
    const [modalFit, setModalFit] = useState(false)

    useEffect(() => {
        if (!selected) return
        const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeModal() }
        document.addEventListener("keydown", onKey)
        document.body.style.overflow = "hidden"
        return () => {
            document.removeEventListener("keydown", onKey)
            document.body.style.overflow = ""
        }
    }, [selected, closeModal])

    // Build structured drug list: prefer drug_details from HTML, fall back to legacy semicolon strings
    const drugsByTier: Map<string, DrugDetail[]> = new Map()
    if (drug_details && drug_details.length > 0) {
        for (const d of drug_details) {
            if (!d.name || d.name === "NA") continue
            if (!drugsByTier.has(d.tier)) drugsByTier.set(d.tier, [])
            drugsByTier.get(d.tier)!.push(d)
        }
    } else {
        const drugList = drugs ? drugs.split(";").map(d => d.trim()).filter(d => d && d !== "NA") : []
        const tierList = drug_tiers ? drug_tiers.split(";").map(t => t.trim()) : []
        drugList.forEach((name, i) => {
            const t = tierList[i] ?? "T5"
            if (!drugsByTier.has(t)) drugsByTier.set(t, [])
            drugsByTier.get(t)!.push({ name, tier: t, databases: [], indication: null })
        })
    }

    const DRUG_TABLE_LIMIT = 5
    const [expandedTiers, setExpandedTiers] = useState<Set<string>>(new Set())
    const toggleTier = useCallback((t: string) => {
        setExpandedTiers(prev => {
            const next = new Set(prev)
            next.has(t) ? next.delete(t) : next.add(t)
            return next
        })
    }, [])

    // Cell className helper
    const cellCls = (isPos: boolean | undefined, clickable: boolean, isActive: boolean) => {
        const base = "w-9 h-[26px] rounded-sm transition-colors"
        if (isActive) return `${base} cursor-pointer bg-red-500 border border-red-700`
        if (isPos) return `${base} bg-[#0d9488] border border-[#0a7c72] ${clickable ? "cursor-pointer hover:bg-[#0a7c72]" : ""}`
        return `${base} bg-[#f5f5f5] dark:bg-gray-800 border border-gray-300 dark:border-gray-600`
    }

    const hasAnyInteractive = Object.keys(plot_map || {}).length > 0 || Object.keys(table_map || {}).length > 0

    if (!isVisible) {
        return (
            <div ref={ref} className="rounded-lg border border-border bg-muted/20 h-32 flex items-center justify-center text-xs text-muted-foreground">
                Drug target profile: {visualization.gene}
            </div>
        )
    }

    if (!features || !cohorts || !presence) {
        return fetchError ? (
            <div ref={ref} className="rounded-lg border border-border bg-muted/20 h-16 flex items-center justify-center text-xs text-muted-foreground">
                Drug target profile: {gene} (data unavailable)
            </div>
        ) : (
            <div ref={ref} className="rounded-lg border border-border bg-muted/20 h-32 flex items-center justify-center text-xs text-muted-foreground animate-pulse">
                Loading {visualization.gene}…
            </div>
        )
    }

    return (
        <div ref={ref} className="rounded-lg border border-border bg-white dark:bg-gray-950 overflow-hidden">
            {/* Header */}
            <div className="px-3 py-2 border-b border-border bg-muted/30">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-sm">{gene}</span>
                    {tier && tier !== "NA" && <TierBadge tier={tier} />}
                    {family && family !== "Other" && family !== "NA" && <span className="text-xs text-muted-foreground">{family}</span>}
                </div>
            </div>

            {/* Drug tables per tier */}
            {drugsByTier.size > 0 && (
                <div className="px-3 pt-3 pb-2 flex flex-wrap gap-4 items-start">
                    {Array.from(drugsByTier.entries()).map(([t, details]) => {
                        const expanded = expandedTiers.has(t)
                        const visible = expanded ? details : details.slice(0, DRUG_TABLE_LIMIT)
                        const hidden = details.length - DRUG_TABLE_LIMIT
                        const hasLinks = details.some(d => d.databases.length > 0 || d.indication)
                        return (
                            <div key={t} className="border border-border rounded-lg overflow-hidden flex-shrink-0 shadow-sm bg-white dark:bg-gray-950">
                                {/* Card title */}
                                <div className="px-3 py-2 border-b border-border">
                                    <span className="text-sm font-semibold text-foreground">{TIER_LABELS[t] ?? t}</span>
                                </div>
                                <table className="text-xs border-collapse w-full">
                                    <thead>
                                        <tr className="bg-muted/40 border-b border-border">
                                            <th className="px-3 py-1.5 text-left font-bold text-foreground whitespace-nowrap">Name</th>
                                            {hasLinks && <th className="px-3 py-1.5 text-left font-bold text-foreground whitespace-nowrap">Database</th>}
                                            {hasLinks && <th className="px-3 py-1.5 text-left font-bold text-foreground whitespace-nowrap">Indication</th>}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {visible.map((d, j) => (
                                            <tr key={j} className="border-t border-border/40 hover:bg-muted/20 transition-colors">
                                                <td className="px-3 py-1.5 whitespace-nowrap text-foreground">{d.name}</td>
                                                {hasLinks && (
                                                    <td className="px-3 py-1.5">
                                                        {d.databases.length > 0
                                                            ? <span className="flex flex-wrap gap-1">
                                                                {d.databases.map((db, k) => (
                                                                    <a
                                                                        key={k}
                                                                        href={db.url}
                                                                        target="_blank"
                                                                        rel="noopener noreferrer"
                                                                        className="inline-block px-1.5 py-0.5 rounded border border-teal-200 bg-teal-50 text-teal-700 text-[11px] font-medium hover:bg-teal-100 hover:border-teal-300 transition-colors no-underline dark:bg-teal-950 dark:border-teal-800 dark:text-teal-300 dark:hover:bg-teal-900"
                                                                    >{db.name}</a>
                                                                ))}
                                                            </span>
                                                            : <span className="text-muted-foreground">-</span>}
                                                    </td>
                                                )}
                                                {hasLinks && (
                                                    <td className="px-3 py-1.5">
                                                        {d.indication
                                                            ? <a
                                                                href={d.indication.url}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                className="inline-block px-1.5 py-0.5 rounded border border-teal-200 bg-teal-50 text-teal-700 text-[11px] font-medium hover:bg-teal-100 hover:border-teal-300 transition-colors no-underline dark:bg-teal-950 dark:border-teal-800 dark:text-teal-300 dark:hover:bg-teal-900"
                                                            >{d.indication.name}</a>
                                                            : <span className="text-muted-foreground">-</span>}
                                                    </td>
                                                )}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                                {details.length > DRUG_TABLE_LIMIT && (
                                    <button
                                        onClick={(e) => { e.stopPropagation(); toggleTier(t) }}
                                        className="w-full text-xs text-muted-foreground hover:text-foreground border-t border-border/50 px-3 py-1.5 text-left bg-transparent hover:bg-muted/20 transition-colors"
                                    >
                                        {expanded ? "Show less" : `+${hidden} more`}
                                    </button>
                                )}
                            </div>
                        )
                    })}
                </div>
            )}

            {/* Grid */}
            <div className={`p-3 overflow-x-auto ${drugsByTier.size > 0 ? "border-t border-border/50 mt-3" : ""}`}>
                <table className="border-collapse text-xs">
                    <thead>
                        <tr>
                            <th className="text-left pr-4 pb-1 text-muted-foreground font-normal min-w-[185px]" />
                            {cohorts.map(c => (
                                <th key={c} className="text-center px-0.5 pb-1 font-medium text-muted-foreground w-10 text-[11px]">{c}</th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {features.map((feat, ri) => {
                            // Skip sub-rows stored in older persisted sessions (now rendered dynamically)
                            if (feat.parent_field) return null
                            const isSummary = feat.field === SUMMARY_FIELD
                            return (
                                <Fragment key={feat.field}>
                                    {/* Main row */}
                                    <tr>
                                        <td className="pr-4 py-0.5 text-muted-foreground whitespace-nowrap text-[12px]">
                                            {isSummary ? (
                                                <button
                                                    className="flex items-center gap-0.5 hover:text-foreground transition-colors"
                                                    onClick={(e) => { e.stopPropagation(); setSummaryExpanded(p => !p) }}
                                                >
                                                    {summaryExpanded
                                                        ? <ChevronDown className="w-3 h-3 shrink-0" />
                                                        : <ChevronRight className="w-3 h-3 shrink-0" />}
                                                    {feat.label}
                                                </button>
                                            ) : feat.label}
                                        </td>
                                        {cohorts.map((cohort, ci) => {
                                            const isPos = presence[ri]?.[ci]
                                            const hasPlot = !!plot_map?.[feat.field]?.[cohort]?.length
                                            const hasTable = !!table_map?.[feat.field]?.[cohort]?.length
                                            const clickable = hasPlot || hasTable
                                            const isActive = activeCell?.field === feat.field && activeCell?.cohort === cohort && !!isPos
                                            return (
                                                <td key={cohort} className="px-0.5 py-0.5">
                                                    <div
                                                        className={cellCls(!!isPos, isSummary ? !!isPos : clickable, isActive)}
                                                        onClick={(e) => {
                                                            if (!isPos) return
                                                            e.stopPropagation()
                                                            if (isSummary) {
                                                                setSummaryExpanded(p => !p)
                                                                setActiveCell(prev => prev?.field === feat.field && prev?.cohort === cohort ? null : { field: feat.field, cohort })
                                                                return
                                                            }
                                                            if (clickable) handleCellClick(feat.label, feat.field, cohort)
                                                        }}
                                                        title={isPos
                                                            ? isSummary
                                                                ? summaryExpanded ? "Click to collapse" : "Click to expand"
                                                                : clickable ? `Click to view: ${feat.label} — ${cohort}` : undefined
                                                            : undefined}
                                                    />
                                                </td>
                                            )
                                        })}
                                    </tr>

                                    {/* Sub-rows: shown when chevron is expanded on summary row */}
                                    {isSummary && summaryExpanded && (() => {
                                        // Show ALL sub-rows for the gene (protein + all phospho sites).
                                        // Presence cells reflect the full cohort matrix for each sub-row.
                                        const subRows: Array<{
                                            label: string
                                            field: string
                                            presentCohorts: Set<string>
                                        }> = []

                                        // Protein: show if any cohort has protein overexpression
                                        const pCohorts = new Set(protein_cohorts ?? [])
                                        if (pCohorts.size > 0) {
                                            subRows.push({ label: "Protein", field: "tumor_increase_protein", presentCohorts: pCohorts })
                                        }

                                        // Phospho: show ALL sites (even those with no positive cohorts)
                                        for (const s of hyper_sites ?? []) {
                                            subRows.push({
                                                label: `Phospho: ${s.site}`,
                                                field: `phospho_${s.site}`,
                                                presentCohorts: new Set(s.cohorts),
                                            })
                                        }

                                        if (!subRows.length) return null
                                        return subRows.map(sub => (
                                            <tr key={sub.field} className="bg-muted/20">
                                                <td className="pr-4 py-0.5 whitespace-nowrap text-[12px] text-muted-foreground pl-5">
                                                    {sub.label}
                                                </td>
                                                {cohorts.map(cohort => {
                                                    const isPos = sub.presentCohorts.has(cohort)
                                                    const hasPlot = !!plot_map?.[sub.field]?.[cohort]?.length
                                                    const isActive = activeCell?.field === sub.field && activeCell?.cohort === cohort && isPos
                                                    return (
                                                        <td key={cohort} className="px-0.5 py-0.5">
                                                            <div
                                                                className={cellCls(isPos, hasPlot, isActive)}
                                                                onClick={(e) => {
                                                                    if (!isPos || !hasPlot) return
                                                                    e.stopPropagation()
                                                                    handleCellClick(sub.label, sub.field, cohort)
                                                                }}
                                                                title={isPos && hasPlot ? `Click to view: ${sub.label} — ${cohort}` : undefined}
                                                            />
                                                        </td>
                                                    )
                                                })}
                                            </tr>
                                        ))
                                    })()}
                                </Fragment>
                            )
                        })}
                    </tbody>
                </table>

                {/* Legend */}
                <div className="flex items-center gap-4 mt-2.5 text-xs text-muted-foreground">
                    <div className="flex items-center gap-1.5">
                        <div className="w-4 h-4 bg-[#0d9488] border border-[#0a7c72] rounded-sm" />
                        <span>Significant</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                        <div className="w-4 h-4 bg-[#f5f5f5] dark:bg-gray-800 border border-gray-300 rounded-sm" />
                        <span>Not significant / NA</span>
                    </div>
                    {hasAnyInteractive && (
                        <span className="italic">Click green cell to view supporting data</span>
                    )}
                </div>

                <div className="mt-2 text-xs text-muted-foreground italic">
                    *BRCA and GBM do not have normal samples.
                </div>
            </div>

            {/* Modal */}
            {selected && typeof document !== "undefined" && createPortal(
                <div
                    className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-sm"
                    onClick={closeModal}
                >
                    <div
                        className="relative bg-white dark:bg-gray-950 rounded-lg shadow-2xl flex flex-col"
                        style={{ width: "min(88vw, 1200px)", maxHeight: "85vh" }}
                        onClick={e => e.stopPropagation()}
                    >
                        <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-muted/30 rounded-t-lg flex-shrink-0">
                            <span className="text-sm font-medium flex-1 truncate">
                                {gene} — {selected.label} — {selected.cohort}
                            </span>
                            {selected.plot_ids && (
                                <button
                                    onClick={() => setModalFit(v => !v)}
                                    className="flex items-center gap-1 px-2 py-0.5 rounded hover:bg-accent text-muted-foreground text-xs"
                                    title={modalFit ? "Show actual size" : "Fit to window"}
                                >
                                    {modalFit ? <><Maximize2 className="h-3 w-3" /><span>Actual size</span></> : <><Minimize2 className="h-3 w-3" /><span>Fit to window</span></>}
                                </button>
                            )}
                            <button onClick={closeModal} className="p-1 rounded hover:bg-accent text-muted-foreground" title="Close">
                                <X className="h-4 w-4" />
                            </button>
                        </div>
                        {selected.plot_ids && (
                            <div className={`p-4 flex flex-wrap gap-4 justify-center ${modalFit ? "overflow-hidden items-center" : "overflow-auto"}`}>
                                {selected.plot_ids.map((pid, i) => (
                                    <img
                                        key={i}
                                        src={`${API_URL}/api/v1/chat/drugtargets/${gene}/${pid}`}
                                        alt={pid.replace(/_/g, " ")}
                                        style={modalFit
                                            ? { maxWidth: "100%", maxHeight: "calc(85vh - 56px)", width: "auto", height: "auto" }
                                            : { maxWidth: "none", height: "auto" }}
                                        onError={e => { (e.target as HTMLImageElement).style.display = "none" }}
                                    />
                                ))}
                            </div>
                        )}
                        {selected.table_rows && (
                            <div className="overflow-auto p-4">
                                <table className="text-xs border-collapse w-full">
                                    <thead>
                                        <tr className="bg-muted/50">
                                            {Object.keys(selected.table_rows[0] ?? {}).map(col => (
                                                <th key={col} className="px-3 py-1.5 text-left border border-border font-semibold whitespace-nowrap">
                                                    {col.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
                                                </th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {selected.table_rows.map((row, i) => (
                                            <tr key={i} className="border-t border-border hover:bg-muted/30">
                                                {Object.values(row).map((val, j) => (
                                                    <td key={j} className="px-3 py-1.5 border border-border">
                                                        {val ?? "—"}
                                                    </td>
                                                ))}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </div>,
                document.body
            )}
        </div>
    )
}
