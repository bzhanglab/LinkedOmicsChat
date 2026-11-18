"use client"

import { useEffect, useRef, useState } from "react"
import { Loader2, Upload } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { chatAPI, type GeneListCheck } from "@/lib/api"

const MAX_FILE_BYTES = 5_000_000

function preview(items: string[], limit: number): string {
    return items.length > limit ? `${items.slice(0, limit).join(", ")} and ${items.length - limit} more` : items.join(", ")
}

/** What the check found, in plain words: kept, converted, renamed, and left out. */
function CheckSummary({ result }: { result: GeneListCheck }) {
    const changes = (rows: { from: string; to: string }[]) => preview(rows.map((r) => `${r.from} → ${r.to}`), 5)
    const ambiguous = result.ambiguous.map((a) => `${a.name} (${a.matches.join(" or ")})`)
    return (
        <div className="space-y-1.5 rounded-lg border border-border p-3 text-sm">
            <p className="font-medium">
                {result.genes.length} {result.genes.length === 1 ? "gene" : "genes"} ready
                <span className="font-normal text-muted-foreground">
                    {" "}from {result.entries} {result.entries === 1 ? "entry" : "entries"}
                    {result.column ? ` in the "${result.column}" column` : ""}
                </span>
            </p>
            {result.converted.length > 0 && <p className="text-xs">IDs converted to gene symbols: {changes(result.converted)}</p>}
            {result.renamed.length > 0 && <p className="text-xs">Old names updated: {changes(result.renamed)}</p>}
            {ambiguous.length > 0 && <p className="text-xs text-amber-700 dark:text-amber-400">Left out, could be several genes: {preview(ambiguous, 3)}</p>}
            {result.unrecognized.length > 0 && <p className="text-xs text-amber-700 dark:text-amber-400">Left out, not recognized: {preview(result.unrecognized, 8)}</p>}
            {result.truncated > 0 && <p className="text-xs text-amber-700 dark:text-amber-400">Only the first 2,000 genes are kept; {result.truncated} more were left out.</p>}
            {result.lookup_failed && <p className="text-xs text-amber-700 dark:text-amber-400">The ID conversion service did not respond, so IDs and old names were left out. Try again in a moment.</p>}
        </div>
    )
}

export function GeneListDialog({
    open,
    onOpenChange,
    attached,
    onAttach,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    attached: GeneListCheck | null
    onAttach: (list: GeneListCheck) => void
}) {
    const [text, setText] = useState("")
    const [fileName, setFileName] = useState<string | null>(null)
    const [checking, setChecking] = useState(false)
    const [result, setResult] = useState<GeneListCheck | null>(null)
    const [error, setError] = useState<string | null>(null)
    const fileInputRef = useRef<HTMLInputElement>(null)

    // Reopening shows the attached list's check; a new list starts from scratch
    useEffect(() => {
        if (!open) return
        setText("")
        setFileName(null)
        setError(null)
        setResult(attached)
    }, [open, attached])

    const check = async (listText: string, name?: string) => {
        if (!listText.trim()) return
        setChecking(true)
        setError(null)
        setResult(null)
        try {
            setResult(await chatAPI.checkGeneList(listText, name))
        } catch (e: any) {
            setError(e?.response?.data?.detail || "The list could not be checked. Try again in a moment.")
        } finally {
            setChecking(false)
        }
    }

    const handleFile = async (file: File | undefined) => {
        if (!file) return
        if (file.size > MAX_FILE_BYTES) {
            setError("The file is larger than 5 MB. Keep only the gene column and try again.")
            return
        }
        const fileText = await file.text()
        setFileName(file.name)
        setText("")
        await check(fileText, file.name)
    }

    return (
        <AlertDialog open={open} onOpenChange={(next) => { if (!checking) onOpenChange(next) }}>
            <AlertDialogContent className="max-w-lg">
                <AlertDialogHeader>
                    <AlertDialogTitle>Attach a gene list</AlertDialogTitle>
                    <AlertDialogDescription>
                        Upload a text, CSV, or TSV file, or paste gene symbols, Ensembl IDs, or UniProt accessions.
                        Enrichment uses the whole list; per-gene analyses, such as survival or drug targets, use the first 50 genes.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <div className="space-y-3">
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept=".txt,.csv,.tsv,.tab,text/plain,text/csv,text/tab-separated-values"
                        className="hidden"
                        onChange={(e) => {
                            void handleFile(e.target.files?.[0])
                            e.target.value = ""
                        }}
                    />
                    <Button type="button" variant="outline" className="w-full gap-2" onClick={() => fileInputRef.current?.click()} disabled={checking}>
                        <Upload className="w-4 h-4" />
                        {fileName ? `Choose another file (${fileName})` : "Choose a file"}
                    </Button>
                    <div className="space-y-2">
                        <textarea
                            value={text}
                            onChange={(e) => setText(e.target.value)}
                            placeholder="Or paste genes here, e.g. TP53, EGFR, ENSG00000141510"
                            rows={4}
                            disabled={checking}
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                        <Button type="button" variant="outline" size="sm" onClick={() => { setFileName(null); void check(text) }} disabled={checking || !text.trim()}>
                            Check pasted genes
                        </Button>
                    </div>
                    {checking && (
                        <p className="flex items-center gap-2 text-sm text-muted-foreground">
                            <Loader2 className="w-4 h-4 animate-spin" /> Checking the list…
                        </p>
                    )}
                    {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
                    {result && <CheckSummary result={result} />}
                </div>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)} disabled={checking}>
                        Cancel
                    </Button>
                    <Button
                        onClick={() => {
                            if (result) onAttach(result)
                            onOpenChange(false)
                        }}
                        disabled={checking || !result || result.genes.length === 0}
                    >
                        {attached && result === attached ? "Keep this list" : "Attach list"}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
