"use client"

import { useState } from "react"
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, AlertCircle, Clock } from "lucide-react"
import { ExecutionTraceStep } from "@/lib/api"

interface ExecutionTraceProps {
    trace: ExecutionTraceStep[]
}

const STATUS_ICON = {
    ok: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" />,
    error: <XCircle className="w-3.5 h-3.5 text-rose-500 flex-shrink-0" />,
    missing: <AlertCircle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />,
    empty: <AlertCircle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />,
}

function formatToolName(tool: string): string {
    // e.g. "linkedomics::compare_cptac_tumor_normal_expression" → "compare_cptac_tumor_normal_expression"
    const bare = tool.includes("::") ? tool.split("::").pop()! : tool
    return bare.replace(/_/g, " ")
}

export default function ExecutionTrace({ trace }: ExecutionTraceProps) {
    const [open, setOpen] = useState(false)

    // Only show tool steps (skip pure agent steps with no tool calls)
    const toolSteps = trace.filter(s => s.node === "tools" && s.tool_calls?.length)
    if (toolSteps.length === 0) return null

    const totalMs = trace.reduce((sum, s) => sum + (s.latency_ms ?? 0), 0)
    const allOk = toolSteps.every(s => s.tool_calls?.every(t => t.status === "ok"))

    return (
        <div className="mt-2 ml-11 text-xs">
            <button
                onClick={() => setOpen(v => !v)}
                className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors"
            >
                {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                <span className="font-medium">How this was answered</span>
                <span className="ml-1 text-muted-foreground/60">
                    {toolSteps.flatMap(s => s.tool_calls ?? []).length} tool{toolSteps.flatMap(s => s.tool_calls ?? []).length !== 1 ? "s" : ""}
                    {" · "}{totalMs < 1000 ? `${totalMs}ms` : `${(totalMs / 1000).toFixed(1)}s`}
                </span>
                {!allOk && <AlertCircle className="w-3.5 h-3.5 text-amber-500" />}
            </button>

            {open && (
                <div className="mt-2 border border-border rounded-lg overflow-hidden">
                    {toolSteps.map((step, si) =>
                        (step.tool_calls ?? []).map((tc, ti) => (
                            <div
                                key={`${si}-${ti}`}
                                className="flex items-center gap-2 px-3 py-2 border-b border-border last:border-b-0 bg-muted/30 hover:bg-muted/50 transition-colors"
                            >
                                {STATUS_ICON[tc.status] ?? STATUS_ICON.ok}
                                <span className="flex-1 capitalize">{formatToolName(tc.tool)}</span>
                                <span className="flex items-center gap-1 text-muted-foreground/70 tabular-nums">
                                    <Clock className="w-3 h-3" />
                                    {tc.latency_ms < 1000 ? `${tc.latency_ms}ms` : `${(tc.latency_ms / 1000).toFixed(1)}s`}
                                </span>
                                <span className={
                                    tc.status === "ok" ? "text-emerald-600 dark:text-emerald-400" :
                                    tc.status === "error" ? "text-rose-600 dark:text-rose-400" :
                                    "text-amber-600 dark:text-amber-400"
                                }>
                                    {tc.status === "ok" ? "data found" : tc.status === "empty" ? "no data" : tc.status}
                                </span>
                            </div>
                        ))
                    )}
                </div>
            )}
        </div>
    )
}
