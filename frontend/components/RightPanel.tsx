"use client"

import { useMemo } from "react"
import { cn } from "@/lib/utils"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { Copy, X } from "lucide-react"
import type { Paper, AnalysisResult } from "@/lib/api"

export interface RightPanelContext {
  lastAssistantText?: string
  lastAssistantImages?: string[]
  lastAssistantPapers?: Paper[]
  lastAssistantAnalyses?: AnalysisResult[]
  hiddenImagesCount?: number
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
  const papers = context?.lastAssistantPapers ?? []
  const analyses = context?.lastAssistantAnalyses ?? []

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
            <div className="text-sm font-semibold mb-2">Plots / Images</div>
            {images.length === 0 ? (
              <div className="text-xs text-muted-foreground">
                {hiddenCount > 0
                  ? `${hiddenCount} plot${hiddenCount > 1 ? 's' : ''} available in history. Click "Load details" in chat to view.`
                  : "No images detected."}
              </div>
            ) : (
              <div className="space-y-3">
                {images.slice(0, 5).map((src, idx) => (
                  <div key={idx} className="rounded-md border border-border bg-background p-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={src}
                      alt={`Plot ${idx + 1}`}
                      className="w-full h-auto rounded"
                      loading="lazy"
                    />
                    <div className="mt-2 text-[11px] text-muted-foreground break-all">
                      {src.startsWith("data:image/") ? "data:image/…" : src}
                    </div>
                  </div>
                ))}
                {images.length > 5 && (
                  <div className="text-xs text-muted-foreground">
                    Showing first 5 of {images.length} images.
                  </div>
                )}
              </div>
            )}
          </div>

          <div>
            <div className="text-sm font-semibold mb-2">
              Analyses ({analyses.length})
            </div>
            {analyses.length === 0 ? (
              <div className="text-xs text-muted-foreground">
                No structured analyses attached to the last assistant message.
              </div>
            ) : (
              <div className="space-y-2">
                {analyses.slice(0, 10).map((a, idx) => (
                  <div key={idx} className="rounded-md border border-border bg-background p-3">
                    <div className="text-sm font-medium">
                      {a.analysis_type || "analysis"}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">
                      {(a.target_gene && `Target: ${a.target_gene}`) || ""}
                      {(a.cancer_type && ` • Cancer: ${a.cancer_type}`) || ""}
                      {(a.data_source && ` • Source: ${a.data_source}`) || ""}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <div className="text-sm font-semibold mb-2">
              Papers ({papers.length})
            </div>
            {papers.length === 0 ? (
              <div className="text-xs text-muted-foreground">
                No papers attached to the last assistant message.
              </div>
            ) : (
              <div className="space-y-2">
                {papers.slice(0, 10).map((p, idx) => (
                  <div key={idx} className="rounded-md border border-border bg-background p-3">
                    {p.link ? (
                      <a
                        href={p.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm font-medium text-primary hover:underline break-words"
                      >
                        {p.title}
                      </a>
                    ) : (
                      <div className="text-sm font-medium break-words">{p.title}</div>
                    )}
                    {p.snippet && (
                      <div className="text-xs text-muted-foreground mt-1 line-clamp-3">
                        {p.snippet}
                      </div>
                    )}
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

