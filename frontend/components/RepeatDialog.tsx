"use client"

import { useEffect, useMemo, useState } from "react"
import { FileText, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { chatAPI, type GeneListCheck, type ToolCallRecord } from "@/lib/api"
import { callGenes, notRepeatableCalls, repeatableCalls } from "@/lib/repeat"
import { TOOL_DISPLAY } from "@/components/ToolExplorer"

// Same as MAX_REPEAT_GENES in backend/services/repeat_workflow.py
const MAX_GENES = 10

function stepLabel(call: ToolCallRecord): string {
    const tool = call.tool_id.split("::").pop() || call.tool_id
    return TOOL_DISPLAY[tool]?.label ?? tool
}

/**
 * Repeat an answer's analyses for other genes. The genes are checked like an uploaded list, so
 * old names and IDs become current symbols; the analyses then run without the model.
 */
export function RepeatDialog({
    calls,
    attachedList,
    onOpenChange,
    onRun,
}: {
    calls: ToolCallRecord[] | null
    attachedList: GeneListCheck | null
    onOpenChange: (open: boolean) => void
    onRun: (genes: string[], description: string) => void
}) {
    const open = calls !== null
    const [text, setText] = useState("")
    const [checking, setChecking] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const steps = useMemo(() => repeatableCalls(calls ?? undefined), [calls])
    const skipped = useMemo(() => notRepeatableCalls(calls ?? undefined), [calls])

    useEffect(() => {
        if (!open) return
        setText("")
        setError(null)
    }, [open])

    const run = (genes: string[], source: string) => {
        const used = genes.slice(0, MAX_GENES)
        const description = used.length === 1 ? used[0]
            : genes.length > MAX_GENES ? `the first ${MAX_GENES} genes of ${source}`
            : `${used.length} genes${source ? ` from ${source}` : ""}`
        onRun(used, description)
        onOpenChange(false)
    }

    const checkAndRun = async () => {
        if (!text.trim() || checking) return
        setChecking(true)
        setError(null)
        try {
            const result = await chatAPI.checkGeneList(text)
            if (!result.genes.length) {
                setError("None of those are recognized gene symbols, Ensembl IDs, or UniProt accessions.")
                return
            }
            if (result.genes.length > MAX_GENES) {
                setError(`Enter up to ${MAX_GENES} genes; that is ${result.genes.length}.`)
                return
            }
            run(result.genes, "")
        } catch (e: any) {
            setError(e?.response?.data?.detail || "The genes could not be checked. Try again in a moment.")
        } finally {
            setChecking(false)
        }
    }

    return (
        <AlertDialog open={open} onOpenChange={(next) => { if (!checking) onOpenChange(next) }}>
            <AlertDialogContent className="max-w-lg">
                <AlertDialogHeader>
                    <AlertDialogTitle>Repeat for other genes</AlertDialogTitle>
                    <AlertDialogDescription>
                        Runs this answer&rsquo;s analyses again for up to {MAX_GENES} genes you choose, without the
                        language model, and shows one table with a row per gene.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <div className="space-y-3 text-sm">
                    <div>
                        <p className="text-xs font-medium text-muted-foreground mb-1">Steps</p>
                        <ul className="space-y-0.5">
                            {steps.map((call, i) => (
                                <li key={i}>
                                    {stepLabel(call)} <span className="text-muted-foreground">({callGenes(call)})</span>
                                </li>
                            ))}
                        </ul>
                        {skipped.length > 0 && (
                            <p className="text-xs text-muted-foreground mt-1">
                                Not repeated, because they are not about one gene: {skipped.map(stepLabel).join(", ")}.
                            </p>
                        )}
                    </div>
                    {attachedList && (
                        <Button type="button" variant="outline" className="w-full gap-2 justify-start" disabled={checking}
                            onClick={() => run(attachedList.genes, attachedList.name)}>
                            <FileText className="w-4 h-4" />
                            {attachedList.genes.length > MAX_GENES
                                ? `Use the first ${MAX_GENES} genes of ${attachedList.name} (${attachedList.genes.length} genes)`
                                : `Use ${attachedList.name} (${attachedList.genes.length} ${attachedList.genes.length === 1 ? "gene" : "genes"})`}
                        </Button>
                    )}
                    <div className="space-y-2">
                        <textarea
                            value={text}
                            onChange={(e) => setText(e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void checkAndRun() } }}
                            placeholder={`${attachedList ? "Or type" : "Type"} up to ${MAX_GENES} genes, e.g. KRAS, EGFR, MYC`}
                            rows={2}
                            // Read-only rather than disabled while checking, so the box keeps focus for a fix after an error
                            readOnly={checking}
                            autoFocus
                            aria-label="Genes to repeat the analyses for"
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
                    </div>
                </div>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)} disabled={checking}>
                        Cancel
                    </Button>
                    <Button onClick={() => void checkAndRun()} disabled={checking || !text.trim()} className="gap-2">
                        {checking && <Loader2 className="w-4 h-4 animate-spin" />}
                        Repeat
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
