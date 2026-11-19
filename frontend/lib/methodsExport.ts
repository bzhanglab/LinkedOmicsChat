import type { ChatMessage } from "./api"

type SourceKey = "linkedomics" | "linkedomicskb" | "cptac" | "tcga" | "clinicalomicsdb" | "targets" | "funmap" | "webgestalt" | "mygene"

// PubMed entries for the resources behind the tools (looked up 2026-11-18)
const REFERENCES: Record<SourceKey, string> = {
    linkedomics: "Vasaikar SV, Straub P, Wang J, Zhang B. LinkedOmics: analyzing multi-omics data within and across 32 cancer types. Nucleic Acids Res. 2018;46(D1):D956-D963. doi:10.1093/nar/gkx1090",
    linkedomicskb: "Liao Y, Savage SR, Dou Y, et al. A proteogenomics data-driven knowledge base of human cancer. Cell Syst. 2023;14(9):777-787.e5. doi:10.1016/j.cels.2023.07.007",
    cptac: "Li Y, Dou Y, Da Veiga Leprevost F, et al. Proteogenomic data and resources for pan-cancer analysis. Cancer Cell. 2023;41(8):1397-1406. doi:10.1016/j.ccell.2023.06.009",
    tcga: "Weinstein JN, Collisson EA, Mills GB, et al. The Cancer Genome Atlas Pan-Cancer analysis project. Nat Genet. 2013;45(10):1113-1120. doi:10.1038/ng.2764",
    clinicalomicsdb: "Moon CI, Elizarraras JM, Lei JT, Jia B, Zhang B. ClinicalOmicsDB: exploring molecular associations of oncology drug responses in clinical trials. Nucleic Acids Res. 2024;52(D1):D1201-D1209. doi:10.1093/nar/gkad871",
    targets: "Savage SR, Yi X, Lei JT, et al. Pan-cancer proteogenomics expands the landscape of therapeutic targets. Cell. 2024;187(16):4389-4407.e15. doi:10.1016/j.cell.2024.05.039",
    funmap: "Shi Z, Lei JT, Elizarraras JM, Zhang B. Mapping the functional network of human cancer through machine learning and pan-cancer proteogenomics. Nat Cancer. 2025;6(1):205-222. doi:10.1038/s43018-024-00869-z",
    webgestalt: "Elizarraras JM, Liao Y, Shi Z, Zhu Q, Pico AR, Zhang B. WebGestalt 2024: faster gene set analysis and new support for metabolomics and multi-omics. Nucleic Acids Res. 2024;52(W1):W415-W421. doi:10.1093/nar/gkae456",
    mygene: "Xin J, Mark A, Afrasiabi C, et al. High-performance web services for querying gene and variant annotation. Genome Biol. 2016;17:91. doi:10.1186/s13059-016-0953-9",
}

const TCGA_OMICS: Record<string, string> = {
    RNAseq: "RNA-seq",
    RPPA: "RPPA protein",
    SCNA: "somatic copy-number",
    Methylation: "DNA methylation",
    miRNASeq: "miRNA-seq",
}

type Args = Record<string, unknown>
type Sentence = { text: string; sources: SourceKey[] }

function list(items: string[]): string {
    if (items.length <= 1) return items.join("")
    return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`
}

function genes(args: Args): string {
    const raw = args.proteins ?? args.protein ?? args.gene
    const symbols = Array.isArray(raw) ? raw.map(String) : String(raw ?? "").split(/[,\s]+/).filter(Boolean)
    return symbols.length > 5 ? `${symbols.length} genes` : list(symbols)
}

function strings(value: unknown): string[] {
    return Array.isArray(value) ? value.map(String).filter(Boolean) : value ? [String(value)] : []
}

function omics(value: unknown): string {
    return TCGA_OMICS[String(value)] ?? String(value)
}

/** " to paclitaxel in breast cancer", from a trial tool's drug, treatment and cancer filters. */
function trialFilter(args: Args, preposition: "to" | "of"): string {
    const parts = [
        strings(args.drugs).length ? list(strings(args.drugs)) : "",
        args.treatment_category ? `${String(args.treatment_category).toLowerCase()} treatment` : "",
    ].filter(Boolean)
    const cancers = strings(args.cancers).map(cancerName)
    return `${parts.length ? ` ${preposition} ${parts.join(", ")}` : ""}${cancers.length ? ` in ${list(cancers)}` : ""}`
}

/** "Breast" -> "breast cancer", but "Melanoma" -> "melanoma". */
function cancerName(name: string): string {
    const lower = name.toLowerCase()
    return /cancer|carcinoma|melanoma|leuka?emia|myeloma|lymphoma|glioblastoma|sarcoma|tumou?r/.test(lower) ? lower : `${lower} cancer`
}

// The same separators the CPTAC tool accepts in a pair such as "RNA vs Protein"
const PAIR_SPLIT = /\s*(?:vs\.?|versus|↔|<->|->|to|\/|,)\s*/i
const LAYER_NAMES: Record<string, string> = { rna: "RNA", mrna: "RNA", protein: "protein", scnv: "copy-number", cnv: "copy-number", scna: "copy-number", methylation: "DNA methylation" }
const LAYER_ORDER = ["RNA", "protein", "DNA methylation", "copy-number"]

/** "RNA vs Protein" or "Protein ↔ RNA" -> "RNA–protein". */
function pairName(pair: string): string {
    const layers = pair.split(PAIR_SPLIT).filter(Boolean)
    if (layers.length !== 2) return pair
    const rank = (name: string) => (LAYER_ORDER.includes(name) ? LAYER_ORDER.indexOf(name) : LAYER_ORDER.length)
    return layers
        .map((layer) => LAYER_NAMES[layer.toLowerCase().replace(/[^a-z0-9]/g, "")] ?? layer)
        .sort((x, y) => rank(x) - rank(y))
        .join("–")
}

const UNIPROT_ACCESSION = /^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})$/

// One sentence per tool, describing what the call retrieved and where from. Statistics are named
// only where the tool reports them (hazard ratios, AUROC, the chosen correlation method).
const SENTENCES: Record<string, (args: Args) => Sentence | null> = {
    compare_cptac_tumor_normal_expression: (a) => ({ text: `Tumor and adjacent normal tissue RNA and protein abundance of ${genes(a)} were compared across CPTAC cohorts with LinkedOmicsKB`, sources: ["linkedomicskb", "cptac"] }),
    batch_compare_cptac_tumor_normal_expression: (a) => ({ text: `Tumor and adjacent normal tissue RNA and protein abundance of ${genes(a)} were compared across CPTAC cohorts with LinkedOmicsKB`, sources: ["linkedomicskb", "cptac"] }),
    analyze_cptac_gene_survival_associations: (a) => ({ text: `Associations of high versus low RNA and protein abundance of ${genes(a)} with overall survival in CPTAC cohorts were taken from LinkedOmicsKB`, sources: ["linkedomicskb", "cptac"] }),
    batch_analyze_cptac_gene_survival_associations: (a) => ({ text: `Associations of high versus low RNA and protein abundance of ${genes(a)} with overall survival in CPTAC cohorts were taken from LinkedOmicsKB`, sources: ["linkedomicskb", "cptac"] }),
    analyze_cptac_cis_associations: (a) => cptacCis(a),
    batch_analyze_cptac_cis_associations: (a) => cptacCis(a),
    analyze_tcga_survival_associations: (a) => ({
        text: `Hazard ratios for overall survival by ${a.omics ? omics(a.omics) : "molecular"} measurements${a.gene ? ` of ${a.gene}` : ""}${a.cohort ? ` in the TCGA ${a.cohort} cohort` : " across TCGA cohorts"} were obtained from LinkedOmics`,
        sources: ["linkedomics", "tcga"],
    }),
    analyze_tcga_cis_associations: (a) => ({
        text: `${a.st_method ? `${String(a.st_method)[0].toUpperCase()}${String(a.st_method).slice(1)} correlations` : "Correlations"} between ${a.source_omics ? omics(a.source_omics) : "molecular"} and ${a.target_omics ? omics(a.target_omics) : "other molecular"} measurements${a.gene ? ` of ${a.gene}` : ""}${a.cohort ? ` in the TCGA ${a.cohort} cohort` : " across TCGA cohorts"} were obtained from LinkedOmics`,
        sources: ["linkedomics", "tcga"],
    }),
    get_drug_target_profile: (a) => ({ text: `Drug-target evidence for ${genes(a)}, including target tier and associated drugs, was retrieved from LinkedOmics Targets`, sources: ["targets"] }),
    batch_get_drug_target_profiles: (a) => ({ text: `Drug-target evidence for ${genes(a)}, including target tiers and associated drugs, was retrieved from LinkedOmics Targets`, sources: ["targets"] }),
    search_drug_target_index: (a) => {
        const filters = [a.tier && `tier ${a.tier}`, a.family && `the ${a.family} family`, a.antigen && `${a.antigen} antigens`, a.drug_name && `the drug ${a.drug_name}`].filter(Boolean) as string[]
        return { text: `The LinkedOmics Targets index was searched${filters.length ? ` for ${list(filters)}` : ""}`, sources: ["targets"] }
    },
    rank_drug_targets: (a) => {
        const filters = [strings(a.tiers).length && `tiers ${list(strings(a.tiers))}`, a.family && `the ${a.family} family`, a.antigen && `${a.antigen} antigens`].filter(Boolean) as string[]
        return { text: `Candidate drug targets${filters.length ? ` in ${list(filters)}` : ""} were ranked by the LinkedOmics Targets composite score${a.ranking_mode ? ` (${a.ranking_mode} mode)` : ""}`, sources: ["targets"] }
    },
    get_funmap_functional_neighborhood: (a) => ({ text: `The functional neighborhood of ${genes(a)}, the 50 genes with the highest random-walk probability from it, was retrieved from the FunMap network`, sources: ["funmap"] }),
    run_webgestalt_go_enrichment: (a) => ({ text: `Gene Ontology biological process over-representation analysis of ${genes(a)} against a genome background was performed with WebGestalt`, sources: ["webgestalt"] }),
    search_gene_response_trials: (a) => ({ text: `Associations between ${genes(a)} expression and treatment response (AUROC) in trial-linked gene-expression studies were retrieved from ClinicalOmicsDB`, sources: ["clinicalomicsdb"] }),
    batch_search_gene_response_trials: (a) => ({ text: `Associations between ${genes(a)} expression and treatment response (AUROC) in trial-linked gene-expression studies were retrieved from ClinicalOmicsDB`, sources: ["clinicalomicsdb"] }),
    search_gene_set_response_trials: (a) => ({ text: `Associations between ${a.gene_set} activity and treatment response (AUROC) in trial-linked gene-expression studies were retrieved from ClinicalOmicsDB`, sources: ["clinicalomicsdb"] }),
    search_trial_studies: (a) => ({ text: `Trial-linked gene-expression studies${trialFilter(a, "of")} were identified in ClinicalOmicsDB`, sources: ["clinicalomicsdb"] }),
    get_trial_study_details: (a) => ({ text: `Details of study ${a.study_id} were retrieved from ClinicalOmicsDB`, sources: ["clinicalomicsdb"] }),
    meta_analyze_response_genes: (a) => ({ text: `Genes consistently associated with response${trialFilter(a, "to")} were ranked by a meta-analysis of trial-linked studies in ClinicalOmicsDB`, sources: ["clinicalomicsdb"] }),
    meta_analyze_response_gene_sets: (a) => ({ text: `Gene sets consistently associated with response${trialFilter(a, "to")} were ranked by a meta-analysis of trial-linked studies in ClinicalOmicsDB`, sources: ["clinicalomicsdb"] }),
    rank_study_response_genes: (a) => ({ text: `Genes associated with treatment response in study ${a.study_id} were ranked with ClinicalOmicsDB`, sources: ["clinicalomicsdb"] }),
    match_signature_to_treatment_response: (a) => ({ text: `A signature of ${genes(a)} was tested against treatment response in trial-linked gene-expression studies from ClinicalOmicsDB: in each study, the signature genes' response AUROCs were compared with those of all other measured genes, with significance judged on the study's patients as well as its genes and false discovery rates across studies`, sources: ["clinicalomicsdb"] }),
    rank_study_response_gene_sets: (a) => ({ text: `Gene sets associated with treatment response in study ${a.study_id} were ranked with ClinicalOmicsDB`, sources: ["clinicalomicsdb"] }),
    // Plain symbols are only checked, so only converted Ensembl or UniProt IDs need a sentence
    resolve_gene_identifier: (a) => {
        const id = String(a.identifier ?? "").trim()
        return /^ENS[A-Z]*G\d+/i.test(id) || UNIPROT_ACCESSION.test(id.toUpperCase())
            ? { text: "Gene identifiers (Ensembl or UniProt) were converted to HGNC gene symbols with MyGene.info", sources: ["mygene"] }
            : null
    },
    search_pubmed_articles: (a) => ({ text: `PubMed was searched for "${a.query}"`, sources: [] }),
    get_pubmed_article_details: () => null,
}

function cptacCis(a: Args): Sentence {
    const pairs = strings(a.pairs)
    const cancers = strings(a.cancers)
    const where = cancers.length ? ` in the CPTAC ${list(cancers)} cohorts` : " across CPTAC cohorts"
    return {
        text: pairs.length
            ? `${list(pairs.map(pairName))} correlations of ${genes(a)}${where} were taken from LinkedOmicsKB`
            : `Correlations between RNA, protein, DNA methylation and copy-number measurements of ${genes(a)}${where} were taken from LinkedOmicsKB`,
        sources: ["linkedomicskb", "cptac"],
    }
}

function formatDate(date: Date): string {
    return date.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })
}

/**
 * Build a methods paragraph and reference list describing the analyses in a chat: one
 * sentence per distinct tool call that returned data, with numbered citations of the
 * resources it drew on.
 */
export function buildMethodsText(messages: ChatMessage[], appUrl: string): string {
    const sentences: string[] = []
    const cited: SourceKey[] = []
    const dates: Date[] = []

    for (const msg of messages) {
        if (msg.role !== "assistant" || !msg.toolCalls?.length) continue
        let described = false
        for (const call of msg.toolCalls) {
            if (call.status !== "ok") continue
            const toolName = call.tool_id.split("::").pop() || call.tool_id
            const template = SENTENCES[toolName]
            const sentence = template ? template(call.arguments ?? {}) : { text: `The LinkedOmicsChat tool ${toolName} was also used`, sources: [] }
            if (!sentence) continue
            described = true
            for (const source of sentence.sources) {
                if (!cited.includes(source)) cited.push(source)
            }
            const numbers = sentence.sources.map((source) => cited.indexOf(source) + 1)
            const text = `${sentence.text[0].toUpperCase()}${sentence.text.slice(1)}${numbers.length ? ` [${numbers.join(", ")}]` : ""}.`
            if (!sentences.includes(text)) sentences.push(text)
        }
        if (described && msg.timestamp) dates.push(msg.timestamp)
    }

    if (!sentences.length) {
        return "This chat ran no analyses that returned data, so there is nothing to describe.\n"
    }

    const days = Array.from(new Set([...dates].sort((x, y) => x.getTime() - y.getTime()).map(formatDate)))
    const when = days.length === 0 ? "" : days.length === 1 ? ` on ${days[0]}` : ` between ${days[0]} and ${days[days.length - 1]}`
    const opening = `Analyses were run in LinkedOmicsChat (${appUrl})${when}.`

    return `Methods

${[opening, ...sentences].join(" ")}

References

${cited.map((source, i) => `${i + 1}. ${REFERENCES[source]}`).join("\n")}

Generated by LinkedOmicsChat from the analyses in a chat. Check it against the chat before using it.
`
}
