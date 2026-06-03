"""
Validate gene symbols used in the frontend's prepopulated questions.

Every gene named in a suggestion (welcome marquee, "Try asking" chips, use-case
examples) must exist in the dataset's canonical symbol list (valid_genes.txt),
otherwise the question routes to a tool that returns no data. This catches the
NFAT1-class bug (an alias the data doesn't use; canonical symbol is NFATC2).

Run from the backend/ directory:
    python admin/check_prepopulated_genes.py            # report + exit non-zero on any miss
    python admin/check_prepopulated_genes.py --list     # also list the genes that passed
"""
import argparse
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
VALID_GENES_PATH = BACKEND_DIR / "valid_genes.txt"

# Where prepopulated question text lives, anchored to the specific field/array so
# we read only user-facing questions (not code comments, SVG paths, or templates).
#   - welcome marquee chips:   `text: "..."`
#   - use-case examples:       `exampleQuery: "..."`
#   - "Try asking" chips:       string literals inside the `suggestions` useState array
SOURCE_PATTERNS: list[tuple[Path, str]] = [
    (FRONTEND_DIR / "app" / "welcome" / "page.tsx", r'text:\s*"([^"]+)"'),
    (FRONTEND_DIR / "components" / "UseCasesPanel.tsx", r'exampleQuery:\s*"([^"]+)"'),
]
SUGGESTIONS_FILE = FRONTEND_DIR / "components" / "ChatInterface.tsx"
SUGGESTIONS_BLOCK_RE = re.compile(r"\[suggestions\]\s*=\s*useState\(\[(.*?)\]\)", re.DOTALL)

# ALL-CAPS tokens that look gene-like but are legitimately not genes. Extend this
# as new vocabulary appears in questions — anything not here and not a valid gene
# gets flagged for review.
NON_GENE_TOKENS = {
    # CPTAC / TCGA cohort abbreviations
    "BRCA", "COAD", "COADREAD", "CCRCC", "GBM", "HNSCC", "HNSC", "LSCC", "LUAD",
    "LUSC", "OV", "PDAC", "PAAD", "UCEC", "KIRC", "LAML", "SKCM", "RCC",
    # Dataset / resource names
    "TCGA", "CPTAC", "FUNMAP", "GSE25066", "GSE", "MSIGDB", "NCT", "PMID",
    # Omics layers / methods
    "RNA", "RNASEQ", "DNA", "SCNA", "SCNV", "RPPA", "CNV",
    # Target taxonomy / misc qualifiers
    "FDA", "GO", "ORA", "HER2", "T1", "T2", "T3", "T4", "T5", "TSA", "TAA", "ID",
    # Gene-set name fragments (HALLMARK_ESTROGEN_RESPONSE etc.)
    "HALLMARK", "ESTROGEN", "RESPONSE", "HYPOXIA", "EMT",
    # Identifier prefixes
    "ENSG", "ENSP", "UNIPROT", "HGNC",
}

# A gene-like token: starts with a letter, all uppercase letters/digits, len >= 2.
TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,}\b")
STRING_LITERAL_RE = re.compile(r'"([^"\\]+)"')
# Ensembl/UniProt-style identifiers used intentionally in gene-ID-resolution examples.
IDENTIFIER_PREFIXES = ("ENSG", "ENSP", "ENST", "ENSEMBL")


def load_valid_genes() -> set[str]:
    return {
        line.strip().upper()
        for line in VALID_GENES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def collect_questions() -> list[tuple[Path, str]]:
    """Return (file, question) pairs from the anchored question sources."""
    questions: list[tuple[Path, str]] = []
    for path, pattern in SOURCE_PATTERNS:
        if not path.exists():
            print(f"WARNING: missing source file {path}", file=sys.stderr)
            continue
        for q in re.findall(pattern, path.read_text(encoding="utf-8")):
            questions.append((path, q))

    if SUGGESTIONS_FILE.exists():
        block = SUGGESTIONS_BLOCK_RE.search(SUGGESTIONS_FILE.read_text(encoding="utf-8"))
        if block:
            for q in STRING_LITERAL_RE.findall(block.group(1)):
                questions.append((SUGGESTIONS_FILE, q))
    else:
        print(f"WARNING: missing source file {SUGGESTIONS_FILE}", file=sys.stderr)
    return questions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List the genes that passed.")
    args = parser.parse_args()

    valid_genes = load_valid_genes()
    misses: list[tuple[Path, str, str]] = []  # (file, token, question)
    passed: set[str] = set()

    for path, question in collect_questions():
        for token in TOKEN_RE.findall(question):
            if token in NON_GENE_TOKENS or token.startswith(IDENTIFIER_PREFIXES):
                continue
            if token in valid_genes:
                passed.add(token)
            elif token not in passed:
                misses.append((path, token, question))

    if args.list and passed:
        print(f"Validated {len(passed)} gene symbols: {', '.join(sorted(passed))}\n")

    if misses:
        print(f"Found {len(misses)} token(s) not in valid_genes.txt (review or fix):")
        for path, token, question in misses:
            print(f"  - {token!r:>12}  in  {path.name}: \"{question}\"")
        print(
            "\nIf a token above is a real gene, it may be an alias — use the canonical "
            "HGNC symbol. If it is not a gene, add it to NON_GENE_TOKENS in this script."
        )
        raise SystemExit(1)

    print(f"OK: all gene symbols in prepopulated questions are valid ({len(passed)} checked).")


if __name__ == "__main__":
    main()
