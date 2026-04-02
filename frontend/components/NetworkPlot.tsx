"use client"
import { useRef, useState, useEffect, useCallback, useMemo } from "react"
import { createPortal } from "react-dom"
import CytoscapeComponent from "react-cytoscapejs"
import type { Core, ElementDefinition, LayoutOptions, StylesheetStyle } from "cytoscape"
import { Download, Maximize2, X, ZoomIn, ZoomOut, Minimize2 } from "lucide-react"
import type { NetworkVisualization } from "@/lib/api"
import { getAuthToken } from "@/lib/auth"

const API_URL = process.env.NEXT_PUBLIC_API_URL || ""

const EDGE_COLOR = "#cccccc"
const BAR_H = 80  // px — must match the SVG height in ColorLegend

// Legend endpoint colors — must match ColorLegend's gradient stops exactly.
const RED_RGB  = [0xc0, 0x39, 0x2b]  // #c0392b
const BLUE_RGB = [0x29, 0x80, 0xb9]  // #2980b9

// Map a signed score to a color that matches the legend bar (white at 0).
function scoreToColor(value: number, absMax: number): string {
    if (absMax === 0) return "#ffffff"
    const t = Math.max(-1, Math.min(1, value / absMax))
    const [tr, tg, tb] = t >= 0 ? RED_RGB : BLUE_RGB
    const abs_t = Math.abs(t)
    const r = Math.round(255 + (tr - 255) * abs_t)
    const g = Math.round(255 + (tg - 255) * abs_t)
    const b = Math.round(255 + (tb - 255) * abs_t)
    return `rgb(${r},${g},${b})`
}

// Choose black or white label text for readability against a computed bg color.
function labelColor(value: number, absMax: number): string {
    if (absMax === 0) return "#333333"
    const t = Math.abs(value / absMax)
    return t > 0.5 ? "#ffffff" : "#333333"
}

// Y pixel position on the gradient bar for a given value.
// Top (y=0) = +absMax (red), bottom (y=BAR_H) = -absMax (blue).
function barYForValue(value: number, absMax: number): number {
    if (absMax === 0) return BAR_H / 2
    const t = Math.max(-1, Math.min(1, value / absMax))
    return ((1 - t) / 2) * BAR_H
}

const CYTOSCAPE_STYLESHEET: StylesheetStyle[] = [
    {
        selector: "node",
        style: {
            label: "data(label)",
            "font-size": 10,
            "text-valign": "center",
            "text-halign": "center",
            color: "data(textColor)" as any,
            "text-outline-color": "#00000022",
            "text-outline-width": 0.5,
            "background-color": "data(nodeColor)" as any,
            width: 36,
            height: 36,
        },
    },
    {
        selector: "node[?center]",
        style: {
            width: 52,
            height: 52,
            "font-size": 12,
            "font-weight": "bold",
            "border-width": 3,
            "border-color": "#333333",
        },
    },
    {
        selector: "edge",
        style: {
            "line-color": EDGE_COLOR,
            width: 1,
            opacity: 0.7,
            "curve-style": "bezier",
        },
    },
    {
        selector: "node:selected",
        style: {
            "border-width": 3,
            "border-color": "#f39c12",
        },
    },
]

function downloadBlob(content: string, filename: string, mime: string) {
    const blob = new Blob([content], { type: mime })
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

interface HoveredNode { name: string; value: number }

interface ColorLegendProps {
    absMax: number
    hovered: HoveredNode | null
    large?: boolean
}

function ColorLegend({ absMax, hovered, large = false }: ColorLegendProps) {
    const gradientId = "funmap-legend-gradient"
    const barH    = large ? 160 : BAR_H
    const barW    = large ? 20  : 12
    const svgW    = large ? 48  : 30
    const fsLabel = large ? 13  : 9
    const fsName  = large ? 13  : 9
    const fsScore = large ? 11  : 8
    const fsNote  = large ? 11  : 8
    const triSize = large ? 6   : 4

    const markerY = hovered !== null ? barYForValue(hovered.value, absMax) / BAR_H * barH : null

    return (
        <div
            style={{
                position: "absolute",
                top: 16,
                right: 18,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: large ? 4 : 2,
                pointerEvents: "none",
                userSelect: "none",
                minWidth: large ? 110 : 80,
            }}
        >
            <span style={{ fontSize: fsLabel, color: "#555", textAlign: "center", lineHeight: 1.2 }}>
                Tumor<br />over-expressed
            </span>

            <svg width={svgW} height={barH} overflow="visible">
                <defs>
                    <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%"   stopColor="#c0392b" />
                        <stop offset="50%"  stopColor="#ffffff" />
                        <stop offset="100%" stopColor="#2980b9" />
                    </linearGradient>
                </defs>
                <rect x={(svgW - barW) / 2} y={0} width={barW} height={barH}
                    fill={`url(#${gradientId})`}
                    stroke="#aaa" strokeWidth={0.5} rx={3} />

                {markerY !== null && (
                    <g>
                        <line
                            x1={(svgW - barW) / 2 - triSize}
                            y1={markerY}
                            x2={(svgW + barW) / 2}
                            y2={markerY}
                            stroke="#333" strokeWidth={large ? 2 : 1.5}
                        />
                        <polygon
                            points={`${(svgW - barW) / 2 - triSize},${markerY - triSize} ${(svgW - barW) / 2 - triSize},${markerY + triSize} ${(svgW - barW) / 2},${markerY}`}
                            fill="#333"
                        />
                    </g>
                )}
            </svg>

            <span style={{ fontSize: fsLabel, color: "#555", textAlign: "center", lineHeight: 1.2 }}>
                Tumor<br />under-expressed
            </span>

            <div style={{ marginTop: large ? 6 : 4, minHeight: large ? 36 : 28, textAlign: "center", lineHeight: 1.3 }}>
                {hovered ? (
                    <>
                        <span style={{ fontSize: fsName, fontWeight: "bold", color: "#222", display: "block" }}>
                            {hovered.name}
                        </span>
                        <span style={{ fontSize: fsScore, color: "#555", display: "block" }}>
                            score: {hovered.value.toFixed(3)}
                        </span>
                    </>
                ) : (
                    <span style={{ fontSize: fsScore, color: "#aaa" }}>hover a node</span>
                )}
            </div>

            <span style={{ fontSize: fsNote, color: "#888", textAlign: "center", lineHeight: 1.2, marginTop: 2 }}>
                Wilcoxon p-value<br />(signed by direction)
            </span>
        </div>
    )
}

// Stable layout config — defined once at module level so the reference never changes.
const COSE_LAYOUT: LayoutOptions = {
    name: "cose",
    animate: false,
    randomize: false,
    nodeRepulsion: () => 8000,
    idealEdgeLength: () => 80,
    edgeElasticity: () => 100,
    numIter: 1000,
} as any

interface NetworkCanvasProps {
    elements: NetworkElement[]
    height: string
    onCy: (cy: Core) => void
}

interface NetworkNodeData {
    id: string
    label: string
    center?: boolean
    nodeValue: number
    nodeColor: string
    textColor: string
}

interface NetworkEdgeData {
    id: string
    source: string
    target: string
}

type NetworkNodeElement = ElementDefinition & { data: NetworkNodeData }
type NetworkEdgeElement = ElementDefinition & { data: NetworkEdgeData }
type NetworkElement = NetworkNodeElement | NetworkEdgeElement

function isEdgeElement(element: NetworkElement): element is NetworkEdgeElement {
    return "source" in element.data
}

// Defined at module level so React never sees a new component type on re-render,
// which would unmount/remount Cytoscape and trigger an unwanted re-layout.
function NetworkCanvas({ elements, height, onCy }: NetworkCanvasProps) {
    return (
        <CytoscapeComponent
            elements={elements}
            stylesheet={CYTOSCAPE_STYLESHEET}
            layout={COSE_LAYOUT}
            style={{ width: "100%", height }}
            cy={onCy}
            wheelSensitivity={0.3}
        />
    )
}

interface NetworkPlotProps {
    visualization: NetworkVisualization
    className?: string
}

export function NetworkPlot({ visualization, className }: NetworkPlotProps) {
    const containerRef = useRef<HTMLDivElement>(null)
    const cyRef = useRef<Core | null>(null)
    const [isVisible, setIsVisible] = useState(false)
    const [resolvedViz, setResolvedViz] = useState<NetworkVisualization | null>(
        visualization.nodes && visualization.nodes.length > 0 ? visualization : null
    )
    const [fetchError, setFetchError] = useState(false)
    const [lightboxOpen, setLightboxOpen] = useState(false)
    const [hoveredNode, setHoveredNode] = useState<HoveredNode | null>(null)

    const openLightbox = useCallback(() => setLightboxOpen(true), [])
    const closeLightbox = useCallback(() => setLightboxOpen(false), [])

    // Escape key + scroll lock for lightbox
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

    // Lazy render on scroll into view
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

    // Fetch full data for historical messages
    useEffect(() => {
        if (!isVisible) return
        if (resolvedViz) return
        if (!visualization.id) return

        const token = getAuthToken()
        fetch(`${API_URL}/api/v1/chat/visualizations/${encodeURIComponent(visualization.id)}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
            .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
            .then(data => {
                if (data?.type === "network_plot" && data.nodes) {
                    setResolvedViz({ ...visualization, ...data })
                } else {
                    setFetchError(true)
                }
            })
            .catch(() => setFetchError(true))
    }, [isVisible, resolvedViz, visualization])

    // Build Cytoscape elements — memoized so absMax is stable and shareable
    const { elements, absMax } = useMemo(() => {
        if (!resolvedViz?.nodes) return { elements: [] as NetworkElement[], absMax: 0 }

        const centerName = resolvedViz.title.replace(/^FunMap neighborhood\s*[—-]\s*/, "").trim()
        const shownNodes = resolvedViz.nodes.slice(0, 51)
        const shownSet = new Set(shownNodes.map(n => n.name))

        const numValues = shownNodes.map(n => parseFloat(n.value) || 0)
        const absMax = Math.max(...numValues.map(Math.abs), 1e-6)

        const nodeEls: NetworkNodeElement[] = shownNodes.map(n => {
            const numVal = parseFloat(n.value) || 0
            return {
                data: {
                    id: n.name,
                    label: n.name,
                    center: n.name === centerName || undefined,
                    nodeValue: numVal,
                    nodeColor: scoreToColor(numVal, absMax),
                    textColor: labelColor(numVal, absMax),
                },
            }
        })

        const seenEdges = new Set<string>()
        const edgeEls: NetworkEdgeElement[] = (resolvedViz.edges || [])
            .filter(e => {
                if (!shownSet.has(e.source) || !shownSet.has(e.target)) return false
                const key = [e.source, e.target].sort().join("\0")
                if (seenEdges.has(key)) return false
                seenEdges.add(key)
                return true
            })
            .map((e, i) => ({
                data: { id: `e${i}`, source: e.source, target: e.target },
            }))

        return { elements: [...nodeEls, ...edgeEls], absMax }
    }, [resolvedViz])

    const edgeCount = useMemo(() => elements.filter(isEdgeElement).length, [elements])
    const nodeCount = elements.length - edgeCount

    // Register Cytoscape hover events
    const handleCy = useCallback((cy: Core) => {
        cyRef.current = cy
        const container = cy.container()
        cy.on("mouseover", "node", e => {
            const d = e.target.data()
            if (container) container.style.cursor = "pointer"
            setHoveredNode({ name: d.id, value: d.nodeValue ?? 0 })
        })
        cy.on("mouseout", "node", () => {
            if (container) container.style.cursor = ""
            setHoveredNode(null)
        })
    }, [])

    const handleDownloadNodesCsv = useCallback(() => {
        if (!resolvedViz?.nodes) return
        const rows = ["gene,score,direction"]
        for (const n of resolvedViz.nodes) {
            const v = parseFloat(n.value) || 0
            const dir = v > 0 ? "over-expressed" : v < 0 ? "under-expressed" : "neutral"
            rows.push(`${n.name},${n.value},${dir}`)
        }
        downloadBlob(rows.join("\n"), `${safeFilename(resolvedViz.title || "network")}_nodes.csv`, "text/csv")
    }, [resolvedViz])

    const handleDownloadPng = useCallback(() => {
        if (!cyRef.current) return
        const png = cyRef.current.png({ output: "blob", bg: "white", full: true, scale: 2 })
        const url = URL.createObjectURL(png as Blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `${safeFilename(resolvedViz?.title || "network")}.png`
        a.click()
        URL.revokeObjectURL(url)
    }, [resolvedViz])

    const handleFitView = useCallback(() => { cyRef.current?.fit(undefined, 24) }, [])
    const handleZoomIn  = useCallback(() => {
        if (!cyRef.current) return
        cyRef.current.zoom(cyRef.current.zoom() * 1.3)
        cyRef.current.center()
    }, [])
    const handleZoomOut = useCallback(() => {
        if (!cyRef.current) return
        cyRef.current.zoom(cyRef.current.zoom() / 1.3)
        cyRef.current.center()
    }, [])

    return (
        <div ref={containerRef} className={className}>
            {isVisible && (
                resolvedViz ? (
                    <div className="rounded-lg border border-border bg-white dark:bg-gray-950 overflow-hidden">
                        {/* Toolbar */}
                        <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-muted/30">
                            <span className="text-xs font-medium text-muted-foreground truncate">
                                {resolvedViz.title}
                            </span>
                            <div className="flex items-center gap-1 flex-shrink-0">
                                <button onClick={handleZoomIn} className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground" title="Zoom in">
                                    <ZoomIn className="h-3.5 w-3.5" />
                                </button>
                                <button onClick={handleZoomOut} className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground" title="Zoom out">
                                    <ZoomOut className="h-3.5 w-3.5" />
                                </button>
                                <button onClick={handleFitView} className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground" title="Fit to view">
                                    <Minimize2 className="h-3.5 w-3.5" />
                                </button>
                                <button onClick={openLightbox} className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground" title="Expand">
                                    <Maximize2 className="h-3.5 w-3.5" />
                                </button>
                            </div>
                        </div>

                        {/* Network canvas */}
                        <div className="relative" style={{ height: "380px" }}>
                            <NetworkCanvas elements={elements} height="100%" onCy={handleCy} />
                            <ColorLegend absMax={absMax} hovered={hoveredNode} />
                            <p className="absolute bottom-2 right-3 text-xs text-muted-foreground pointer-events-none">
                                {edgeCount === 0
                                    ? `${nodeCount} nodes`
                                    : `${nodeCount} nodes · ${edgeCount} edges`
                                } · drag to pan · scroll to zoom
                            </p>
                        </div>

                        {/* Lightbox */}
                        {lightboxOpen && typeof document !== "undefined" && createPortal(
                            <div
                                className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 backdrop-blur-sm"
                                onClick={closeLightbox}
                            >
                                <div
                                    className="relative bg-white dark:bg-gray-950 rounded-lg shadow-2xl"
                                    style={{ width: "90vw", height: "90vh" }}
                                    onClick={e => e.stopPropagation()}
                                >
                                    <button
                                        onClick={closeLightbox}
                                        className="absolute top-2 right-2 z-10 bg-black/50 hover:bg-black/70 text-white rounded p-1 transition-colors"
                                    >
                                        <X className="h-4 w-4" />
                                    </button>
                                    <div className="relative w-full h-full">
                                        <NetworkCanvas elements={elements} height="100%" onCy={handleCy} />
                                        <ColorLegend absMax={absMax} hovered={hoveredNode} large />
                                    </div>
                                </div>
                            </div>,
                            document.body
                        )}

                        {/* Color explanation */}
                        <div className="px-3 py-1.5 border-t border-border text-xs text-muted-foreground">
                            Node color reflects tumor vs. normal protein abundance (Wilcoxon rank-sum, CCRCC/HCC/HNSCC/LSCC/LUAD):
                            {" "}<span className="font-medium" style={{ color: "#c0392b" }}>red</span> = over-expressed,
                            {" "}<span className="font-medium" style={{ color: "#2980b9" }}>blue</span> = under-expressed,
                            {" "}white = no change.
                        </div>

                        {/* Download bar */}
                        <div className="flex items-center gap-2 px-3 py-2 border-t border-border bg-muted/30">
                            <Download className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                            <span className="text-xs text-muted-foreground mr-1">Download:</span>
                            <button className="text-xs text-primary hover:underline" onClick={handleDownloadPng}>
                                PNG
                            </button>
                            {resolvedViz.nodes && resolvedViz.nodes.length > 0 && (<>
                                <span className="text-muted-foreground">·</span>
                                <button className="text-xs text-primary hover:underline" onClick={handleDownloadNodesCsv}>
                                    CSV (nodes)
                                </button>
                            </>)}
                            {resolvedViz.csv && (<>
                                <span className="text-muted-foreground">·</span>
                                <button
                                    className="text-xs text-primary hover:underline"
                                    onClick={() => downloadBlob(resolvedViz.csv!, `${safeFilename(resolvedViz.title || "network")}.csv`, "text/csv")}
                                >
                                    CSV (edges)
                                </button>
                            </>)}
                        </div>
                    </div>
                ) : fetchError ? (
                    <div className="text-xs text-muted-foreground italic px-3 py-2 border rounded-lg border-border bg-muted/20">
                        {visualization.title ? `Network: ${visualization.title}` : "Network"} — not available (re-run query to regenerate)
                    </div>
                ) : (
                    <div className="text-xs text-muted-foreground italic px-3 py-2 border rounded-lg border-border bg-muted/20 animate-pulse">
                        Loading network{visualization.title ? `: ${visualization.title}` : ""}…
                    </div>
                )
            )}
        </div>
    )
}
