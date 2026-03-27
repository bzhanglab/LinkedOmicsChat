"use client"
import { useRef, useState, useEffect, useMemo, useCallback } from "react"
import { createPortal } from "react-dom"
import { Download, Table, Maximize2, X, ZoomIn, ZoomOut, RotateCcw } from "lucide-react"
import type { AnyVisualization, StaticVisualization } from "@/lib/api"
import { getAuthToken } from "@/lib/auth"

interface AtRiskRow {
    time: number
    [group: string]: number
}

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
    const rows = Array.from(byTime.entries())
        .sort(([a], [b]) => a - b)
        .map(([time, vals]) => ({ time, ...vals }))

    return rows.length > 0 ? { rows, groups } : null
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || ""

interface StaticPlotProps {
    visualization: AnyVisualization
    className?: string
}

function downloadBlob(content: string, filename: string, mime: string) {
    const blob = new Blob([content], { type: mime })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
}

function downloadBase64(b64: string, filename: string, mime: string) {
    const byteStr = atob(b64)
    const buf = new Uint8Array(byteStr.length)
    for (let i = 0; i < byteStr.length; i++) buf[i] = byteStr.charCodeAt(i)
    const blob = new Blob([buf], { type: mime })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
}

function safeFilename(title: string) {
    return title.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "").toLowerCase()
}

export function StaticPlot({ visualization, className }: StaticPlotProps) {
    const containerRef = useRef<HTMLDivElement>(null)
    const [isVisible, setIsVisible] = useState(false)
    // resolvedViz holds the fully-loaded viz (with png_b64). For live messages it's
    // set immediately; for historical ones it's fetched from the API on first scroll.
    const [resolvedViz, setResolvedViz] = useState<StaticVisualization | null>(
        visualization.type === "static_plot" && (visualization as StaticVisualization).png_b64
            ? (visualization as StaticVisualization)
            : null
    )
    const [fetchError, setFetchError] = useState(false)
    const [showAtRisk, setShowAtRisk] = useState(false)
    const [lightboxOpen, setLightboxOpen] = useState(false)
    const [zoom, setZoom] = useState(1)

    const openLightbox  = useCallback(() => { setLightboxOpen(true); setZoom(1) }, [])
    const closeLightbox = useCallback(() => setLightboxOpen(false), [])

    const clampZoom = (z: number) => Math.min(5, Math.max(0.5, z))

    useEffect(() => {
        if (!lightboxOpen) return
        const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeLightbox() }
        document.addEventListener("keydown", onKey)
        document.body.style.overflow = "hidden"
        return () => {
            document.removeEventListener("keydown", onKey)
            document.body.style.overflow = ""
        }
    }, [lightboxOpen, closeLightbox])

    const atRiskData = useMemo(() => {
        if (!resolvedViz?.csv) return null
        return parseAtRiskCsv(resolvedViz.csv)
    }, [resolvedViz?.csv])

    // Lazy-render once scrolled into view
    useEffect(() => {
        const el = containerRef.current
        if (!el) return
        const observer = new IntersectionObserver(
            ([entry]) => { if (entry.isIntersecting) { setIsVisible(true); observer.disconnect() } },
            { rootMargin: "200px" }
        )
        observer.observe(el)
        return () => observer.disconnect()
    }, [])

    // Fetch full viz data from API when the plot scrolls into view and data is missing
    useEffect(() => {
        if (!isVisible) return
        if (resolvedViz) return  // already have data
        if (visualization.type !== "static_plot") return
        const viz = visualization as StaticVisualization
        if (!viz.id) return

        const token = getAuthToken()
        fetch(`${API_URL}/api/v1/chat/visualizations/${encodeURIComponent(viz.id)}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
            .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
            .then((data) => {
                if (data?.png_b64) setResolvedViz({ ...(visualization as StaticVisualization), ...data })
                else setFetchError(true)
            })
            .catch(() => setFetchError(true))
    }, [isVisible, resolvedViz, visualization])

    const viz = visualization as StaticVisualization

    return (
        <div ref={containerRef} className={className}>
            {isVisible && (
                resolvedViz ? (
                    <div className="rounded-lg border border-border bg-white dark:bg-gray-950 overflow-hidden">
                        {/* Plot image — click to expand */}
                        <div
                            className="relative p-2 flex justify-center cursor-zoom-in group"
                            onClick={openLightbox}
                        >
                            <img
                                src={`data:image/png;base64,${resolvedViz.png_b64}`}
                                alt={resolvedViz.title}
                                className="max-w-full h-auto"
                                style={{ maxHeight: "420px" }}
                            />
                            <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity bg-black/50 text-white rounded p-1">
                                <Maximize2 className="h-3.5 w-3.5" />
                            </div>
                        </div>

                        {/* Lightbox */}
                        {lightboxOpen && typeof document !== "undefined" && createPortal(
                            <div
                                className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 backdrop-blur-sm"
                                onClick={closeLightbox}
                            >
                                <div
                                    className="relative rounded-lg bg-white dark:bg-gray-950 shadow-2xl flex flex-col"
                                    style={{ maxWidth: "95vw", maxHeight: "95vh" }}
                                    onClick={e => e.stopPropagation()}
                                >
                                    {/* Lightbox toolbar */}
                                    <div className="flex items-center gap-1 px-2 py-1 border-b border-border bg-muted/30 rounded-t-lg flex-shrink-0">
                                        <span className="text-xs text-muted-foreground flex-1 truncate px-1">{resolvedViz.title}</span>
                                        <button onClick={() => setZoom(z => clampZoom(z * 1.25))} className="p-1 rounded hover:bg-accent text-muted-foreground" title="Zoom in"><ZoomIn className="h-3.5 w-3.5" /></button>
                                        <button onClick={() => setZoom(z => clampZoom(z / 1.25))} className="p-1 rounded hover:bg-accent text-muted-foreground" title="Zoom out"><ZoomOut className="h-3.5 w-3.5" /></button>
                                        <button onClick={() => setZoom(1)} className="p-1 rounded hover:bg-accent text-muted-foreground" title="Reset zoom"><RotateCcw className="h-3.5 w-3.5" /></button>
                                        <button onClick={closeLightbox} className="p-1 rounded hover:bg-accent text-muted-foreground" title="Close"><X className="h-3.5 w-3.5" /></button>
                                    </div>
                                    {/* Scrollable image area */}
                                    <div
                                        className="overflow-auto p-3"
                                        style={{ maxHeight: "calc(95vh - 36px)" }}
                                        onWheel={e => {
                                            e.preventDefault()
                                            setZoom(z => clampZoom(z * (e.deltaY < 0 ? 1.1 : 0.9)))
                                        }}
                                    >
                                        <img
                                            src={`data:image/png;base64,${resolvedViz.png_b64}`}
                                            alt={resolvedViz.title}
                                            style={{ width: `${zoom * 100}%`, minWidth: "100%", display: "block", height: "auto" }}
                                            draggable={false}
                                        />
                                    </div>
                                </div>
                            </div>,
                            document.body
                        )}

                        {/* Download bar */}
                        <div className="flex items-center gap-2 px-3 py-2 border-t border-border bg-muted/30">
                            <Download className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                            <span className="text-xs text-muted-foreground mr-1">Download:</span>
                            <button
                                className="text-xs text-primary hover:underline"
                                onClick={() => downloadBase64(resolvedViz.png_b64!, `${safeFilename(resolvedViz.title || "plot")}.png`, "image/png")}
                            >
                                PNG
                            </button>
                            {resolvedViz.svg && (<>
                                <span className="text-muted-foreground">·</span>
                                <button
                                    className="text-xs text-primary hover:underline"
                                    onClick={() => downloadBlob(resolvedViz.svg!, `${safeFilename(resolvedViz.title || "plot")}.svg`, "image/svg+xml")}
                                >
                                    SVG
                                </button>
                            </>)}
                            {resolvedViz.csv && (<>
                                <span className="text-muted-foreground">·</span>
                                <button
                                    className="text-xs text-primary hover:underline"
                                    onClick={() => downloadBlob(resolvedViz.csv!, `${safeFilename(resolvedViz.title || "plot")}.csv`, "text/csv")}
                                >
                                    CSV
                                </button>
                            </>)}
                            {atRiskData && (<>
                                <span className="text-muted-foreground">·</span>
                                <button
                                    className="flex items-center gap-1 text-xs text-primary hover:underline"
                                    onClick={() => setShowAtRisk(v => !v)}
                                >
                                    <Table className="h-3 w-3" />
                                    {showAtRisk ? "Hide" : "At-risk table"}
                                </button>
                            </>)}
                        </div>

                        {/* At-risk table */}
                        {showAtRisk && atRiskData && (
                            <div className="border-t border-border px-3 py-2">
                                <p className="text-xs font-medium text-muted-foreground mb-1.5">At-risk counts by time (days)</p>
                                <div className="max-h-48 overflow-y-auto rounded border border-border text-xs">
                                    <table className="w-full border-collapse">
                                        <thead className="sticky top-0 bg-muted/80 backdrop-blur-sm">
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
                            </div>
                        )}
                    </div>
                ) : fetchError ? (
                    <div className="text-xs text-muted-foreground italic px-3 py-2 border rounded-lg border-border bg-muted/20">
                        {viz.title ? `Chart: ${viz.title}` : "Chart"} — file not available (re-run query to regenerate)
                    </div>
                ) : (
                    <div className="text-xs text-muted-foreground italic px-3 py-2 border rounded-lg border-border bg-muted/20 animate-pulse">
                        Loading chart{viz.title ? `: ${viz.title}` : ""}…
                    </div>
                )
            )}
        </div>
    )
}
