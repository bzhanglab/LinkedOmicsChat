"""Gene identifier normalization utilities.

Converts external gene identifiers (Ensembl Gene IDs, UniProt accessions)
to HGNC gene symbols required by the LinkedOmics APIs.
"""

import re
from pathlib import Path
from typing import FrozenSet

import requests

# UniProt canonical accession: [A-N,R-Z][0-9][A-Z][A-Z0-9]{2}[0-9]  (reviewed SwissProt)
#                            or [O,P,Q][0-9][A-Z0-9]{3}[0-9]          (reviewed SwissProt alt)
# Also covers TrEMBL entries with the same patterns.
_UNIPROT_RE = re.compile(
    r"^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})$",
    re.IGNORECASE,
)

# Lazy-loaded set of valid HGNC symbols (uppercased) from valid_genes.txt.
_VALID_HGNC: FrozenSet[str] | None = None


def _get_valid_hgnc() -> FrozenSet[str]:
    """Load valid_genes.txt once and cache as a frozenset for O(1) lookups."""
    global _VALID_HGNC
    if _VALID_HGNC is None:
        genes_file = Path(__file__).parent.parent.parent / "valid_genes.txt"
        if genes_file.exists():
            _VALID_HGNC = frozenset(
                line.strip().upper() for line in genes_file.read_text().splitlines() if line.strip()
            )
        else:
            # File not found — skip validation so tools still work
            _VALID_HGNC = frozenset()
    return _VALID_HGNC


def resolve_to_hgnc(identifier: str) -> str:
    """Resolve any gene identifier to an uppercase HGNC gene symbol.

    Accepts:
        - HGNC gene symbol (e.g., ``"TP53"``, ``"ESR1"``) — validated against known symbols.
        - Ensembl Gene ID (e.g., ``"ENSG00000141510"``) — converted via mygene.info.
        - UniProt accession (e.g., ``"P04637"``) — converted via mygene.info.

    Returns:
        str: Uppercase HGNC gene symbol.

    Raises:
        ValueError: If the identifier cannot be resolved to a known gene symbol.
    """
    identifier = identifier.strip()

    # Ensembl Gene ID: "ENSG" followed by digits
    if re.match(r"^ENSG\d+$", identifier, re.IGNORECASE):
        return _query_mygene(
            identifier,
            scopes="ensembl.gene",
            original=identifier,
        )

    # UniProt accession
    if _UNIPROT_RE.match(identifier):
        return _query_mygene(
            identifier,
            scopes="uniprot.Swiss-Prot,uniprot.TrEMBL",
            original=identifier,
        )

    # Treat as HGNC symbol — validate against the known gene list
    symbol = identifier.upper()
    valid = _get_valid_hgnc()
    if valid and symbol not in valid:
        raise ValueError(
            f"'{identifier}' is not a recognized gene symbol. "
            "Please provide a valid HGNC gene symbol (e.g., TP53, ESR1, EGFR), "
            "an Ensembl Gene ID (e.g., ENSG00000141510), "
            "or a UniProt accession (e.g., P04637)."
        )
    return symbol


def _query_mygene(query: str, scopes: str, original: str) -> str:
    """Query mygene.info to convert an external gene ID to an HGNC symbol.

    Args:
        query: The identifier to look up.
        scopes: Comma-separated mygene.info field scopes to search.
        original: The original user-supplied identifier (for error messages).

    Returns:
        Uppercase HGNC gene symbol.

    Raises:
        ValueError: If no matching gene is found.
    """
    try:
        resp = requests.get(
            "https://mygene.info/v3/query",
            params={
                "q": query,
                "scopes": scopes,
                "fields": "symbol",
                "species": "human",
            },
            timeout=5,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        if hits and "symbol" in hits[0]:
            return hits[0]["symbol"].upper()
    except requests.RequestException:
        pass

    raise ValueError(
        f"Could not resolve '{original}' to a gene symbol. "
        "Please provide an HGNC gene symbol (e.g., TP53, ESR1, EGFR)."
    )
