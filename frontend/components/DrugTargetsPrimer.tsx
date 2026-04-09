"use client"

import type { ComponentProps } from "react"
import { ToolCategoryGuide, type ToolCategoryGuideKey, DRUG_TARGET_TIER_GUIDE, getDrugTargetTierDefinition } from "@/components/ToolCategoryGuide"

type DrugTargetsPrimerProps = Omit<ComponentProps<typeof ToolCategoryGuide>, "category">

export { DRUG_TARGET_TIER_GUIDE, getDrugTargetTierDefinition }

export function DrugTargetsPrimer(props: DrugTargetsPrimerProps) {
    return <ToolCategoryGuide {...props} category={"drug-targets" satisfies ToolCategoryGuideKey} />
}
