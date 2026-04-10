"use client"

import type { PredictiveResultsTableVisualization, TCGACisResultsTableVisualization } from "@/lib/api"
import { PredictiveResultsTable } from "@/components/PredictiveResultsTable"

interface Props {
    visualization: TCGACisResultsTableVisualization
}

export function TCGACisResultsTable({ visualization }: Props) {
    const mapped: PredictiveResultsTableVisualization = {
        type: "predictive_results_table",
        variant: "tcga_cis",
        id: visualization.id,
        title: visualization.title,
        row_label: "Gene",
        col_auroc: "Correlation",
        col_fdr: "FDR",
        page_size: 10,
        description: visualization.description,
        rows: (visualization.rows || []).map((row) => ({
            rank: row.rank,
            label: row.gene,
            avg_auroc: row.correlation,
            meta_fdr: row.fdr,
            meta_fdr_sci: row.fdr_sci,
            studies: row.n,
            direction: row.correlation >= 0 ? "positive" : "negative",
        })),
    }

    return <PredictiveResultsTable visualization={mapped} />
}
