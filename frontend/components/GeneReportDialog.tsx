"use client"

import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { chatAPI } from "@/lib/api"

/**
 * Ask for one gene and start its gene report. The entry is checked like an uploaded gene list,
 * so old names and Ensembl or UniProt IDs become current symbols and typos are caught here.
 */
export function GeneReportDialog({
    open,
    onOpenChange,
    onRun,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    onRun: (gene: string) => void
}) {
    const [entry, setEntry] = useState("")
    const [checking, setChecking] = useState(false)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!open) return
        setEntry("")
        setError(null)
    }, [open])

    const run = async () => {
        const text = entry.trim()
        if (!text || checking) return
        setChecking(true)
        setError(null)
        try {
            const result = await chatAPI.checkGeneList(text)
            if (result.genes.length === 1) {
                onRun(result.genes[0])
                onOpenChange(false)
            } else if (result.genes.length > 1) {
                setError("Enter one gene; a report covers a single gene.")
            } else if (result.ambiguous.length) {
                setError(`${result.ambiguous[0].name} could be ${result.ambiguous[0].matches.join(" or ")}. Enter one of those.`)
            } else {
                setError(`${text} is not a recognized gene symbol, Ensembl ID, or UniProt accession.`)
            }
        } catch (e: any) {
            setError(e?.response?.data?.detail || "The gene could not be checked. Try again in a moment.")
        } finally {
            setChecking(false)
        }
    }

    return (
        <AlertDialog open={open} onOpenChange={(next) => { if (!checking) onOpenChange(next) }}>
            <AlertDialogContent className="max-w-md">
                <AlertDialogHeader>
                    <AlertDialogTitle>Gene report</AlertDialogTitle>
                    <AlertDialogDescription>
                        Runs seven analyses of one gene at once: tumor vs normal expression and survival in CPTAC,
                        survival across TCGA cohorts, its drug-target profile, treatment response in trials, FunMap
                        neighbors, and recent literature.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <div className="space-y-2">
                    <Input
                        value={entry}
                        onChange={(e) => setEntry(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") void run() }}
                        placeholder="Gene symbol, e.g. ERBB2"
                        disabled={checking}
                        autoFocus
                        aria-label="Gene for the report"
                    />
                    {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
                </div>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)} disabled={checking}>
                        Cancel
                    </Button>
                    <Button onClick={() => void run()} disabled={checking || !entry.trim()} className="gap-2">
                        {checking && <Loader2 className="w-4 h-4 animate-spin" />}
                        Run report
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
