"use client"

import type { ComponentProps } from "react"
import { ToolCategoryGuide, type ToolCategoryGuideKey } from "@/components/ToolCategoryGuide"

type ClinicalTrialsPrimerProps = Omit<ComponentProps<typeof ToolCategoryGuide>, "category">

export function ClinicalTrialsPrimer(props: ClinicalTrialsPrimerProps) {
    return <ToolCategoryGuide {...props} category={"clinical-trials" satisfies ToolCategoryGuideKey} />
}
