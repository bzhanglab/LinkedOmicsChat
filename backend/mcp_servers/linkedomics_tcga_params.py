from typing import Literal, Any


TCGA_COHORT_DESCRIPTIONS = {
    "ACC": "Adrenocortical carcinoma",
    "BLCA": "Bladder urothelial carcinoma",
    "BRCA": "Breast invasive carcinoma",
    "CESC": "Cervical and endocervical cancers",
    "CHOL": "Cholangiocarcinoma",
    "COADREAD": "Colorectal adenocarcinoma",
    "DLBC": "Lymphoid Neoplasm Diffuse Large B-cell Lymphoma",
    "ESCA": "Esophageal carcinoma",
    "GBM": "Glioblastoma multiforme",
    "GBMLGG": "Glioma",
    "HNSC": "Head and Neck squamous cell carcinoma",
    "KICH": "Kidney Chromophobe",
    "KIPAN": "Pan-kidney cohort (KICH+KIRC+KIRP)",
    "KIRC": "Kidney renal clear cell carcinoma",
    "KIRP": "Kidney renal papillary cell carcinoma",
    "LAML": "Acute Myeloid Leukemia",
    "LGG": "Brain Lower Grade Glioma",
    "LIHC": "Liver hepatocellular carcinoma",
    "LUAD": "Lung adenocarcinoma",
    "LUSC": "Lung squamous cell carcinoma",
    "MESO": "Mesothelioma",
    "OV": "Ovarian serous cystadenocarcinoma",
    "PAAD": "Pancreatic adenocarcinoma",
    "PCPG": "Pheochromocytoma and Paraganglioma",
    "PRAD": "Prostate adenocarcinoma",
    "SARC": "Sarcoma",
    "SKCM": "Skin Cutaneous Melanoma",
    "STAD": "Stomach adenocarcinoma",
    "STES": "Stomach and Esophageal carcinoma",
    "TGCT": "Testicular Germ Cell Tumors",
    "THCA": "Thyroid carcinoma",
    "THYM": "Thymoma",
    "UCEC": "Uterine Corpus Endometrial Carcinoma",
    "UCS": "Uterine Carcinosarcoma",
    "UVM": "Uveal Melanoma",
}

TCGA_OMICS_ALIASES = {
    "methylation": "Methylation",
    "rnaseq": "RNAseq",
    "rna_seq": "RNAseq",
    "rna-seq": "RNAseq",
    "rppa": "RPPA",
    "scna": "SCNA",
    "mirnaseq": "miRNASeq",
    "mirna_seq": "miRNASeq",
    "mirna-seq": "miRNASeq",
}

TCGA_OMICS_DESCRIPTIONS = {
    "Methylation": "DNA methylation",
    "RNAseq": "mRNA expression from RNA-seq",
    "RPPA": "protein abundance measured by RPPA",
    "SCNA": "somatic copy number alteration",
    "miRNASeq": "microRNA expression from miRNA-seq",
}

TCGA_CIS_OMICS_DESCRIPTIONS = {
    "Methylation": "DNA methylation",
    "RNAseq": "mRNA expression from RNA-seq",
    "RPPA": "protein abundance measured by RPPA",
    "SCNA": "somatic copy number alteration",
}

TCGA_ST_METHOD_ALIASES = {
    "spearman": "spearman",
    "pearson": "pearson",
}

TCGA_ST_METHOD_DESCRIPTIONS = {
    "spearman": "Spearman rank correlation",
    "pearson": "Pearson correlation",
}

TCGACohort = Literal[
    "ACC", "BLCA", "BRCA", "CESC", "CHOL", "COADREAD", "DLBC", "ESCA", "GBM",
    "GBMLGG", "HNSC", "KICH", "KIPAN", "KIRC", "KIRP", "LAML", "LGG", "LIHC",
    "LUAD", "LUSC", "MESO", "OV", "PAAD", "PCPG", "PRAD", "SARC", "SKCM",
    "STAD", "STES", "TGCT", "THCA", "THYM", "UCEC", "UCS", "UVM",
]

TCGAOmics = Literal["Methylation", "RNAseq", "RPPA", "SCNA", "miRNASeq"]
TCGACisOmics = Literal["Methylation", "RNAseq", "RPPA", "SCNA"]

TCGAStMethod = Literal["spearman", "pearson"]

TCGA_VALID_MODES = [
    "cohort + gene + omics",
    "cohort + gene",
    "gene + omics",
    "cohort + omics",
]


def normalize_tcga_cohort(cohort: str) -> str:
    normalized = cohort.strip().upper()
    if normalized not in TCGA_COHORT_DESCRIPTIONS:
        raise ValueError(f"Unsupported cohort: {cohort}")
    return normalized


def normalize_tcga_omics(omics: str) -> str:
    canonical = TCGA_OMICS_ALIASES.get(omics.strip().lower())
    if canonical is None:
        raise ValueError(f"Unsupported omics: {omics}")
    return canonical


def normalize_tcga_cis_omics(omics: str) -> str:
    canonical = normalize_tcga_omics(omics)
    if canonical not in TCGA_CIS_OMICS_DESCRIPTIONS:
        raise ValueError(f"Unsupported cis-association omics: {omics}")
    return canonical


def normalize_tcga_st_method(method: str) -> str:
    """Normalize statistical method name."""
    canonical = TCGA_ST_METHOD_ALIASES.get(method.strip().lower())
    if canonical is None:
        raise ValueError(f"Unsupported st_method: {method}. Use 'spearman' or 'pearson'.")
    return canonical


def detect_tcga_survival_mode(
    cohort: str | None, gene: str | None, omics: str | None
) -> int | None:
    if cohort and gene and omics:
        return 1
    if cohort and gene:
        return 2
    if gene and omics:
        return 3
    if cohort and omics:
        return 4
    return None


def tcga_parameter_error(message: str) -> dict:
    return {
        "error": message,
        "supported_cohorts": TCGA_COHORT_DESCRIPTIONS,
        "supported_omics": TCGA_OMICS_DESCRIPTIONS,
        "valid_modes": TCGA_VALID_MODES,
    }

def detect_tcga_cis_association_mode(
    cohort: str | None,
    gene: str | None,
    source_omics: str | None,
    target_omics: str | None,
) -> int | None:
    if cohort and gene and source_omics and target_omics:
        return 1
    if cohort and gene:
        return 2
    if gene and source_omics and target_omics:
        return 3
    if cohort and source_omics and target_omics:
        return 4
    return None


TCGA_CIS_VALID_MODES = [
    "cohort + gene + source_omics + target_omics",
    "cohort + gene (+ optional source_omics and/or target_omics filters)",
    "gene + source_omics + target_omics",
    "cohort + source_omics + target_omics",
]


def tcga_cis_parameter_error(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": message,
        "supported_cohorts": TCGA_COHORT_DESCRIPTIONS,
        "supported_omics": TCGA_CIS_OMICS_DESCRIPTIONS,
        "supported_st_methods": TCGA_ST_METHOD_DESCRIPTIONS,
        "valid_modes": TCGA_CIS_VALID_MODES,
    }
