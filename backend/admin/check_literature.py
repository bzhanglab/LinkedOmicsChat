"""
Check for the literature check's claim extraction (services/literature_check.py).

Extracts claims again from saved abstracts with the current prompt and verification, and compares them with
hand-reviewed labels: findings that must be found, and misreadings that must never appear (a difference
between tumor regions read as tumor vs normal, SPP1 on macrophages, Ki-67 predicted from imaging, a
pan-cancer statement mapped to one cancer). It fails if any forbidden claim appears or too few expected
ones are found. Run it before changing the prompts in services/literature_check.py.

The abstracts (6 gene-and-cancer searches, about 110 abstracts) are saved in data/literature_cases/, which git
ignores; --collect searches PubMed again and replaces them. The labels below refer to PubMed IDs, so after a
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


async def _collect() -> None:
    from services.mcp_aggregator import MCPAggregator

    aggregator = MCPAggregator()
    await aggregator.initialize()
    cases = []
    for gene, cancer in PAIRS:
        (tool_id, args), = lc.literature_calls(gene, cancer)
        result = json.loads(await aggregator.call_tool(tool_id, args))
        cases.append({"gene": gene, "cancer": cancer, "query": args["query"], "articles": result.get("articles", [])})
    CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CASES_PATH.write_text(json.dumps(cases))
    print(f"Saved {sum(len(c['articles']) for c in cases)} abstracts to {CASES_PATH}")


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
    found = {}
    for case in cases:
        for claim in await lc.extract_claims(case["gene"], case["cancer"], case["articles"], ask):
            found.setdefault(claim["pmid"], set()).add((claim["claim_type"], claim["direction"], claim["cancer"]))
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
    passed = not forbidden and recall >= MIN_RECALL
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
