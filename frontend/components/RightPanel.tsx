"use client"

import { useMemo } from "react"
import { cn } from "@/lib/utils"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { Copy, X } from "lucide-react"
import type { Paper, AnalysisResult, AnyVisualization } from "@/lib/api"
// Paper and AnalysisResult kept for RightPanelContext interface compatibility
import { StaticPlot } from "@/components/StaticPlot"

export interface RightPanelContext {
  lastAssistantText?: string
  lastAssistantImages?: string[]
  lastAssistantPapers?: Paper[]
  lastAssistantAnalyses?: AnalysisResult[]
  hiddenImagesCount?: number
  allVisualizations?: Array<AnyVisualization & { messageKey: string }>
  onNavigateToViz?: (messageKey: string) => void
}

function extractMarkdownImages(markdown: string): string[] {
  if (!markdown) return []
  const matches = Array.from(markdown.matchAll(/!\[[^\]]*\]\(([^)]+)\)/g))
  const urls = matches.map((m) => (m[1] || "").trim()).filter(Boolean)
  // Deduplicate while preserving order
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

export function RightPanel({
  sessionId,
  context,
  className,
  onClose,
}: {
  sessionId: string | null
  context: RightPanelContext | null
  className?: string
  onClose?: () => void
}) {
  const images = useMemo(() => {
    const fromCtx = context?.lastAssistantImages ?? []
    if (fromCtx.length) return fromCtx
    return extractMarkdownImages(context?.lastAssistantText ?? "")
  }, [context])

  const hiddenCount = context?.hiddenImagesCount ?? 0
  const visualizations = context?.allVisualizations ?? []
  const onNavigateToViz = context?.onNavigateToViz

  return (
    <aside
      className={cn(
        "w-96 border-l border-border bg-card flex flex-col",
        className
      )}
    >
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between gap-2">
          <div>
            <div className="text-sm font-semibold">Context</div>
            <div className="text-xs text-muted-foreground">
              Session / plots / results
            </div>
          </div>
          <div className="flex items-center gap-2">
            {sessionId && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigator.clipboard.writeText(sessionId)}
                title="Copy session id"
              >
                <Copy className="h-4 w-4" />
              </Button>
            )}
            {onClose && (
              <Button
                variant="ghost"
                size="icon"
                onClick={onClose}
                title="Close panel"
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
        {sessionId && (
          <div className="mt-2 text-xs text-muted-foreground break-all">
            <span className="font-medium text-foreground">Session:</span> {sessionId}
          </div>
        )}
      </div>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-6">
          <div>
            <div className="text-sm font-semibold mb-2">
              Plots {visualizations.length > 0 ? `(${visualizations.length})` : images.length > 0 ? `(${images.length})` : ""}
            </div>
            {visualizations.length === 0 && images.length === 0 ? (
              <div className="text-xs text-muted-foreground">
                {hiddenCount > 0
                  ? `${hiddenCount} plot${hiddenCount > 1 ? 's' : ''} available in history. Click "Load details" in chat to view.`
                  : "No plots in this session yet."}
              </div>
            ) : (
              <div className="space-y-4">
                {/* Plotly thumbnail previews — click to jump to message in chat */}
                <div className="flex flex-wrap gap-2">
                {visualizations.map((viz, idx) => (
                  <div
                    key={idx}
                    className="rounded-md border border-border bg-background overflow-hidden cursor-pointer hover:border-teal-400 transition-colors group"
                    style={{ width: 140 }}
                    onClick={() => onNavigateToViz?.(viz.messageKey)}
                    title="Click to jump to this plot in the chat"
                  >
                    {viz.title && (
                      <div className="px-2 pt-2 text-[11px] font-medium text-foreground truncate group-hover:text-teal-600">{viz.title}</div>
                    )}
                    <div className="relative" style={{ height: 80 }}>
                      {/* Non-interactive scaled chart */}
                      <div style={{ pointerEvents: "none", overflow: "hidden", height: 80 }}>
                        <div style={{ transform: "scale(0.2)", transformOrigin: "top left", width: "500%", height: "400px" }}>
                          <StaticPlot visualization={viz} />
                        </div>
                      </div>
                      {/* Transparent overlay to capture clicks and show hover state */}
                      <div className="absolute inset-0 flex items-end justify-end p-1.5">
                        <span className="text-[10px] bg-black/50 text-white rounded px-1.5 py-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                          Go to plot ↗
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
                </div>
                {/* Static markdown images (fallback) */}
                {images.map((src, idx) => (
                  <div key={`img-${idx}`} className="rounded-md border border-border bg-background p-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={src}
                      alt={`Plot ${idx + 1}`}
                      className="w-full h-auto rounded"
                      loading="lazy"
                    />
                  </div>
                ))}
              </div>
            )}
          </div>

        </div>
      </ScrollArea>
    </aside>
  )
}

