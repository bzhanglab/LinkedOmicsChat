"""
LangGraph evaluation runner using a checked-in golden query set.

Run from the backend/ directory:
    python admin/langgraph_eval.py
    python admin/langgraph_eval.py --list-cases
    python admin/langgraph_eval.py --case survival_dual_dataset --strict
    python admin/langgraph_eval.py --case survival_dual_dataset --verbose
    python admin/langgraph_eval.py --json-out /tmp/langgraph_eval.json
"""
import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

# Ignore unrelated shell DEBUG values so Settings can read backend/.env cleanly.
os.environ.pop("DEBUG", None)

logging.disable(logging.INFO)

from core.config import settings
from services.mcp_orchestrator import MCPOrchestrator


DEFAULT_DATASET_PATH = Path(__file__).parent.parent / "examples" / "langgraph_golden_queries.json"


def _normalize_tool_id(tool_id: str) -> str:
    return tool_id.rsplit("#", 1)[0] if "#" in tool_id else tool_id


def _format_execution_trace(execution_trace: list[dict[str, Any]]) -> str:
    if not execution_trace:
        return "none"

    parts: list[str] = []
    for entry in execution_trace:
        node = entry.get("node", "unknown")
        step = entry.get("step", "?")
        latency_ms = entry.get("latency_ms", 0)
        if node == "agent":
            tool_calls = entry.get("tool_calls") or []
            tools_text = ",".join(tool_calls) if tool_calls else "final"
            parts.append(
                "agent#{step}({latency}ms in={in_tok} out={out_tok} -> {tools})".format(
                    step=step,
                    latency=latency_ms,
                    in_tok=entry.get("input_tokens", 0),
                    out_tok=entry.get("output_tokens", 0),
                    tools=tools_text,
                )
            )
            continue

        if node == "tools":
            tool_parts = []
            for tool_call in entry.get("tool_calls") or []:
                tool_parts.append(
                    "{tool}:{latency}ms:{status}".format(
                        tool=tool_call.get("tool", "tool"),
                        latency=tool_call.get("latency_ms", 0),
                        status=tool_call.get("status", "ok"),
                    )
                )
            tools_text = ",".join(tool_parts) if tool_parts else "none"
            parts.append(f"tools#{step}({latency_ms}ms {tools_text})")
            continue

        parts.append(f"{node}#{step}({latency_ms}ms)")

    return " | ".join(parts)


def _extract_trace_tools(execution_trace: list[dict[str, Any]]) -> list[str]:
    observed_tools: list[str] = []
    for entry in execution_trace:
        if entry.get("node") == "tools":
            for tool_call in entry.get("tool_calls") or []:
                tool_name = tool_call.get("tool")
                if tool_name:
                    observed_tools.append(_normalize_tool_id(str(tool_name)))
            continue

        if entry.get("node") == "agent":
            for tool_name in entry.get("tool_calls") or []:
                if tool_name:
                    observed_tools.append(_normalize_tool_id(str(tool_name)))

    return _ordered_unique(observed_tools)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _load_cases(dataset_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        return payload["cases"]
    raise ValueError(f"Unsupported dataset format in {dataset_path}")


def _select_cases(
    cases: list[dict[str, Any]],
    case_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    selected = cases
    if case_ids:
        wanted = set(case_ids)
        selected = [case for case in cases if case.get("id") in wanted]
    if limit is not None:
        selected = selected[:limit]
    return selected


def _evaluate_case(case: dict[str, Any], result: dict[str, Any], elapsed_ms: int) -> dict[str, Any]:
    raw_tools_used = list(result.get("tools_used") or [])
    tools_used = _ordered_unique([_normalize_tool_id(tool_id) for tool_id in raw_tools_used])
    success = bool(result.get("success"))
    failures: list[str] = []
    execution_trace = list(result.get("_execution_trace") or [])
    observed_tools = _extract_trace_tools(execution_trace)
    evaluation_tools = _ordered_unique(observed_tools + tools_used)

    if not success:
        failures.append("query failed")

    if case.get("expect_no_tools") and evaluation_tools:
        failures.append(f"expected no tools, saw {evaluation_tools}")

    for tool_id in case.get("expected_tools_all", []):
        if tool_id not in evaluation_tools:
            failures.append(f"missing expected tool: {tool_id}")

    for tool_id in case.get("forbidden_tools", []):
        if tool_id in evaluation_tools:
            failures.append(f"forbidden tool used: {tool_id}")

    expect_general_knowledge = case.get("expect_general_knowledge")
    if expect_general_knowledge is not None:
        actual = bool(result.get("is_general_knowledge"))
        if actual != bool(expect_general_knowledge):
            failures.append(
                f"expected is_general_knowledge={bool(expect_general_knowledge)}, saw {actual}"
            )

    message = str(result.get("message") or result.get("summary") or "").replace("\n", " ").strip()
    return {
        "id": case.get("id"),
        "session_key": case.get("session_key"),
        "query": case.get("query"),
        "notes": case.get("notes", ""),
        "success": success,
        "passed": not failures,
        "failures": failures,
        "elapsed_ms": elapsed_ms,
        "tools_used": tools_used,
        "observed_tools": observed_tools,
        "input_tokens": int(result.get("_input_tokens", 0) or 0),
        "output_tokens": int(result.get("_output_tokens", 0) or 0),
        "is_general_knowledge": bool(result.get("is_general_knowledge")),
        "message_preview": message[:240],
        "execution_trace": execution_trace,
        "execution_trace_summary": _format_execution_trace(execution_trace),
    }


def _print_case_report(report: dict[str, Any], *, verbose: bool = False) -> None:
    status = "PASS" if report["passed"] else "FAIL"
    tools = ", ".join(report["tools_used"]) if report["tools_used"] else "none"
    print(
        f"[{status}] {report['id']}: {report['elapsed_ms']} ms | "
        f"tokens {report['input_tokens']}/{report['output_tokens']} | tools: {tools}"
    )
    if report["failures"]:
        for failure in report["failures"]:
            print(f"  - {failure}")
    if verbose:
        print(f"  query: {report['query']}")
        if report["observed_tools"] != report["tools_used"]:
            print(f"  observed tools: {', '.join(report['observed_tools'])}")
        print(f"  trace: {report['execution_trace_summary']}")
        if report["message_preview"]:
            print(f"  preview: {report['message_preview']}")


async def _run_case_with_trace(
    orchestrator: MCPOrchestrator,
    case: dict[str, Any],
    *,
    user_id: str,
    session_id: str | None,
) -> tuple[dict[str, Any], int]:
    langgraph_orch = getattr(orchestrator, "_langgraph_orch", None)
    if langgraph_orch is None:
        raise RuntimeError("LangGraphOrchestrator is not available for trace capture.")

    started = time.perf_counter()
    session, effective_query, active_gene, initial_state = await langgraph_orch._prepare_execution_context(
        case["query"],
        user_id,
        session_id,
        None,
        log_prefix="[LangGraph Eval]",
    )
    final_state = await langgraph_orch._graph.ainvoke(initial_state)
    formatted_response = await langgraph_orch._build_response_from_final_state(
        query=case["query"],
        effective_query=effective_query,
        session=session,
        active_gene=active_gene,
        final_state=final_state,
        log_prefix="[LangGraph Eval]",
    )
    turn_id = await langgraph_orch._save_query(session, case["query"], formatted_response)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        **formatted_response,
        "session_id": session["id"],
        "turn_id": turn_id,
        "_execution_trace": list(final_state.get("execution_trace", [])),
    }, elapsed_ms


async def _run_eval(
    cases: list[dict[str, Any]],
    *,
    strict: bool = False,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    if not settings.USE_LANGGRAPH:
        raise RuntimeError("USE_LANGGRAPH must be true to run the LangGraph evaluation harness.")

    if settings.MOCK_LLM:
        print("WARNING: MOCK_LLM=true, so tool-selection results are not meaningful.")

    orchestrator = MCPOrchestrator()
    session_ids: dict[str, str] = {}
    reports: list[dict[str, Any]] = []

    await orchestrator.initialize()
    try:
        for case in cases:
            session_id = None
            session_key = case.get("session_key")
            if session_key:
                session_id = session_ids.get(session_key)
                if session_id is None:
                    session_id = f"eval-{session_key}"
                    session_ids[session_key] = session_id

            if verbose:
                result, elapsed_ms = await _run_case_with_trace(
                    orchestrator,
                    case,
                    user_id="guest",
                    session_id=session_id,
                )
            else:
                started = time.perf_counter()
                result = await orchestrator.process_query(
                    query=case["query"],
                    user_id="guest",
                    session_id=session_id,
                    client_ip=None,
                )
                elapsed_ms = int((time.perf_counter() - started) * 1000)
            report = _evaluate_case(case, result, elapsed_ms)
            reports.append(report)
            _print_case_report(report, verbose=verbose)
    finally:
        await orchestrator.cleanup()

    total = len(reports)
    passed = sum(1 for report in reports if report["passed"])
    failed = total - passed
    print(f"\nSummary: {passed}/{total} passed, {failed} failed.")

    if strict and failed:
        raise SystemExit(1)

    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LangGraph golden-query evaluation harness.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="Path to a JSON file containing evaluation cases.",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=None,
        help="Run only the specified case id. Can be passed multiple times.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only run the first N selected cases.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="Print available case ids and exit.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write the full evaluation report as JSON.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any case fails expectation checks.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-case query, execution trace, and response preview.",
    )
    args = parser.parse_args()

    cases = _load_cases(args.dataset)
    if args.list_cases:
        for case in cases:
            print(case.get("id"))
        return

    selected_cases = _select_cases(cases, args.case, args.limit)
    if not selected_cases:
        raise SystemExit("No evaluation cases matched the provided filters.")

    reports = asyncio.run(_run_eval(selected_cases, strict=args.strict, verbose=args.verbose))
    if args.json_out:
        args.json_out.write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(f"Wrote JSON report to {args.json_out}")


if __name__ == "__main__":
    main()
