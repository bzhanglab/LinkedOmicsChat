"""PubMed Literature MCP Server.

Provides real-time literature search via NCBI E-utilities (free, no API key required,
though setting NCBI_EMAIL in .env improves rate limits per NCBI ToS).

Representative Questions & Use Cases:
1. "Find recent papers on ESR1 and breast cancer survival." (Uses search_pubmed)
2. "What does the literature say about TP53 mutations in lung cancer?" (Uses search_pubmed)
3. "Get the abstract for PMID 25892560." (Uses get_pubmed_abstract)
4. "Find papers about KRAS inhibitors published after 2022." (Uses search_pubmed)
5. "Search for clinical trials involving EGFR in NSCLC." (Uses search_pubmed)
"""

import os
import xml.etree.ElementTree as ET
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("literature_mcp", json_response=True)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
TIMEOUT     = 15

_base_params: dict[str, str] = {"tool": "LinkedOmicsChat", "retmode": "json"}
_ncbi_email = os.environ.get("NCBI_EMAIL", "")
_ncbi_api_key = os.environ.get("NCBI_API_KEY", "")
if _ncbi_email:
    _base_params["email"] = _ncbi_email
if _ncbi_api_key:
    _base_params["api_key"] = _ncbi_api_key


def _esearch(query: str, max_results: int) -> list[str]:
    """Return a list of PMIDs matching *query*."""
    params = {**_base_params, "db": "pubmed", "term": query,
              "retmax": str(max_results), "usehistory": "n"}
    r = requests.get(ESEARCH_URL, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("esearchresult", {}).get("idlist", [])


def _efetch_xml(pmids: list[str]) -> ET.Element:
    """Fetch PubMed XML records for a list of PMIDs."""
    params = {**_base_params, "db": "pubmed", "id": ",".join(pmids),
              "rettype": "xml", "retmode": "xml"}
    r = requests.get(EFETCH_URL, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return ET.fromstring(r.text)


def _parse_article(article_node: ET.Element) -> dict[str, Any]:
    """Extract key fields from a <PubmedArticle> XML node."""
    ma = article_node.find(".//MedlineCitation/Article")
    if ma is None:
        return {}

    # Title
    title_el = ma.find("ArticleTitle")
    title = "".join(title_el.itertext()).strip() if title_el is not None else ""

    # Abstract (may have multiple AbstractText sections)
    abstract_parts = [
        "".join(ab.itertext()).strip()
        for ab in ma.findall(".//Abstract/AbstractText")
    ]
    abstract = " ".join(p for p in abstract_parts if p) or "No abstract available."

    # Authors
    authors = []
    for author in ma.findall(".//AuthorList/Author"):
        last = author.findtext("LastName", "")
        initials = author.findtext("Initials", "")
        if last:
            authors.append(f"{last} {initials}".strip())
    authors_str = ", ".join(authors[:6])
    if len(authors) > 6:
        authors_str += " et al."

    # Journal & year
    journal = ma.findtext(".//Journal/Title", "")
    year = (
        ma.findtext(".//Journal/JournalIssue/PubDate/Year")
        or ma.findtext(".//Journal/JournalIssue/PubDate/MedlineDate", "")[:4]
    )

    # PMID
    pmid = article_node.findtext(".//MedlineCitation/PMID", "")

    # DOI
    doi = ""
    for eid in article_node.findall(".//PubmedData/ArticleIdList/ArticleId"):
        if eid.get("IdType") == "doi":
            doi = eid.text or ""
            break

    return {
        "pmid": pmid,
        "title": title,
        "authors": authors_str,
        "journal": journal,
        "year": year,
        "doi": doi,
        "doi_url": f"https://doi.org/{doi}" if doi else "",
        "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        "abstract": abstract,
    }


@mcp.tool()
def search_pubmed(
    query: str,
    max_results: int = 10,
) -> dict[str, Any]:
    """Search PubMed for peer-reviewed biomedical literature.

    Returns titles, authors, journal, year, abstract, PMID, and DOI for each article.
    Use this tool whenever the user asks about research papers, publications,
    clinical evidence, or literature related to genes, diseases, or treatments.

    Args:
        query: PubMed search query. Use MeSH terms or gene names for best results.
               Examples: "ESR1 breast cancer survival", "TP53 lung cancer prognosis",
               "KRAS inhibitors pancreatic cancer 2022:2025[dp]"
        max_results: Number of articles to return (default 10, max 20).
    """
    max_results = min(max(1, max_results), 20)
    try:
        pmids = _esearch(query, max_results)
        if not pmids:
            return {"query": query, "total_found": 0, "articles": [],
                    "message": "No articles found for this query. Try broader terms."}

        root = _efetch_xml(pmids)
        articles = [
            _parse_article(node)
            for node in root.findall("PubmedArticle")
        ]
        articles = [a for a in articles if a]  # drop empty

        return {
            "query": query,
            "total_found": len(articles),
            "articles": articles,
        }
    except requests.RequestException as e:
        return {"error": f"PubMed request failed: {e}", "query": query, "articles": []}


@mcp.tool()
def get_pubmed_abstract(pmid: str) -> dict[str, Any]:
    """Fetch full details and abstract for a specific PubMed article by PMID.

    Use this when the user provides a PMID or when you want the full abstract
    for a specific article found via search_pubmed.

    Args:
        pmid: PubMed ID, e.g. "25892560"
    """
    pmid = pmid.strip()
    try:
        root = _efetch_xml([pmid])
        nodes = root.findall("PubmedArticle")
        if not nodes:
            return {"error": f"PMID {pmid} not found.", "pmid": pmid}
        return _parse_article(nodes[0])
    except requests.RequestException as e:
        return {"error": f"PubMed request failed: {e}", "pmid": pmid}


if __name__ == "__main__":
    mcp.run()
