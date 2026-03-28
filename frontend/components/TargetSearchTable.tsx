"use client"
import { useState, useMemo } from "react"
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react"
import type { TargetSearchVisualization } from "@/lib/api"

const TIER_LABELS: Record<string, string> = {
    T1: "Approved oncology",
    T2: "Approved non-oncology",
    T3: "Investigational",
    T4: "Pre-clinical",
    T5: "Surface protein",
}

const TIER_BADGE: Record<string, string> = {
    T1: "bg-green-100 text-green-800 border-green-300",
    T2: "bg-blue-100 text-blue-800 border-blue-300",
    T3: "bg-yellow-100 text-yellow-800 border-yellow-300",
    T4: "bg-orange-100 text-orange-800 border-orange-300",
    T5: "bg-gray-100 text-gray-700 border-gray-300",
}

const PAGE_SIZE = 15

type SortKey = "gene" | "tier" | "family" | "antigen" | "count" | "lo_score"
type SortDir = "asc" | "desc"

interface Props {
    visualization: TargetSearchVisualization
}

export function TargetSearchTable({ visualization }: Props) {
    const { title, total, genes, description, score_label } = visualization
    const hasLoScore = genes.some(g => g.lo_score != null)

    const [page, setPage] = useState(1)
    const [sortKey, setSortKey] = useState<SortKey>("tier")
    const [sortDir, setSortDir] = useState<SortDir>("asc")
    const [search, setSearch] = useState("")

    const filtered = useMemo(() => {
        const q = search.trim().toLowerCase()
        if (!q) return genes
        return genes.filter(g =>
            g.gene.toLowerCase().includes(q) ||
            g.family.toLowerCase().includes(q) ||
            g.tier.toLowerCase().includes(q) ||
            g.drugs.toLowerCase().includes(q)
        )
    }, [genes, search])

    const sorted = useMemo(() => {
        return [...filtered].sort((a, b) => {
            if (sortKey === "count" || sortKey === "lo_score") {
                const diff = (Number((a as any)[sortKey]) || 0) - (Number((b as any)[sortKey]) || 0)
                return sortDir === "asc" ? diff : -diff
            }
            const av = (a as any)[sortKey] ?? ""
            const bv = (b as any)[sortKey] ?? ""
            const cmp = av.localeCompare(bv)
            return sortDir === "asc" ? cmp : -cmp
        })
    }, [filtered, sortKey, sortDir])

    const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
    const currentPage = Math.min(page, totalPages)
    const pageRows = sorted.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

    const handleSort = (key: SortKey) => {
        if (sortKey === key) {
            setSortDir(d => d === "asc" ? "desc" : "asc")
        } else {
            setSortKey(key)
            setSortDir("asc")
        }
        setPage(1)
    }

    const SortIcon = ({ col }: { col: SortKey }) => {
        if (sortKey !== col) return <ChevronsUpDown className="w-3 h-3 opacity-40" />
        return sortDir === "asc"
            ? <ChevronUp className="w-3 h-3" />
            : <ChevronDown className="w-3 h-3" />
    }

    const thCls = "px-3 py-2 text-left font-semibold text-xs text-foreground whitespace-nowrap select-none"

    return (
        <div className="rounded-lg border border-border bg-white dark:bg-gray-950 overflow-hidden shadow-sm my-2">
            {/* Header */}
            <div className="px-3 py-2 border-b border-border bg-muted/30 flex items-center justify-between gap-3 flex-wrap">
                <span className="text-sm font-semibold">{title}</span>
                <input
                    type="text"
                    placeholder="Filter by gene, family, drug…"
                    value={search}
                    onChange={e => { setSearch(e.target.value); setPage(1) }}
                    className="text-xs border border-border rounded px-2 py-1 bg-background w-52 focus:outline-none focus:ring-1 focus:ring-ring"
                />
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
                <table className="w-full text-xs border-collapse">
                    <thead>
                        <tr className="bg-muted/40 border-b border-border">
                            <th className={thCls}>
                                <button className="flex items-center gap-1 hover:text-teal-700" onClick={() => handleSort("gene")}>
                                    Gene <SortIcon col="gene" />
                                </button>
                            </th>
                            <th className={thCls}>
                                <button className="flex items-center gap-1 hover:text-teal-700" onClick={() => handleSort("tier")}>
                                    Tier <SortIcon col="tier" />
                                </button>
                            </th>
                            <th className={thCls}>
                                <button className="flex items-center gap-1 hover:text-teal-700" onClick={() => handleSort("family")}>
                                    Family <SortIcon col="family" />
                                </button>
                            </th>
                            <th className={thCls}>Drugs</th>
                            <th className={thCls}>
                                <button className="flex items-center gap-1 hover:text-teal-700" onClick={() => handleSort("antigen")}>
                                    Antigen <SortIcon col="antigen" />
                                </button>
                            </th>
                            {hasLoScore && (
                                <th className={thCls}>
                                    <button className="flex items-center gap-1 hover:text-teal-700" onClick={() => handleSort("lo_score")}>
                                        Score <SortIcon col="lo_score" />
                                    </button>
                                </th>
                            )}
                            <th className={thCls}>
                                <button className="flex items-center gap-1 hover:text-teal-700" onClick={() => handleSort("count")}>
                                    {hasLoScore ? "Composite Score" : (score_label ?? "Score")} <SortIcon col="count" />
                                </button>
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {pageRows.map((row, i) => (
                            <tr key={row.gene} className={`border-t border-border/40 hover:bg-muted/20 transition-colors ${i % 2 === 1 ? "bg-muted/10" : ""}`}>
                                <td className="px-3 py-1.5 font-medium text-foreground whitespace-nowrap">{row.gene}</td>
                                <td className="px-3 py-1.5 whitespace-nowrap">
                                    {row.tier && row.tier !== "NA"
                                        ? <span className={`inline-block px-1.5 py-0.5 rounded border text-[11px] font-medium ${TIER_BADGE[row.tier] ?? "bg-gray-100 text-gray-700 border-gray-300"}`}>
                                            {row.tier} · {TIER_LABELS[row.tier] ?? row.tier}
                                          </span>
                                        : <span className="text-muted-foreground">—</span>}
                                </td>
                                <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">{row.family || "—"}</td>
                                <td className="px-3 py-1.5 text-muted-foreground max-w-xs truncate" title={row.drugs}>{row.drugs || "—"}</td>
                                <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">{row.antigen || "—"}</td>
                                {hasLoScore && (
                                    <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap text-center tabular-nums">{row.lo_score ?? "—"}</td>
                                )}
                                <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap text-center tabular-nums">{row.count ?? "—"}</td>
                            </tr>
                        ))}
                        {pageRows.length === 0 && (
                            <tr>
                                <td colSpan={hasLoScore ? 7 : 6} className="px-3 py-6 text-center text-muted-foreground italic">No results.</td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            {/* Footer: count + pagination */}
            <div className="flex items-center justify-between px-3 py-2 border-t border-border/50 bg-muted/10 gap-2 flex-wrap">
                <span className="text-xs text-muted-foreground">
                    {filtered.length < total
                        ? `${filtered.length} of ${total} genes`
                        : `${total} gene${total !== 1 ? "s" : ""}`}
                </span>
                {totalPages > 1 && (
                    <div className="flex items-center gap-1">
                        <button
                            onClick={() => setPage(p => Math.max(1, p - 1))}
                            disabled={currentPage === 1}
                            className="px-2 py-0.5 text-xs rounded border border-border disabled:opacity-40 hover:bg-muted/40 transition-colors"
                        >‹</button>
                        {Array.from({ length: totalPages }, (_, i) => i + 1)
                            .filter(p => p === 1 || p === totalPages || Math.abs(p - currentPage) <= 1)
                            .reduce<(number | "…")[]>((acc, p, idx, arr) => {
                                if (idx > 0 && (arr[idx - 1] as number) !== p - 1) acc.push("…")
                                acc.push(p)
                                return acc
                            }, [])
                            .map((p, i) => p === "…"
                                ? <span key={`e${i}`} className="px-1 text-xs text-muted-foreground">…</span>
                                : <button
                                    key={p}
                                    onClick={() => setPage(p as number)}
                                    className={`px-2 py-0.5 text-xs rounded border transition-colors ${currentPage === p ? "bg-[#0d9488] text-white border-[#0a7c72]" : "border-border hover:bg-muted/40"}`}
                                >{p}</button>
                            )}
                        <button
                            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                            disabled={currentPage === totalPages}
                            className="px-2 py-0.5 text-xs rounded border border-border disabled:opacity-40 hover:bg-muted/40 transition-colors"
                        >›</button>
                    </div>
                )}
            </div>

            {/* Ranking explanation */}
            {description && (
                <div className="px-3 py-2 border-t border-border/50 bg-muted/10 text-xs text-muted-foreground leading-relaxed">
                    <span dangerouslySetInnerHTML={{ __html: description.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>") }} />
                </div>
            )}
        </div>
    )
}
