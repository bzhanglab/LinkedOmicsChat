"""
Known-answer check for investigation mode's ratings (services/investigation.py).

Runs the investigation analyses for known drug targets, known prognostic markers and 20 random
genes, then rates them with the current rules. The random genes show how often the rules find
support by chance; the known answers show whether they find it where it should be. Run it before
changing the rating rules.

The raw results (about 250 tool calls, 5 minutes) are saved in data/investigation_cases/, which
git ignores, so later runs re-rate the saved results in a second. --collect runs the analyses again.

Run from the backend/ directory:
    python admin/check_investigation.py --collect   # run the analyses and save them
    python admin/check_investigation.py             # re-rate the saved results
"""
import argparse
import asyncio
import json
import logging
import random
import sys
from collections import Counter
from pathlib import Path

import requests

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
logging.disable(logging.CRITICAL)

from services import investigation as inv  # noqa: E402

CASES_PATH = BACKEND / "data" / "investigation_cases" / "cases.json"

KNOWN_TARGETS = [  # gene, cancer, why it is a target
    ("ERBB2", "BRCA", "amplified and overexpressed; trastuzumab and others"),
    ("EGFR", "LUAD", "mutated; erlotinib, osimertinib and others"),
    ("MET", "LUAD", "amplified or exon-14 skipped; capmatinib, tepotinib"),
    ("KRAS", "PDAC", "mutated in most tumors; KRAS inhibitors in trials"),
    ("CDK4", "BRCA", "CDK4/6 inhibitors approved, but these data are thin"),
]
KNOWN_PROGNOSTIC = [  # gene, cancer, expected direction (+1: higher level, poorer survival), why
    ("CDKN2A", "HNSCC", -1, "p16 marks HPV-positive tumors, which do better"),
    ("MKI67", "LUAD", 1, "proliferation"),
    ("MKI67", "CCRCC", 1, "proliferation"),
    ("ESR1", "BRCA", -1, "ER-positive tumors do better"),
    ("SPP1", "LUAD", 1, "osteopontin, reported as a poor-prognosis marker"),
]
RANDOM_GENES, SEED = 20, 11
# Limits the current rules meet (2026-11-19: 4 of 4 known targets with data rated moderate, 1 of 20
# random genes; the draft rules, on significance alone, rated 5 of 20 random genes moderate or strong)
MIN_KNOWN_TARGETS_SUPPORTED = 3
MAX_RANDOM_TARGETS_SUPPORTED = 2
TARGETS_INDEX = "https://targets.linkedomics.org/index.json"


def _random_cases() -> list[tuple[str, str]]:
    """20 protein-coding genes from the LinkedOmics Targets index, spread over the 10 cancers."""
    genes = sorted({row["gene"] for row in requests.get(TARGETS_INDEX, timeout=60).json()})
    cancers = list(inv.COHORTS)
    return [(gene, cancers[i % len(cancers)]) for i, gene in enumerate(random.Random(SEED).sample(genes, RANDOM_GENES))]


async def _collect() -> None:
    from services.mcp_aggregator import MCPAggregator

    aggregator = MCPAggregator()
    await aggregator.initialize()
    limit, tcga_limit = asyncio.Semaphore(6), asyncio.Semaphore(2)  # the TCGA service fails beyond 2 at once

    async def call(tool_id: str, args: dict) -> dict:
        async with tcga_limit if "tcga" in tool_id else limit:
            try:
                result = json.loads(await aggregator.call_tool(tool_id, args))
            except Exception as exc:
                return {"error": str(exc)}
        for row in result.get("results") or []:
            row.pop("samples", None)  # patient-level rows; ratings don't use them
        return result

    async def run(gene: str, cancer: str) -> dict:
        calls = inv.investigation_calls(gene, cancer, "target")  # includes every prognostic call
        results = await asyncio.gather(*(call(tool_id, args) for tool_id, args in calls))
        counts: Counter = Counter()
        tool_results = {}
        for (tool_id, args), result in zip(calls, results):
            tool_results[f"{tool_id}#{counts[tool_id]}"] = {"_gene": gene, "_args": args, "_result": result}
            counts[tool_id] += 1
        return {"gene": gene, "cancer": cancer, "tool_results": tool_results}

    pairs = sorted({(g, c) for g, c, _ in KNOWN_TARGETS} | {(g, c) for g, c, _, _ in KNOWN_PROGNOSTIC} | set(_random_cases()))
    cases = await asyncio.gather(*(run(gene, cancer) for gene, cancer in pairs))
    CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CASES_PATH.write_text(json.dumps(cases))
    failed = sum("error" in w["_result"] for case in cases for w in case["tool_results"].values())
    print(f"Saved {len(cases)} cases ({failed} failed calls) to {CASES_PATH}")


_SHORT = {"strong": "strong", "moderate": "moderate", "weak": "weak", "against": "AGAINST", "mixed": "MIXED",
          "no_association": "none", "no_data": "-", "failed": "FAILED"}


def _cell(rating: dict) -> str:
    text = _SHORT[rating["rating"]]
    if rating["rating"] in ("strong", "moderate", "weak") and not rating["protein"]:
        text += " (RNA)"
    return text


def check() -> bool:
    if not CASES_PATH.exists():
        print(f"No saved results; run with --collect first ({CASES_PATH}).")
        return False
    cases = {(c["gene"], c["cancer"]): c for c in json.loads(CASES_PATH.read_text())}
    rated = {
        (gene, cancer, question): inv.rate(inv.extract_evidence(gene, cancer, question, case["tool_results"]))
        for (gene, cancer), case in cases.items() for question in inv.QUESTIONS
    }
    known = {(g, c) for g, c, _ in KNOWN_TARGETS} | {(g, c) for g, c, _, _ in KNOWN_PROGNOSTIC}
    random_pairs = sorted(set(cases) - known)

    print(f"\n{'DRUG TARGET':<15}{'tumor vs normal':<17}{'copy number':<17}{'survival':<17}verdict")
    for label, pairs in (("known", [(g, c) for g, c, _ in KNOWN_TARGETS]), ("random", random_pairs)):
        print(f"-- {label}")
        for gene, cancer in pairs:
            r = rated[(gene, cancer, "target")]
            print(f"{gene + ' ' + cancer:<15}" + "".join(f"{_cell(x):<17}" for x in r["ratings"]) + r["verdict"])

    print(f"\n{'PROGNOSTIC':<15}{'survival':<17}{'direction':<12}{'expected':<10}verdict")
    wrong_direction = []
    for label, rows in (("known", [(g, c, d) for g, c, d, _ in KNOWN_PROGNOSTIC]), ("random", [(g, c, None) for g, c in random_pairs])):
        print(f"-- {label}")
        for gene, cancer, expected in rows:
            r = rated[(gene, cancer, "prognostic")]
            got = r["ratings"][0]["direction"]
            words = {1: "poorer", -1: "better", None: ""}
            mark = "" if expected is None else ("ok" if got in (None, expected) else "WRONG")
            if mark == "WRONG":
                wrong_direction.append(f"{gene} {cancer}")
            print(f"{gene + ' ' + cancer:<15}{_cell(r['ratings'][0]):<17}{words[got]:<12}"
                  f"{words.get(expected, ''):<10}{r['verdict']}  {mark}")

    supported = {"strong", "moderate"}
    known_supported = sum(rated[(g, c, "target")]["verdict"] in supported for g, c, _ in KNOWN_TARGETS)
    random_supported = sum(rated[(g, c, "target")]["verdict"] in supported for g, c in random_pairs)
    random_target = Counter(rated[(g, c, "target")]["verdict"] for g, c in random_pairs)
    random_prognostic = Counter(rated[(g, c, "prognostic")]["verdict"] for g, c in random_pairs)
    print(f"\nRandom genes ({len(random_pairs)}): target verdicts {dict(random_target)}; prognostic verdicts {dict(random_prognostic)}")
    print(f"Known targets rated moderate or strong: {known_supported} (need {MIN_KNOWN_TARGETS_SUPPORTED}); "
          f"random genes: {random_supported} (at most {MAX_RANDOM_TARGETS_SUPPORTED})")
    if wrong_direction:
        print("Known prognostic markers rated in the wrong direction:", ", ".join(wrong_direction))
    passed = (not wrong_direction and known_supported >= MIN_KNOWN_TARGETS_SUPPORTED
              and random_supported <= MAX_RANDOM_TARGETS_SUPPORTED)
    print("PASS" if passed else "FAIL")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--collect", action="store_true", help="Run the analyses again and save them.")
    args = parser.parse_args()
    if args.collect:
        asyncio.run(_collect())
    sys.exit(0 if check() else 1)


if __name__ == "__main__":
    main()
