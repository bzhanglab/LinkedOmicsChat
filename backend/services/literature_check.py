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
    text = re.sub(r"\brcc\b", "renal cell carcinoma", text)
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


# ── Comparing claims with the data ───────────────────────────────────────────

VERDICT_LABELS = {"supported": "Supported", "opposite": "Opposite in these data", "mixed": "Mixed in these data",
                  "not_seen": "Not seen in these data", "cant_test": "Can't test"}
_CLAIM_LINES = {"tumor_vs_normal": "tumor_vs_normal", "survival": "survival"}
# The data direction a claim expects on its line (+1: higher in tumor, or higher level with poorer survival)
_EXPECTED = {"higher_in_tumor": 1, "lower_in_tumor": -1, "no_difference": 0, "higher_level_poorer_survival": 1,
             "higher_level_better_survival": -1, "no_association": 0}


def data_calls(gene: str, cancer: str) -> List[Tuple[str, Dict[str, Any]]]:
    """The analyses a literature check compares claims with: the same as a drug-target investigation."""
    return investigation.investigation_calls(gene, cancer, "target")


def compare_claim(claim: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    """The verdict for one claim against the evidence lines for the checked cancer: supported, opposite,
    mixed, not_seen, or cant_test, with the reason and the data results it rests on."""
    cancer = evidence["cancer"]

    def verdict(value: str, reason: str = "", results: Optional[List[str]] = None, support: str = "") -> Dict[str, Any]:
        return {**claim, "verdict": value, "reason": reason, "results": results or [], "support": support}

    if claim["cancer"] != cancer:
        return verdict("cant_test", f"about {claim['cancer_text'] or 'another cancer'}" if claim["cancer"]
                       else f"names no single cancer covered here ({claim['cancer_text'] or 'unstated'})")
    if claim["sample"] != "tumor tissue":
        return verdict("cant_test", "measured outside tumor tissue")
    if claim["claim_type"] == "treatment_response":
        return verdict("cant_test", "treatment response is not compared")
    lines = evidence["lines"]
    if claim["claim_type"] == "copy_number":
        call = next((l for l in lines if l["line"] == "copy_number" and l["source"] == "LinkedOmics Targets"), None)
        if claim["direction"] != "amplified" or call is None or call["status"] != "tested":
            return verdict("cant_test", "only amplification is compared, with LinkedOmics Targets' driver call")
        return verdict("supported" if call["direction"] == 1 else "not_seen", "", [investigation._result_text(call)])

    group = [l for l in lines if l["line"] == _CLAIM_LINES[claim["claim_type"]] and l["source"] in ("CPTAC", "TCGA")
             and l["layer"] in ("protein", "RNA")]
    tested = [l for l in group if l["status"] == "tested"]
    if not tested:
        gaps = sorted({l["note"].replace("this cancer", investigation.CANCER_NAMES[cancer]) for l in group
                       if l["status"] == "no_data" and "this cancer" in l["note"]})
        return verdict("cant_test", "; ".join(gaps) or "no data for this gene", [investigation._result_text(l) for l in group])
    results = [investigation._result_text(l) for l in tested]
    want = _EXPECTED[claim["direction"]]
    significant = [l for l in tested if l["significant"] and l["direction"]]
    # How many of the tests back a supported finding, so "supported" by one test of three reads as such
    if want == 0:
        if significant:
            return verdict("opposite", "", results)
        return verdict("supported", "", results, f"{len(tested)} of {len(tested)} tests" if len(tested) > 1 else "")
    agree = [l for l in significant if l["direction"] == want]
    against = [l for l in significant if l["direction"] == -want]
    if agree and against:
        return verdict("mixed", "", results)
    if agree:
        return verdict("supported", "", results, f"{len(agree)} of {len(tested)} tests" if len(tested) > 1 else "")
    return verdict("opposite" if against else "not_seen", "", results)


def compare_claims(claims: List[Dict[str, Any]], gene: str, cancer: str, tool_results: Dict[str, Any]) -> Dict[str, Any]:
    """Every claim with its verdict, from the data analyses' results ({"tool_id#n": {"_args", "_result"}})."""
    evidence = investigation.extract_evidence(gene, cancer, "target", tool_results)
    compared = [compare_claim(c, evidence) for c in claims]
    counts = {v: sum(c["verdict"] == v for c in compared) for v in VERDICT_LABELS}
    return {"gene": gene, "cancer": cancer, "claims": compared, "counts": counts, "evidence": evidence}


# ── Requests and the written report ───────────────────────────────────────────

# "Check the literature on SPP1 in lung adenocarcinoma"
_REQUEST_RE = re.compile(
    r"^\s*check\s+(?:the\s+)?literature\s+(?:on|for|about)\s+(?P<gene>[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?)"
    r"\s+in\s+(?P<cancer>.+?)\s*[.?!]?\s*$",
    re.IGNORECASE,
)


def parse_request(query: str) -> Optional[Dict[str, Any]]:
    """The gene and cancer a literature check request names, or None when the query is not one.
    "cancer" is None when the cancer is not one of the 10 covered."""
    match = _REQUEST_RE.match(query or "")
    if not match:
        return None
    cancer = investigation._CANCER_LOOKUP.get(re.sub(r"[^a-z0-9]", "", match.group("cancer").lower()))
    return {"gene": match.group("gene").upper(), "cancer": cancer}


_LITERATURE_WORDS = re.compile(r"\b(?:literature|papers?|publications?|published|studies|reported)\b", re.IGNORECASE)


def request_text(gene: str, cancer: str) -> str:
    return f"Check the literature on {gene} in {investigation.CANCER_NAMES[cancer]}"


def offer_request(query: str, genes: List[str]) -> Optional[str]:
    """The literature check to offer under an ordinary answer: one gene, one covered cancer, and a question
    about papers or published findings. Returns the request text, which parse_request reads back."""
    cancer = investigation._mentioned_cancer(query)
    if len(genes) != 1 or cancer is None or not _LITERATURE_WORDS.search(query or ""):
        return None
    return request_text(genes[0], cancer)


def unsupported_cancer_message(gene: str) -> str:
    covered = ", ".join(f"{name} ({code})" for code, name in investigation.CANCER_NAMES.items())
    return (f"The literature check covers 10 cancers, each in both CPTAC and TCGA: {covered}. "
            f"Name one of them, for example \"Check the literature on {gene} in breast cancer\".")


_FINDING_LABELS = {
    "higher_in_tumor": "Higher in tumor than normal", "lower_in_tumor": "Lower in tumor than normal",
    "no_difference": "No tumor-normal difference", "higher_level_poorer_survival": "Higher level, poorer survival",
    "higher_level_better_survival": "Higher level, better survival", "no_association": "Not linked to survival",
    "amplified": "Amplified", "deleted": "Deleted", "higher_level_better_response": "Higher level, better response",
    "higher_level_worse_response": "Higher level, worse response",
}
_VERDICT_ORDER = ("opposite", "mixed", "not_seen", "supported")


def _cell(text: str) -> str:
    return _squash(text).replace("|", "/")


def _paper(claim: Dict[str, Any]) -> str:
    year = f" ({claim['year']})" if claim.get("year") else ""
    return f"[PMID {claim['pmid']}](https://pubmed.ncbi.nlm.nih.gov/{claim['pmid']}/){year}"


def _counts_line(result: Dict[str, Any], papers: int) -> str:
    counts = result["counts"]
    parts = [f"{counts[v]} {VERDICT_LABELS[v][0].lower() + VERDICT_LABELS[v][1:]}" for v in (*_VERDICT_ORDER, "cant_test") if counts[v]]
    findings = len(result["claims"])
    return (f"{papers} paper{'s' if papers != 1 else ''} read · {findings} finding{'s' if findings != 1 else ''}"
            + (f": {', '.join(parts)}" if parts else ""))


def report_markdown(result: Dict[str, Any], papers: int) -> str:
    """The literature check's report: counts, a table of the findings compared, the findings it could not
    test, and the caveats. Built from the verdicts alone, so the written summary cannot change them."""
    gene, cancer = result["gene"], result["cancer"]
    out = [f"## Literature check: {gene} in {investigation.CANCER_NAMES[cancer]} ({cancer})", "",
           f"**{_counts_line(result, papers)}.**", ""]
    compared = sorted((c for c in result["claims"] if c["verdict"] != "cant_test"),
                      key=lambda c: _VERDICT_ORDER.index(c["verdict"]))
    if compared:
        out += ["| Finding | Paper | What these data show | Verdict |", "|---|---|---|---|"]
        for c in compared:
            label = VERDICT_LABELS[c["verdict"]] + (f" ({c['support']})" if c.get("support") else "")
            out.append(f"| {_FINDING_LABELS[c['direction']]} | {_paper(c)}: \"{_cell(c['quote'])}\" | "
                       f"{_cell('; '.join(c['results']))} | {label} |")
    else:
        out.append("No finding in these papers could be compared with the data." if result["claims"] else
                   f"These abstracts state no finding about the level of {gene} in tumor tissue that these data can "
                   "test: higher or lower than in normal tissue, linked to survival, or amplified.")
    # The chat's table cells show text only, so the links are listed under the table
    papers_with_findings = {}
    for c in [*compared, *(c for c in result["claims"] if c["verdict"] == "cant_test")]:
        papers_with_findings.setdefault(c["pmid"], c)
    if papers_with_findings:
        out += ["", "**Papers:**"] + [f"- {_paper(c)}: {_cell(c.get('title') or '')}" for c in papers_with_findings.values()]
    untested = [c for c in result["claims"] if c["verdict"] == "cant_test"]
    if untested:
        out += ["", "**Couldn't test:** " + "; ".join(
            f"{_FINDING_LABELS[c['direction']].lower()}, {_paper(c)} ({c['reason']})" for c in untested) + "."]
    out += ["", "_Each finding is set beside CPTAC and TCGA only. Cohorts, assays, and cutoffs differ, so \"not seen in "
                "these data\" does not mean a finding is wrong, and papers that drew on TCGA agree partly by design._"]
    return "\n".join(out)


def summary_prompt(result: Dict[str, Any], papers: int) -> str:
    """What the summary step is asked to write, from the verdicts, which it may not change."""
    support = lambda c: f" ({c['support']})" if c.get("support") else ""
    gene, cancer = result["gene"], investigation.CANCER_NAMES[result["cancer"]]
    rows = "\n".join(
        f"- {VERDICT_LABELS[c['verdict']]}{support(c)}: "
        f"{_FINDING_LABELS[c['direction']]} (PMID {c['pmid']}, {c.get('year') or 'year unknown'}). "
        f"Paper: \"{c['quote']}\". Data: {'; '.join(c['results']) or c['reason']}"
        for c in result["claims"])
    return f"""Literature check of {gene} in {cancer}: published findings about {gene} set beside CPTAC and TCGA, each with the verdict the app gave it.

{_counts_line(result, papers)}.
Findings:
{rows or "- none"}

Write a short summary with no headings and no numbered items. Start with one sentence on how well these data agree with the published findings. Then up to three bullets: first, if there are any, the findings marked Opposite, Mixed, or Not seen, naming each PMID and what the paper and the data each show; then one bullet on the supported findings as a group, saying how many tests back them where the verdict gives it. End with one sentence noting that cohorts and assays differ between the papers and these data.

Rules: never change a verdict or judge a paper yourself. Do not mention these instructions or say what is absent. Use only the numbers above. Do not discuss other cancers. Use **bold** for gene names and statistics. Do not offer a follow-up analysis."""


def report_text(result: Dict[str, Any]) -> str:
    """The compared findings as plain text, for the number check."""
    return "\n".join(f"{c['quote']} {'; '.join(c['results'])}" for c in result["claims"])
