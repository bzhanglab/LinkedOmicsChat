"""LinkedOmics MCP Server.

This MCP provides access to multi-omics cancer data from the LinkedOmics project, primarily focusing on
the CPTAC (Clinical Proteomic Tumor Analysis Consortium) cohorts. It allows for the investigation of
gene expression, protein levels, clinical associations, drug targeting, and functional networks.

Representative Questions & Use Cases:
1. "Identify genes functionally related to ESR1 and check if any of them are FDA-approved oncology targets." (Uses funmap_neighborhood and get_target)
2. "In which cancers is EGFR significantly overexpressed at the protein level, and is this driven by gene copy number (SCNV)?" (Uses cancer_gene_expression and get_cis_correlations)
3. "Is high expression of BRCA1 associated with poor survival in Breast Cancer (BRCA) or Colon Adenocarcinoma (COAD)?" (Uses overall_survival_per_cancer)
4. "Find clinical trials where ESR1 expression levels are linked to resistance to specific chemotherapy agents like paclitaxel." (Uses clinical_trial_information)
5. "Analyze the correlation between RNA and Protein levels for TP53 across all cohorts to assess translation efficiency." (Uses get_cis_correlations)

"""

import json
import re
import time
from typing import Any, Optional
import sys

import requests
from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage
from linkedomics_tcga_params import (
    detect_tcga_survival_mode,
    normalize_tcga_cohort,
    normalize_tcga_omics,
    tcga_parameter_error,
)

# Create an MCP server
mcp = FastMCP("linkedomics_mcp", json_response=True)


def get_target_json() -> dict[str, dict[str, str]]:
    """Get the target JSON data from the LinkedOmics API."""
    json_req = requests.get("https://targets.linkedomics.org/index.json", timeout=5000)

    targets_orig = json_req.json()

    targets = {}

    # make the gene the key
    for entry in targets_orig:
        targets[entry["gene"]] = {}
        for key in entry.keys():
            if key == "gene":
                continue
            targets[entry["gene"]][key] = str(entry[key])

    return targets


targets = get_target_json()


# Add an addition tool
@mcp.tool()
def funmap_neighborhood(protein: str) -> dict:
    """Retrieve the functional neighborhood of a protein in the FunMap network.

    FunMap is a functional network where proteins are connected if a connection is predicted by a
    machine learning model trained on expression correlation across different cancer types
    and previously identified protein-protein interactions (PPI). This tool is useful for
    identifying genes that may share similar functions, are co-regulated or co-expressed, or belong to the same pathway or network.

    Use this tool when the query involves:
    - Functional partners
    - Co-expression relationships
    - Co-regulation
    - Pathway expansion
    - Network-based inference

    Use cases:
    - "Which genes are functionally related to ESR1 in the FunMap network?"
    - "Find potential novel members of the Estrogen Receptor signaling pathway by looking at the ESR1 neighborhood."
    - "Identify co-regulated partners of TP53 that might cooperate in tumor suppression."

    Args:
        protein (str): The gene symbol of the protein of interest (e.g., "ESR1", "TP53").

    Returns:
        dict: A dictionary with:
            - "nodes" (list[dict]): Each node has "name" (gene symbol) and "value" (score string).
              The score is a p-value derived from the difference in average protein abundance
              between tumor and normal samples using the Wilcoxon rank-sum test, based on data
              from 5 cohorts: CCRCC, HCC, HNSCC, LSCC, and LUAD.
            - "edges" (list[dict]): Each edge has "source" and "target" gene symbols representing functional connections.
            - "neighborhood" (list[str]): Flat list of neighbor gene symbols for quick reference.
    """
    req = requests.get(
        f"https://funmap.linkedomics.org/data/dag/gene/{protein.upper()}.json",
        timeout=1000,
    )
    if req.status_code != 200:
        print(f"Got status code: {req.status_code}")
        return {"nodes": [], "edges": [], "neighborhood": []}  # Could not find protein

    data = req.json()
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    neighborhood = [node["name"] for node in nodes if node.get("name") != protein.upper()]
    return {"nodes": nodes, "edges": edges, "neighborhood": neighborhood}


@mcp.tool()
def get_target(protein: str) -> dict[str, Any]:
    """Retrieve clinical targeting data, oncology tiers, and tumor dependency for a gene.

    This tool integrates data from multiple sources to provide a snapshot of a gene's clinical potential:
    - **Drug Targets**: List of approved or experimental drugs.
    - **Tiers**: Clinical relevance levels (T1: FDA-approved oncology targets, T2: FDA-approved for other indications, T3: Clinical trials, T4: Pre-clinical/Druggable, T5: Surface proteins).
    - **Cell Line Dependency**: Indicates if the gene is essential for cancer cell survival (from Project Achilles/DepMap).
    - **Tumor Overexpression**: Summary of whether the protein is frequently overexpressed in cancer cohorts.
    - **Hyperactivated Sites**: Specific phosphorylation sites showing increased activity in tumors.

    Use this tool when asking whether a gene is a therapeutic target.

    Use cases:
    - "Is ESR1 a validated oncology target, and what drugs are approved for it?"
    - "Does TP53 show dependency in any cancer cell lines, suggesting it's essential for survival?"
    - "What are the hyperactivated phosphorylation sites for EGFR across different cancers?"
    - "Which tier does the gene BRCA1 fall into for drug development?"

    Args:
        protein (str): The gene symbol (e.g., "ESR1").

    Returns:
        dict[str, Any]: A result dictionary containing tier, family, drugs, dependency, and overexpression summaries.
    """
    global targets

    if protein.upper() not in targets:
        return {"result": "No target information found"}

    base = targets[protein.upper()]

    protein_html_req = requests.get(
        f"https://targets.linkedomics.org/{protein.upper()}/",
        timeout=1000,
    )
    if protein_html_req.status_code != 200:
        return {"result": base}

    protein_html = protein_html_req.text

    # extract the const tn = variable using regex
    tn_match = re.search(
        r"const tn = (\[.*\])\.concat\((.*)\)\.concat\((.*)\)\.concat\((.*)\);",
        protein_html,
    )

    # TN Groups
    # Group 1: cell line dependency
    # Group 2: tumor overexpression summary
    # Group 3: Protein Overexpressed
    # Group 4: Site hyper activation

    dependent_cell_lines = []

    tn_overexpressed = []

    hyperactivated_sites = {}

    if tn_match:
        cl = json.loads(tn_match.group(1))

        for row in cl:
            cohort = row["cohort"]
            if row["value"] == 1:
                dependent_cell_lines.append(cohort)

        tn = json.loads(tn_match.group(3))

        for row in tn:
            cohort = row["cohort"]
            if row["value"] == 1:
                tn_overexpressed.append(cohort)

        site_info = json.loads(tn_match.group(4))

        for site in site_info:
            if site["value"] == 1:
                if site["site"] not in hyperactivated_sites:
                    hyperactivated_sites[site["site"]] = [site["cohort"]]
                else:
                    hyperactivated_sites[site["site"]].append(site["cohort"])

    if len(dependent_cell_lines) == 0:
        base["cell_line_dependency"] = "No evidence of cell line dependency"
    else:
        base["cell_line_dependency"] = (
            f"Dependent cell lines: {', '.join(dependent_cell_lines)}"
        )

    if len(tn_overexpressed) == 0:
        base["tumor_overexpression"] = "No evidence of tumor overexpression"
    else:
        base["tumor_overexpression"] = f"Overexpressed in {', '.join(tn_overexpressed)}"
    if len(hyperactivated_sites) == 0:
        base["hyperactivated_sites"] = "No evidence of hyperactivated sites"
    else:
        base["hyperactivated_sites"] = []
        for site, cohorts in hyperactivated_sites.items():
            base["hyperactivated_sites"].append(
                {site: f"Hyperactivated in {', '.join(cohorts)}"}
            )

    return {"result": base}


@mcp.tool()
def batch_get_target(proteins: list[str]) -> dict[str, Any]:
    """Retrieve clinical targeting data, oncology tiers, and tumor dependency for multiple genes.

    This tool integrates data from multiple sources to provide a snapshot of a gene's clinical potential:
    - **Drug Targets**: List of approved or experimental drugs.
    - **Tiers**: Clinical relevance levels (T1: FDA-approved oncology targets, T2: FDA-approved for other indications, T3: Clinical trials, T4: Pre-clinical/Druggable, T5: Surface proteins).
    - **Cell Line Dependency**: Indicates if the gene is essential for cancer cell survival (from Project Achilles/DepMap).
    - **Tumor Overexpression**: Summary of whether the protein is frequently overexpressed in cancer cohorts.
    - **Hyperactivated Sites**: Specific phosphorylation sites showing increased activity in tumors.

    Use this tool when asking whether a list of genes contains a therapeutic target.

    Use cases:
    - "From the list of genes provided, which ones are FDA-approved oncology targets?"
    - "What genes are have strong indications for cell line dependency? What does this mean"
    - "Do any of these genes have hyperactivated phosphorylation sites?"
    - "In this list of genes, are all of them overexpressed in cancer?"

    Args:
        proteins (list[str]): List of gene symbols (e.g., ["ESR1", "TP53"]).

    Returns:
        dict[str, Any]: A result dictionary containing tier, family, drugs, dependency, and overexpression summaries for each gene.
            status of error should not used to formulate the response.
    """
    results = {}
    for protein in proteins:
        try:
            targets = get_target(protein)
        except Exception as e:
            targets = {"status": "error", "message": str(e)}
        results[protein] = targets
    return {"status": "available", "data": results}


def transform_tn(
    data: dict[str, Any], sig_threshold: float = 0.05
) -> tuple[bool, dict[str, Any]]:
    CANCER_TYPES = [
        "CCRCC",
        "HNSCC",
        "LSCC",
        "LUAD",
        "PDAC",
        "BRCA",
        "COAD",
        "GBM",
        "OV",
        "UCEC",
    ]
    is_available = False
    ret_val = {}

    for cancer in CANCER_TYPES:
        if cancer in data:
            pval = float(data[cancer]["pval"])
            if abs(pval) < sig_threshold:
                if pval < 0:
                    ret_val[cancer] = (
                        f"Significantly lower expressed in tumor (p={pval:.3e})"
                    )
                else:
                    ret_val[cancer] = (
                        f"Significantly higher expressed in tumor (p={pval:.3e})"
                    )
            else:
                ret_val[cancer] = (
                    f"No significant difference between tumor and normal (p={pval:.3e})"
                )
        else:
            ret_val[cancer] = "Data unavailable"
    is_available = True  # Data ready
    return (is_available, ret_val)


def transform_os(
    data: dict[str, Any], sig_threshold: float = 0.05
) -> tuple[bool, dict[str, Any]]:
    CANCER_TYPES = [
        "CCRCC",
        "HNSCC",
        "LSCC",
        "LUAD",
        "PDAC",
        "BRCA",
        "COAD",
        "GBM",
        "OV",
        "UCEC",
    ]
    is_available = False
    ret_val = {}

    for cancer in CANCER_TYPES:
        if cancer in data:
            pval = float(data[cancer]["pval"])
            if abs(pval) < sig_threshold:
                if pval < 0:
                    ret_val[cancer] = (
                        f"Lower expression associated with poor survival (p={pval:.3e})"
                    )
                else:
                    ret_val[cancer] = (
                        f"Higher expression associated with poor survival (p={pval:.3e})"
                    )
            else:
                ret_val[cancer] = (
                    f"No significant difference between tumor and normal (p={pval:.3e})"
                )
        else:
            ret_val[cancer] = "Data unavailable"
    is_available = True  # Data ready
    return (is_available, ret_val)


@mcp.tool()
def cancer_gene_expression(protein: str) -> dict[str, Any]:
    """Evaluate tumor–normal differential expression of a gene at RNA and protein levels across 10 CPTAC cancer cohorts.

    This tool performs Tumor-Normal (TN) comparison using CPTAC data. It reports direction and statistical significance of expression changes.
    Significant results indicate potential oncogenic overexpression or tumor-suppressive downregulation.

    Use this tool when the query involves:
    - Differential expression between tumor and normal tissue in a certain cancer type
    - Overexpression or downregulation in cancer
    - RNA vs protein concordance
    - Cross-cancer expression comparison

    Use cases:
    - "Is ESR1 significantly overexpressed in BRCA at the protein level compared to normal tissue?"
    - "Identify cancer types where TP53 RNA expression is significantly lower in tumors."
    - "Compare the protein vs. RNA expression patterns of EGFR across all available cancer types."

    Args:
        protein (str): The gene symbol (e.g., "ESR1").

    Returns:
        dict[str, Any]: RNA and Protein expression status (Higher/Lower/No difference) for each cohort.

    Notes:
    - Available cohorts: BRCA (Breast), COAD (Colon), CCRCC (Kidney), GBM (Brain), HNSCC (Head/Neck), LSCC (Lung Squamous), LUAD (Lung Adeno), OV (Ovarian), PDAC (Pancreatic), UCEC (Uterine).
    - Available omic types: RNA, protein.
    """
    req = requests.get(
        f"https://kb.linkedomics.org/data/tn/gene?gene={protein.upper()}&sort=metap&order=asc&offset=0&limit=10",
        timeout=1000,
    )
    rna_data = {"status": "unavailable", "data": {}}
    protein_data = {"status": "unavailable", "data": {}}
    if req.status_code == 200:
        data = req.json()
        for element in data:
            if element.get("datatype", "") == "RNA":
                (is_available, processed_data) = transform_tn(element)
                rna_data["data"] = processed_data
                rna_data["status"] = "available" if is_available else rna_data["status"]
            elif element.get("datatype", "") == "protein":
                (is_available, processed_data) = transform_tn(element)
                protein_data["data"] = processed_data
                protein_data["status"] = (
                    "available" if is_available else protein_data["status"]
                )
    return {"protein_level": protein_data, "RNA_level": rna_data}


@mcp.tool()
def batch_cancer_gene_expression(proteins: list[str]) -> dict[str, Any]:
    """Evaluate tumor–normal differential expression of multiple genes at RNA and protein levels across 10 CPTAC cancer cohorts.

    This tool performs Tumor-Normal (TN) comparison using CPTAC data. It reports direction and statistical significance of expression changes.
    Significant results indicate potential oncogenic overexpression or tumor-suppressive downregulation.

    Use this tool when the query involves:
    - Differential expression between tumor and normal tissue for a list of genes
    - Overexpression or downregulation patterns across a gene set
    - RNA vs protein concordance comparison for multiple genes
    - Cross-cancer expression comparison for a panel of genes

    Use cases:
    - "Are any of these genes significantly overexpressed in BRCA at the protein level?"
    - "Identify cancer types where this neighborhood of proteins' RNA expression is lower in tumors."
    - "Compare the protein vs. RNA expression patterns of these proteins across all cancer types."

    Args:
        proteins (list[str]): The gene symbols (e.g., ["ESR1", "TP53"]).

    Returns:
        dict[str, Any]: RNA and Protein expression status (Higher/Lower/No difference) per cohort for each gene.

    Notes:
    - Available cohorts: BRCA (Breast), COAD (Colon), CCRCC (Kidney), GBM (Brain), HNSCC (Head/Neck), LSCC (Lung Squamous), LUAD (Lung Adeno), OV (Ovarian), PDAC (Pancreatic), UCEC (Uterine).
    - Available omic types: RNA, protein.
    """
    results = {}
    for protein in proteins:
        try:
            targets = cancer_gene_expression(protein)
        except Exception as e:
            targets = {"status": "error", "message": str(e)}
        results[protein] = targets
    return {"status": "available", "data": results}


@mcp.tool()
def overall_survival_per_cancer(protein: str) -> dict[str, Any]:
    """Evaluate the association between gene expression and overall survival across 10 CPTAC cancer cohorts.

    Expression levels are stratified (e.g., high vs. low), determines if high or low expression (RNA/Protein) is a significant predictor of overall survival.
    "Higher expression associated with poor survival" suggests the gene may serve as a negative prognostic biomarker.

    Use this tool when the query involves:
    - Prognostic value of a gene
    - Survival association
    - Overall survival correlation
    - Risk stratification by expression

    Use cases:
    - "Does high expression of ESR1 correlate with better or worse survival outcomes in Breast Cancer (BRCA)?"
    - "Which cancers show that TP53 protein levels are a significant prognostic factor for survival?"
    - "Is low expression of a specific gene associated with poor survival in Lung Adenocarcinoma (LUAD)?"

    Args:
        protein (str): The gene symbol (e.g., "ESR1").

    Returns:
        dict[str, Any]: Survival association results for RNA and Protein levels across 10 cohorts.

    Notes:
    - Available omic types: RNA, protein.
    - Available cohorts: BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC.
    """
    req = requests.get(
        f"https://kb.linkedomics.org/data/associations/phenotype/gene?phenotype=clinical__overall_survival&gene={protein.upper()}",
        timeout=1000,
    )
    rna_data = {"status": "unavailable", "data": {}}
    protein_data = {"status": "unavailable", "data": {}}
    if req.status_code == 200:
        data = req.json()

        for element in data:
            if element.get("datatype", "") == "RNA":
                (is_available, processed_data) = transform_os(element)
                rna_data["data"] = processed_data
                rna_data["status"] = "available" if is_available else rna_data["status"]
            elif element.get("datatype", "") == "protein":
                (is_available, processed_data) = transform_os(element)
                protein_data["data"] = processed_data
                protein_data["status"] = (
                    "available" if is_available else protein_data["status"]
                )
    return {"protein_level": protein_data, "RNA_level": rna_data}


@mcp.tool()
def batch_overall_survival_per_cancer(proteins: list[str]) -> dict[str, Any]:
    """Evaluate the association between gene expression and overall survival across 10 CPTAC cancer cohorts for a list of genes.

    Expression levels are stratified (e.g., high vs. low), determines if high or low expression (RNA/Protein) is a significant predictor of overall survival.
    "Higher expression associated with poor survival" suggests the gene may serve as a negative prognostic biomarker.

    Use this tool when the query involves:
    - Prognostic value of multiple genes
    - Comparing survival associations across a gene set
    - Risk stratification by expression for a panel of genes

    Use cases:
    - "Does high expression of ESR1 correlate with worse survival in BRCA? How does it compare to TP53 and IDO1?"
    - "Which cancers show that TP53 protein levels are a significant prognostic factor but not IDO1?"
    - "Is low expression of these genes associated with poor survival in Lung Adenocarcinoma (LUAD)?"

    Args:
        proteins (list[str]): The gene symbols (e.g., ["ESR1", "TP53"]).

    Returns:
        dict[str, Any]: Survival association results for RNA and Protein levels across 10 cohorts per gene.

    Notes:
    - Available omic types: RNA, protein.
    - Available cohorts: BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC.
    """
    results = {}
    for protein in proteins:
        try:
            targets = overall_survival_per_cancer(protein)
        except Exception as e:
            targets = {"status": "error", "message": str(e)}
        results[protein] = targets
    return {"status": "available", "data": results}


def get_top_n_trials(
    data: list[dict[str, Any]], n: int = 10, sig_threshold: float = 0.05
) -> dict[str, Any]:
    """Get the top n trials with the most significant association in both directions."""
    data = [study for study in data if abs(float(study["fdr"])) < sig_threshold]

    ret_val = {}
    pos = [study for study in data if float(study["fdr"]) > 0]
    neg = [study for study in data if float(study["fdr"]) < 0]
    pos.sort(key=lambda study: -study["sorted_fdr"])
    neg.sort(key=lambda study: study["sorted_fdr"])
    pos = pos[:n]
    neg = neg[:n]
    ret_val["Top Resistant Associated Studies"] = []
    for study in pos:
        ret_val["Top Resistant Associated Studies"].append(
            {"study": study["series"], "treatment": study["treatment"]}
        )
    ret_val["Top Sensitive Associated Studies"] = []
    for study in neg:
        ret_val["Top Sensitive Associated Studies"].append(
            {"study": study["series"], "treatment": study["treatment"]}
        )
    return ret_val


@mcp.tool()
def clinical_trial_information(protein: str) -> dict[str, Any]:
    """Identify drugs and trials where gene expression predicts treatment response.

    Uses public clinical trial data (GSE series) to find associations between a gene's expression
    and drug sensitivity or resistance.
    - **Sensitive**: Higher gene expression correlates with better response (or lower IC50).
    - **Resistant**: Higher gene expression correlates with worse response (or higher IC50).

    Use this tool when:
    - The query involves drug sensitivity or resistance
    - Treatment response biomarkers
    - Expression-associated drug response
    - Gene–drug association


    Use cases:
    - "Which drugs are patients likely to be resistant to if they have high ESR1 expression?"
    - "Find clinical trials where TP53 expression is a marker for drug sensitivity."
    - "What treatments are associated with resistance when BRCA1 is overexpressed?"

    Args:
        protein (str): The gene symbol (e.g., "ESR1").

    Returns:
        dict[str, Any]: Lists of the top 10 sensitive and resistant associated studies/treatments.
    """
    ret_val = {"status": "unavailable", "data": {}}
    req = requests.get(
        f"https://trials.linkedomics.org/api/table/gene/{protein.upper()}", timeout=1000
    )
    if req.status_code == 200:
        ret_val["status"] = "available"
        ret_val["data"] = get_top_n_trials(req.json())
    return ret_val


@mcp.tool()
def batch_clinical_trial_information(proteins: list[str]) -> dict[str, Any]:
    """Identify drugs and trials where gene expression predicts treatment response for a list of proteins.

    Uses public clinical trial data (GSE series) to find associations between a gene's expression
    and drug sensitivity or resistance.
    - **Sensitive**: Higher gene expression correlates with better response (or lower IC50).
    - **Resistant**: Higher gene expression correlates with worse response (or higher IC50).

    Use this tool when:
    - The query involves drug sensitivity or resistance for multiple proteins
    - Treatment response biomarkers
    - Expression-associated drug response
    - Gene–drug association


    Use cases:
    - "Which drugs are patients likely to be resistant to if they have high ESR1 or TP53 expression?"
    - "Find clinical trials where expression of these genes is a marker for drug sensitivity."
    - "What treatments are associated with resistance when any of these genes are overexpressed?"

    Args:
        proteins (list[str]): The gene symbols (e.g., ["ESR1", "TP53"]).

    Returns:
        dict[str, Any]: Lists of the top 10 sensitive and resistant associated studies/treatments for each protein.
    """
    results = {}
    for protein in proteins:
        try:
            targets = clinical_trial_information(protein)
        except Exception as e:
            targets = {"status": "error", "message": str(e)}
        results[protein] = targets
    return {"status": "available", "data": results}


@mcp.tool()
def get_cis_correlations(protein: str) -> dict[str, Any]:
    """Analyze cis-regulatory relationships between molecular layers (RNA, Protein, Methylation, SCNV) for a gene.

    Cis-correlations help determine what drives a gene's expression levels across CPTAC cohorts.

    Use this tool when the query involves:
    - Identifying what drives a gene's expression (copy number, methylation, translation)
    - RNA vs. protein translation efficiency
    - Epigenetic regulation of a gene
    - Copy number dosage effects on expression

    Use cases:
    - "Is the high protein level of ESR1 in BRCA driven by its RNA levels or by gene amplification (SCNV)?"
    - "How much does DNA methylation influence TP53 expression in Lung Adenocarcinoma (LUAD)?"
    - "Check if there's a strong dosage effect (SCNV vs RNA) for EGFR in Glioblastoma (GBM)."

    Args:
        protein (str): The gene symbol (e.g., "ESR1").

    Returns:
        dict[str, Any]: Correlation coefficients (val) and p-values for all molecular pairs across cohorts.

    Notes:
    - RNA vs. Protein: translation efficiency (mRNA → protein conversion rate).
    - RNA vs. Methylation: epigenetic silencing or activation of transcription.
    - RNA vs. SCNV: gene copy number dosage effect on mRNA levels.
    """
    base_url = f"https://kb.linkedomics.org/gene/{protein.upper()}"
    req = requests.get(base_url, timeout=5000)
    html_text = req.text

    # extract the cor_data js variable using regex.
    cor_data_res = re.search(r"let cor_data = (\{.*?\})(?=\s+for)", html_text)
    if cor_data_res is None:
        return {"status": "error", "message": "Failed to extract cor_data"}
    cor_data = cor_data_res.group(1)
    cor_data = json.loads(cor_data)

    # convert all float and integer values to strings
    for cohort in cor_data:
        cohort_data = cor_data[cohort]
        for index, entry in enumerate(cohort_data):
            for key, value in entry.items():
                cor_data[cohort][index][key] = str(value)

    return {"status": "available", "data": cor_data}


@mcp.tool()
def batch_get_cis_correlations(proteins: list[str]) -> dict[str, Any]:
    """Analyze cis-regulatory relationships between molecular layers (RNA, Protein, Methylation, SCNV) for a list of genes.

    Cis-correlations help determine what drives each gene's expression levels across CPTAC cohorts.

    Use this tool when the query involves:
    - Identifying expression drivers for a panel of genes
    - Comparing translation efficiency or epigenetic regulation across a gene set
    - Copy number dosage effects on expression for multiple genes

    Use cases:
    - "Is the high protein level of ESR1 or TP53 in BRCA driven by RNA levels or gene amplification (SCNV)?"
    - "How much does DNA methylation influence the expression of these genes in Lung Adenocarcinoma (LUAD)?"
    - "Check if there's a strong dosage effect (SCNV vs RNA) for these proteins in Glioblastoma (GBM)."

    Args:
        proteins (list[str]): The gene symbols (e.g., ["ESR1", "TP53"]).

    Returns:
        dict[str, Any]: Correlation coefficients (val) and p-values for all molecular pairs across cohorts per gene.

    Notes:
    - RNA vs. Protein: translation efficiency (mRNA → protein conversion rate).
    - RNA vs. Methylation: epigenetic silencing or activation of transcription.
    - RNA vs. SCNV: gene copy number dosage effect on mRNA levels.
    """
    results = {}
    for protein in proteins:
        try:
            targets = get_cis_correlations(protein)
        except Exception as e:
            targets = {"status": "error", "message": str(e)}
        results[protein] = targets
    return {"status": "available", "data": results}


@mcp.tool()
def webgestalt(proteins: list[str], top_n: int = 5) -> dict[str, Any]:
    """Perform Gene Ontology (GO) overrepresentation analysis on a list of proteins using WebGestalt. Identifies biological processes significantly enriched in the input gene set compared to a genomic background.

    This tool answers questions like:
    - "What biological processes are shared among these cancer genes?"
    - "What pathways are enriched in the FunMap neighborhood of ESR1?"
    - "After identifying co-expressed partners of MYC, what functions do they share?"

    Best used AFTER:
    - funmap_neighborhood() — to interpret what a gene's functional network does
    - A custom gene list from hypothesis-driven selection

    Args:
        proteins (list[str]):
            List of HGNC gene symbols to analyze (e.g., ["TP53", "BRCA1", "EGFR"]).
            Recommended: 10–50 genes. Too few genes will yield no enrichment;
            too many (>200) may dilute signal.

        top_n (int, optional):
            Number of top-ranked enriched GO terms to return, sorted by p-value.
            Default: 5. Recommended: 10–20 for exploratory analysis.

    Returns:
        dict with keys:
            "status" (str): "success" or error indicator.
            "data" (list[dict]): List of enriched gene sets, each containing:
                - "geneSet" (str): GO term ID (e.g., "GO:0044843")
                - "description" (str): Human-readable GO term name
                  (e.g., "cell cycle G1/S phase transition")
                - "link" (str): AmiGO URL for the GO term — use to get full term details
                - "size" (int): Total number of genes annotated to this GO term
                  in the reference genome
                - "overlap" (int): Number of your input genes found in this GO term
                - "expect" (float): Expected overlap by chance given input list size
                - "enrichmentRatio" (float): overlap / expect — values >>1 indicate
                  strong enrichment (e.g., 32.0 = 32x over background)
                - "pValue" (float): Hypergeometric p-value (uncorrected)
                - "FDR" (float): Benjamini-Hochberg corrected p-value — use this
                  for significance calls; FDR < 0.05 is the standard threshold
                - "overlapId" (str): Semicolon-delimited Entrez Gene IDs of the
                  overlapping genes (useful for identifying which input genes
                  drive the enrichment)

    Notes:
    - Sort results by FDR (already sorted in output) — not raw pValue.
    - enrichmentRatio > 5 with FDR < 0.01 = strong, reliable enrichment.
    - overlapId can be mapped back to gene symbols using NCBI Entrez.
    - Results reflect GO Biological Process terms only (not Molecular Function or Cellular Component).
    - Input genes not recognized as valid HGNC symbols are silently dropped.
    - Best used after funmap_neighborhood() to interpret a gene's functional network, or with any custom gene list.
    """
    gene_list = "\n".join(proteins)

    url = "https://www.webgestalt.org/process.php"

    payload = {
        "enrich_method": "ORA",
        "organism": "hsapiens",
        "enriched_database_category[]": "geneontology",
        "enriched_database_name[]": "Biological_Process_noRedundant",
        "gene_list": gene_list,
        "ref_set": "genome_protein-coding",
        "id_type": "genesymbol",
        "ref_file": "",  # empty like in JS
        "hasWSC": "on",
        "min_num": "3",
        "max_num": "2000",
        "fdr_method": "BH",
        "sig_method": "top",
        "sig_value": "10",
        "set_cover_num": "10",
        "kMedoid_k": "10",
        "report_num": "40",
        "color_scheme": "continuous",
    }

    response = requests.post(url, data=payload)

    process_text = response.text

    process_id_res = re.search(r"var ts = (\d+);", process_text)
    if process_id_res is None:
        return {"status": "error", "message": "Could not find process ID"}
    process_id = process_id_res.group(1)

    print("Found process ID:", process_id)

    # wait for results to have good response
    response_code = 404

    # thirty_second_timeout
    timeout = 30

    current_cycle = 0

    while response_code != 200 and current_cycle < timeout:
        response = requests.get(f"https://www.webgestalt.org/results/{process_id}/")
        response_code = response.status_code
        time.sleep(1)
        current_cycle += 1

    if response_code != 200:
        return {"status": "error", "message": "Timed out waiting for results"}

    enrich_text = response.text
    enrich_results_text = re.search(r"var enrichment = (\[.+\]);", enrich_text)
    if enrich_results_text is None:
        return {"status": "error", "message": "Could not find enrichment results"}
    enrich_results: list[dict[str, str | float]] = json.loads(
        enrich_results_text.group(1)
    )
    enrich_results.sort(key=lambda x: x["FDR"])

    ret_val = {"status": "success", "data": enrich_results[:top_n]}

    return ret_val


@mcp.tool()
def tcga_survival_analysis(
    cohort: Optional[str] = None,
    gene: Optional[str] = None,
    omics: Optional[str] = None
) -> dict:
    """Perform survival analysis using TCGA multi-omics data via the LinkedOmics API.

    Evaluates whether gene expression (or other molecular measurements) is associated
    with overall survival across TCGA cancer cohorts. Supports flexible query modes
    from single-gene analysis to genome-wide scans.

    Use this tool when:
    - The user asks about survival associations in TCGA cohorts
    - Queries involve gene expression and patient survival across TCGA cancer types
    - The user wants to scan which genes predict survival within a cohort

    Use cases:
    - "Is TP53 RNA expression associated with survival in LAML?"
    - "Which genes are prognostic in BRCA at the RNA level?"
    - "Does EGFR protein level predict survival across all TCGA cancers?"
    - "Compare survival impact of ESR1 methylation vs RNA in BRCA"

    Args:
        cohort (str, optional): TCGA cancer cohort abbreviation (e.g., "BRCA", "LUAD").
        gene (str, optional): HGNC gene symbol (e.g., "TP53", "ESR1"). Use "hsa-mir-XX" for microRNA.
        omics (str, optional): Omics type — one of: Methylation, RNAseq, RPPA, SCNA, miRNASeq.

    Returns:
        dict:
            A dictionary containing survival results from the TCGA backend.

            The response always has the form:

                {
                    "dataset": "TCGA",
                    "mode": mode,
                    "query": params,
                    "n_results": len(results),
                    "results": [...]
                }

            `results` is always a list of gene-level result objects.

            Common fields that may appear in each result item:
            - cohort
            - omics
            - gene
            - hr
            - pvalue
            - fdr
            - n
            - samples

            Returned fields depend on query mode because keys already provided
            in the request are removed from each result item.

            Mode 1 (`cohort + gene + omics`)
            - Returns one detailed single-gene result.
            - Result items typically contain:
            hr, pvalue, n, samples

            Mode 2 (`cohort + gene`)
            - Returns one detailed single-gene result per available omics type.
            - Result items typically contain:
            omics, hr, pvalue, n, samples

            Mode 3 (`gene + omics`)
            - Returns one result per cohort.
            - Result items typically contain:
            cohort, hr, pvalue, n
            - `fdr` is removed for this mode.

            Mode 4 (`cohort + omics`)
            - Returns one result per gene for the requested cohort and omics.
            - Result items typically contain:
            gene, hr, pvalue, fdr, n

            On request failure, the function returns:

                {
                    "status": "error",
                    "dataset": "TCGA",
                    "mode": mode,
                    "query": params,
                    "message": "...",
                    "results": []
                }


    Notes:
    - Four query modes: (1) cohort+gene+omics, (2) cohort+gene all omics, (3) gene+omics all cohorts, (4) cohort+omics genome-wide scan.
    - Supported cohorts: ACC, BLCA, BRCA, CESC, CHOL, COADREAD, DLBC, ESCA, GBM, GBMLGG, HNSC, KICH, KIPAN, KIRC, KIRP, LAML, LGG, LIHC, LUAD, LUSC, MESO, OV, PAAD, PCPG, PRAD, SARC, SKCM, STAD, STES, TGCT, THCA, THYM, UCEC, UCS, UVM.
    - Supported omics: Methylation, RNAseq, RPPA, SCNA, miRNASeq.
    - Significant associations rely on p-values or FDR thresholds (interpretation depends on downstream processing).
    - Positive vs. negative associations reflect directionality of risk (e.g., high expression → worse survival).
    - Mode 4 (genome-wide scan) may return large datasets; downstream filtering is recommended.
    - Missing or empty results indicate lack of data or an unsupported query combination.
    """


    base_url = "http://aws1.zhang-lab.org:8236/api/survival"
    cohort = cohort.strip() or None if cohort is not None else None
    gene = gene.strip() or None if gene is not None else None
    omics = omics.strip() or None if omics is not None else None
    mode = detect_tcga_survival_mode(cohort, gene, omics)

    if mode is None:
        return tcga_parameter_error("Invalid parameter combination")

    try:
        params = {}

        if cohort:
            params["cohort"] = normalize_tcga_cohort(cohort)

        if gene:
            params["gene"] = gene.upper()

        if omics:
            params["omics"] = normalize_tcga_omics(omics)
    except ValueError as e:
        return tcga_parameter_error(str(e))


    try:
        r = requests.get(
            base_url,
            params=params,
            timeout=(80, 1200)
        )

        try:
            resp = r.json()
        except ValueError:
            resp = {"raw_text": r.text}

        r.raise_for_status()

        results = resp.get("results", [])
        if not isinstance(results, list):
            return {
                "status": "error",
                "error": "Unexpected API response format",
                "dataset": "TCGA",
                "mode": mode,
                "query": params,
                "raw": resp,
                "results": [],
            }

        return {
            "dataset": "TCGA",
            "mode": mode,
            "query": params,
            "n_results": len(results),
            "results": results,
        }

    except requests.exceptions.HTTPError as e:
        detail = None
        try:
            detail = r.json().get("detail")
        except Exception:
            detail = str(e)

        return {
            "status": "error",
            "dataset": "TCGA",
            "mode": mode,
            "query": params,
            "message": detail,
            "results": [],
        }

    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "dataset": "TCGA",
            "mode": mode,
            "query": params,
            "message": str(e),
            "results": [],
        }




# Run with stdio transport
if __name__ == "__main__":
    mcp.run(transport="stdio")
