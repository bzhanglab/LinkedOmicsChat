"""Literature check: published findings about one gene in one cancer, read from PubMed abstracts, to set
beside what CPTAC and TCGA show.

This part finds the papers and extracts their testable claims: findings a study states about the gene's own
level in human tumors (tumor vs normal, survival, copy number), each with a quote that must appear verbatim
in the abstract. Two feasibility checks (2026-11-20, 105 abstracts) shaped it: a plain search returns the
newest papers that only mention the gene, so the search asks for the gene in the title and sorts by relevance;
and the model misread a difference between tumor regions as tumor vs normal, so the prompt rules that out.
"""
import asyncio
import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from services import investigation

PAPERS = 20  # the PubMed tool's maximum; about a fifth of abstracts state a testable finding

# Names papers use in titles besides the symbol. MyGene's aliases mix these with disease loci and words too
# generic to search for (ER, NEU, LFS1, CMM3), so well-known genes get a short hand-picked list
COMMON_NAMES: Dict[str, Tuple[str, ...]] = {
    "CCND1": ("cyclin D1",), "CD274": ("PD-L1", "PDL1"), "CDKN1A": ("p21",), "CDKN1B": ("p27",),
    "CDKN2A": ("p16", "p16INK4a"), "CTLA4": ("CTLA-4",), "ERBB2": ("HER2", "HER-2"),
    "ESR1": ("ER-alpha", "ERalpha", "estrogen receptor alpha"), "MET": ("c-Met",), "MKI67": ("Ki-67", "Ki67"),
    "MYC": ("c-Myc",), "PDCD1": ("PD-1",), "PGR": ("progesterone receptor",), "PTGS2": ("COX-2", "COX2"),
    "SPP1": ("osteopontin",), "TP53": ("p53",), "VEGFA": ("VEGF", "VEGF-A"),
}

# How papers name each covered cancer, for the search
CANCER_TERMS: Dict[str, Tuple[str, ...]] = {
    "BRCA": ("breast cancer", "breast carcinoma"),
    "CCRCC": ("renal cell carcinoma", "ccRCC", "kidney cancer"),
    "COAD": ("colon cancer", "colorectal cancer", "colon adenocarcinoma"),
    "GBM": ("glioblastoma",),
    "HNSCC": ("head and neck", "HNSCC", "oral squamous cell carcinoma"),
    "LSCC": ("lung squamous", "squamous cell lung", "LUSC"),
    "LUAD": ("lung adenocarcinoma", "LUAD"),
    "OV": ("ovarian cancer", "ovarian carcinoma"),
    "PDAC": ("pancreatic cancer", "pancreatic ductal adenocarcinoma", "PDAC"),
    "UCEC": ("endometrial cancer", "endometrial carcinoma"),
}
# The organ a paper must mention for a claim that names only the histology ("adenocarcinoma") to count
_ORGANS = {"BRCA": "breast", "CCRCC": "renal|kidney", "COAD": "colon|colorectal", "GBM": "glioblastoma|glioma",
           "HNSCC": "head and neck|oral", "LSCC": "lung", "LUAD": "lung", "OV": "ovar", "PDAC": "pancrea",
           "UCEC": "endometri|uter"}

CLAIM_TYPES = ("tumor_vs_normal", "survival", "copy_number", "treatment_response")
DIRECTIONS = ("higher_in_tumor", "lower_in_tumor", "no_difference", "higher_level_poorer_survival",
              "higher_level_better_survival", "no_association", "amplified", "deleted",
              "higher_level_better_response", "higher_level_worse_response")

PROMPT = """From this PubMed abstract, list the findings about {gene} that a cancer patient-cohort dataset could test.

Report only findings this study states about the level of {gene} itself (RNA, protein, or copy number) in human patients:
- tumor_vs_normal: {gene} is higher or lower in tumor than in normal tissue. Not differences between tumor grades, stages, subtypes, or regions within a tumor (such as immune or tertiary lymphoid structure regions).
- survival: higher or lower {gene} goes with poorer or better survival, recurrence, or prognosis, or with no difference in it
- copy_number: {gene} is amplified or deleted, or its copy number drives its level
- treatment_response: {gene} level goes with response or resistance to a named treatment in patients
Skip findings from cell lines, mice, or mechanism only; skip levels predicted from imaging, radiomics, or a model instead of measured; skip claims about other genes, cell populations (such as "{gene}+ macrophages" or {gene} on macrophages), pathways, or scores combining several genes; skip statements about many cancers at once; skip background statements and earlier work ("we previously showed", "we recently revealed").
The quote must itself state the finding and its direction.

Return JSON only: {{"claims": [{{"claim_type": "...", "cancer": "the cancer as the abstract names it", "direction": "...", "level": "protein|RNA|copy number|unspecified", "sample": "tumor tissue|serum or plasma|other", "quote": "the exact words from the abstract that state it"}}]}}
direction is one of: {directions}.
Return {{"claims": []}} when there are none.

Title: {title}
Abstract: {abstract}"""


def search_query(gene: str, cancer: str) -> str:
    """The PubMed query: the gene in the title, the cancer anywhere, and a finding of the kinds tested.
    Titles about inhibitors or inhibition are left out: they are about drugs (CDK4/6 inhibition) or mechanism,
    rarely the gene's own level in patients."""
    names = " OR ".join(f'"{name}"[Title]' for name in (gene, *COMMON_NAMES.get(gene, ())))
    cancers = " OR ".join(f'"{term}"[Title/Abstract]' for term in CANCER_TERMS[cancer])
    findings = "prognos*[Title/Abstract] OR survival[Title/Abstract] OR expression[Title/Abstract] OR overexpress*[Title/Abstract]"
    return f"({names}) AND ({cancers}) AND ({findings}) AND hasabstract NOT inhibit*[Title]"


def literature_calls(gene: str, cancer: str) -> List[Tuple[str, Dict[str, Any]]]:
    return [("literature::search_pubmed_articles",
             {"query": search_query(gene, cancer), "max_results": PAPERS, "sort": "relevance"})]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def claim_cancer(cancer_text: str, abstract: str, requested: str) -> Optional[str]:
    """The covered cancer a claim is about. A claim naming only the histology ("adenocarcinoma") takes the
    organ from its paper; a mixed lung cohort ("non-small cell lung cancer") matches no single cancer."""
    text = re.sub(r"\bpulmonary\b", "lung", cancer_text.lower()).replace("renal clear cell", "clear cell renal cell")
    if re.search(r"\bmost\b|pan-?cancer|tumou?r types|cancer types", text):
        return None  # a statement about many cancers, even if the list names this one
    code = investigation._mentioned_cancer(text)
    if code:
        return code
    if re.search(r"non-small|nsclc", text) or not re.search(_ORGANS[requested], abstract, re.IGNORECASE):
        return None
    if requested in ("LUAD", "LSCC"):
        return "LUAD" if "adeno" in text else "LSCC" if "squamous" in text else None
    return requested if re.fullmatch(r"(the )?(cancer|tumou?rs?|carcinoma|adenocarcinoma|patients)?", text.strip()) else None


def _parse(text: str) -> List[Dict[str, Any]]:
    try:
        claims = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())).get("claims", [])
    except (ValueError, AttributeError):
        return []
    return [c for c in claims if isinstance(c, dict)]


def claims_from_abstract(gene: str, cancer: str, article: Dict[str, Any], raw: str) -> List[Dict[str, Any]]:
    """The usable claims in one model reply: a known type and direction, a quote found in the abstract."""
    abstract = _squash(article.get("abstract"))
    out = []
    for c in _parse(raw):
        quote = _squash(c.get("quote")).rstrip(".")
        if c.get("claim_type") not in CLAIM_TYPES or c.get("direction") not in DIRECTIONS or not quote or quote not in abstract:
            continue
        out.append({
            "pmid": article.get("pmid"), "year": article.get("year"), "title": article.get("title"),
            "claim_type": c["claim_type"], "direction": c["direction"], "level": c.get("level") or "unspecified",
            "sample": c.get("sample") or "other", "cancer_text": _squash(c.get("cancer")),
            "cancer": claim_cancer(_squash(c.get("cancer")), abstract, cancer), "quote": quote,
        })
    return out


def merge_duplicates(claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One claim per paper, type, cancer, and direction (the model sometimes quotes a finding twice)."""
    seen, out = set(), []
    for c in claims:
        key = (c["pmid"], c["claim_type"], c["cancer"] or c["cancer_text"].lower(), c["direction"])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


_DIRECTION_WORDS = {
    "higher_in_tumor": "is higher in tumor than in normal tissue", "lower_in_tumor": "is lower in tumor than in normal tissue",
    "no_difference": "does not differ between tumor and normal tissue",
    "higher_level_poorer_survival": "goes with poorer survival, recurrence, or prognosis when higher",
    "higher_level_better_survival": "goes with better survival or prognosis when higher",
    "no_association": "is not associated with survival or prognosis", "amplified": "is amplified", "deleted": "is deleted",
    "higher_level_better_response": "goes with better response to treatment when higher",
    "higher_level_worse_response": "goes with worse response or resistance to treatment when higher",
}

VERIFY_PROMPT = """Quote from a PubMed abstract: "{quote}"

Does this quote itself state, as this study's own finding in human patients, that the measured level of {gene} {finding}? The quote need not name the cancer; the paper is about {cancer}. Answer "no" if the quote reports earlier work, a cell population, a level predicted from imaging, a statement about many cancers, a difference between tumor regions, grades, or stages, or does not state the direction.

Answer with one word: yes or no."""


async def verify_claims(gene: str, claims: List[Dict[str, Any]], ask: Callable[[str], Awaitable[str]],
                        parallel: int = 6) -> List[Dict[str, Any]]:
    """Keep the claims a second, narrow model call confirms against their quotes."""
    limit = asyncio.Semaphore(parallel)

    names = COMMON_NAMES.get(gene, ())
    named = f"{gene} (also called {', '.join(names)})" if names else gene  # quotes often use Ki-67, not MKI67

    async def one(c: Dict[str, Any]) -> bool:
        prompt = VERIFY_PROMPT.format(quote=c["quote"], gene=named, finding=_DIRECTION_WORDS[c["direction"]],
                                      cancer=c["cancer_text"] or "this cancer")
        async with limit:
            reply = await ask(prompt)
        return re.sub(r"[^a-z]", "", reply.lower()).startswith("yes")  # replies come as "Yes", "**Yes**", "yes."

    keep = await asyncio.gather(*(one(c) for c in claims))
    return [c for c, ok in zip(claims, keep) if ok]


async def extract_claims(gene: str, cancer: str, articles: List[Dict[str, Any]],
                         ask: Callable[[str], Awaitable[str]], parallel: int = 6) -> List[Dict[str, Any]]:
    """Ask the model for each abstract's claims (ask: prompt -> reply text) and keep the usable ones."""
    limit = asyncio.Semaphore(parallel)

    async def one(article: Dict[str, Any]) -> List[Dict[str, Any]]:
        abstract = article.get("abstract") or ""
        if not abstract or abstract == "No abstract available.":
            return []
        prompt = PROMPT.format(gene=gene, title=article.get("title", ""), abstract=abstract,
                               directions=", ".join(DIRECTIONS))
        async with limit:
            raw = await ask(prompt)
        return claims_from_abstract(gene, cancer, article, raw)

    found = await asyncio.gather(*(one(a) for a in articles))
    return await verify_claims(gene, merge_duplicates([c for claims in found for c in claims]), ask, parallel)
