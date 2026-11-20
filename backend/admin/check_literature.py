"""
Check for the literature check's claim extraction (services/literature_check.py).

Extracts claims again from saved abstracts with the current prompt and verification, and compares them with
hand-reviewed labels: findings that must be found, and misreadings that must never appear (a difference
between tumor regions read as tumor vs normal, SPP1 on macrophages, Ki-67 predicted from imaging, a
pan-cancer statement mapped to one cancer). It also compares the claims with the saved data and checks their
verdicts, including planted wrong claims that must come out "opposite". It fails if any forbidden claim
appears, too few expected ones are found, or a verdict is wrong. Run it before changing the prompts or the
comparison in services/literature_check.py.

The abstracts (6 gene-and-cancer searches, about 110 abstracts) and each pair's data analyses are saved in
data/literature_cases/, which git ignores; --collect searches PubMed and runs the analyses again. The labels below refer to PubMed IDs, so after a
--collect some may no longer be in the set; the check reports how many it could use. Each run costs about
0.5 cents of model use.

Run from the backend/ directory:
    python admin/check_literature.py --collect   # search PubMed again and save the abstracts
    python admin/check_literature.py             # extract and compare
"""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
logging.disable(logging.CRITICAL)

from services import literature_check as lc  # noqa: E402

CASES_PATH = BACKEND / "data" / "literature_cases" / "cases.json"
PAIRS = [("SPP1", "PDAC"), ("SPP1", "LUAD"), ("CDK4", "BRCA"), ("CDK4", "LUAD"), ("MKI67", "LUAD"), ("MKI67", "CCRCC")]

TN, SV, NA = "tumor_vs_normal", "survival", "no_association"
HI, POOR, BETTER = "higher_in_tumor", "higher_level_poorer_survival", "higher_level_better_survival"
# Reviewed by hand on 2026-11-20 against each abstract: (claim type, direction, cancer)
EXPECTED = {
    "42996528": [(TN, HI, "PDAC"), (SV, POOR, "PDAC")],
    "22461132": [(TN, HI, "PDAC"), (SV, BETTER, "PDAC")],
    "42210008": [(TN, HI, "LUAD"), (SV, POOR, "LUAD")],
    "31740923": [(TN, HI, "LUAD"), (SV, POOR, "LUAD")],
    "36266702": [(TN, HI, "LUAD"), (SV, POOR, "LUAD")],
    "29849788": [(TN, HI, "LUAD"), (SV, POOR, "LUAD")],
    "38329443": [(SV, POOR, "LUAD")],
    "38622884": [(SV, POOR, "LUAD")],
    "34178613": [(TN, HI, "LUAD"), (SV, POOR, "LUAD")],
    "30240883": [(SV, POOR, "LUAD")],
    "38867223": [(TN, HI, "BRCA")],
    "33626488": [(SV, POOR, "LUAD")],
    "35548181": [(SV, POOR, "LUAD")],
    "29327288": [(SV, POOR, "LUAD")],
    "39021279": [(SV, POOR, "LUAD"), (SV, BETTER, "LSCC")],
    "15263808": [(SV, POOR, "LUAD")],
    "41353523": [(SV, POOR, "CCRCC")],
    "38030468": [(SV, POOR, "CCRCC")],
    "39788813": [(SV, POOR, "CCRCC")],
    "12670587": [(SV, POOR, "CCRCC")],
}
FORBIDDEN = {
    "42996528": [(TN, "lower_in_tumor", "PDAC")],    # lower in tertiary lymphoid structure regions, not in tumors
    "37190178": [(SV, POOR, "LUAD"), ("treatment_response", "higher_level_worse_response", "LUAD")],  # earlier work, on macrophages
    "36139536": [(SV, POOR, "LUAD")],                 # SPP1 on macrophages
    "34422248": [(TN, HI, "LUAD")],                   # "highly expressed in most cancers"
    "38867154": [(SV, POOR, "LUAD")],                 # Ki-67 predicted from imaging
    "32813926": [(SV, POOR, "LUAD")],                 # a cutoff value, no direction stated
    "30464630": [(SV, POOR, "CCRCC")],                # predictors named, no direction stated
}
MIN_RECALL = 0.6  # 2026-11-20: verification drops some correct claims rather than risk wrong verdicts

# Verdicts the labeled claims must get against the saved data (CPTAC and TCGA as of 2026-11-20)
EXPECTED_VERDICTS = {
    ("42996528", TN, HI, "PDAC"): "supported", ("42996528", SV, POOR, "PDAC"): "supported",
    ("22461132", TN, HI, "PDAC"): "supported",
    ("22461132", SV, BETTER, "PDAC"): "opposite",   # longer survival with osteopontin; CPTAC and TCGA show poorer
    ("42210008", TN, HI, "LUAD"): "supported", ("31740923", SV, POOR, "LUAD"): "supported",
    ("38867223", TN, HI, "BRCA"): "cant_test",       # CPTAC has no normal breast tissue
    ("33626488", SV, POOR, "LUAD"): "supported", ("38030468", SV, POOR, "CCRCC"): "supported",
    ("39021279", SV, BETTER, "LSCC"): "cant_test",   # lung squamous, in a lung adenocarcinoma check
}
# Claims nobody made, to check that wrong directions come out "opposite"
PLANTED = [
    ("SPP1", "LUAD", TN, "lower_in_tumor", "opposite"),
    ("SPP1", "PDAC", SV, BETTER, "opposite"),
    ("SPP1", "LUAD", SV, NA, "opposite"),
    ("MKI67", "CCRCC", SV, BETTER, "opposite"),
    ("SPP1", "LUAD", TN, HI, "supported"),
]


async def _data(aggregator, gene: str, cancer: str) -> dict:
    """One pair's data analyses, run as a literature check runs them."""
    limit, tcga_limit = asyncio.Semaphore(6), asyncio.Semaphore(2)  # the TCGA service fails beyond 2 at once

    async def call(tool_id: str, args: dict) -> dict:
        async with tcga_limit if "tcga" in tool_id else limit:
            try:
                result = json.loads(await aggregator.call_tool(tool_id, args))
            except Exception as exc:
                return {"error": str(exc)}
        for row in result.get("results") or []:
            row.pop("samples", None)  # patient-level rows; verdicts don't use them
        return result

    calls = lc.data_calls(gene, cancer)
    results = await asyncio.gather(*(call(tool_id, args) for tool_id, args in calls))
    tool_results, counts = {}, {}
    for (tool_id, args), result in zip(calls, results):
        n = counts.get(tool_id, 0)
        counts[tool_id] = n + 1
        tool_results[f"{tool_id}#{n}"] = {"_args": args, "_result": result}
    return tool_results


async def _collect(cases: list | None = None) -> list:
    """Search PubMed and run the data analyses for every pair; with saved cases, fill in only missing data."""
    from services.mcp_aggregator import MCPAggregator

    aggregator = MCPAggregator()
    await aggregator.initialize()
    if cases is None:
        cases = []
        for gene, cancer in PAIRS:
            (tool_id, args), = lc.literature_calls(gene, cancer)
            result = json.loads(await aggregator.call_tool(tool_id, args))
            cases.append({"gene": gene, "cancer": cancer, "query": args["query"], "articles": result.get("articles", [])})
    for case in cases:
        if "data" not in case:
            case["data"] = await _data(aggregator, case["gene"], case["cancer"])
    CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CASES_PATH.write_text(json.dumps(cases))
    print(f"Saved {sum(len(c['articles']) for c in cases)} abstracts and {len(cases)} pairs' data to {CASES_PATH}")
    return cases


async def _check() -> bool:
    from langchain_core.messages import HumanMessage
    from core.llm_factory import LLMFactory

    if not CASES_PATH.exists():
        print(f"No saved abstracts; run with --collect first ({CASES_PATH}).")
        return False
    llm = LLMFactory.create_llm(temperature=0)

    async def ask(prompt: str) -> str:
        return (await LLMFactory.invoke_async_with_metadata(llm, [HumanMessage(content=prompt)])).text

    cases = json.loads(CASES_PATH.read_text())
    if any("data" not in case for case in cases):
        cases = await _collect(cases)
    found, verdicts = {}, {}
    for case in cases:
        claims = await lc.extract_claims(case["gene"], case["cancer"], case["articles"], ask)
        for claim in lc.compare_claims(claims, case["gene"], case["cancer"], case["data"])["claims"]:
            key = (claim["claim_type"], claim["direction"], claim["cancer"])
            found.setdefault(claim["pmid"], set()).add(key)
            verdicts[(claim["pmid"], *key)] = claim["verdict"]
    saved = {a.get("pmid") for case in cases for a in case["articles"]}

    expected = [(pmid, c) for pmid, claims in EXPECTED.items() if pmid in saved for c in claims]
    hits = [(pmid, c) for pmid, c in expected if c in found.get(pmid, set())]
    forbidden = [(pmid, c) for pmid, claims in FORBIDDEN.items() if pmid in saved for c in claims if c in found.get(pmid, set())]
    labeled = {(pmid, c) for pmid, claims in {**EXPECTED}.items() for c in claims}
    unlabeled = [(pmid, c) for pmid, claims in found.items() for c in claims
                 if (pmid, c) not in labeled and c[2] is not None]
    recall = len(hits) / len(expected) if expected else 0.0

    print(f"\n{len(saved)} abstracts; labels usable for {len({p for p, _ in expected})} of {len(EXPECTED)} expected papers")
    print(f"Expected claims found: {len(hits)}/{len(expected)} ({recall:.0%}, need {MIN_RECALL:.0%})")
    for pmid, c in expected:
        if (pmid, c) not in hits:
            print(f"   missed  {pmid} {c}")
    print(f"Forbidden claims found: {len(forbidden)} (need 0)")
    for pmid, c in forbidden:
        print(f"   FORBIDDEN {pmid} {c}")
    print(f"Unlabeled claims in a covered cancer (review these): {len(unlabeled)}")
    for pmid, c in unlabeled:
        print(f"   {pmid} {c}")
    wrong_verdicts = [(key, want, verdicts[key]) for key, want in EXPECTED_VERDICTS.items()
                      if key in verdicts and verdicts[key] != want]
    checked = sum(key in verdicts for key in EXPECTED_VERDICTS)
    print(f"Verdicts of labeled claims that were found: {checked - len(wrong_verdicts)}/{checked} right")
    for key, want, got in wrong_verdicts:
        print(f"   WRONG VERDICT {key}: {got}, should be {want}")
    data = {(case["gene"], case["cancer"]): case["data"] for case in cases}
    planted_wrong = []
    for gene, cancer, claim_type, direction, want in PLANTED:
        claim = {"pmid": "planted", "claim_type": claim_type, "direction": direction, "sample": "tumor tissue",
                 "cancer": cancer, "cancer_text": cancer, "quote": ""}
        got = lc.compare_claims([claim], gene, cancer, data[(gene, cancer)])["claims"][0]["verdict"]
        if got != want:
            planted_wrong.append((gene, cancer, claim_type, direction, got, want))
    print(f"Planted claims: {len(PLANTED) - len(planted_wrong)}/{len(PLANTED)} right")
    for item in planted_wrong:
        print(f"   WRONG {item[:4]}: {item[4]}, should be {item[5]}")
    passed = not forbidden and recall >= MIN_RECALL and not wrong_verdicts and not planted_wrong
    print("PASS" if passed else "FAIL")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--collect", action="store_true", help="Search PubMed again and save the abstracts.")
    args = parser.parse_args()
    if args.collect:
        asyncio.run(_collect())
    sys.exit(0 if asyncio.run(_check()) else 1)


if __name__ == "__main__":
    main()
