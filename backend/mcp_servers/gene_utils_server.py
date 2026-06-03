"""Gene Utilities MCP Server.

Provides gene identifier resolution (Ensembl IDs, UniProt accessions → HGNC symbols)
as a standalone MCP tool. Call resolve_gene_identifier FIRST whenever the user provides
a non-symbol identifier before passing it to any LinkedOmics analysis tool.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from gene_converter import resolve_to_hgnc

mcp = FastMCP("gene_utils_mcp", json_response=True)


@mcp.tool()
def resolve_gene_identifier(identifier: str) -> dict[str, Any]:
    """Resolves user-provided HGNC symbols, Ensembl gene identifiers or UniProt accessions to canonical HGNC gene symbols before downstream analyses.

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
        hgnc_symbol (str): Resolved uppercase HGNC gene symbol, or an empty string on failure.
        input (str): The original identifier as provided.
        error (str, optional): Present only if resolution failed; describes why resolution did not succeed.
    """
    try:
        symbol = resolve_to_hgnc(identifier)
        return {"hgnc_symbol": symbol, "input": identifier}
    except ValueError as e:
        return {"hgnc_symbol": "", "input": identifier, "error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
