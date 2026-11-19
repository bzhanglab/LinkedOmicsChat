"""
Smoke-test every MCP tool by calling it once with its Tool Explorer example input.

Calls POST /api/v1/tools/execute directly (no LLM), one tool at a time, and
prints OK/FAIL, latency, and response size per tool. Example inputs are read
from TOOL_EXAMPLE_ARGS in frontend/components/ToolExplorer.tsx, so `node` must
be on PATH.

Run from the backend/ directory against a running backend:
    python admin/check_tools.py
    python admin/check_tools.py --base-url https://chat.linkedomics.org
    python admin/check_tools.py --variants   # also argument combinations; local backend only
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

# Values for optional arguments the examples leave out, for --variants. Enum arguments take their
# first allowed value and integers a small number, so only free-text arguments are listed here.
VARIANT_VALUES: dict[str, dict[str, Any]] = {
    "analyze_cptac_cis_associations": {"pairs": ["SCNV vs Protein"], "cancers": ["BRCA"]},
    "batch_analyze_cptac_cis_associations": {"pairs": ["SCNV vs Protein"], "cancers": ["BRCA"]},
    "search_trial_studies": {"drugs": ["paclitaxel"], "treatment_category": "Chemotherapy"},
    "meta_analyze_response_genes": {"cancers": ["Breast"], "treatment_category": "Chemotherapy"},
    "meta_analyze_response_gene_sets": {"cancers": ["Breast"], "treatment_category": "Chemotherapy"},
    "search_drug_target_index": {"drug_name": "Palbociclib"},
}


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


def _sample_value(schema: dict[str, Any]) -> Any:
    """A valid value for an enum or integer argument; None for free text."""
    for option in [schema, *schema.get("anyOf", [])]:
        if option.get("enum"):
            return option["enum"][0]
        if option.get("type") == "array" and (option.get("items") or {}).get("enum"):
            return [option["items"]["enum"][0]]
        if option.get("type") == "integer":
            return 3
    return None


def _variants(name: str, example: dict[str, Any], schema: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The example with one optional argument switched on or off at a time, then each list
    argument sent as one plain value, as a model sometimes sends it."""
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    toggles: list[tuple[str, dict[str, Any], str | None]] = []
    for key, prop in properties.items():
        if key in required:
            continue
        if key in example:
            toggles.append((f"without {key}", {k: v for k, v in example.items() if k != key}, None))
        else:
            value = VARIANT_VALUES.get(name, {}).get(key, _sample_value(prop))
            if value is not None:
                toggles.append((f"with {key}", {**example, key: value}, key))
    singles = []
    for label, arguments, added in [("example", example, None), *toggles]:
        for key in [added] if added else list(arguments):
            value = arguments.get(key)
            if isinstance(value, list) and value and _is_array(properties.get(key, {})):
                singles.append((f"{label}, {key} as one value", {**arguments, key: value[0]}))
    return [(label, arguments) for label, arguments, _ in toggles] + singles


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
        "--variants",
        action="store_true",
        help="Also run argument combinations (about 100 calls); use a local backend, since a public one's hourly limit stops it.",
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

    ok = calls = tools_ok = 0
    for tool_id, meta in sorted(tools.items()):
        name = tool_id.split("::")[-1]
        example = examples.get(name)
        if example is None:
            print(f"SKIP           {tool_id}: no example input", flush=True)
            continue
        schema = meta.get("inputSchema") or {}
        runs = [("", _coerce_args(example, schema))]
        if args.variants:
            runs += [(f" [{label}]", arguments) for label, arguments in _variants(name, runs[0][1], schema)]
        tool_ok = True
        for label, arguments in runs:
            started = time.perf_counter()
            error, size = _execute(base_url, tool_id, arguments, args.timeout)
            elapsed = time.perf_counter() - started
            calls += 1
            ok += error is None
            tool_ok = tool_ok and error is None
            print(f"{'FAIL' if error else 'OK':4s} {elapsed:6.1f}s  {tool_id}{label}  ({size:,} chars)", flush=True)
            if error:
                print(f"       -> {error}", flush=True)
                if label:
                    print(f"       arguments: {json.dumps(arguments)}", flush=True)
        tools_ok += tool_ok

    print(f"\nSummary: {tools_ok}/{len(tools)} tools OK." + (f" {ok}/{calls} calls OK." if args.variants else ""))
    if tools_ok < len(tools):
        sys.exit(1)


if __name__ == "__main__":
    main()
