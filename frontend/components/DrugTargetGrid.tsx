"use client"
import { useState, useCallback, useEffect } from "react"
import { createPortal } from "react-dom"
import { X } from "lucide-react"
import type { DrugTargetVisualization } from "@/lib/api"

const API_URL = process.env.NEXT_PUBLIC_API_URL || ""

// Tier badge color
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

interface Props {
    visualization: DrugTargetVisualization
}

export function DrugTargetGrid({ visualization }: Props) {
    const { gene, tier, family, drugs, drug_tiers, features, cohorts, presence, plot_map, hyper_sites } = visualization

    const [selected, setSelected] = useState<{ label: string; cohort: string; plot_ids: string[] } | null>(null)

    const handleCellClick = useCallback((feat_label: string, feat_field: string, cohort: string) => {
        const pids = plot_map?.[feat_field]?.[cohort]
        if (!pids?.length) return
        setSelected({ label: feat_label, cohort, plot_ids: pids })
    }, [plot_map])

    const closeModal = useCallback(() => setSelected(null), [])

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

    const drugList = drugs ? drugs.split(";").map(d => d.trim()).filter(Boolean) : []
    const tierList = drug_tiers ? drug_tiers.split(";").map(t => t.trim()) : []

    const hasAnyPlot = Object.keys(plot_map || {}).length > 0

    return (
        <div className="rounded-lg border border-border bg-white dark:bg-gray-950 overflow-hidden">
            {/* Header: tier + family + drug pills */}
            <div className="px-3 py-2 border-b border-border bg-muted/30">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className="font-semibold text-sm">{gene}</span>
                    {tier && <TierBadge tier={tier} />}
                    {family && <span className="text-xs text-muted-foreground">{family}</span>}
                </div>
                {drugList.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                        {drugList.slice(0, 12).map((drug, i) => {
                            const t = tierList[i] ?? ""
                            return (
                                <span key={i} className={`text-xs px-1.5 py-0.5 rounded border ${
                                    t === "T1" ? "border-green-400 bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-300" :
                                    t === "T2" ? "border-blue-400 bg-blue-50 text-blue-800 dark:bg-blue-950 dark:text-blue-300" :
                                    "border-gray-300 bg-gray-50 text-gray-700 dark:bg-gray-800 dark:text-gray-300"
                                }`}>{drug}</span>
                            )
                        })}
                        {drugList.length > 12 && (
                            <span className="text-xs text-muted-foreground self-center">+{drugList.length - 12} more</span>
                        )}
                    </div>
                )}
            </div>

            {/* Grid */}
            <div className="p-3 overflow-x-auto">
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
                        {features.map((feat, ri) => (
                            <tr key={feat.field}>
                                <td className="pr-4 py-0.5 text-muted-foreground whitespace-nowrap text-[12px]">{feat.label}</td>
                                {cohorts.map((cohort, ci) => {
                                    const isPos = presence[ri]?.[ci]
                                    const hasPlot = !!plot_map?.[feat.field]?.[cohort]?.length
                                    return (
                                        <td key={cohort} className="px-0.5 py-0.5">
                                            <div
                                                className={`w-9 h-[26px] border rounded-sm transition-colors ${
                                                    isPos
                                                        ? `bg-[#2d6a2d] border-[#1e4d1e] ${hasPlot ? "cursor-pointer hover:bg-[#1a4a1a]" : ""}`
                                                        : "bg-[#f5f5f5] dark:bg-gray-800 border-gray-300 dark:border-gray-600"
                                                }`}
                                                onClick={() => isPos && hasPlot && handleCellClick(feat.label, feat.field, cohort)}
                                                title={isPos && hasPlot ? `Click to view: ${feat.label} — ${cohort}` : undefined}
                                            />
                                        </td>
                                    )
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>

                {/* Legend */}
                <div className="flex items-center gap-4 mt-2.5 text-xs text-muted-foreground">
                    <div className="flex items-center gap-1.5">
                        <div className="w-4 h-4 bg-[#2d6a2d] border border-[#1e4d1e] rounded-sm" />
                        <span>Significant</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                        <div className="w-4 h-4 bg-[#f5f5f5] dark:bg-gray-800 border border-gray-300 rounded-sm" />
                        <span>Not significant / NA</span>
                    </div>
                    {hasAnyPlot && (
                        <span className="italic">Click green cell to view supporting plot</span>
                    )}
                </div>

                {/* Hyperactivated phospho sites footer */}
                {hyper_sites && hyper_sites.length > 0 && (
                    <div className="mt-2 text-xs text-muted-foreground italic">
                        Hyperactivated phospho sites:{" "}
                        {hyper_sites.map(s => `${s.site} (${s.cohorts.join(", ")})`).join("  |  ")}
                    </div>
                )}
            </div>

            {/* Boxplot modal */}
            {selected && typeof document !== "undefined" && createPortal(
                <div
                    className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-sm"
                    onClick={closeModal}
                >
                    <div
                        className="relative bg-white dark:bg-gray-950 rounded-lg shadow-2xl flex flex-col"
                        style={{ maxWidth: "92vw", maxHeight: "92vh" }}
                        onClick={e => e.stopPropagation()}
                    >
                        {/* Modal toolbar */}
                        <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-muted/30 rounded-t-lg flex-shrink-0">
                            <span className="text-sm font-medium flex-1 truncate">
                                {gene} — {selected.label} — {selected.cohort}
                            </span>
                            <button onClick={closeModal} className="p-1 rounded hover:bg-accent text-muted-foreground" title="Close">
                                <X className="h-4 w-4" />
                            </button>
                        </div>
                        {/* Plot images */}
                        <div className="overflow-auto p-4 flex flex-wrap gap-4 justify-center">
                            {selected.plot_ids.map((pid, i) => (
                                <img
                                    key={i}
                                    src={`${API_URL}/api/v1/chat/drugtargets/${gene}/${pid}`}
                                    alt={pid.replace(/_/g, " ")}
                                    className="max-h-[75vh] w-auto"
                                    onError={e => { (e.target as HTMLImageElement).style.display = "none" }}
                                />
                            ))}
                        </div>
                    </div>
                </div>,
                document.body
            )}
        </div>
    )
}
