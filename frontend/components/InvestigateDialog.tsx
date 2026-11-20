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
import { INVESTIGATION_CANCERS as CANCERS } from "@/lib/investigation"

const QUESTIONS: [string, string][] = [
    ["a drug target", "Drug target"],
    ["a prognostic marker", "Prognostic marker"],
    ["literature", "Published findings"],  // a literature check, not an investigation
]

const selectClass =
    "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background " +
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"

/**
 * Ask for a gene, a question and a cancer, and start the investigation. The gene is checked like a
 * gene report's, so old names and Ensembl or UniProt IDs become current symbols and typos are caught here.
 */
export function InvestigateDialog({
    open,
    onOpenChange,
    onRun,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    onRun: (request: string) => void
}) {
    const [entry, setEntry] = useState("")
    const [question, setQuestion] = useState(QUESTIONS[0][0])
    const [cancer, setCancer] = useState(CANCERS[0][1])
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
                onRun(question === "literature"
                    ? `Check the literature on ${result.genes[0]} in ${cancer}`
                    : `Investigate ${result.genes[0]} as ${question} in ${cancer}`)
                onOpenChange(false)
            } else if (result.genes.length > 1) {
                setError("Enter one gene; an investigation covers a single gene.")
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
                    <AlertDialogTitle>Investigate</AlertDialogTitle>
                    <AlertDialogDescription>
                        Runs every analysis that bears on the question in one cancer and rates the evidence by fixed
                        rules: a verdict, one rated line per piece of evidence, and the gaps in the data. Published
                        findings instead sets what papers report about the gene beside CPTAC and TCGA.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <div className="space-y-3">
                    <div className="space-y-1">
                        <label htmlFor="investigate-gene" className="text-sm font-medium">Gene</label>
                        <Input
                            id="investigate-gene"
                            value={entry}
                            onChange={(e) => setEntry(e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Enter") void run() }}
                            placeholder="Gene symbol, e.g. CDK4"
                            disabled={checking}
                            autoFocus
                        />
                    </div>
                    <div className="space-y-1">
                        <label htmlFor="investigate-question" className="text-sm font-medium">Question</label>
                        <select id="investigate-question" value={question} onChange={(e) => setQuestion(e.target.value)}
                            disabled={checking} className={selectClass}>
                            {QUESTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                        </select>
                    </div>
                    <div className="space-y-1">
                        <label htmlFor="investigate-cancer" className="text-sm font-medium">Cancer</label>
                        <select id="investigate-cancer" value={cancer} onChange={(e) => setCancer(e.target.value)}
                            disabled={checking} className={selectClass}>
                            {CANCERS.map(([code, name]) => (
                                <option key={code} value={name}>{name.charAt(0).toUpperCase() + name.slice(1)} ({code})</option>
                            ))}
                        </select>
                    </div>
                    {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
                </div>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)} disabled={checking}>
                        Cancel
                    </Button>
                    <Button onClick={() => void run()} disabled={checking || !entry.trim()} className="gap-2">
                        {checking && <Loader2 className="w-4 h-4 animate-spin" />}
                        Investigate
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
