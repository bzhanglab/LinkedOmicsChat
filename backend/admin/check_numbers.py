"""
Regression test for the number check (services/number_check.py).

Re-checks saved answers with the current code and fails when a number in them comes out
"not found" (the saved answers were reviewed and have none) or when too few made-up numbers,
planted in place of real ones, are flagged. It also runs number-format cases that need no saved
answers. Run it before changing services/number_check.py.

The saved answers (50 golden questions and 10 feature questions, about 36 MB) are kept in
data/number_check_cases/, which git ignores. --collect asks the questions again on a running
backend and replaces them (about $0.40 of model use on Claude Haiku 5.5); review any new
"not found" by hand before trusting a fresh set.

Run from the backend/ directory:
    python admin/check_numbers.py
    python admin/check_numbers.py --collect            # needs a backend at http://localhost:8000
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services import number_check as nc  # noqa: E402

CASES_DIR = BACKEND / "data" / "number_check_cases"
GOLDEN = BACKEND / "examples" / "langgraph_golden_queries.json"
# Share of made-up numbers that must be flagged. Text the agent wrote itself (answers with literature)
# comes with far more results, so more made-up numbers match some value by chance (2026-11-19:
# summaries 84%, agent text 51%)
MIN_PLANTED_FLAGGED = {"summary": 0.80, "message": 0.45}

_LIST = {"name": "breast_genes.txt", "genes": "ESR1 PGR GATA3 FOXA1 ERBB2 GRB7 KRT5 KRT14 EGFR MKI67 TOP2A BIRC5 "
         "CCNB1 CDK4 CCND1 MYC TP53 PIK3CA BRCA1 PTEN".split()}
_ER = {"name": "er_signature.txt", "genes": "ESR1 PGR GATA3 FOXA1 XBP1 TFF1 TFF3 AGR2 CA12 SCUBE2 BCL2 NAT1 SLC39A6 "
       "MAPT ERBB4".split()}
FEATURE_QUESTIONS = [
    ("list_survival", "Which genes in my list are linked to worse survival in CPTAC breast cancer?", _LIST),
    ("list_enrichment", "Run GO enrichment on my list.", _LIST),
    ("list_targets", "Which genes in my list are drug targets?", _LIST),
    ("report_kras", "Report on KRAS", None),
    ("report_esr1", "Report on ESR1", None),
    ("signature_typed", "Does this signature predict response to immunotherapy: CXCL9, CXCL10, IDO1, GZMB, CD8A, "
     "STAT1, LAG3, PDCD1LG2?", None),
    ("signature_attached", "Which treatments does my list predict response to?", _ER),
    ("mixed_kras", "Is KRAS a drug target, and is its expression associated with survival in CPTAC and across TCGA "
     "cohorts?", None),
    ("cis_erbb2", "How do RNA and protein levels of ERBB2 correlate across CPTAC cohorts?", None),
    ("compare_survival", "Compare survival for TP53 and BRCA1 across cancers.", None),
]

# Number formats against one result record: (sentence, number as written, expected status)
_FORMAT_RESULT = {"t::x#0": {"_args": {}, "_result": {"results": [{"gene": "TP53", "pvalue": 3.1382e-06, "hr": 1.8371,
                  "share": 0.1834, "score": -0.106, "fdr": 0.04507, "n": 469, "big": 12345.678}]}}}
FORMAT_CASES = [
    ("p = 3.14e-06", "3.14e-06", "found"), ("p = 3.1 × 10⁻⁶", "3.1 × 10⁻⁶", "found"), ("p=3.1x10^-6", "3.1x10^-6", "found"),
    ("p = 3.14E-6", "3.14E-6", "found"), ("p = 0.0000031", "0.0000031", "found"), ("HR 1.84", "1.84", "found"),
    ("HR = 1.8", "1.8", "found"), ("HR 1.837", "1.837", "found"), ("HR 1.83", "1.83", "not_found"),
    ("score −0.106", "−0.106", "found"), ("score -0.11", "-0.11", "found"), ("18% of patients", "18%", "found"),
    ("18.3%", "18.3%", "found"), ("FDR 0.045", "0.045", "found"), ("FDR 0.0451", "0.0451", "found"),
    ("469 patients", "469", "found"), ("470 patients", "470", "not_checked"), ("p < 0.05", "0.05", "not_checked"),
    ("HR 2.51", "2.51", "not_found"), ("12,345.68 units", "12,345.68", "found"),
]


def collect(base_url: str) -> None:
    golden = json.loads(GOLDEN.read_text())["cases"]
    questions = [(c["id"], c["query"], None) for c in golden] + FEATURE_QUESTIONS
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    for i, (case_id, query, gene_list) in enumerate(questions, 1):
        body = {"message": query, **({"gene_list": gene_list} if gene_list else {})}
        request = urllib.request.Request(f"{base_url}/api/v1/chat/stream", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
        started, final = time.perf_counter(), None
        for raw in urllib.request.urlopen(request, timeout=600):
            line = raw.decode().strip()
            if line.startswith("data: ") and json.loads(line[6:]).get("type") == "final":
                final = json.loads(line[6:])["content"]
        (CASES_DIR / f"{case_id}.json").write_text(json.dumps({"id": case_id, "query": query, "response": final}, default=str))
        print(f"{i:>2}/{len(questions)} {case_id:<40} {time.perf_counter() - started:4.0f} s", flush=True)


def _planted(written: str, factor: float) -> str | None:
    """The number scaled by `factor`, written the same way; None for whole numbers (counts)."""
    match = re.match(r"^([−-]?)(\d*\.?\d+)(?:[eE]([−+-]?\d+))?$", written)
    if not match:
        return None
    sign, mantissa, exponent = match.groups()
    decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
    if decimals == 0 and not exponent:
        return None
    return f"{sign}{float(mantissa) * factor:.{decimals}f}" + (f"e{exponent}" if exponent else "")


def check() -> bool:
    ok = True
    print("Number formats")
    for sentence, written, want in FORMAT_CASES:
        got = next((n["status"] for n in nc.check_numbers(sentence, _FORMAT_RESULT)["numbers"] if n["text"] == written), None)
        if got != want:
            ok = False
            print(f"  FAIL {sentence!r}: {got}, expected {want}")
    print(f"  {len(FORMAT_CASES)} cases{'' if ok else ' (failures above)'}")

    files = sorted(CASES_DIR.glob("*.json"))
    if not files:
        print(f"\nNo saved answers in {CASES_DIR}; run with --collect first.")
        return False
    from services.langgraph_orchestrator import agent_view_of_results
    from services.mcp_orchestrator import MCPOrchestrator
    prepare = MCPOrchestrator()._compact_results_for_llm  # what the summary step was given

    totals = {"found": 0, "not_found": 0, "not_checked": 0}
    planted = {"summary": 0, "message": 0}
    flagged = {"summary": 0, "message": 0}
    checked_answers = 0
    for path in files:
        case = json.loads(path.read_text())
        response = case.get("response") or {}
        raw = response.get("raw_results") or {}
        # As the app does: the summary, or for answers with literature the message the agent wrote
        on_message = (response.get("number_check") or {}).get("target") == "message"
        summary = (response.get("message") if on_message else response.get("summary")) or ""
        if not summary or not raw:
            continue
        model_input = prepare(raw) + (f"\n{agent_view_of_results(raw)}" if on_message else "")
        result = nc.check_numbers(summary, raw, model_input=model_input)
        checked_answers += 1
        kind = "message" if on_message else "summary"
        if not result:
            continue
        for key in totals:
            totals[key] += result["counts"][key]
        for entry in result["numbers"]:
            if entry["status"] == "not_found":
                ok = False
                print(f"  NOT FOUND in {case['id']}: {entry['text']!r}")
        # Replace each found decimal with a value no result holds, and see how many get flagged
        skipped = [(m.start(), m.end()) for m in nc._SKIP_RE.finditer(summary)]
        matches = [m for m in nc._NUMBER_RE.finditer(summary) if not any(s <= m.start() < e for s, e in skipped)]
        pieces, cursor, fakes = [], 0, []
        for match, entry in zip(matches, result["numbers"]):
            fake = _planted(match.group(0), 1.37 if planted[kind] % 2 else 0.63) if entry["status"] == "found" else None
            if fake:
                pieces += [summary[cursor:match.start()], fake]
                cursor = match.end()
                fakes.append(fake)
                planted[kind] += 1
        pieces.append(summary[cursor:])
        rechecked = nc.check_numbers("".join(pieces), raw, model_input=model_input)["numbers"]
        flagged[kind] += sum(1 for fake in fakes if next((n["status"] for n in rechecked if n["text"] == fake), None) == "not_found")

    print(f"\nSaved answers ({len(files)}, {checked_answers} with numbers to check): {totals}")
    for kind, label in (("summary", "summaries"), ("message", "text the agent wrote")):
        share = flagged[kind] / max(1, planted[kind])
        print(f"Planted made-up numbers flagged in {label}: {flagged[kind]} of {planted[kind]} "
              f"({share:.0%}; at least {MIN_PLANTED_FLAGGED[kind]:.0%} expected)")
        if planted[kind] and share < MIN_PLANTED_FLAGGED[kind]:
            ok = False
    print("\nOK" if ok else "\nFAILED")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--collect", action="store_true", help="Ask the questions again and replace the saved answers.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend to ask, for --collect.")
    args = parser.parse_args()
    if args.collect:
        collect(args.base_url.rstrip("/"))
    sys.exit(0 if check() else 1)


if __name__ == "__main__":
    main()
