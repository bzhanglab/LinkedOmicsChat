"""Parse and check a user-supplied gene list (an uploaded file or pasted text).

Finds the gene column, keeps current gene symbols as they are, and converts Ensembl gene IDs,
UniProt accessions, and old or alternative symbols to current symbols with one batched
MyGene.info request. Ambiguous names (an alias shared by several genes) are not guessed.
"""

import csv
import io
import logging
import re
from typing import Any, Dict, List, Optional

import requests

from services.langgraph_orchestrator import _VALID_GENES

logger = logging.getLogger(__name__)

MAX_GENES = 2000
MAX_ENTRIES = 20_000
MAX_TEXT_CHARS = 5_000_000

_ENSEMBL_RE = re.compile(r"^ENSG\d+(\.\d+)?$", re.IGNORECASE)
_UNIPROT_RE = re.compile(r"^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})$", re.IGNORECASE)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-_/@]*$")
# Column headers that name a gene column, compared lowercase without spaces, dots, or underscores
_GENE_HEADERS = {
    "gene", "genes", "symbol", "genesymbol", "genename", "hgnc", "hgncsymbol", "name",
    "ensembl", "ensemblid", "ensemblgene", "ensemblgeneid", "geneid", "uniprot", "uniprotid", "protein", "id",
}
_MYGENE_URL = "https://mygene.info/v3/query"
_MYGENE_BATCH = 1000


def _looks_like_gene(token: str) -> bool:
    return token.upper() in _VALID_GENES or bool(_ENSEMBL_RE.match(token) or _UNIPROT_RE.match(token))


def _is_number(cell: str) -> bool:
    try:
        float(cell)
        return True
    except ValueError:
        return False


def _gene_header_index(row: List[str]) -> Optional[int]:
    return next((i for i, cell in enumerate(row) if re.sub(r"[\s._]+", "", cell.lower()) in _GENE_HEADERS), None)


def _read_entries(text: str) -> tuple[List[str], Optional[str]]:
    """Return the raw gene entries and the name of the column they came from, if any.

    Text is read as a table only when a gene column header is recognized or some cells are
    numbers (as in a differential expression result); otherwise it is a plain list separated
    by spaces, commas, semicolons, tabs, or new lines.
    """
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    sample = "\n".join(lines[:20])
    delimiter = "\t" if "\t" in sample else "," if "," in sample else ";" if ";" in sample else None
    if delimiter:
        rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter) if row]
        if rows and (_gene_header_index(rows[0]) is not None or any(_is_number(cell) for row in rows[:50] for cell in row)):
            column, header, has_header = _pick_column(rows)
            return [row[column] for row in (rows[1:] if has_header else rows) if column < len(row)], header
    entries = [entry for entry in re.split(r"[\s,;]+", "\n".join(lines)) if entry]
    if entries and _gene_header_index(entries[:1]) is not None and entries[0].upper() not in _VALID_GENES:
        return entries[1:], entries[0]  # a one-column file with a header line such as "gene"
    return entries, None


def _pick_column(rows: List[List[str]]) -> tuple[int, Optional[str], bool]:
    """Return (column index, header name or None, whether the first row is a header)."""
    first = rows[0]
    index = _gene_header_index(first)
    if index is not None:
        return index, first[index], True
    width = max(len(row) for row in rows[:200])
    counts = [sum(1 for row in rows[1:200] if i < len(row) and _looks_like_gene(row[i])) for i in range(width)]
    best = max(range(width), key=lambda i: counts[i])
    has_header = not any(_looks_like_gene(cell) for cell in first)
    return best, (first[best] or None) if has_header else None, has_header


def _query_mygene(tokens: List[str]) -> Optional[Dict[str, List[str]]]:
    """Map each token to the distinct current symbols MyGene.info finds for it; None if the service failed."""
    found: Dict[str, List[str]] = {token: [] for token in tokens}
    try:
        for start in range(0, len(tokens), _MYGENE_BATCH):
            chunk = tokens[start:start + _MYGENE_BATCH]
            response = requests.post(
                _MYGENE_URL,
                data={"q": ",".join(chunk), "scopes": "symbol,alias,ensembl.gene,uniprot", "fields": "symbol", "species": "human"},
                timeout=30,
            )
            response.raise_for_status()
            for hit in response.json():
                symbol = str(hit.get("symbol") or "").upper()
                query = hit.get("query")
                if symbol and query in found and symbol in _VALID_GENES and symbol not in found[query]:
                    found[query].append(symbol)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("MyGene.info lookup for a gene list failed: %s", exc)
        return None
    return found


def parse_gene_list(text: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Parse a gene list and report what was kept, converted, and left out."""
    entries, header = _read_entries(text)

    tokens: List[str] = []
    seen = set()
    for entry in entries:
        token = entry.strip().strip("\"'")
        if _ENSEMBL_RE.match(token):
            token = token.split(".")[0]  # drop the version suffix
        if token and _TOKEN_RE.match(token) and token.upper() not in seen:
            seen.add(token.upper())
            tokens.append(token)
    if not tokens:
        raise ValueError("No gene names or IDs were found in the list.")
    if len(tokens) > MAX_ENTRIES:
        raise ValueError(f"The list has {len(tokens):,} entries; the limit is {MAX_ENTRIES:,}.")

    to_look_up = [token for token in tokens if token.upper() not in _VALID_GENES]
    lookups = _query_mygene(to_look_up) if to_look_up else {}

    genes: List[str] = []
    converted, renamed, ambiguous, unrecognized = [], [], [], []
    for token in tokens:
        if token.upper() in _VALID_GENES:
            symbol = token.upper()
        else:
            matches = (lookups or {}).get(token) or []
            if len(matches) != 1:
                if len(matches) > 1:
                    ambiguous.append({"name": token, "matches": matches[:5]})
                else:
                    unrecognized.append(token)
                continue
            symbol = matches[0]
            is_id = bool(_ENSEMBL_RE.match(token) or _UNIPROT_RE.match(token))
            (converted if is_id else renamed).append({"from": token, "to": symbol})
        if symbol not in genes:
            genes.append(symbol)

    return {
        "name": (name or "").strip() or "Pasted list",
        "column": header,
        "genes": genes[:MAX_GENES],
        "entries": len(tokens),
        "converted": converted,
        "renamed": renamed,
        "ambiguous": ambiguous,
        "unrecognized": unrecognized,
        "truncated": max(0, len(genes) - MAX_GENES),
        "lookup_failed": lookups is None,
    }
