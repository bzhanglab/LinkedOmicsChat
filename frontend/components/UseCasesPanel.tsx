"use client"

import { ArrowRight } from "lucide-react"

type Topic =
    | "Expression and cis-associations"
    | "Survival"
    | "Drug targets"
    | "Treatment response"
    | "Clinical studies"
    | "Networks and pathways"
    | "Literature and gene IDs"

// Display order of the tiles, with the data sources each topic draws on.
const TOPICS: { title: Topic; sources: string }[] = [
    { title: "Expression and cis-associations", sources: "CPTAC · TCGA" },
    { title: "Survival", sources: "CPTAC · TCGA" },
    { title: "Drug targets", sources: "LinkedOmics Targets" },
    { title: "Treatment response", sources: "ClinicalOmicsDB" },
    { title: "Clinical studies", sources: "ClinicalOmicsDB" },
    { title: "Networks and pathways", sources: "FunMap · WebGestalt" },
    { title: "Literature and gene IDs", sources: "PubMed · MyGene.info" },
]

// The `exampleQuery` key is what backend/admin/check_prepopulated_genes.py looks for.
const USE_CASES: { topic: Topic; exampleQuery: string }[] = [
    { topic: "Expression and cis-associations", exampleQuery: "How is EGFR expressed tumor vs normal in LUAD?" },
    { topic: "Expression and cis-associations", exampleQuery: "Show cis-correlations for BRCA1 across CPTAC cohorts." },
    { topic: "Expression and cis-associations", exampleQuery: "Show cis associations for TP53 in BRCA across available omics pairs." },
    { topic: "Survival", exampleQuery: "Show TP53 overall survival in BRCA." },
    { topic: "Survival", exampleQuery: "Show TP53 methylation survival in BRCA from TCGA." },
    { topic: "Survival", exampleQuery: "Compare survival impact of EGFR methylation vs RNA in BRCA." },
    { topic: "Drug targets", exampleQuery: "Is EGFR a validated oncology target?" },
    { topic: "Drug targets", exampleQuery: "Which kinases are FDA-approved oncology targets?" },
    { topic: "Drug targets", exampleQuery: "Which genes are tumor-specific antigens (TSA) in T1 tier?" },
    { topic: "Drug targets", exampleQuery: "What are the most attractive therapeutic targets for cancer?" },
    { topic: "Treatment response", exampleQuery: "Which drugs are patients likely to be resistant to if they have high EGFR expression?" },
    { topic: "Treatment response", exampleQuery: "Which drugs do ESR1 and ERBB2 predict resistance to?" },
    { topic: "Treatment response", exampleQuery: "Does the HALLMARK_ESTROGEN_RESPONSE_EARLY pathway predict tamoxifen sensitivity?" },
    { topic: "Treatment response", exampleQuery: "Which genes best predict paclitaxel response in breast cancer?" },
    { topic: "Treatment response", exampleQuery: "What pathways predict platinum resistance in ovarian cancer?" },
    { topic: "Clinical studies", exampleQuery: "Which studies tested nivolumab in melanoma?" },
    { topic: "Clinical studies", exampleQuery: "Which genes predict response in study GSE25066?" },
    { topic: "Clinical studies", exampleQuery: "What was study GSE25066 about?" },
    { topic: "Networks and pathways", exampleQuery: "Find functional neighbors of TP53 in the FunMap network." },
    { topic: "Networks and pathways", exampleQuery: "Find functional partners of BRCA1, identify which are druggable oncology targets, and check if any predict survival in breast cancer." },
    { topic: "Networks and pathways", exampleQuery: "Run pathway enrichment analysis on TP53, MDM2, CDKN1A, ATM, and BRCA1." },
    { topic: "Networks and pathways", exampleQuery: "What pathways are enriched in this gene set: EGFR, MET, ERBB2, ALK, RET?" },
    { topic: "Literature and gene IDs", exampleQuery: "Find recent papers on ESR1 and breast cancer survival." },
    { topic: "Literature and gene IDs", exampleQuery: "Get the abstract for PMID 25892560." },
    { topic: "Literature and gene IDs", exampleQuery: "What gene is ENSG00000141510?" },
]

interface UseCasesPanelProps {
    onStartChat: (query: string) => void
}

export function UseCasesPanel({ onStartChat }: UseCasesPanelProps) {
    return (
        <div className="h-full overflow-y-auto bg-gray-50 dark:bg-gray-900">
            <div className="max-w-6xl mx-auto px-6 py-8">
                <div className="mb-6">
                    <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">Use cases</h1>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                        Questions that work well, grouped by what they ask. Click one to put it in the chat box, then edit it or send it.
                    </p>
                </div>
                {/* CSS columns balance the uneven tile heights */}
                <div className="columns-1 lg:columns-2 2xl:columns-3 gap-4">
                    {TOPICS.map((topic) => (
                        <section key={topic.title} className="break-inside-avoid mb-4 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-5">
                            <h2 className="font-semibold text-gray-900 dark:text-gray-100">{topic.title}</h2>
                            <p className="text-xs text-gray-400 mt-0.5">{topic.sources}</p>
                            <ul className="mt-3 space-y-0.5">
                                {USE_CASES.filter((uc) => uc.topic === topic.title).map((uc) => (
                                    <li key={uc.exampleQuery}>
                                        <button
                                            onClick={() => onStartChat(uc.exampleQuery)}
                                            className="group flex items-start gap-2 w-full text-left rounded-md px-2 py-1.5 -mx-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-teal-50 dark:hover:bg-teal-900/20 hover:text-teal-800 dark:hover:text-teal-200"
                                        >
                                            <ArrowRight className="w-3.5 h-3.5 mt-[3px] shrink-0 text-gray-300 dark:text-gray-600 group-hover:text-teal-500" />
                                            <span>{uc.exampleQuery}</span>
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        </section>
                    ))}
                </div>
            </div>
        </div>
    )
}
