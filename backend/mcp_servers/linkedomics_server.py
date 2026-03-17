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
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage

from gene_converter import resolve_to_hgnc

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


targets: dict[str, dict[str, str]] | None = None


def get_targets() -> dict[str, dict[str, str]]:
    """Lazy-load targets data on first use to avoid crashing at import time."""
    global targets
    if targets is None:
        targets = get_target_json()
    return targets


# Add an addition tool
@mcp.tool()
def funmap_neighborhood(protein: str) -> dict[str, Any]:
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
    - "Use returned neighborhood as input to webgestalt to find enriched GO terms."

    Args:
        protein (str): Gene symbol, Ensembl Gene ID (ENSG...), or UniProt accession (e.g., "ESR1", "ENSG00000091831", "P03372").

    Returns:
        dict[str, Any]: A dictionary with a "neighborhood" key containing a list of gene symbols,
                        or an "error" key if the identifier could not be resolved.
    """
    try:
        gene = resolve_to_hgnc(protein)
    except ValueError as e:
        return {"neighborhood": [], "error": str(e)}

    req = requests.get(
        f"https://funmap.linkedomics.org/data/dag/gene/{gene}.json",
        timeout=1000,
    )
    if req.status_code != 200:
        return {"neighborhood": [], "error": f"Gene '{gene}' was not found in the FunMap network."}

    return {"neighborhood": [node["name"] for node in req.json()["nodes"]]}


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
        protein (str): Gene symbol, Ensembl Gene ID (ENSG...), or UniProt accession (e.g., "ESR1", "ENSG00000091831", "P03372").

    Returns:
        dict[str, Any]: A result dictionary containing tier, family, drugs, dependency, and overexpression summaries.
    """
    try:
        gene = resolve_to_hgnc(protein)
    except ValueError as e:
        return {"result": str(e)}

    current_targets = get_targets()

    if gene not in current_targets:
        return {"result": f"No target information found for '{gene}'. It may not be in the LinkedOmics drug target database."}

    base = dict(current_targets[gene])

    protein_html_req = requests.get(
        f"https://targets.linkedomics.org/{gene}/",
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

    Cancer Cohorts:
    - BRCA (Breast), COAD (Colon), CCRCC (Kidney), GBM (Brain), HNSCC (Head/Neck),
      LSCC (Lung Squamous), LUAD (Lung Adeno), OV (Ovarian), PDAC (Pancreatic), UCEC (Uterine).

    Available omic types:
    "RNA", "protein".

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
        protein (str): Gene symbol, Ensembl Gene ID (ENSG...), or UniProt accession (e.g., "ESR1", "ENSG00000091831", "P03372").

    Returns:
        dict[str, Any]: RNA and Protein expression status (Higher/Lower/No difference) for each cohort.
    """
    try:
        gene = resolve_to_hgnc(protein)
    except ValueError as e:
        return {"protein_level": {"status": "error", "data": {}}, "RNA_level": {"status": "error", "data": {}}, "error": str(e)}

    req = requests.get(
        f"https://kb.linkedomics.org/data/tn/gene?gene={gene}&sort=metap&order=asc&offset=0&limit=10",
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
def overall_survival_per_cancer(protein: str) -> dict[str, Any]:
    """Evaluate the association between gene expression and overall survival across 10 CPTAC cancer cohorts.

    Expression levels are stratified (e.g., high vs. low), determines if high or low expression (RNA/Protein) is a significant predictor of overall survival.
    "Higher expression associated with poor survival" suggests the gene may serve as a negative prognostic biomarker.

    Available omic types:
    "RNA", "protein".

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
        protein (str): Gene symbol, Ensembl Gene ID (ENSG...), or UniProt accession (e.g., "ESR1", "ENSG00000091831", "P03372").

    Returns:
        dict[str, Any]: Survival association results for RNA and Protein levels across 10 cohorts.
    """
    try:
        gene = resolve_to_hgnc(protein)
    except ValueError as e:
        return {"protein_level": {"status": "error", "data": {}}, "RNA_level": {"status": "error", "data": {}}, "error": str(e)}

    req = requests.get(
        f"https://kb.linkedomics.org/data/associations/phenotype/gene?phenotype=clinical__overall_survival&gene={gene}",
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


# @mcp.tool()
# def get_survival_plot(protein: str, cancer: str, omic: str) -> Image | None:
#     """Generate a Kaplan-Meier survival plot image for a specific gene and cancer type.

#     The plot compares survival probability over time between patients
#     stratified by gene expression level (e.g., high vs. low groups)
#     at either the RNA or protein level. Kaplan–Meier survival curves with log-rank testing, and Cox proportional hazards regression for hazard ratio estimation.

#     Available Cancer Types: CCRCC, HNSCC, LSCC, LUAD, PDAC, BRCA, COAD, GBM, OV, UCEC.
#     Available Omic types: "RNA", "protein".

#     Available omic types:
#     "RNA", "protein".

#     Use this tool when:
#     - A visual Kaplan–Meier survival curve is requested
#     - The user asks to see a survival plot
#     - A graphical survival comparison is needed for a specific gene and cancer

#     Use cases:
#     - "Show me the survival plot for ESR1 RNA expression in BRCA."
#     - "Get a protein-level survival plot for TP53 in LUAD."

#     Args:
#         protein (str): Gene symbol (e.g., "ESR1").
#         cancer (str): Cancer type abbreviation (e.g., "BRCA").
#         omic (str): Type of data, either "RNA" or "protein".

#     Returns:
#         Image | None: A PIL Image object containing the survival plot, or None if the request fails.
#     """
#     base_url = f"https://kb.linkedomics.org/plot/gene?gene={protein.upper()}&datatype={omic}&cohort={cancer}&phenotype=clinical__overall_survival"

#     req = requests.get(base_url, timeout=5000)
#     if req.status_code != 200:
#         return None  # Could not get image
#     image = Image(data=req.content, format="png")
#     return image


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
        protein (str): Gene symbol, Ensembl Gene ID (ENSG...), or UniProt accession (e.g., "ESR1", "ENSG00000091831", "P03372").

    Returns:
        dict[str, Any]: Lists of the top 10 sensitive and resistant associated studies/treatments.
    """
    try:
        gene = resolve_to_hgnc(protein)
    except ValueError as e:
        return {"status": "error", "data": {}, "error": str(e)}

    ret_val = {"status": "unavailable", "data": {}}
    req = requests.get(
        f"https://trials.linkedomics.org/api/table/gene/{gene}", timeout=1000
    )
    if req.status_code == 200:
        ret_val["status"] = "available"
        ret_val["data"] = get_top_n_trials(req.json())
    return ret_val


@mcp.tool()
def get_cis_correlations(protein: str) -> dict[str, Any]:
    """Analyze regulatory relationships between molecular layers (RNA, Protein, Methylation, SCNV).

    Cis-correlations help determine the drivers of a gene's expression:
    - **RNA vs. Protein**: Indicates translation efficiency (how well mRNA is converted to protein).
    - **RNA vs. Methylation**: Impact of DNA methylation on silencing or activating transcription.
    - **RNA vs. SCNV**: Impact of gene copy number changes (dosage effect) on mRNA levels.

    Use cases:
    - "Is the high protein level of ESR1 in BRCA driven by its RNA levels or by gene amplification (SCNV)?"
    - "How much does DNA methylation influence TP53 expression in Lung Adenocarcinoma (LUAD)?"
    - "Check if there's a strong dosage effect (SCNV vs RNA) for EGFR in Glioblastoma (GBM)."

    Args:
        protein (str): Gene symbol, Ensembl Gene ID (ENSG...), or UniProt accession (e.g., "ESR1", "ENSG00000091831", "P03372").

    Returns:
        dict[str, Any]: Correlation coefficients (val) and p-values for all molecular pairs across cohorts.
    """
    try:
        gene = resolve_to_hgnc(protein)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    base_url = f"https://kb.linkedomics.org/gene/{gene}"
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
def webgestalt(proteins: list[str], top_n: int = 5) -> dict[str, Any]:
    """PRIMARY TOOL for Gene Ontology (GO) Enrichment Analysis.
    IDENTIFIES BIOLOGICAL FUNCTIONS & PATHWAYS enriched in a gene list.

    TRIGGERS:
    - "What do these genes do?"
    - "Perform pathway analysis"
    - "Functional enrichment"
    - "Biological meaning of the neighborhood"
    - "What functions are shared?"

    CRITICAL USAGE:
    - ALWAYS call this tool immediately after generating a gene list (e.g., from `funmap_neighborhood` or `co_expression`).
    - Used to interpret the *biological significance* of a list of genes.

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

    Interpretation Tips:
        - Sort results by FDR (already sorted in output) — not raw pValue
        - enrichmentRatio > 5 with FDR < 0.01 = strong, reliable enrichment
        - overlapId can be mapped back to gene symbols using NCBI Entrez
        - Results reflect GO Biological Process terms only (not Molecular Function
          or Cellular Component — confirm if this changes in future versions)
        - Input genes not recognized as valid HGNC symbols are silently dropped;
          verify your symbols are current if overlap counts seem unexpectedly low

    Example Usage:
        # After getting FunMap neighbors of a kinase, interpret their shared function:
        neighbors = funmap_neighborhood("EGFR")["neighborhood"]
        results = webgestalt(neighbors[:30], top_n=10)
        for term in results["data"]:
            print(term["description"], term["enrichmentRatio"], term["FDR"])
    """
    # Resolve any non-HGNC identifiers; skip entries that can't be resolved
    resolved = []
    skipped = []
    for p in proteins:
        try:
            resolved.append(resolve_to_hgnc(p))
        except ValueError:
            skipped.append(p)

    if not resolved:
        return {"status": "error", "data": [], "error": f"None of the provided identifiers could be resolved to gene symbols. Skipped: {skipped}"}

    gene_list = "\n".join(resolved)

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

    process_id = re.search(r"var ts = (\d+);", process_text).group(1)

    print("Found process ID:", process_id)

    # wait for results to have good response
    response_code = 404

    while response_code != 200:
        response = requests.get(f"https://www.webgestalt.org/results/{process_id}/")
        response_code = response.status_code
        time.sleep(1)

    enrich_text = response.text
    enrich_results_text = re.search(r"var enrichment = (\[.+\]);", enrich_text).group(1)
    enrich_results: list[dict[str, str | float]] = json.loads(enrich_results_text)
    enrich_results.sort(key=lambda x: x["FDR"])

    ret_val = {"status": "success", "data": enrich_results[:top_n]}

    return ret_val


@mcp.tool()
def resolve_gene_identifier(identifier: str) -> dict[str, Any]:
    """Resolve any gene identifier to an HGNC gene symbol using a live database lookup.

    Call this tool FIRST when the user provides an Ensembl Gene ID (ENSG...) or
    UniProt accession (e.g., P04637) before calling any analysis tool. This validates
    the identifier against current databases — do NOT rely on your training knowledge
    to convert gene identifiers.

    Use cases:
    - "What gene is ENSG00000141510?" → resolves to TP53
    - "Convert P04637 to gene symbol" → resolves to TP53
    - Validate any identifier before running expression, survival, or FunMap analysis.

    Args:
        identifier (str): Gene symbol, Ensembl Gene ID (ENSG...), or UniProt accession.

    Returns:
        dict with keys:
            "hgnc_symbol" (str): Resolved uppercase HGNC gene symbol, or empty string on failure.
            "input" (str): The original identifier as provided.
            "error" (str, optional): Present only if resolution failed — describes why.
    """
    try:
        symbol = resolve_to_hgnc(identifier)
        return {"hgnc_symbol": symbol, "input": identifier}
    except ValueError as e:
        return {"hgnc_symbol": "", "input": identifier, "error": str(e)}


# Run with stdio transport
if __name__ == "__main__":
    mcp.run(transport="stdio")
