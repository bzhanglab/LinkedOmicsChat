"use client"
import { useRef, useLayoutEffect, useState } from "react"

const OMICS = [
    { code: "RNAseq",             desc: "mRNA expression (RNA-seq)",                         source: "TCGA" },
    { code: "RPPA",               desc: "Protein abundance (Reverse Phase Protein Array)",    source: "TCGA" },
    { code: "Methylation",        desc: "DNA methylation (Illumina 450K array)",              source: "TCGA" },
    { code: "SCNA",               desc: "Somatic copy number alteration",                     source: "TCGA" },
    { code: "miRNASeq",           desc: "microRNA expression (miRNA-seq); survival only",     source: "TCGA" },
    { code: "RNA",                desc: "mRNA expression",                                    source: "CPTAC" },
    { code: "Proteomics",         desc: "Global protein abundance (mass spectrometry)",       source: "CPTAC" },
    { code: "Methylation",        desc: "DNA methylation; same-gene correlations only",       source: "CPTAC" },
    { code: "SCNV",               desc: "Somatic copy number; same-gene correlations only",   source: "CPTAC" },
    { code: "Phosphoproteomics",  desc: "Phosphosite activation, shown in drug-target profiles only", source: "CPTAC" },
]

const CPTAC_COHORTS = ["BRCA", "CCRCC", "COAD", "GBM", "HNSCC", "LSCC", "LUAD", "OV", "PDAC", "UCEC"]

const COHORTS = [
    ["ACC", "Adrenocortical carcinoma"],
    ["BLCA", "Bladder urothelial carcinoma"],
    ["BRCA", "Breast invasive carcinoma"],
    ["CESC", "Cervical and endocervical cancers"],
    ["CHOL", "Cholangiocarcinoma"],
    ["COADREAD", "Colorectal adenocarcinoma"],
    ["DLBC", "Diffuse Large B-cell Lymphoma"],
    ["ESCA", "Esophageal carcinoma"],
    ["GBM", "Glioblastoma multiforme"],
    ["GBMLGG", "Glioma"],
    ["HNSC", "Head and Neck squamous cell carcinoma"],
    ["KICH", "Kidney Chromophobe"],
    ["KIPAN", "Pan-kidney cohort (KICH+KIRC+KIRP)"],
    ["KIRC", "Kidney renal clear cell carcinoma"],
    ["KIRP", "Kidney renal papillary cell carcinoma"],
    ["LAML", "Acute Myeloid Leukemia"],
    ["LGG", "Brain Lower Grade Glioma"],
    ["LIHC", "Liver hepatocellular carcinoma"],
    ["LUAD", "Lung adenocarcinoma"],
    ["LUSC", "Lung squamous cell carcinoma"],
    ["MESO", "Mesothelioma"],
    ["OV", "Ovarian serous cystadenocarcinoma"],
    ["PAAD", "Pancreatic adenocarcinoma"],
    ["PCPG", "Pheochromocytoma and Paraganglioma"],
    ["PRAD", "Prostate adenocarcinoma"],
    ["SARC", "Sarcoma"],
    ["SKCM", "Skin Cutaneous Melanoma"],
    ["STAD", "Stomach adenocarcinoma"],
    ["STES", "Stomach and Esophageal carcinoma"],
    ["TGCT", "Testicular Germ Cell Tumors"],
    ["THCA", "Thyroid carcinoma"],
    ["THYM", "Thymoma"],
    ["UCEC", "Uterine Corpus Endometrial Carcinoma"],
    ["UCS", "Uterine Carcinosarcoma"],
    ["UVM", "Uveal Melanoma"],
]

export function OmicsCohorts() {
    const omicsRef = useRef<HTMLUListElement>(null)
    const [cohortsHeight, setCohortsHeight] = useState<number | null>(null)

    useLayoutEffect(() => {
        if (omicsRef.current) {
            setCohortsHeight(omicsRef.current.offsetHeight)
        }
    }, [])

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {/* Omics — full content, drives height */}
            <div>
                <h3 className="text-sm font-semibold mb-2 text-muted-foreground uppercase tracking-wider">
                    <a href="https://www.linkedomics.org/login.php#omicsData" target="_blank" rel="noopener noreferrer" className="hover:underline">
                        Omics data ↗
                    </a>
                </h3>
                <ul className="space-y-2" ref={omicsRef}>
                    {OMICS.map(({ code, desc, source }) => (
                        <li key={`${source}-${code}`} className="rounded border border-border bg-background px-3 py-2 flex items-center justify-between gap-3">
                            <div className="min-w-0">
                                <span className="font-mono text-sm text-teal-700 dark:text-teal-400 block">{code}</span>
                                <span className="text-sm text-muted-foreground">{desc}</span>
                            </div>
                            <span className={`text-xs px-1.5 py-0.5 rounded font-medium shrink-0 ${
                                source === "CPTAC"
                                    ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-400"
                                    : "bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-400"
                            }`}>{source}</span>
                        </li>
                    ))}
                </ul>
                <p className="mt-3 text-sm text-muted-foreground">
                    CPTAC cohorts ({CPTAC_COHORTS.length}): {CPTAC_COHORTS.join(", ")}
                </p>
            </div>

            {/* Cohorts — scrollable, matches omics height */}
            <div className="flex flex-col">
                <h3 className="text-sm font-semibold mb-2 text-muted-foreground uppercase tracking-wider">
                    TCGA cohorts ({COHORTS.length}, including 4 combined)
                </h3>
                <div
                    className="overflow-y-auto rounded border border-border text-sm"
                    style={cohortsHeight ? { height: cohortsHeight } : { maxHeight: 400 }}
                >
                    <table className="w-full border-collapse">
                        <tbody>
                            {COHORTS.map(([code, name], i) => (
                                <tr key={code} className={i % 2 === 0 ? "bg-background" : "bg-muted/20"}>
                                    <td className="px-2 py-1 font-mono font-medium text-teal-700 dark:text-teal-400 w-24">{code}</td>
                                    <td className="px-2 py-1 text-muted-foreground">{name}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}
