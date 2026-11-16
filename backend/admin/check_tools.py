"""
Smoke-test every MCP tool by calling it once with its Tool Explorer example input.

Calls POST /api/v1/tools/execute directly (no LLM), one tool at a time, and
prints OK/FAIL, latency, and response size per tool. Example inputs are read
from TOOL_EXAMPLE_ARGS in frontend/components/ToolExplorer.tsx, so `node` must
be on PATH.

Run from the backend/ directory against a running backend:
    python admin/check_tools.py
    python admin/check_tools.py --base-url https://chat.linkedomics.org
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

TOOL_EXPLORER_PATH = Path(__file__).resolve().parents[2] / "frontend" / "components" / "ToolExplorer.tsx"


def _load_examples() -> dict[str, dict[str, Any]]:
    source = TOOL_EXPLORER_PATH.read_text(encoding="utf-8")
    match = re.search(r"const TOOL_EXAMPLE_ARGS[^=]*=\s*(\{.*?\n\})", source, re.S)
    if match is None:
        raise SystemExit(f"TOOL_EXAMPLE_ARGS not found in {TOOL_EXPLORER_PATH}")
    output = subprocess.check_output(["node", "-e", f"console.log(JSON.stringify({match.group(1)}))"])
    return json.loads(output)


def _is_array(schema: dict[str, Any]) -> bool:
    if schema.get("type") == "array":
        return True
    return any(_is_array(option) for option in schema.get("anyOf", []))


def _coerce_args(args: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any]:
    """Mirror the Tool Explorer: comma-separated strings become lists for array params."""
    properties = (schema or {}).get("properties", {})
    coerced: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and _is_array(properties.get(key, {})):
            value = [item.strip() for item in value.split(",") if item.strip()]
        coerced[key] = value
    return coerced


def _error_in(result: Any) -> str | None:
    if isinstance(result, dict) and (result.get("error") or result.get("success") is False):
        return str(result.get("error") or result)[:200]
    if isinstance(result, str) and re.match(r"\s*(error|exception|traceback)", result, re.I):
        return result[:200]
    return None


def _execute(base_url: str, tool_id: str, arguments: dict[str, Any], timeout: int) -> tuple[str | None, int]:
    request = urllib.request.Request(
        f"{base_url}/api/v1/tools/execute",
        data=json.dumps({"tool_id": tool_id, "arguments": arguments}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        response = json.load(urllib.request.urlopen(request, timeout=timeout))
    except Exception as exc:  # network error, timeout, non-JSON response
        return f"{type(exc).__name__}: {exc}", 0
    if not response.get("success"):
        return str(response.get("error")), 0
    return _error_in(response.get("result")), len(json.dumps(response.get("result")))


def main() -> None:
    parser = argparse.ArgumentParser(description="Call every MCP tool once with its example input.")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Backend to test (default: the local backend at http://localhost:8000).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Per-tool timeout in seconds.",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    examples = _load_examples()
    tools = json.load(urllib.request.urlopen(f"{base_url}/api/v1/tools/", timeout=30))["tools"]

    ok = 0
    for tool_id, meta in sorted(tools.items()):
        example = examples.get(tool_id.split("::")[-1])
        if example is None:
            print(f"SKIP           {tool_id}: no example input", flush=True)
            continue
        started = time.perf_counter()
        error, size = _execute(base_url, tool_id, _coerce_args(example, meta.get("inputSchema")), args.timeout)
        elapsed = time.perf_counter() - started
        ok += error is None
        print(f"{'FAIL' if error else 'OK':4s} {elapsed:6.1f}s  {tool_id}  ({size:,} chars)", flush=True)
        if error:
            print(f"       -> {error}", flush=True)

    print(f"\nSummary: {ok}/{len(tools)} tools OK.")
    if ok < len(tools):
        sys.exit(1)


if __name__ == "__main__":
    main()
