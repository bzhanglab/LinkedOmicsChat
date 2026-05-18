"""
LangGraph-based Orchestrator
Replaces the single-shot tool planning in MCPOrchestrator with a proper
LangGraph agent that supports chained, parallel, and conditional tool execution.

The LLM autonomously decides which tools to call, sees each tool's output, and
decides if further tool calls are needed — enabling natural multi-step workflows
like funmap_neighborhood → webgestalt without any hardcoded chains.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import pathlib
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Sequence, Type

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, create_model
from typing_extensions import Annotated, TypedDict

from core.config import settings
from core.llm_factory import LLMFactory
from services.mcp_aggregator import MCPAggregator

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    """State that flows through the LangGraph nodes."""
    messages: Annotated[List[BaseMessage], add_messages]
    # Accumulated raw MCP results keyed by unique call id (for _generate_response)
    tool_results: Dict[str, Any]
    # Active gene tracked across steps (for session context)
    active_gene: Optional[str]
    # Step counter (safety cap)
    steps: int
    # Accumulated token usage across all LLM calls in this query
    input_tokens: int
    output_tokens: int
    # Per-node execution trace for observability and tuning
    execution_trace: List[Dict[str, Any]]
    # Ordered unique gene symbols detected in the current user query
    requested_genes: List[str]
    # Ordered unique user-provided gene / identifier tokens detected in the current query
    requested_identifiers: List[str]
    # Whether this query explicitly refers back to the session's active gene ("it", "the gene", etc.)
    allow_active_gene_reference: bool
    # Conservative routing scope inferred from the user query
    tool_scope: str
    # More specific deterministic workflow label layered on top of tool_scope
    workflow: str
    # Planner decision: intent, approach, and optional clarification request
    query_plan: Optional[Dict[str, Any]]


# ─────────────────────────────────────────────────────────────────────────────
# MCP → LangChain tool adapter
# ─────────────────────────────────────────────────────────────────────────────

def _json_type_to_python(t: str) -> type:
    """Map JSON schema primitive type string to a Python type."""
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
    }.get(t, str)  # note: 'array' handled separately in _get_python_type


def _get_python_type(prop: Dict[str, Any]) -> type:
    """
    Return the Python type for a JSON-schema property dict.

    For 'array' types this recurses into the 'items' sub-schema so that
    Pydantic emits a proper {"type": "array", "items": {...}} JSON schema
    (required by Gemini; bare `list` is rejected with INVALID_ARGUMENT).
    """
    t = prop.get("type", "string")
    if t == "array":
        items_schema = prop.get("items") or {}
        item_py_type = _json_type_to_python(items_schema.get("type", "string"))
        return List[item_py_type]  # type: ignore[valid-type]
    return _json_type_to_python(t)


def _build_args_schema(input_schema: Dict[str, Any]) -> Type[BaseModel]:
    """Dynamically create a Pydantic model from an MCP inputSchema dict."""
    properties = (input_schema or {}).get("properties") or {}
    required = set((input_schema or {}).get("required") or [])
    fields: Dict[str, Any] = {}
    import pydantic
    for name, prop in properties.items():
        py_type = _get_python_type(prop)  # handles arrays with items correctly
        description = prop.get("description", "")
        field_kwargs = {"description": description} if description else {}
        if name in required:
            fields[name] = (py_type, pydantic.Field(..., **field_kwargs))
        else:
            default = prop.get("default", None)
            fields[name] = (Optional[py_type], pydantic.Field(default, **field_kwargs))
    return create_model("MCPToolArgs", **fields)


def build_mcp_tools(
    aggregator: MCPAggregator,
    allowed_tool_ids: Optional[Sequence[str]] = None,
) -> List[BaseTool]:
    """
    Convert every registered MCP tool into a LangChain StructuredTool.

    Tool names use '__' instead of '::' because LangChain tool names must be
    valid Python identifiers (no colons).  The mapping is reversed when
    calling call_tool on the aggregator.
    """
    allowed_tool_id_set = set(allowed_tool_ids or [])
    tools: List[BaseTool] = []
    for tool_id, meta in aggregator.list_tools().items():
        if allowed_tool_id_set and tool_id not in allowed_tool_id_set:
            continue
        lc_name = tool_id.replace("::", "__")
        description = (meta.get("description") or "").strip()
        input_schema = meta.get("inputSchema") or {}

        # Build args schema
        try:
            args_schema = _build_args_schema(input_schema)
        except Exception as e:
            logger.warning(f"Could not build schema for {tool_id}: {e}. Using empty schema.")
            args_schema = create_model("EmptyArgs")

        # Closure captures tool_id (not lc_name) for the actual MCP call
        async def _run(aggregator=aggregator, _tid=tool_id, **kwargs):
            logger.info(f"[LangGraph] Calling MCP tool: {_tid} with args: {kwargs}")
            try:
                result = await aggregator.call_tool(_tid, kwargs)
                return result
            except Exception as e:
                logger.error(f"[LangGraph] Tool {_tid} failed: {e}")
                return {"error": str(e)}

        tool = StructuredTool(
            name=lc_name,
            description=description,
            args_schema=args_schema,
            coroutine=_run,
        )
        tools.append(tool)
        logger.debug(f"[LangGraph] Registered tool: {lc_name}")

    logger.info(
        "[LangGraph] Built %s MCP tools for LangGraph agent%s",
        len(tools),
        f" (scoped from {len(allowed_tool_id_set)} allowed ids)" if allowed_tool_id_set else "",
    )
    return tools


# ─────────────────────────────────────────────────────────────────────────────
# Graph nodes
# ─────────────────────────────────────────────────────────────────────────────

MAX_STEPS = 8  # Safety cap on tool-call iterations


def _normalize_runtime_tool_name(tool_name: str) -> str:
    """Normalize LangChain tool names to MCP-style ids for logs and traces."""
    return tool_name.replace("__", "::").rsplit("#", 1)[0]


def _bare_tool_name(tool_name: str) -> str:
    """Return the namespace-free, index-free tool name."""
    return tool_name.replace("::", "__").split("__")[-1].rsplit("#", 1)[0]


def _string_has_usable_data(value: str) -> bool:
    stripped = (value or "").strip()
    if not stripped:
        return False
    if stripped.upper() in {"NA", "N/A", "NONE", "NULL"}:
        return False
    lower = stripped.lower()
    return not any(marker in lower for marker in _EMPTY_TEXT_MARKERS)


def _expression_payload_has_data(payload: Any) -> bool:
    def _level_has_data(level: Any) -> bool:
        if not isinstance(level, dict):
            return False
        if str(level.get("status", "")).lower() != "available":
            return False
        data = level.get("data")
        return isinstance(data, dict) and any(_string_has_usable_data(str(v)) for v in data.values())

    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return any(_expression_payload_has_data(item) for item in payload["data"].values())
    return isinstance(payload, dict) and (
        _level_has_data(payload.get("RNA_level")) or _level_has_data(payload.get("protein_level"))
    )


def _trial_payload_has_data(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("data"), dict) and not (
        "top_sensitive" in payload["data"] or "top_resistant" in payload["data"]
        or "sensitive" in payload["data"] or "resistant" in payload["data"]
    ):
        return any(_trial_payload_has_data(item) for item in payload["data"].values())
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return False
    if (data.get("total_studies") or 0) > 0:
        return True
    return bool(
        data.get("top_sensitive") or data.get("top_resistant")
        or data.get("sensitive") or data.get("resistant")
    )


def _correlation_payload_has_data(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("data"), dict):
        values = list(payload["data"].values())
        if values and all(isinstance(item, dict) for item in values):
            return any(_correlation_payload_has_data(item) for item in values)
        return any(isinstance(records, list) and len(records) > 0 for records in values)
    return False


def _target_payload_has_data(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("data"), dict):
        return any(_target_payload_has_data(item) for item in payload["data"].values())

    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if not isinstance(result, dict):
        return False

    tier = str(result.get("tier", "")).strip().upper()
    if tier and tier != "NA":
        return True
    if _string_has_usable_data(str(result.get("drugs", ""))):
        return True
    if isinstance(result.get("drug_details"), list) and len(result["drug_details"]) > 0:
        return True
    if any(bool(item) for item in result.get("hyper_sites") or []):
        return True
    if isinstance(result.get("presence"), list) and any(any(bool(cell) for cell in row or []) for row in result["presence"]):
        return True
    if isinstance(result.get("plot_map"), dict) and result["plot_map"]:
        return True
    if isinstance(result.get("table_map"), dict) and result["table_map"]:
        return True
    return False


def _generic_payload_has_data(payload: Any, *, parent_key: str = "", depth: int = 0) -> bool:
    if depth > 6:
        return False
    if payload is None:
        return False
    if isinstance(payload, bool):
        return payload is True
    if isinstance(payload, (int, float)):
        return True
    if isinstance(payload, str):
        return _string_has_usable_data(payload)
    if isinstance(payload, list):
        return any(_generic_payload_has_data(item, parent_key=parent_key, depth=depth + 1) for item in payload)
    if not isinstance(payload, dict):
        return bool(payload)

    if payload.get("error"):
        return False
    status = str(payload.get("status", "")).lower()
    if status in _RESULT_EMPTY_STATUS and not any(
        _generic_payload_has_data(v, parent_key=k, depth=depth + 1)
        for k, v in payload.items()
        if k not in {"status", "error", "message"}
    ):
        return False

    ignored = {
        "status", "message", "query", "filters", "applied_filters", "filter_label",
        "study_id", "series", "treatment", "disease", "subtype", "clinical_trial_id",
        "gene", "protein", "cohort", "omics", "title", "description",
    }
    for key, value in payload.items():
        if key.startswith("_") or key in ignored:
            continue
        if _generic_payload_has_data(value, parent_key=key, depth=depth + 1):
            return True
    return False


def _classify_tool_result_payload(tool_name: str, payload: Any) -> str:
    """Classify a tool payload as usable data, empty/no-data, or error."""
    bare = _bare_tool_name(tool_name)
    if isinstance(payload, dict) and payload.get("error"):
        return "error"

    if bare in {"cancer_gene_expression", "batch_cancer_gene_expression", "overall_survival_per_cancer", "batch_overall_survival_per_cancer"}:
        return "ok" if _expression_payload_has_data(payload) else "empty"
    if bare in {"clinical_trial_information", "batch_clinical_trial_information"}:
        return "ok" if _trial_payload_has_data(payload) else "empty"
    if bare in {"get_cis_correlations", "batch_get_cis_correlations"}:
        return "ok" if _correlation_payload_has_data(payload) else "empty"
    if bare in {"get_target", "batch_get_target"}:
        return "ok" if _target_payload_has_data(payload) else "empty"
    if bare == "funmap_neighborhood":
        if isinstance(payload, dict) and (payload.get("neighborhood") or payload.get("nodes") or payload.get("edges")):
            return "ok"
        return "empty"
    if bare == "webgestalt":
        if isinstance(payload, dict) and isinstance(payload.get("data"), list) and payload["data"]:
            return "ok"
        return "empty"
    if bare == "tcga_survival_analysis":
        if isinstance(payload, dict) and isinstance(payload.get("results"), list) and payload["results"]:
            return "ok"
        return "empty"
    if bare == "tcga_cis_association_analysis":
        if isinstance(payload, dict) and isinstance(payload.get("results"), list) and payload["results"]:
            return "ok"
        return "empty"

    return "ok" if _generic_payload_has_data(payload) else "empty"


_NO_DATA_SUGGESTIONS: Dict[str, str] = {
    "expression": (
        "- Try a different cancer cohort (e.g. BRCA, LUAD, COAD).\n"
        "- Verify the gene symbol is a valid HGNC official name.\n"
        "- Check if expression data exists for this gene in LinkedOmics."
    ),
    "survival": (
        "- Try the complementary dataset: if CPTAC returned nothing, TCGA may have data (add 'in TCGA').\n"
        "- Specify a different omics layer (e.g. protein, methylation, miRNA).\n"
        "- Check that the cohort name is supported (e.g. BRCA, LUAD, OV)."
    ),
    "tcga_survival": (
        "- Confirm the TCGA cohort abbreviation (e.g. BRCA, LUAD, SKCM).\n"
        "- Try specifying the omics type explicitly (e.g. 'mRNA', 'methylation', 'copy number').\n"
        "- Some genes may not have significant associations in all cohorts."
    ),
    "tcga_cis": (
        "- Confirm the gene symbol and TCGA cohort abbreviation (e.g. BRCA, LUAD).\n"
        "- Specify the omics pair explicitly (e.g. source_omics='Methylation', target_omics='RNAseq').\n"
        "- Try a different omics pair — not all combinations have data for every gene."
    ),
    "correlation": (
        "- Verify the gene symbol is correct.\n"
        "- Try a different cohort — cis-correlation data varies by cancer type.\n"
        "- RNA-protein correlations require the gene to be measured in both omics layers."
    ),
    "targets": (
        "- The gene may not be in the LinkedOmics drug target index.\n"
        "- Try `search_targets` with a broader filter (e.g. omit tier or drug name).\n"
        "- Consider looking up a related gene or a pathway instead."
    ),
    "trials": (
        "- This gene may not have predictive data in the current clinical trial studies.\n"
        "- Try a broader search: remove specific drug or cancer-type filters.\n"
        "- Use `filter_clinical_trials` to see which studies are available first."
    ),
    "funmap": (
        "- The gene may not be present in the FunMap co-functional network.\n"
        "- Try calling `resolve_gene_identifier` first to confirm the official symbol.\n"
        "- Some lowly-expressed or non-protein-coding genes are excluded from FunMap."
    ),
    "pathway": (
        "- WebGestalt requires a list of genes — a single gene or empty list returns no results.\n"
        "- Try a broader gene set, or specify a different database (e.g. KEGG, GO Biological Process).\n"
        "- Ensure the gene symbols are HGNC official names."
    ),
}


def _build_no_data_message(raw_results: Dict[str, Any], tool_scope: Optional[str] = None) -> str:
    """Create a deterministic response when tools ran but returned no usable data."""
    lines = ["No matching data was returned by the requested tools.", ""]
    lines.append("Checked:")
    for key, value in raw_results.items():
        if not isinstance(value, dict):
            continue
        tool_label = _bare_tool_name(key).replace("_", " ")
        gene = value.get("_gene")
        payload = value.get("_result", {})
        data_status = value.get("_data_status") or _classify_tool_result_payload(key, payload)
        if data_status == "error" and isinstance(payload, dict):
            reason = payload.get("error") or payload.get("message") or "tool error"
        else:
            reason = "no usable rows returned"
        suffix = f" for {gene}" if gene else ""
        lines.append(f"- `{tool_label}`{suffix}: {reason}")
    lines.append("")
    lines.append("This means the queried datasets/tools did not return usable results for the requested input.")
    suggestion_block = _NO_DATA_SUGGESTIONS.get(tool_scope or "")
    if suggestion_block:
        lines.append("")
        lines.append("**Suggestions:**")
        lines.append(suggestion_block)
    return "\n".join(lines)


def _format_execution_trace(execution_trace: Sequence[Dict[str, Any]]) -> str:
    """Render a compact one-line summary of per-step LangGraph execution."""
    if not execution_trace:
        return "none"

    parts: List[str] = []
    for entry in execution_trace:
        node = entry.get("node", "unknown")
        step = entry.get("step", "?")
        latency_ms = entry.get("latency_ms", 0)
        if node == "agent":
            tool_calls = entry.get("tool_calls") or []
            tool_text = ",".join(tool_calls) if tool_calls else "final"
            parts.append(
                "agent#{step}({latency}ms in={in_tok} out={out_tok} -> {tool_text})".format(
                    step=step,
                    latency=latency_ms,
                    in_tok=entry.get("input_tokens", 0),
                    out_tok=entry.get("output_tokens", 0),
                    tool_text=tool_text,
                )
            )
            continue

        if node == "tools":
            tool_summaries = []
            for tool_call in entry.get("tool_calls") or []:
                tool_name = tool_call.get("tool", "tool")
                tool_latency = tool_call.get("latency_ms", 0)
                status = tool_call.get("status", "ok")
                tool_summaries.append(f"{tool_name}:{tool_latency}ms:{status}")
            tools_text = ",".join(tool_summaries) if tool_summaries else "none"
            parts.append(f"tools#{step}({latency_ms}ms {tools_text})")
            continue

        parts.append(f"{node}#{step}({latency_ms}ms)")

    return " | ".join(parts)


def _should_continue(state: AgentState) -> str:
    """
    Routing function: continue to tool execution or stop?

    Returns 'tools' if the last AI message has tool_calls, else END.
    Also enforces the MAX_STEPS safety cap.
    """
    if state["steps"] >= MAX_STEPS:
        logger.warning(f"[LangGraph] Reached MAX_STEPS={MAX_STEPS}, stopping.")
        return END

    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return END


def _resolved_identifier_map(tool_results: Dict[str, Any]) -> Dict[str, str]:
    """Map exact resolver inputs from this turn to resolver-approved HGNC symbols."""
    resolved: Dict[str, str] = {}
    for key, value in tool_results.items():
        if _bare_tool_name(key) != "resolve_gene_identifier":
            continue
        if not isinstance(value, dict):
            continue
        args = value.get("_args") or {}
        payload = value.get("_result") or {}
        identifier = _normalize_identifier_token(args.get("identifier"))
        hgnc_symbol = _normalize_identifier_token(
            payload.get("hgnc_symbol") if isinstance(payload, dict) else None
        )
        if identifier and hgnc_symbol and not (isinstance(payload, dict) and payload.get("error")):
            resolved[identifier] = hgnc_symbol
    return resolved


def _derived_webgestalt_gene_values(tool_results: Dict[str, Any]) -> set[str]:
    """Return gene symbols from prior same-turn results that may feed WebGestalt."""
    derived: set[str] = set()
    for key, value in tool_results.items():
        if _bare_tool_name(key) != "funmap_neighborhood":
            continue
        if not isinstance(value, dict):
            continue
        payload = value.get("_result") or {}
        if not isinstance(payload, dict) or payload.get("error"):
            continue
        neighborhood = payload.get("neighborhood") or []
        if isinstance(neighborhood, list):
            for gene in neighborhood:
                normalized = _normalize_identifier_token(gene)
                if normalized:
                    derived.add(normalized)
        nodes = payload.get("nodes") or []
        if isinstance(nodes, list):
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                normalized = _normalize_identifier_token(node.get("name"))
                if normalized:
                    derived.add(normalized)
    return derived


def _format_identifier_choices(values: Sequence[str]) -> str:
    """Render a short human-readable list of identifiers."""
    unique_values: List[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_identifier_token(value)
        if normalized and normalized not in seen:
            unique_values.append(normalized)
            seen.add(normalized)
    if not unique_values:
        return "no approved identifiers"
    return ", ".join(f"'{value}'" for value in unique_values)


def _validate_tool_identifier_integrity(
    *,
    tool_name: str,
    args: Dict[str, Any],
    requested_identifiers: Sequence[str],
    active_gene: Optional[str],
    allow_active_gene_reference: bool,
    tool_results: Dict[str, Any],
) -> Optional[str]:
    """Reject silent gene rewrites before a tool call is executed."""
    bare = _bare_tool_name(tool_name)

    resolved_map = _resolved_identifier_map(tool_results)
    requested_normalized = [
        _normalize_identifier_token(token) for token in requested_identifiers
        if _normalize_identifier_token(token)
    ]
    explicit_gene_symbols = [
        token for token in requested_normalized
        if not _is_external_gene_identifier(token)
    ]

    context_values: List[str] = []
    active_gene_normalized = _normalize_identifier_token(active_gene)
    if active_gene_normalized and (allow_active_gene_reference or not requested_normalized):
        context_values.append(active_gene_normalized)

    allowed_nonresolver_values = set(explicit_gene_symbols)
    allowed_nonresolver_values.update(resolved_map.values())
    allowed_nonresolver_values.update(context_values)
    if bare == "webgestalt":
        allowed_nonresolver_values.update(_derived_webgestalt_gene_values(tool_results))

    if bare == "resolve_gene_identifier":
        identifier = _normalize_identifier_token(args.get("identifier"))
        if not identifier:
            return None
        allowed_resolver_inputs = set(requested_normalized)
        allowed_resolver_inputs.update(context_values)
        if allowed_resolver_inputs and identifier not in allowed_resolver_inputs:
            return (
                "Blocked silent gene rewrite: "
                f"`resolve_gene_identifier` tried to resolve '{identifier}', but this turn only provided "
                f"{_format_identifier_choices(sorted(allowed_resolver_inputs))}. "
                "Use the exact user-supplied identifier or ask the user to confirm a different symbol."
            )
        return None

    arg_values: List[str] = []
    gene_arg = args.get("protein") or args.get("gene_symbol") or args.get("gene")
    if isinstance(gene_arg, str):
        normalized = _normalize_identifier_token(gene_arg)
        if normalized:
            arg_values.append(normalized)
    proteins_arg = args.get("proteins")
    if isinstance(proteins_arg, list):
        for item in proteins_arg:
            if isinstance(item, str):
                normalized = _normalize_identifier_token(item)
                if normalized:
                    arg_values.append(normalized)

    if not arg_values:
        return None

    if not allowed_nonresolver_values:
        return (
            "Blocked unexpected gene selection: "
            f"`{bare}` tried to use {_format_identifier_choices(arg_values)}, but the user did not provide "
            "a gene identifier in this turn and there is no active gene reference to reuse."
        )

    for value in arg_values:
        if value in allowed_nonresolver_values:
            continue
        if value in requested_normalized and _is_external_gene_identifier(value):
            return (
                "Blocked external identifier passthrough: "
                f"'{value}' must be resolved with `resolve_gene_identifier` before calling `{bare}`."
            )
        return (
            "Blocked silent gene rewrite: "
            f"`{bare}` tried to use '{value}', but this turn only authorized "
            f"{_format_identifier_choices(sorted(allowed_nonresolver_values))}. "
            "Use the exact user-provided gene symbol, or first call `resolve_gene_identifier` "
            "and then use its returned `hgnc_symbol`."
        )
    return None


_TOOL_SCOPE_MAP: Dict[str, tuple[str, ...]] = {
    "none": (),
    "expression": (
        "gene_utils::resolve_gene_identifier",
        "linkedomics::cancer_gene_expression",
        "linkedomics::batch_cancer_gene_expression",
    ),
    "survival": (
        "gene_utils::resolve_gene_identifier",
        "linkedomics::overall_survival_per_cancer",
        "linkedomics::batch_overall_survival_per_cancer",
        "linkedomics::tcga_survival_analysis",
    ),
    "tcga_survival": (
        "gene_utils::resolve_gene_identifier",
        "linkedomics::tcga_survival_analysis",
    ),
    "targets": (
        "gene_utils::resolve_gene_identifier",
        "linkedomics::get_target",
        "linkedomics::batch_get_target",
        "linkedomics::search_targets",
        "linkedomics::rank_targets",
    ),
    "trials": (
        "gene_utils::resolve_gene_identifier",
        "linkedomics::clinical_trial_information",
        "linkedomics::batch_clinical_trial_information",
        "linkedomics::gene_set_trial_information",
        "linkedomics::get_study_info",
        "linkedomics::filter_clinical_trials",
        "linkedomics::meta_analysis_predictive_genes",
        "linkedomics::meta_analysis_predictive_gene_sets",
        "linkedomics::get_study_predictive_genes",
        "linkedomics::get_study_predictive_gene_sets",
    ),
    "trials_genes": (
        "linkedomics::meta_analysis_predictive_genes",
    ),
    "trials_pathways": (
        "linkedomics::meta_analysis_predictive_gene_sets",
    ),
    "literature": (
        "literature::search_pubmed",
        "literature::get_pubmed_abstract",
    ),
    "funmap": (
        "gene_utils::resolve_gene_identifier",
        "linkedomics::funmap_neighborhood",
    ),
    "tcga_cis": (
        "gene_utils::resolve_gene_identifier",
        "linkedomics::tcga_cis_association_analysis",
    ),
    "cis_dual": (
        "gene_utils::resolve_gene_identifier",
        "linkedomics::get_cis_correlations",
        "linkedomics::batch_get_cis_correlations",
        "linkedomics::tcga_cis_association_analysis",
    ),
    "correlation": (
        "gene_utils::resolve_gene_identifier",
        "linkedomics::get_cis_correlations",
        "linkedomics::batch_get_cis_correlations",
    ),
    "pathway": (
        "gene_utils::resolve_gene_identifier",
        "linkedomics::webgestalt",
    ),
}


@dataclass(frozen=True)
class RouteDecision:
    """Deterministic routing decision layered on top of the broad tool scope."""

    tool_scope: str
    workflow: str

_PENDING_OFFER_RE = re.compile(
    r"If you['’]d like, I can\s+(.+?)(?:[.?!])?\s*$",
    re.IGNORECASE | re.DOTALL,
)

_CONVERSATIONAL_QUERIES = {
    "hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "cool",
}

_PLATFORM_PATTERNS = (
    "what can you analyze",
    "what can you do",
    "what data do you have",
    "what data do you access",
    "what cancer types",
    "what cohorts",
    "what is linkedomicschat",
)

_CPTAC_SURVIVAL_COHORTS = frozenset({
    "BRCA", "COAD", "CCRCC", "GBM", "HNSCC", "LSCC", "LUAD", "OV", "PDAC", "UCEC",
})

_SURVIVAL_TCGA_ONLY_OMICS = (
    "methylation", "mirna", "mirnaseq", "scna", "copy number",
)

_STRUCTURE_OUT_OF_SCOPE_PATTERNS = (
    re.compile(r"\b3d structure\b", re.IGNORECASE),
    re.compile(r"\bthree[- ]dimensional structure\b", re.IGNORECASE),
    re.compile(r"\bprotein structure\b", re.IGNORECASE),
    re.compile(r"\bcrystal structure\b", re.IGNORECASE),
    re.compile(r"\bstructural model\b", re.IGNORECASE),
    re.compile(r"\balphafold\b", re.IGNORECASE),
    re.compile(r"\bpdb\b", re.IGNORECASE),
)

_DEFAULT_WORKFLOW_BY_SCOPE: Dict[str, str] = {
    "none": "direct_response",
    "expression": "expression_analysis",
    "survival": "survival_dual_dataset",
    "tcga_survival": "survival_tcga_only",
    "targets": "target_lookup",
    "trials": "clinical_trials",
    "trials_genes": "clinical_trials_gene_biomarkers",
    "trials_pathways": "clinical_trials_pathway_biomarkers",
    "literature": "literature_search",
    "funmap": "funmap_neighborhood",
    "tcga_cis": "tcga_cis_association",
    "cis_dual": "cis_dual_dataset",
    "correlation": "cptac_cis_correlation",
    "pathway": "pathway_enrichment",
    "full": "broad_full",
}

_LITERATURE_KEYWORDS = (
    "paper", "papers", "pubmed", "literature", "publication", "publications",
    "abstract", "citation", "citations",
)

_TARGET_KEYWORDS = (
    "drug target", "drug targets",
    "druggable",
    "therapeutic target", "therapeutic targets",
    "oncology target", "oncology targets",
    "tumor antigen", "tumour antigen",
    "tumor-associated antigen", "tumour-associated antigen",
    "tumor specific antigen", "tumour specific antigen",
    "neoantigen",
    "depmap", "cell line dependency",
    "target tier",
    "rank target", "top target", "best target",
)

_TRIAL_KEYWORDS = (
    "clinical trial", "clinical trials", "drug", "drugs", "treatment", "treatments",
    "resistant", "resistance", "sensitive", "sensitivity", "biomarker", "biomarkers",
    "predict response", "predict treatment", "response to", "therapy",
    # Additional: predictive value / chemotherapy / immunotherapy contexts
    "predictive", "chemo", "chemotherapy", "immunotherapy", "targeted therapy",
    "checkpoint inhibitor", "checkpoint inhibitors", "immune checkpoint", "ici",
    "drug response", "drug sensitivity", "drug resistance", "chemoresist",
    "treatment response", "treatment resistance", "treatment sensitivity",
    "anticancer", "anti-cancer", "antitumor", "anti-tumor",
)

_TRIAL_META_GENE_KEYWORDS = (
    " gene ", " genes ", "biomarker", "biomarkers", "marker", "markers",
)

_TRIAL_META_PATHWAY_KEYWORDS = (
    "pathway", "pathways", "gene set", "gene sets", "geneset", "genesets",
    "signature", "signatures",
)

_TRIAL_META_INTENT_KEYWORDS = (
    "predict", "predictive", "predictor", "predictors", "top", "best",
    "most predictive", "robust", "biomarker", "biomarkers",
)

_FUNMAP_KEYWORDS = (
    "funmap", "functional neighbor", "functional neighbourhood", "gene network",
    "protein network", "functional network", "co-functional", "network neighbor", "network neighbourhood",
    "interaction network", "functional interaction",
    # Additional: common bioinformatics phrasings
    "functional partner", "functional association", "protein partner",
    "co-regulated", "co regulated",
    "protein-protein interaction", "protein interaction network",
    "interactor", "interactome",
)

_TCGA_CIS_KEYWORDS = (
    # TCGA-specific cis-association phrasing
    "cis association", "cis-association", "cis associations", "cis-associations",
    "genome-wide cis", "pan-cancer cis",
    "strongest.*cis", "top.*cis", "cis.*across",
)

_TCGA_CIS_ASSOCIATION_WORDS = (
    "associat", "correlat", "relationship", "relation", "cis", " vs ", " versus ",
)

_TCGA_SPECIFIC_CIS_TERMS = (
    "rppa", "scna", "mirnaseq", "mirna-seq",
)

_TCGA_CIS_OMICS_PATTERNS: Dict[str, tuple[str, ...]] = {
    "RNAseq": ("rnaseq", "rna-seq", "rna seq", "mrna", "rna expression"),
    "RPPA": ("rppa", "protein"),
    "Methylation": ("methylation", "methylated"),
    "SCNA": ("scna", "scnv", "copy number", "copy-number", "cnv"),
    "miRNASeq": ("mirna", "mirnaseq", "mirna-seq", "mirna seq"),
}

_OMICS_LAYER_TOKENS = frozenset({
    "RNASEQ", "RPPA", "SCNA", "SCNV", "MIRNA", "MIRNASEQ", "METHYLATION",
})

_CORRELATION_KEYWORDS = (
    "cis-correl", "cis correl",
    "drives expression", "drive expression", "driving expression",
    "translation efficiency",
    "rna vs protein", "rna-protein correlation",
    "copy number effect", "dosage effect",
    # Additional: co-expression / multi-omics correlation phrasing
    "co-expression", "coexpression", "co expression", "co-expressed", "coexpressed", "co expressed",
    "mrna protein correlation", "rna protein",
    "regulated by copy number", "methylation effect",
)

def _has_cptac_cis_correlation_intent(normalized_query: str) -> bool:
    """Return True when the user explicitly asks for CPTAC cis/correlation data."""
    if "cptac" not in normalized_query:
        return False
    if any(keyword in normalized_query for keyword in _CORRELATION_KEYWORDS):
        return True
    layers = _mentioned_cross_omics_layers(normalized_query)
    if len(layers) >= 2 and any(marker in normalized_query for marker in _TCGA_CIS_ASSOCIATION_WORDS):
        return True
    return "cis" in normalized_query and any(
        marker in normalized_query
        for marker in ("correlat", "association", "associat", "across")
    )


def _mentioned_tcga_cis_omics_layers(normalized_query: str) -> set[str]:
    """Return TCGA cis omics layers mentioned as data layers, not genes."""
    layers: set[str] = set()
    for layer, aliases in _TCGA_CIS_OMICS_PATTERNS.items():
        if any(re.search(rf"\b{re.escape(alias)}\b", normalized_query) for alias in aliases):
            layers.add(layer)
    return layers


def _mentioned_cross_omics_layers(normalized_query: str) -> set[str]:
    """Return generic molecular layers mentioned in a cross-omics query."""
    patterns: Dict[str, tuple[str, ...]] = {
        "RNA": ("rna", "mrna", "rnaseq", "rna-seq", "rna seq", "rna expression"),
        "Protein": ("protein", "rppa"),
        "Methylation": ("methylation", "methylated"),
        "CopyNumber": ("copy number", "copy-number", "cnv", "scnv", "scna"),
        "miRNA": ("mirna", "mirnaseq", "mirna-seq", "mirna seq"),
    }
    layers: set[str] = set()
    for layer, aliases in patterns.items():
        if any(re.search(rf"\b{re.escape(alias)}\b", normalized_query) for alias in aliases):
            layers.add(layer)
    return layers


def _has_tcga_cis_association_intent(normalized_query: str) -> bool:
    """Return True for cross-omics association/correlation wording."""
    if "cptac" in normalized_query:
        return False

    if "tcga" in normalized_query:
        layers = _mentioned_cross_omics_layers(normalized_query)
        if len(layers) < 2:
            layers = _mentioned_tcga_cis_omics_layers(normalized_query)
        return len(layers) >= 2

    # Without an explicit dataset, keep generic RNA/RNAseq + protein/methylation/
    # copy-number wording ambiguous. Only TCGA-specific layer names such as RPPA,
    # SCNA, or miRNASeq should imply the TCGA cis-association tool.
    if not _has_tcga_specific_cis_terms(normalized_query):
        return False

    layers = _mentioned_tcga_cis_omics_layers(normalized_query)
    if len(layers) < 2:
        return False
    return any(marker in normalized_query for marker in _TCGA_CIS_ASSOCIATION_WORDS)


def _has_tcga_specific_cis_terms(normalized_query: str) -> bool:
    """Return True when the query uses TCGA-style omics layer names."""
    return any(re.search(rf"\b{re.escape(term)}\b", normalized_query) for term in _TCGA_SPECIFIC_CIS_TERMS)


def _has_dual_cis_association_intent(normalized_query: str) -> bool:
    """Return True for generic cross-omics cis wording that should query both datasets."""
    if not normalized_query or "cptac" in normalized_query or "tcga" in normalized_query:
        return False
    if _has_tcga_specific_cis_terms(normalized_query):
        return False
    if "cis-correl" in normalized_query or "cis correl" in normalized_query:
        # In this app, "cis-correlations" is the CPTAC tool wording.
        return False
    if not any(marker in normalized_query for marker in _TCGA_CIS_ASSOCIATION_WORDS):
        return False
    layers = _mentioned_cross_omics_layers(normalized_query)
    dual_supported_layers = {"RNA", "Protein", "Methylation", "CopyNumber"}
    return len(layers) >= 2 and layers.issubset(dual_supported_layers)


_CROSS_OMICS_LAYER_ALIASES: Dict[str, tuple[str, ...]] = {
    "RNA": ("rna expression", "rna-seq", "rna seq", "rnaseq", "mrna", "rna"),
    "Protein": ("protein", "rppa"),
    "Methylation": ("methylation", "methylated"),
    "CopyNumber": ("copy number", "copy-number", "scnv", "scna", "cnv"),
}

_CPTAC_CIS_LAYER_BY_GENERIC = {
    "RNA": "RNA",
    "Protein": "Protein",
    "Methylation": "Methylation",
    "CopyNumber": "SCNV",
}

_TCGA_CIS_LAYER_BY_GENERIC = {
    "RNA": "RNAseq",
    "Protein": "RPPA",
    "Methylation": "Methylation",
    "CopyNumber": "SCNA",
}


def _ordered_cross_omics_layers(query: str) -> List[str]:
    """Return generic omics layers in first-mentioned order."""
    normalized = re.sub(r"\s+", " ", (query or "").strip().lower())
    positions: Dict[str, int] = {}
    for layer, aliases in _CROSS_OMICS_LAYER_ALIASES.items():
        for alias in aliases:
            match = re.search(rf"\b{re.escape(alias)}\b", normalized)
            if match:
                positions[layer] = min(positions.get(layer, match.start()), match.start())
    return [layer for layer, _ in sorted(positions.items(), key=lambda item: item[1])]


def _infer_dual_cis_tool_args(query: str, gene: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Infer matching CPTAC and TCGA cis tool args for a generic cross-omics query."""
    cptac_args: Dict[str, Any] = {"protein": gene}
    tcga_args: Dict[str, Any] = {"gene": gene}

    cohort_codes = _extract_cancer_codes(query)
    if cohort_codes:
        cohort = cohort_codes[0]
        cptac_args["cancers"] = [cohort]
        tcga_args["cohort"] = cohort

    layers = _ordered_cross_omics_layers(query)
    if len(layers) >= 2:
        left, right = layers[0], layers[1]
        cptac_left = _CPTAC_CIS_LAYER_BY_GENERIC.get(left)
        cptac_right = _CPTAC_CIS_LAYER_BY_GENERIC.get(right)
        tcga_left = _TCGA_CIS_LAYER_BY_GENERIC.get(left)
        tcga_right = _TCGA_CIS_LAYER_BY_GENERIC.get(right)
        if cptac_left and cptac_right:
            cptac_args["pairs"] = [f"{cptac_left} vs {cptac_right}"]
        if tcga_left and tcga_right:
            tcga_args["source_omics"] = tcga_left
            tcga_args["target_omics"] = tcga_right

    return cptac_args, tcga_args


_PATHWAY_KEYWORDS = (
    "pathway", "enrichment", "gsea", "gene ontology", "go term",
    "kegg", "webgestalt", "ora ", "wikipathway",
    # Additional
    "gene set", "gene sets", "biological process", "molecular function",
    "pathway analysis", "overrepresentation",
)

_EXPRESSION_KEYWORDS = (
    "tumor vs normal", "expression", "expressed", "overexpress", "underexpress",
    "upregulat", "downregulat", "tumour vs normal",
    # Additional: common expression-query phrasings
    "differentially expressed", "differential expression",
    "transcript level", "mrna level", "protein level", "protein abundance",
    "high expression", "low expression", "expression level",
)

_SURVIVAL_KEYWORDS = (
    "survival", "overall survival", "prognos", "kaplan", "km curve", "hazard ratio", "os ",
    # Additional: common survival/outcome phrasings
    "prognostic value", "prognostic impact", "prognostic significance",
    "outcome", "patient outcome", "mortality", "recurrence",
    "disease-free", "progression-free", "relapse-free",
)

_SURVIVAL_OMICS_KEYWORDS = (
    "methylation", "mirna", "mirnaseq", "scna", "copy number", "rppa", "rnaseq", "tcga",
)


# Regex pattern that matches alphanumeric tokens that could plausibly be a gene symbol
# or external gene identifier when judged alongside the original token casing.
_IDENTIFIER_TOKEN_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{1,15})\b")
_ENSG_IDENTIFIER_RE = re.compile(r"^ENSG\d+$", re.IGNORECASE)
_UNIPROT_IDENTIFIER_RE = re.compile(
    r"^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})$",
    re.IGNORECASE,
)
_ACTIVE_GENE_REFERENCE_RE = re.compile(
    r"\b(it|its|this gene|the gene|that gene|this protein|that protein|the protein)\b",
    re.IGNORECASE,
)
_NON_GENE_ACCESSION_RE = re.compile(
    r"^(GSE|GSM|SRP|PRJNA|NCT|PMID)\d+$",
    re.IGNORECASE,
)
def _load_valid_genes() -> frozenset[str]:
    """Load the HGNC gene symbol list from valid_genes.txt (uppercase, one per line)."""
    candidates = [
        pathlib.Path(__file__).parent.parent.parent / "valid_genes.txt",
        pathlib.Path(__file__).parent.parent / "valid_genes.txt",
        pathlib.Path(__file__).parent / "valid_genes.txt",
    ]
    for path in candidates:
        if path.exists():
            with path.open() as f:
                return frozenset(line.strip().upper() for line in f if line.strip())
    logger.warning("valid_genes.txt not found — lowercase gene normalization disabled")
    return frozenset()


_VALID_GENES: frozenset[str] = _load_valid_genes()

_GENE_STOPWORDS = {
    "RNA", "DNA", "ATP", "GTP", "PCR", "LLM", "AI", "API",
    "TCGA", "CPTAC", "WHO", "FDA", "USA", "UK", "OR", "AND",
    "NOT", "FOR", "THE", "WITH", "FROM", "BRCA", "LUAD", "LUSC",
    "HNSC", "HNSCC", "CCRCC", "UCEC", "PDAC", "COAD", "LSCC",
    # Common English words that look like gene symbols when uppercased
    "HOW", "WHY", "WHAT", "WHEN", "WHERE", "IS", "ARE", "IN", "VS",
    "TUMOR", "NORMAL", "CANCER", "EXPRESSED", "EXPRESSION", "LEVEL",
    "HIGH", "LOW", "FIND", "SHOW", "GET", "LIST", "COMPARE", "ANALYSIS",
    "DATA", "GENE", "PROTEIN", "STUDY", "TYPE", "PLOT", "CHART",
}
_CANCER_TYPE_MAP: Dict[str, str] = {
    "BRCA": "breast cancer (BRCA)",
    "LUAD": "lung adenocarcinoma (LUAD)",
    "LUSC": "lung squamous cell carcinoma (LUSC)",
    "HNSC": "head and neck squamous cell carcinoma (HNSCC)",
    "HNSCC": "head and neck squamous cell carcinoma (HNSCC)",
    "CCRCC": "clear cell renal cell carcinoma (CCRCC)",
    "UCEC": "uterine corpus endometrial carcinoma (UCEC)",
    "PDAC": "pancreatic ductal adenocarcinoma (PDAC)",
    "COAD": "colon adenocarcinoma (COAD)",
    "LSCC": "lung squamous cell carcinoma (LSCC)",
    "GBM": "glioblastoma (GBM)",
    "OV": "ovarian serous cystadenocarcinoma (OV)",
    "STAD": "stomach adenocarcinoma (STAD)",
    "BLCA": "bladder urothelial carcinoma (BLCA)",
    "KIRC": "kidney renal clear cell carcinoma (KIRC)",
    "THCA": "thyroid carcinoma (THCA)",
    "PRAD": "prostate adenocarcinoma (PRAD)",
    "LIHC": "liver hepatocellular carcinoma (LIHC)",
    "SKCM": "skin cutaneous melanoma (SKCM)",
    "CESC": "cervical squamous cell carcinoma (CESC)",
    "LAML": "acute myeloid leukemia (LAML)",
}
_AUTO_BATCH_SINGLE_TOOL_MAP: Dict[str, str] = {
    "linkedomics__cancer_gene_expression": "linkedomics__batch_cancer_gene_expression",
    "linkedomics__overall_survival_per_cancer": "linkedomics__batch_overall_survival_per_cancer",
    "linkedomics__get_target": "linkedomics__batch_get_target",
    "linkedomics__get_cis_correlations": "linkedomics__batch_get_cis_correlations",
    "linkedomics__clinical_trial_information": "linkedomics__batch_clinical_trial_information",
}
_AUTO_BATCH_SCOPES = {"expression", "survival", "targets", "trials", "correlation"}
_RESULT_EMPTY_STATUS = {"error", "unavailable", "missing", "not_found", "no_studies", "no_data"}
_EMPTY_TEXT_MARKERS = (
    "data unavailable",
    "no data",
    "no matching data",
    "not found",
    "no studies found",
    "no significant results found",
)


def _normalize_identifier_token(value: Any) -> str:
    """Normalize a gene / identifier token for strict comparisons."""
    return str(value or "").strip().upper()


def _is_external_gene_identifier(token: str) -> bool:
    """Return True for Ensembl or UniProt-style gene identifiers."""
    normalized = _normalize_identifier_token(token)
    return bool(
        normalized
        and (
            _ENSG_IDENTIFIER_RE.fullmatch(normalized)
            or _UNIPROT_IDENTIFIER_RE.fullmatch(normalized)
        )
    )


def _looks_like_explicit_gene_token(token: str) -> bool:
    """Heuristic for explicit gene-like tokens typed by the user."""
    normalized = _normalize_identifier_token(token)
    if not normalized or normalized in _GENE_STOPWORDS:
        return False
    if _NON_GENE_ACCESSION_RE.fullmatch(normalized):
        return False
    if _is_external_gene_identifier(normalized):
        return True
    if not any(ch.isalpha() for ch in normalized):
        return False
    # Molecular layer names can look like uppercase gene symbols (e.g. RPPA).
    # Only treat them as genes if the HGNC symbol list explicitly contains them.
    if normalized in _OMICS_LAYER_TOKENS and normalized not in _VALID_GENES:
        return False
    # Accept unambiguous alphanumeric symbols like TP53 / BRCA1 / C11ORF1 even
    # when the user types them in lowercase, but avoid plain lowercase words.
    if any(ch.isdigit() for ch in normalized):
        return True
    # Accept already-capitalized symbol-like tokens (EGFR, MET, KRAS, etc.).
    if token.isupper() and 2 <= len(normalized) <= 10:
        return True
    # Accept lowercase/mixed-case tokens whose uppercase form is a known HGNC symbol.
    return bool(_VALID_GENES and normalized in _VALID_GENES)


def _extract_query_identifiers(query: str) -> List[str]:
    """Return ordered unique gene / identifier tokens explicitly provided by the user."""
    identifiers: List[str] = []
    seen: set[str] = set()
    for token in _IDENTIFIER_TOKEN_RE.findall(query or ""):
        if not _looks_like_explicit_gene_token(token):
            continue
        normalized = _normalize_identifier_token(token)
        if normalized not in seen:
            identifiers.append(normalized)
            seen.add(normalized)
    return identifiers


def _extract_query_genes(query: str) -> List[str]:
    """Return ordered unique explicit HGNC-like symbols mentioned in the query."""
    return [
        token for token in _extract_query_identifiers(query)
        if not _is_external_gene_identifier(token)
    ]


def _extract_cancer_type(query: str) -> Optional[str]:
    """Return a human-readable cancer type label if the query mentions a known cohort abbreviation."""
    upper = (query or "").upper()
    for abbrev, label in _CANCER_TYPE_MAP.items():
        if re.search(r"\b" + re.escape(abbrev) + r"\b", upper):
            return label
    return None


def _extract_cancer_codes(query: str) -> List[str]:
    """Return ordered cohort abbreviations mentioned in the query."""
    upper = (query or "").upper()
    matches: List[str] = []
    for abbrev in _CANCER_TYPE_MAP:
        if re.search(r"\b" + re.escape(abbrev) + r"\b", upper):
            matches.append(abbrev)
    return matches


def _query_uses_active_gene_reference(query: str) -> bool:
    """Return True when the user explicitly refers back to the previous gene context."""
    return bool(_ACTIVE_GENE_REFERENCE_RE.search(query or ""))

def _detect_multi_gene(query: str) -> bool:
    """Return True when the query contains 2+ likely gene symbols."""
    return len(_extract_query_genes(query)) >= 2


def _looks_conversational(query: str) -> bool:
    normalized = re.sub(r"\s+", " ", query.strip().lower()).strip(" ?!.,")
    return normalized in _CONVERSATIONAL_QUERIES


def _looks_platform_question(query: str) -> bool:
    normalized = query.strip().lower()
    return any(pattern in normalized for pattern in _PLATFORM_PATTERNS)


def _is_out_of_scope_structure_query(query: str) -> bool:
    """Return True for explicit protein-structure requests outside LinkedOmics scope."""
    normalized = (query or "").strip()
    return any(pattern.search(normalized) for pattern in _STRUCTURE_OUT_OF_SCOPE_PATTERNS)


def _infer_tool_scope(query: str, active_gene: Optional[str] = None) -> str:
    """Choose a conservative tool subset for obvious query types."""
    normalized = re.sub(r"\s+", " ", query.strip().lower())
    if not normalized:
        return "full"

    if normalized.startswith("show what linkedomicschat can analyze for"):
        return "full"
    if normalized.startswith("answer using general knowledge"):
        return "none"
    if _looks_conversational(normalized) or _looks_platform_question(normalized):
        return "none"

    # If the query spans multiple distinct analysis scopes, give the agent all tools
    # rather than locking into the first matching keyword (e.g. "papers" → literature only).
    _MULTI_SCOPE_SIGNALS = [
        _LITERATURE_KEYWORDS,
        _TARGET_KEYWORDS,
        _TRIAL_KEYWORDS,
        _PATHWAY_KEYWORDS,
        _FUNMAP_KEYWORDS,
        _SURVIVAL_KEYWORDS,
        _EXPRESSION_KEYWORDS,
        _CORRELATION_KEYWORDS,
    ]
    scopes_hit = sum(
        1 for kw_list in _MULTI_SCOPE_SIGNALS
        if any(kw in normalized for kw in kw_list)
    )
    if scopes_hit >= 2:
        return "full"

    if any(keyword in normalized for keyword in _LITERATURE_KEYWORDS):
        return "literature"
    if any(keyword in normalized for keyword in _TARGET_KEYWORDS):
        return "targets"
    if any(keyword in normalized for keyword in _TRIAL_KEYWORDS):
        return "trials"
    if any(keyword in normalized for keyword in _PATHWAY_KEYWORDS):
        return "pathway"
    if any(keyword in normalized for keyword in _FUNMAP_KEYWORDS):
        return "funmap"
    # Generic cross-omics wording like "RNA/RNAseq associated with protein" can
    # be answered from both CPTAC and TCGA, so query both instead of guessing.
    if _has_dual_cis_association_intent(normalized):
        return "cis_dual"
    # Explicit CPTAC cis/correlation requests should use CPTAC cis-correlations,
    # even if broad text like "cis ... across" also matches TCGA cis scan wording.
    if _has_cptac_cis_correlation_intent(normalized):
        return "correlation"
    # Check TCGA cis association before generic correlation and TCGA survival routing.
    if _has_tcga_cis_association_intent(normalized):
        return "tcga_cis"
    if "cptac" not in normalized and any(re.search(keyword, normalized) for keyword in _TCGA_CIS_KEYWORDS):
        return "tcga_cis"
    # TCGA + explicit cross-omics correlation phrasing → cis association (not survival).
    _OMICS_LAYER_WORDS = ("methylation", "scna", "copy number", "rppa", "mirna", "mirnaseq")
    if "tcga" in normalized and "correlat" in normalized and any(w in normalized for w in _OMICS_LAYER_WORDS):
        return "tcga_cis"
    if any(keyword in normalized for keyword in _CORRELATION_KEYWORDS):
        return "correlation"
    has_survival = any(keyword in normalized for keyword in _SURVIVAL_KEYWORDS)
    if any(keyword in normalized for keyword in _EXPRESSION_KEYWORDS) and not has_survival:
        return "expression"
    if has_survival:
        # If the query explicitly mentions TCGA, restrict to tcga_survival_analysis only.
        if "tcga" in normalized:
            return "tcga_survival"
        return "survival"
    if active_gene and any(keyword in normalized for keyword in _SURVIVAL_OMICS_KEYWORDS):
        if "tcga" in normalized:
            return "tcga_survival"
        return "survival"
    # Bare TCGA mention with no survival keyword still uses full survival scope.
    if "tcga" in normalized:
        return "tcga_survival"

    # Bare gene query (≤5 tokens, has a gene symbol, no action verb) → default to expression.
    # This avoids firing all tools for simple "tell me about GENE" or bare gene-name queries.
    _ACTION_VERBS = ("surviv", "correlat", "target", "trial", "pathway", "funmap", "literatur", "paper")
    tokens = normalized.split()
    has_explicit_gene = bool(_extract_query_genes(query)) or bool(active_gene and active_gene != "unknown")
    if (
        len(tokens) <= 5
        and has_explicit_gene
        and not any(v in normalized for v in _ACTION_VERBS)
    ):
        return "expression"

    return "full"


def _infer_survival_route_decision(query: str, initial_scope: str) -> RouteDecision:
    """Choose the specific survival workflow after broad survival routing matched."""
    normalized = re.sub(r"\s+", " ", (query or "").strip().lower())
    cohort_codes = _extract_cancer_codes(query)

    if any(code not in _CPTAC_SURVIVAL_COHORTS for code in cohort_codes):
        return RouteDecision(tool_scope="tcga_survival", workflow="survival_tcga_only")
    if any(marker in normalized for marker in _SURVIVAL_TCGA_ONLY_OMICS):
        return RouteDecision(tool_scope="tcga_survival", workflow="survival_tcga_only")
    if "tcga" in normalized or initial_scope == "tcga_survival":
        return RouteDecision(tool_scope="tcga_survival", workflow="survival_tcga_only")
    if "cptac" in normalized:
        return RouteDecision(tool_scope="survival", workflow="survival_cptac_only")
    return RouteDecision(tool_scope="survival", workflow="survival_dual_dataset")


def _infer_trials_route_decision(query: str) -> RouteDecision:
    """Choose a narrower clinical-trials workflow for explicit genes-vs-pathways requests."""
    normalized = re.sub(r"\s+", " ", (query or "").strip().lower())
    padded = f" {normalized} "

    # Keep study-specific and study-discovery requests on the broader trials workflow.
    if "study" in normalized or "studies" in normalized or re.search(r"\bgse\d+\b", normalized, re.IGNORECASE):
        return RouteDecision(tool_scope="trials", workflow="clinical_trials")

    has_meta_intent = any(keyword in normalized for keyword in _TRIAL_META_INTENT_KEYWORDS)
    has_gene_request = any(keyword in padded for keyword in _TRIAL_META_GENE_KEYWORDS)
    has_pathway_request = any(keyword in normalized for keyword in _TRIAL_META_PATHWAY_KEYWORDS)

    if has_meta_intent and has_gene_request and not has_pathway_request:
        return RouteDecision(tool_scope="trials_genes", workflow="clinical_trials_gene_biomarkers")
    if has_meta_intent and has_pathway_request and not has_gene_request:
        return RouteDecision(tool_scope="trials_pathways", workflow="clinical_trials_pathway_biomarkers")

    return RouteDecision(tool_scope="trials", workflow="clinical_trials")


def _infer_route_decision(query: str, active_gene: Optional[str] = None) -> RouteDecision:
    """Infer a deterministic tool scope plus a more specific workflow label."""
    normalized = re.sub(r"\s+", " ", (query or "").strip().lower())
    if normalized.startswith("answer using general knowledge"):
        return RouteDecision(tool_scope="none", workflow="general_knowledge")
    if normalized.startswith("show what linkedomicschat can analyze for"):
        return RouteDecision(tool_scope="full", workflow="capability_overview")
    if _looks_conversational(query):
        return RouteDecision(tool_scope="none", workflow="direct_response")
    if _looks_platform_question(query):
        return RouteDecision(tool_scope="none", workflow="platform_question")
    if _is_out_of_scope_structure_query(query):
        return RouteDecision(tool_scope="none", workflow="out_of_scope_structure")

    tool_scope = _infer_tool_scope(query, active_gene)
    if tool_scope in {"survival", "tcga_survival"}:
        return _infer_survival_route_decision(query, tool_scope)
    if tool_scope == "trials":
        return _infer_trials_route_decision(query)
    return RouteDecision(
        tool_scope=tool_scope,
        workflow=_DEFAULT_WORKFLOW_BY_SCOPE.get(tool_scope, "broad_full"),
    )


def _make_agent_node(llm_with_tools, system_prompt: str):
    """Return an async agent node function closed over the bound LLM."""
    async def agent_node(state: AgentState) -> Dict[str, Any]:
        # Inject planner's intent/approach as a private note in the system prompt
        plan = state.get("query_plan") or {}
        if plan and not plan.get("needs_clarification") and plan.get("intent"):
            planning_note = (
                "\n\n[PLANNING NOTE — internal context, do not repeat to user]\n"
                f"Intent: {plan['intent']}\n"
                f"Approach: {plan.get('approach', '')}"
            )
            enriched_prompt = system_prompt + planning_note
        else:
            enriched_prompt = system_prompt
        # Prepend system message on every call so it's always in context
        messages = [SystemMessage(content=enriched_prompt)] + state["messages"]
        started = time.perf_counter()
        response = await llm_with_tools.ainvoke(messages)
        latency_ms = int((time.perf_counter() - started) * 1000)

        # Accumulate token usage from this LLM call
        usage = LLMFactory._extract_usage(response, llm_with_tools)
        in_tok = usage.input_tokens
        out_tok = usage.output_tokens
        agent_step = state["steps"] + 1
        tool_calls = [
            _normalize_runtime_tool_name(str(tc.get("name", "")))
            for tc in getattr(response, "tool_calls", []) or []
            if tc.get("name")
        ]
        trace_entry = {
            "node": "agent",
            "step": agent_step,
            "latency_ms": latency_ms,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "tool_calls": tool_calls,
        }
        logger.info(
            "[LangGraph] Agent step %s | latency_ms=%s | input_tokens=%s | output_tokens=%s | tool_calls=%s",
            agent_step,
            latency_ms,
            in_tok,
            out_tok,
            tool_calls or ["final"],
        )

        return {
            "messages": [response],
            "steps": agent_step,
            "input_tokens": state.get("input_tokens", 0) + in_tok,
            "output_tokens": state.get("output_tokens", 0) + out_tok,
            "execution_trace": list(state.get("execution_trace", [])) + [trace_entry],
        }
    return agent_node


def _compact_literature(content: str) -> str:
    """
    Replace full abstracts in literature tool results with 200-char snippets.
    This prevents the LLM from dumping the raw JSON and forces it to summarise.
    """
    try:
        data = json.loads(content)
    except Exception:
        return content

    articles = data.get("articles") if isinstance(data, dict) else None
    if articles is None:
        # Single-article response from get_pubmed_abstract
        if isinstance(data, dict) and "abstract" in data:
            ab = data["abstract"] or ""
            data["abstract"] = ab[:300] + ("…" if len(ab) > 300 else "")
            # Drop doi_url noise — pubmed_url is enough
            data.pop("doi_url", None)
            return json.dumps(data)
        return content

    for a in articles:
        ab = a.get("abstract") or ""
        a["abstract"] = ab[:300] + ("…" if len(ab) > 300 else "")
        a.pop("doi_url", None)  # redundant with pubmed_url

    return json.dumps(data)


def _survival_significance_key(result: Dict[str, Any]) -> float:
    """Sort survival rows by strongest reported significance (lower is better)."""
    for key in ("fdr", "pvalue"):
        value = result.get(key)
        if value is None or value == "":
            continue
        try:
            return abs(float(value))
        except (TypeError, ValueError):
            continue
    return float("inf")


def _compact_tcga_survival(content: str) -> str:
    """
    Reduce TCGA survival payloads before feeding them back to the LLM.

    The raw result is still preserved separately for downstream rendering. Here we
    remove KM sample arrays and, for broader query modes, keep only the most
    informative rows so the second agent turn does not re-ingest massive JSON.
    """
    try:
        data = json.loads(content)
    except Exception:
        return content

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(results, list):
        return content

    mode = int(data.get("mode", 0) or 0)
    compacted = {k: v for k, v in data.items() if k != "results"}

    simplified_results: List[Dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        reduced: Dict[str, Any] = {}
        for key in ("gene", "cohort", "omics", "hr", "pvalue", "fdr", "n"):
            value = item.get(key)
            if value is not None and value != "":
                reduced[key] = value
        if not reduced:
            reduced = {
                key: value
                for key, value in item.items()
                if key != "samples" and not isinstance(value, (list, dict))
            }
        simplified_results.append(reduced)

    sorted_results = sorted(simplified_results, key=_survival_significance_key)
    significant_results = [
        result for result in sorted_results if _survival_significance_key(result) < 0.05
    ]

    if mode in (1, 2):
        compact_results = sorted_results[:10]
    elif mode == 3:
        compact_results = sorted_results[:12]
    elif mode == 4:
        compact_results = (significant_results or sorted_results)[:20]
    else:
        compact_results = sorted_results[:10]

    compacted["results"] = compact_results
    compacted["result_summary"] = {
        "total_results": len(results),
        "returned_results": len(compact_results),
        "significant_results": len(significant_results),
        "samples_omitted": any(isinstance(item, dict) and "samples" in item for item in results),
    }
    compacted["results_truncated"] = len(compact_results) < len(results)
    compacted["tool_message_compacted"] = True
    return json.dumps(compacted)


def _annotate_empty_result(content: str, tool_name: str) -> str:
    """
    If a tool returned no usable data, prepend a clear marker so the LLM
    says "no data available" rather than hallucinating a summary.
    """
    try:
        data = json.loads(content)
    except Exception:
        return content

    if not isinstance(data, dict):
        return content

    # Explicit error or unavailable status
    if data.get("error") or data.get("status") in ("error", "unavailable"):
        bare = tool_name.split("__")[-1]
        marker = f"[NO DATA — {bare} returned no results or an error]"
        return f"{marker}\n{content}"

    # Empty results list / dict
    results = data.get("results") or data.get("articles") or data.get("genes") or data.get("data")
    if results is not None and len(results) == 0:
        bare = tool_name.split("__")[-1]
        marker = f"[NO SIGNIFICANT RESULTS FOUND — {bare} returned an empty dataset]"
        return f"{marker}\n{content}"

    return content


def _compact_tool_message(tool_name: str, content: str) -> str:
    """Shrink tool outputs for the LLM while keeping raw payloads elsewhere."""
    if tool_name in ("literature__search_pubmed", "literature__get_pubmed_abstract"):
        compacted = _compact_literature(content)
    elif tool_name == "linkedomics__tcga_survival_analysis":
        compacted = _compact_tcga_survival(content)
    else:
        compacted = content
    return _annotate_empty_result(compacted, tool_name)


def _make_tool_node(tools: List[BaseTool]):
    """
    Return an async tool node that executes all tool_calls from the last AIMessage,
    collects raw results, and updates tool_results + active_gene in the state.
    """
    tool_map = {t.name: t for t in tools}
    bare_tool_map: Dict[str, List[str]] = {}
    for tool_name in tool_map:
        bare_name = tool_name.split("__")[-1]
        bare_tool_map.setdefault(bare_name, []).append(tool_name)

    def _resolve_tool(tool_name: str) -> tuple[str, Optional[BaseTool]]:
        tool = tool_map.get(tool_name)
        if tool:
            return tool_name, tool

        normalized_name = tool_name.replace("::", "__")
        tool = tool_map.get(normalized_name)
        if tool:
            return normalized_name, tool

        bare_name = normalized_name.split("__")[-1]
        bare_matches = bare_tool_map.get(bare_name, [])
        if len(bare_matches) == 1:
            resolved_name = bare_matches[0]
            logger.info(
                "[LangGraph] Resolved tool alias %r -> %r",
                tool_name,
                resolved_name,
            )
            return resolved_name, tool_map[resolved_name]

        return tool_name, None

    async def tool_node(state: AgentState) -> Dict[str, Any]:
        last_ai: AIMessage = state["messages"][-1]
        tool_messages: List[ToolMessage] = []
        new_results = dict(state.get("tool_results") or {})
        active_gene = state.get("active_gene")
        requested_genes = list(state.get("requested_genes") or [])
        requested_identifiers = list(state.get("requested_identifiers") or [])
        allow_active_gene_reference = bool(state.get("allow_active_gene_reference"))
        tool_scope = state.get("tool_scope", "full")
        call_counts: Dict[str, int] = {}
        for existing_key in new_results:
            base_key, sep, suffix = existing_key.rpartition("#")
            normalized_key = base_key if sep and suffix.isdigit() else existing_key
            next_count = int(suffix) + 1 if sep and suffix.isdigit() else 1
            call_counts[normalized_key] = max(call_counts.get(normalized_key, 0), next_count)
        step_tool_metrics: List[Dict[str, Any]] = []
        started = time.perf_counter()
        single_tool_counts: Dict[str, int] = {}

        for tc in getattr(last_ai, "tool_calls", []) or []:
            single_name = tc.get("name", "").replace("::", "__").rsplit("#", 1)[0]
            if single_name in _AUTO_BATCH_SINGLE_TOOL_MAP:
                single_tool_counts[single_name] = single_tool_counts.get(single_name, 0) + 1

        batch_tools_emitted: set[str] = set()

        for tc in last_ai.tool_calls:
            original_tool_name = tc["name"]
            rewritten_tool_name = original_tool_name.replace("::", "__").rsplit("#", 1)[0]
            args = dict(tc["args"])
            call_id = tc["id"]

            batch_tool_name = _AUTO_BATCH_SINGLE_TOOL_MAP.get(rewritten_tool_name)
            should_batch = bool(
                batch_tool_name
                and len(requested_genes) >= 2
                and (
                    single_tool_counts.get(rewritten_tool_name, 0) >= 2
                    or tool_scope in _AUTO_BATCH_SCOPES
                )
            )

            if should_batch:
                if batch_tool_name in batch_tools_emitted:
                    logger.info(
                        "[LangGraph] Skipping duplicate single-gene tool call %r after batch rewrite",
                        original_tool_name,
                    )
                    continue
                batch_tools_emitted.add(batch_tool_name)
                original_tool_name = batch_tool_name
                args = {"proteins": requested_genes}
                call_id = f"{call_id}-batch"

            validation_error = _validate_tool_identifier_integrity(
                tool_name=original_tool_name,
                args=args,
                requested_identifiers=requested_identifiers,
                active_gene=active_gene,
                allow_active_gene_reference=allow_active_gene_reference,
                tool_results=new_results,
            )

            tool_name, tool = _resolve_tool(original_tool_name)
            if validation_error:
                raw_content = json.dumps({"error": validation_error})
                content = raw_content
                tool_latency_ms = 0
                status = "error"
            elif not tool:
                raw_content = json.dumps({"error": f"Unknown tool: {original_tool_name}"})
                content = raw_content
                tool_latency_ms = 0
                status = "missing"
            else:
                try:
                    tool_started = time.perf_counter()
                    raw = await tool.coroutine(**args)
                    tool_latency_ms = int((time.perf_counter() - tool_started) * 1000)
                    raw_content = json.dumps(raw) if not isinstance(raw, str) else raw
                    content = _compact_tool_message(tool_name, raw_content)
                    status = "ok"
                except Exception as e:
                    logger.error(f"[LangGraph] Tool {tool_name} error: {e}")
                    tool_latency_ms = int((time.perf_counter() - tool_started) * 1000)
                    raw_content = json.dumps({"error": str(e)})
                    content = raw_content
                    status = "error"

            # Track result with unique key (mirrors mcp_orchestrator convention)
            mcp_tool_id = tool_name.replace("__", "::")
            count = call_counts.get(mcp_tool_id, 0)
            unique_key = f"{mcp_tool_id}#{count}"
            call_counts[mcp_tool_id] = count + 1

            # Parse content back to dict for raw_results
            try:
                result_dict = json.loads(raw_content)
            except Exception:
                result_dict = {"raw": raw_content}

            data_status = status if status in {"error", "missing"} else _classify_tool_result_payload(tool_name, result_dict)
            trace_status = data_status if data_status != "error" else "error"

            # Extract gene from args (protein, gene_symbol, gene, or proteins list for batch tools)
            gene_arg = args.get("protein") or args.get("gene_symbol") or args.get("gene")
            proteins_arg = args.get("proteins")  # batch tools use a list
            if gene_arg and isinstance(gene_arg, str) and gene_arg.lower() not in {"it", "its", "it's"}:
                active_gene = gene_arg.upper()
            elif proteins_arg and isinstance(proteins_arg, list) and proteins_arg:
                active_gene = proteins_arg[0].upper()
                gene_arg = None  # keep gene_arg None so renderers detect batch via data structure

            new_results[unique_key] = {
                "_gene": gene_arg,
                "_args": args,
                "_result": result_dict,
                "_data_status": data_status,
            }

            tool_messages.append(
                ToolMessage(content=content, tool_call_id=call_id, name=tool_name)
            )
            step_tool_metrics.append(
                {
                    "tool": mcp_tool_id,
                    "latency_ms": tool_latency_ms,
                    "status": trace_status,
                }
            )
            logger.info(f"[LangGraph] Tool {mcp_tool_id} executed → stored as {unique_key}")

        tool_step = state.get("steps", 0)
        total_latency_ms = int((time.perf_counter() - started) * 1000)
        trace_entry = {
            "node": "tools",
            "step": tool_step,
            "latency_ms": total_latency_ms,
            "tool_calls": step_tool_metrics,
        }
        logger.info(
            "[LangGraph] Tool step %s | latency_ms=%s | tool_calls=%s",
            tool_step,
            total_latency_ms,
            step_tool_metrics,
        )
        return {
            "messages": tool_messages,
            "tool_results": new_results,
            "active_gene": active_gene,
            "execution_trace": list(state.get("execution_trace", [])) + [trace_entry],
        }

    return tool_node


# ─────────────────────────────────────────────────────────────────────────────
# Graph builder
# ─────────────────────────────────────────────────────────────────────────────

# Maps bare tool names → inline source key (used in #source:X hrefs)
_TOOL_SOURCE_KEY: dict = {
    "cancer_gene_expression":      "linkedomics",
    "batch_cancer_gene_expression": "linkedomics",
    "get_cis_correlations":        "linkedomics",
    "batch_get_cis_correlations":  "linkedomics",
    "get_trans_correlations":      "linkedomics",
    "overall_survival_per_cancer": "linkedomics",
    "batch_overall_survival_per_cancer": "linkedomics",
    "tcga_survival_analysis":      "linkedomics",
    "tcga_cis_association_analysis": "linkedomics",
    "clinical_trial_information":       "trials",
    "batch_clinical_trial_information": "trials",
    "get_study_info":                   "trials",
    "gene_set_trial_information":       "trials",
    "filter_clinical_trials":           "trials",
    "meta_analysis_predictive_genes":   "trials",
    "get_study_predictive_genes":           "trials",
    "get_study_predictive_gene_sets":       "trials",
    "meta_analysis_predictive_gene_sets":   "trials",
    "funmap_neighborhood":              "funmap",
    "get_target":                  "targets",
    "batch_get_target":            "targets",
    "search_targets":              "targets",
    "rank_targets":                "targets",
    "webgestalt":                  "webgestalt",
    "search_literature":           "pubmed",
    "pubmed_search":               "pubmed",
    "search_pubmed":               "pubmed",
    "get_cptac_proteomics":        "cptac",
    "get_cptac_transcriptomics":   "cptac",
    "get_cptac_phosphoproteomics": "cptac",
    "get_cptac_clinical":          "cptac",
    "list_cptac_datasets":         "cptac",
}


def _build_tool_source_url(bare_tool_name: str, args: dict) -> Optional[str]:
    """Return a user-facing source URL for inline citations.

    Keep these links on human-readable landing pages. Raw JSON/API endpoints are
    exposed through plot/table downloads where appropriate, and make poor
    citation targets in chat.
    """
    gene = args.get("protein") or args.get("gene_symbol") or args.get("gene")
    gene = str(gene).upper() if gene else None
    linkedomics_home = "https://www.linkedomics.org"
    targets_home = "https://targets.linkedomics.org"
    trials_home = "https://trials.linkedomics.org"
    _TEMPLATES: Dict[str, Any] = {
        "cancer_gene_expression":      lambda _: linkedomics_home,
        "batch_cancer_gene_expression": lambda _: linkedomics_home,
        "get_cis_correlations":        lambda _: linkedomics_home,
        "batch_get_cis_correlations":  lambda _: linkedomics_home,
        "get_trans_correlations":      lambda _: linkedomics_home,
        "overall_survival_per_cancer": lambda _: linkedomics_home,
        "batch_overall_survival_per_cancer": lambda _: linkedomics_home,
        "tcga_survival_analysis":      lambda _: linkedomics_home,
        "tcga_cis_association_analysis": lambda _: linkedomics_home,
        "funmap_neighborhood":         lambda _: "https://funmap.linkedomics.org",
        "get_target":                  lambda g: f"{targets_home}/{g}/" if g else targets_home,
        "batch_get_target":            lambda _: targets_home,
        "search_targets":              lambda _: targets_home,
        "rank_targets":                lambda _: targets_home,
        "clinical_trial_information":       lambda _: trials_home,
        "batch_clinical_trial_information": lambda _: trials_home,
        "filter_clinical_trials":               lambda _: f"{trials_home}/treatment_gene/",
        "meta_analysis_predictive_genes":       lambda _: f"{trials_home}/treatment_gene/",
        "meta_analysis_predictive_gene_sets":   lambda _: f"{trials_home}/treatment_gene_set/",
        "webgestalt":                       lambda _: "https://www.webgestalt.org",
        "search_literature":                lambda _: "https://pubmed.ncbi.nlm.nih.gov",
        "search_pubmed":                    lambda _: "https://pubmed.ncbi.nlm.nih.gov",
    }
    # Tools that need the full args dict rather than the extracted gene string
    _ARGS_TEMPLATES: Dict[str, Any] = {
        "get_study_info":                   lambda a: trials_home,
        "gene_set_trial_information":       lambda a: f"{trials_home}/treatment_gene_set/",
        "get_study_predictive_genes":       lambda a: f"{trials_home}/treatment_gene/",
        "get_study_predictive_gene_sets":   lambda a: f"{trials_home}/treatment_gene_set/",
    }
    if bare_tool_name in _ARGS_TEMPLATES:
        try:
            return _ARGS_TEMPLATES[bare_tool_name](args)
        except Exception:
            return None
    builder = _TEMPLATES.get(bare_tool_name)
    if not builder:
        return None
    try:
        return builder(gene) if gene else builder(None)
    except Exception:
        return None


def _build_tool_sources(raw_results: dict) -> Dict[str, str]:
    """Build a {source_key: user-facing source URL} map from raw tool results."""
    sources: Dict[str, str] = {}
    for key, value in raw_results.items():
        if not isinstance(value, dict):
            continue
        args = value.get("_args", {})
        bare = key.replace("::", "__").split("__")[-1].rsplit("#", 1)[0]
        source_key = _TOOL_SOURCE_KEY.get(bare)
        if not source_key or source_key in sources:
            continue
        url = _build_tool_source_url(bare, args)
        if url:
            sources[source_key] = url
    return sources


def _strip_invalid_source_citations(text: str, tools_used: list) -> str:
    """Remove [Label](#source:key) markers for sources not backed by an actual tool call."""
    import re
    valid_keys: set = set()
    for tool in tools_used:
        # Normalise "linkedomics::cancer_gene_expression#0" → "cancer_gene_expression"
        bare = tool.replace("::", "__").split("__")[-1].rsplit("#", 1)[0]
        key = _TOOL_SOURCE_KEY.get(tool) or _TOOL_SOURCE_KEY.get(bare)
        if key:
            valid_keys.add(key)
    return re.sub(
        r'\[([^\]]+)\]\(#source:([^)]+)\)',
        lambda m: m.group(0) if m.group(2) in valid_keys else "",
        text,
    )


def _inlineize_source_blockquotes(text: str) -> str:
    """Convert formatter-emitted `> **Source:** ...` blockquotes into inline citations."""
    lines = text.splitlines()
    output: List[str] = []

    for line in lines:
        match = re.match(r'^\s*>\s*\*\*Source:\*\*\s*(.+?)\s*$', line)
        if not match:
            output.append(line)
            continue

        source_markup = match.group(1).strip()
        attached = False
        for idx in range(len(output) - 1, -1, -1):
            stripped = output[idx].strip()
            if not stripped:
                continue
            if stripped.startswith(("#", ">", "|", "[PLOT:", "[NETWORK:", "[TABLE:", "```")):
                continue
            if "#source:" not in stripped:
                output[idx] = output[idx].rstrip() + f" {source_markup}"
            attached = True
            break
        if not attached:
            output.append(source_markup)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()


def _ensure_inline_source_citations(text: str, tools_used: list) -> str:
    """Add deterministic inline source citations when a tool-backed response lacks them."""
    if not text.strip() or "#source:" in text:
        return text

    source_keys: List[str] = []
    for tool in tools_used:
        key = _TOOL_SOURCE_KEY.get(_bare_tool_name(tool))
        if key and key not in source_keys:
            source_keys.append(key)
    if not source_keys:
        return text

    citation_markup = " ".join(f"[Source](#source:{key})" for key in source_keys)
    lines = text.splitlines()
    paragraph_last_idx: Optional[int] = None

    for idx, line in enumerate(lines + [""]):
        stripped = line.strip()
        if not stripped:
            if paragraph_last_idx is not None and "#source:" not in lines[paragraph_last_idx]:
                lines[paragraph_last_idx] = lines[paragraph_last_idx].rstrip() + f" {citation_markup}"
            paragraph_last_idx = None
            continue
        if stripped.startswith(("```", "|", "[PLOT:", "[NETWORK:", "[TABLE:", ">")):
            continue
        if stripped.startswith("#"):
            continue
        paragraph_last_idx = idx

    return "\n".join(lines)


def _normalize_duplicate_markdown_headings(text: str) -> str:
    """Collapse headings like `### ### Results` to `### Results`."""
    if not isinstance(text, str) or not text:
        return text
    return re.sub(r"(?m)^(#{1,6})[ \t]+(?:#{1,6}[ \t]+)+", r"\1 ", text)


def _safe_float(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def _format_pvalue(value: Any) -> str:
    numeric = _safe_float(value)
    if numeric is None:
        text = str(value or "").strip()
        return text or "NA"
    if numeric == 0:
        return "0"
    return f"{numeric:.2e}"


def _webgestalt_top_terms(raw_results: Dict[str, Any], limit: int = 4) -> List[Dict[str, Any]]:
    """Extract top WebGestalt enrichment rows from raw tool results."""
    terms: List[Dict[str, Any]] = []
    for key, wrapped in (raw_results or {}).items():
        if _bare_tool_name(key) != "webgestalt" or not isinstance(wrapped, dict):
            continue
        payload = wrapped.get("_result", wrapped)
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        if not isinstance(payload, dict) or payload.get("error"):
            continue
        rows = payload.get("data")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                terms.append(row)

    def _rank(row: Dict[str, Any]) -> float:
        fdr = _safe_float(row.get("FDR"))
        pval = _safe_float(row.get("pValue"))
        return fdr if fdr is not None else (pval if pval is not None else 1.0)

    return sorted(terms, key=_rank)[:limit]


def _text_covers_webgestalt_terms(text: str, terms: List[Dict[str, Any]]) -> bool:
    """Return True when the text already names WebGestalt or the top terms."""
    normalized = (text or "").lower()
    if "webgestalt" in normalized:
        return True
    if not terms:
        return False
    matches = 0
    for row in terms[:3]:
        description = str(row.get("description") or row.get("geneSet") or "").strip().lower()
        if description and description in normalized:
            matches += 1
    return matches >= min(2, len(terms[:3]))


def _ordered_unique_strings(values: Sequence[Any]) -> List[str]:
    """Return non-empty strings in first-seen order."""
    unique_values: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        unique_values.append(text)
        seen.add(text)
    return unique_values


def _build_webgestalt_enrichment_sentence(raw_results: Dict[str, Any], limit: int = 4) -> str:
    """Build a deterministic one-sentence summary for WebGestalt results."""
    terms = _webgestalt_top_terms(raw_results, limit=limit)
    if not terms:
        return ""
    term_bits = []
    for row in terms:
        description = str(row.get("description") or row.get("geneSet") or "enriched term").strip()
        term_bits.append(f"**{description}** (FDR={_format_pvalue(row.get('FDR'))})")
    return (
        "WebGestalt pathway enrichment highlights "
        + ", ".join(term_bits[:-1])
        + (f", and {term_bits[-1]}" if len(term_bits) > 1 else term_bits[0])
        + " [Source](#source:webgestalt)."
    )


def _ensure_webgestalt_enrichment_summary(text: str, raw_results: Dict[str, Any], *, section: bool = False) -> str:
    """Ensure responses explicitly summarize WebGestalt enrichment results."""
    terms = _webgestalt_top_terms(raw_results)
    if not terms or _text_covers_webgestalt_terms(text, terms):
        return text
    sentence = _build_webgestalt_enrichment_sentence(raw_results)
    if not sentence:
        return text
    addition = f"### Pathway Enrichment\n{sentence}" if section else sentence
    stripped = (text or "").strip()
    return f"{stripped}\n\n{addition}" if stripped else addition


def _cptac_survival_payloads(raw_results: Dict[str, Any]) -> List[tuple[str, Dict[str, Any]]]:
    """Return wrapped CPTAC overall-survival payloads as (gene, payload)."""
    payloads: List[tuple[str, Dict[str, Any]]] = []
    for key, wrapped in (raw_results or {}).items():
        if _bare_tool_name(key) != "overall_survival_per_cancer" or not isinstance(wrapped, dict):
            continue
        payload = wrapped.get("_result", wrapped)
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        if not isinstance(payload, dict) or payload.get("error"):
            continue
        gene = str(wrapped.get("_gene") or (wrapped.get("_args") or {}).get("protein") or "").upper()
        payloads.append((gene, payload))
    return payloads


def _classify_cptac_survival_value(value: Any) -> tuple[str, Optional[str]]:
    """Convert a CPTAC survival cell into a summary label and optional p-value."""
    text = str(value or "").strip()
    normalized = text.lower()
    p_match = re.search(r"p\s*=\s*([0-9.eE+-]+)", text)
    p_text = _format_pvalue(p_match.group(1)) if p_match else None
    if not text or "data unavailable" in normalized or normalized in {"n/a", "na", "-"}:
        return "unavailable", None
    if "no significant" in normalized or "not significant" in normalized:
        return "no significant association", p_text
    if "higher expression associated with poor survival" in normalized:
        return "higher expression associated with poor survival", p_text
    if "lower expression associated with poor survival" in normalized:
        return "lower expression associated with poor survival", p_text
    return text, p_text


def _format_cptac_layer_status(layer: str, value: Any) -> str:
    label, p_text = _classify_cptac_survival_value(value)
    if label == "unavailable":
        return f"{layer} **unavailable**"
    if label == "no significant association":
        return f"{layer} **no significant association**" + (f" (p={p_text})" if p_text else "")
    return f"{layer} **{label}**" + (f" (p={p_text})" if p_text else "")


def _build_cptac_survival_sentence(raw_results: Dict[str, Any], query: str) -> str:
    """Build a deterministic CPTAC survival note when LLM summary omits it."""
    payloads = _cptac_survival_payloads(raw_results)
    if not payloads:
        return ""

    requested_cohorts = [code for code in _extract_cancer_codes(query) if code in _CPTAC_SURVIVAL_COHORTS]
    gene, payload = payloads[0]
    gene_label = f"**{gene}**" if gene else "the queried gene"

    def _layer_value(layer_key: str, cohort: str) -> Any:
        layer = payload.get(layer_key) if isinstance(payload.get(layer_key), dict) else {}
        data = layer.get("data") if isinstance(layer.get("data"), dict) else {}
        return data.get(cohort)

    if requested_cohorts:
        cohort_bits: List[str] = []
        for cohort in requested_cohorts[:3]:
            rna_text = _format_cptac_layer_status("RNA", _layer_value("RNA_level", cohort))
            protein_text = _format_cptac_layer_status("protein", _layer_value("protein_level", cohort))
            cohort_bits.append(f"in **{cohort}**, {rna_text} and {protein_text}")
        return (
            f"CPTAC survival was also queried for {gene_label}: "
            + "; ".join(cohort_bits)
            + "."
        )

    notable: List[str] = []
    for cohort in sorted(_CPTAC_SURVIVAL_COHORTS):
        for layer_label, layer_key in (("RNA", "RNA_level"), ("protein", "protein_level")):
            value = _layer_value(layer_key, cohort)
            label, p_text = _classify_cptac_survival_value(value)
            if label not in {"unavailable", "no significant association"}:
                notable.append(
                    f"{layer_label} in **{cohort}**: **{label}**"
                    + (f" (p={p_text})" if p_text else "")
                )
    if notable:
        return (
            f"CPTAC survival was also queried for {gene_label}; notable CPTAC signals were "
            + ", ".join(notable[:3])
            + "."
        )
    return (
        f"CPTAC survival was also queried for {gene_label} across available cohorts, "
        "but no significant RNA/protein survival association was returned."
    )


def _build_cptac_batch_sentence(payload: Any, *, analysis: str) -> str:
    """Build a compact note for batch CPTAC expression/survival tools."""
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not data:
        return f"CPTAC {analysis} was also queried in batch mode, but no per-gene results were returned."
    genes = [str(g).upper() for g in data.keys() if str(g).strip()]
    significant = 0
    unavailable_only = 0
    for gene_payload in data.values():
        if not isinstance(gene_payload, dict):
            continue
        values: List[str] = []
        for layer_key in ("RNA_level", "protein_level"):
            layer = gene_payload.get(layer_key) if isinstance(gene_payload.get(layer_key), dict) else {}
            layer_data = layer.get("data") if isinstance(layer.get("data"), dict) else {}
            values.extend(str(v or "") for v in layer_data.values())
        normalized_values = [value.lower() for value in values if value.strip()]
        if any("significantly" in value and "no significant" not in value for value in normalized_values):
            significant += 1
        elif normalized_values and all("data unavailable" in value for value in normalized_values):
            unavailable_only += 1
    gene_text = ", ".join(f"**{gene}**" for gene in genes[:4])
    if len(genes) > 4:
        gene_text += f", and **{len(genes) - 4}** more"
    if significant:
        return f"CPTAC {analysis} was also queried for {gene_text}; **{significant}** gene(s) had at least one significant RNA/protein result."
    if unavailable_only == len(data):
        return f"CPTAC {analysis} was also queried for {gene_text}, but all returned entries were unavailable."
    return f"CPTAC {analysis} was also queried for {gene_text}, with no significant RNA/protein result returned in the compact summary."


def _unwrap_tool_payload(wrapped: Any) -> tuple[str, Dict[str, Any], Any]:
    """Return (gene, args, payload) for a wrapped tool result."""
    if not isinstance(wrapped, dict):
        return "", {}, wrapped
    gene = str(wrapped.get("_gene") or "").strip().upper()
    args = wrapped.get("_args") if isinstance(wrapped.get("_args"), dict) else {}
    payload = wrapped.get("_result") if "_result" in wrapped else wrapped
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            pass
    if not gene:
        gene = str(args.get("protein") or args.get("gene") or args.get("gene_symbol") or "").strip().upper()
    return gene, args, payload


def _text_mentions_tool_category(text: str, category: str) -> bool:
    """Return True when the prose already appears to cover a tool category."""
    normalized = (text or "").lower()
    if category == "cptac_expression":
        return "cptac" in normalized and any(
            marker in normalized for marker in ("expression", "tumor vs normal", "tumor-vs-normal", "tumor-normal")
        )
    if category == "cptac_survival":
        return "cptac" in normalized and any(
            marker in normalized for marker in ("survival", "overall survival", "prognos")
        )
    if category == "tcga_survival":
        return "tcga" in normalized and any(
            marker in normalized for marker in ("survival", "overall survival", "kaplan", "hazard ratio", " hr ")
        )
    if category == "cptac_cis":
        return "cptac" in normalized and any(
            marker in normalized for marker in ("cis", "correl", "association")
        )
    if category == "tcga_cis":
        return "tcga" in normalized and any(
            marker in normalized for marker in ("cis", "correl", "association", "rnaseq", "rppa", "methylation", "scna")
        )
    marker_sets: Dict[str, tuple[str, ...]] = {
        "webgestalt": ("webgestalt", "pathway enrichment", "go enrichment"),
        "funmap": ("funmap", "functional neighborhood", "co-functional", "cofunctional"),
        "targets": ("drug target", "target status", "linkedOmics targets".lower(), "target index"),
        "trials": ("clinical trial", "clinical trials", "treatment response", "drug response"),
        "literature": ("pubmed", "literature", "papers", "publications"),
        "cptac": ("cptac",),
        "tcga": ("tcga",),
    }
    return any(marker in normalized for marker in marker_sets.get(category, (category,)))


def _first_payload_for_tool(raw_results: Dict[str, Any], bare_tool: str) -> tuple[str, Dict[str, Any], Any] | None:
    """Return the first wrapped payload matching a bare tool name."""
    for key, wrapped in (raw_results or {}).items():
        if _bare_tool_name(key) == bare_tool:
            return _unwrap_tool_payload(wrapped)
    return None


def _build_cptac_expression_sentence(raw_results: Dict[str, Any], query: str) -> str:
    """Build a deterministic CPTAC expression note when that tool is omitted."""
    first = _first_payload_for_tool(raw_results, "cancer_gene_expression")
    if not first:
        return ""
    gene, _, payload = first
    if not isinstance(payload, dict) or payload.get("error"):
        return ""

    requested_cohorts = [code for code in _extract_cancer_codes(query) if code in _CPTAC_SURVIVAL_COHORTS]
    gene_label = f"**{gene}**" if gene else "the queried gene"

    def _layer_value(layer_key: str, cohort: str) -> Any:
        layer = payload.get(layer_key) if isinstance(payload.get(layer_key), dict) else {}
        data = layer.get("data") if isinstance(layer.get("data"), dict) else {}
        return data.get(cohort)

    def _format_expression_layer(layer: str, value: Any) -> str:
        text = str(value or "").strip()
        normalized = text.lower()
        p_match = re.search(r"p\s*=\s*([0-9.eE+-]+)", text)
        p_text = _format_pvalue(p_match.group(1)) if p_match else None
        if not text or "data unavailable" in normalized:
            return f"{layer} **unavailable**"
        if "no significant" in normalized:
            return f"{layer} **no significant tumor-normal difference**" + (f" (p={p_text})" if p_text else "")
        if "higher expressed" in normalized or "higher expression" in normalized:
            return f"{layer} **higher in tumor**" + (f" (p={p_text})" if p_text else "")
        if "lower expressed" in normalized or "lower expression" in normalized:
            return f"{layer} **lower in tumor**" + (f" (p={p_text})" if p_text else "")
        return f"{layer} **{text}**"

    if requested_cohorts:
        cohort_bits = []
        for cohort in requested_cohorts[:3]:
            rna_text = _format_expression_layer("RNA", _layer_value("RNA_level", cohort))
            protein_text = _format_expression_layer("protein", _layer_value("protein_level", cohort))
            cohort_bits.append(f"in **{cohort}**, {rna_text} and {protein_text}")
        return (
            f"CPTAC tumor-normal expression was also queried for {gene_label}: "
            + "; ".join(cohort_bits)
            + "."
        )

    notable: List[str] = []
    for cohort in sorted(_CPTAC_SURVIVAL_COHORTS):
        for layer_label, layer_key in (("RNA", "RNA_level"), ("protein", "protein_level")):
            text = str(_layer_value(layer_key, cohort) or "")
            normalized = text.lower()
            if "significantly" in normalized and "no significant" not in normalized:
                notable.append(f"{layer_label} in **{cohort}**: **{text}**")
    if notable:
        return (
            f"CPTAC tumor-normal expression was also queried for {gene_label}; notable signals were "
            + ", ".join(notable[:3])
            + "."
        )
    return (
        f"CPTAC tumor-normal expression was also queried for {gene_label}, "
        "but no significant RNA/protein tumor-normal differences were returned."
    )


def _build_tcga_survival_coverage_sentence(gene: str, payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    gene_label = f"**{(gene or query.get('gene') or '').upper()}**" if (gene or query.get("gene")) else "the queried gene"
    cohort = str(query.get("cohort") or "").upper()
    cohort_text = f" in **{cohort}**" if cohort else ""
    if payload.get("status") == "error":
        return f"TCGA survival was also queried for {gene_label}{cohort_text}, but the tool returned an error: {payload.get('message') or payload.get('error') or 'unknown error'}."
    if not results:
        return f"TCGA survival was also queried for {gene_label}{cohort_text}, but no survival rows were returned."
    significant = [
        row for row in results
        if _safe_float(row.get("fdr") if row.get("fdr") is not None else row.get("pvalue")) is not None
        and (_safe_float(row.get("fdr") if row.get("fdr") is not None else row.get("pvalue")) or 1.0) < 0.05
    ]
    if significant:
        first = significant[0]
        omics = first.get("omics") or query.get("omics") or "omics"
        pval = _format_pvalue(first.get("fdr") if first.get("fdr") is not None else first.get("pvalue"))
        hr = _safe_float(first.get("hr"))
        hr_text = f", HR=**{hr:.4f}**" if hr is not None else ""
        return f"TCGA survival was also queried for {gene_label}{cohort_text}; **{len(significant)} of {len(results)}** result(s) were significant, led by **{omics}** (p={pval}{hr_text})."
    return f"TCGA survival was also queried for {gene_label}{cohort_text}; **{len(results)}** result(s) were returned, with no significant association at p<**0.05**."


def _build_tcga_cis_coverage_sentence(gene: str, payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    gene_label = f"**{(gene or query.get('gene') or '').upper()}**" if (gene or query.get("gene")) else "the queried gene"
    cohort = str(query.get("cohort") or "").upper()
    pair = " vs. ".join(
        str(query.get(k) or "").strip()
        for k in ("source_omics", "target_omics")
        if query.get(k)
    )
    context = f" for {gene_label}" + (f" in **{cohort}**" if cohort else "") + (f" ({pair})" if pair else "")
    if payload.get("status") == "error":
        return f"TCGA cis-association was also queried{context}, but the tool returned an error: {payload.get('message') or payload.get('error') or 'unknown error'}."
    if not results:
        return f"TCGA cis-association was also queried{context}, but no association rows were returned."
    first = results[0]
    corr = _safe_float(first.get("correlation") or first.get("corr") or first.get("cor"))
    pval = _format_pvalue(first.get("fdr") if first.get("fdr") is not None else first.get("pvalue"))
    corr_text = f" with correlation **{corr:.3f}**" if corr is not None else ""
    return f"TCGA cis-association was also queried{context} and returned **{len(results)}** result(s){corr_text} (p={pval})."


def _count_nested_records(value: Any) -> int:
    """Best-effort count of list-like records inside a payload."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        count = 0
        for nested in value.values():
            count += _count_nested_records(nested)
        return count
    return 0


def _build_generic_tool_coverage_note(key: str, wrapped: Any, query: str, raw_results: Dict[str, Any]) -> tuple[str, str] | None:
    """Return (category, markdown bullet) for a tool result, or None for utility tools."""
    bare = _bare_tool_name(key)
    gene, args, payload = _unwrap_tool_payload(wrapped)
    status = (
        wrapped.get("_data_status") if isinstance(wrapped, dict) else None
    ) or _classify_tool_result_payload(key, payload)

    if bare == "resolve_gene_identifier":
        return None

    if bare == "overall_survival_per_cancer":
        sentence = _build_cptac_survival_sentence(raw_results, query)
        return ("cptac_survival", sentence) if sentence else None
    if bare == "batch_overall_survival_per_cancer":
        sentence = _build_cptac_batch_sentence(payload, analysis="survival")
        return ("cptac_survival", sentence) if sentence else None
    if bare == "cancer_gene_expression":
        sentence = _build_cptac_expression_sentence(raw_results, query)
        return ("cptac_expression", sentence) if sentence else None
    if bare == "batch_cancer_gene_expression":
        sentence = _build_cptac_batch_sentence(payload, analysis="tumor-normal expression")
        return ("cptac_expression", sentence) if sentence else None
    if bare == "tcga_survival_analysis":
        sentence = _build_tcga_survival_coverage_sentence(gene, payload)
        return ("tcga_survival", sentence) if sentence else None
    if bare == "tcga_cis_association_analysis":
        sentence = _build_tcga_cis_coverage_sentence(gene, payload)
        return ("tcga_cis", sentence) if sentence else None
    if bare in {"get_cis_correlations", "batch_get_cis_correlations"}:
        record_count = _count_nested_records(payload.get("data") if isinstance(payload, dict) else payload)
        gene_label = f" for **{gene}**" if gene else ""
        if status == "error" and isinstance(payload, dict):
            return ("cptac_cis", f"CPTAC cis-correlations were also queried{gene_label}, but the tool returned an error: {payload.get('message') or payload.get('error') or 'unknown error'}.")
        if record_count:
            return ("cptac_cis", f"CPTAC cis-correlations were also queried{gene_label} and returned **{record_count}** correlation row(s).")
        return ("cptac_cis", f"CPTAC cis-correlations were also queried{gene_label}, but no correlation rows were returned.")
    if bare == "webgestalt":
        rows = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(rows, list) and rows:
            sentence = _build_webgestalt_enrichment_sentence({key: wrapped})
            return ("webgestalt", sentence) if sentence else None
        return ("webgestalt", "WebGestalt enrichment was also run, but no enriched terms were returned.")
    if bare == "funmap_neighborhood":
        if isinstance(payload, dict):
            count = len(payload.get("neighborhood") or payload.get("nodes") or [])
            gene_label = f" for **{gene}**" if gene else ""
            if count:
                return ("funmap", f"FunMap was also queried{gene_label} and returned **{count}** functional neighbor(s).")
        return ("funmap", f"FunMap was also queried{f' for **{gene}**' if gene else ''}, but no functional neighbors were returned.")
    if bare in {"get_target", "batch_get_target", "search_targets", "rank_targets"}:
        gene_label = f" for **{gene}**" if gene else ""
        if status == "ok":
            return ("targets", f"LinkedOmics Targets was also queried{gene_label} and returned target-index data.")
        return ("targets", f"LinkedOmics Targets was also queried{gene_label}, but no target-index data was returned.")
    if bare in {
        "clinical_trial_information", "batch_clinical_trial_information", "gene_set_trial_information",
        "get_study_info", "filter_clinical_trials", "meta_analysis_predictive_genes",
        "meta_analysis_predictive_gene_sets", "get_study_predictive_genes",
        "get_study_predictive_gene_sets",
    }:
        record_count = _count_nested_records(payload)
        if status == "ok" and record_count:
            return ("trials", f"LinkedOmics Trials was also queried and returned **{record_count}** treatment-response record(s).")
        return ("trials", "LinkedOmics Trials was also queried, but no matching treatment-response records were returned.")
    if bare in {"search_pubmed", "pubmed_search", "search_literature"}:
        record_count = _count_nested_records(payload)
        if record_count:
            return ("literature", f"PubMed literature search was also run and returned **{record_count}** record(s).")
        return ("literature", "PubMed literature search was also run, but no publication records were returned.")

    return None


def _ensure_tool_result_coverage_summary(
    text: str,
    raw_results: Dict[str, Any],
    query: str,
    *,
    section: bool = False,
) -> str:
    """Append compact notes for called analysis tools omitted from the summary."""
    if not raw_results:
        return text

    notes_by_category: Dict[str, str] = {}
    for key, wrapped in raw_results.items():
        built = _build_generic_tool_coverage_note(key, wrapped, query, raw_results)
        if not built:
            continue
        category, sentence = built
        if not sentence or category in notes_by_category:
            continue
        if _text_mentions_tool_category(text, category):
            continue
        notes_by_category[category] = sentence

    if not notes_by_category:
        return text

    notes = list(notes_by_category.values())
    if section:
        addition = "### Additional Tool Results\n" + "\n".join(f"- {note}" for note in notes)
    else:
        addition = "**Additional tool results:**\n" + "\n".join(f"- {note}" for note in notes)
    stripped = (text or "").strip()
    return f"{stripped}\n\n{addition}" if stripped else addition


_VAGUE_ANALYSIS_RE = re.compile(
    r"\b(analyz|study|investigat|explor|summar|overview|tell me about|what can you tell|show me everything)",
    re.IGNORECASE,
)
_SPECIFIC_ANALYSIS_KEYWORDS = (
    "surviv", "express", "correlat", "target", "trial", "pathway",
    "funmap", "literatur", "tumor vs normal", "prognos", "methyl", "copy number",
)


def _is_vague_analysis_query(query: str, requested_genes: List[str]) -> bool:
    """Return True if the query is a vague 'analyze/study GENE' with no specific analysis type."""
    if not requested_genes:
        return False
    normalized = query.strip().lower()
    if len(normalized.split()) > 8:
        return False
    if not _VAGUE_ANALYSIS_RE.search(normalized):
        return False
    return not any(kw in normalized for kw in _SPECIFIC_ANALYSIS_KEYWORDS)


_CORRELATION_DISAMBIGUATORS = (
    "cis", "tcga", "cptac", "methyl", "copy number", "scna", "mirna", "mirnaseq",
    "rna", "rnaseq", "mrna", "protein", "rppa", "surviv", "trial", "drug",
    "target", "funmap", "network", "interaction", "pathway",
)


def _is_bare_gene_context_query(
    query: str,
    requested_genes: List[str],
    requested_identifiers: List[str],
    active_gene: Optional[str] = None,
) -> bool:
    """Return True for bare or context-only gene prompts that need clarification."""
    normalized = re.sub(r"\s+", " ", (query or "").strip().lower())
    if not normalized or _looks_conversational(query) or _looks_platform_question(query):
        return False
    if any(kw in normalized for kw in _SPECIFIC_ANALYSIS_KEYWORDS):
        return False

    tokens = normalized.split()
    has_explicit_gene = bool(requested_genes or requested_identifiers)
    has_context_gene_ref = bool(active_gene and active_gene != "unknown" and _query_uses_active_gene_reference(query))

    if len(tokens) <= 3 and has_explicit_gene:
        return True
    if len(tokens) <= 5 and has_context_gene_ref:
        return True
    return False


def _is_ambiguous_correlation_query(
    query: str,
    requested_genes: List[str],
    requested_identifiers: List[str],
    active_gene: Optional[str] = None,
) -> bool:
    """Return True for generic correlation requests that need disambiguation."""
    normalized = re.sub(r"\s+", " ", (query or "").strip().lower())
    if "correlat" not in normalized:
        return False

    has_gene_context = bool(requested_genes or requested_identifiers)
    if not has_gene_context and not (active_gene and active_gene != "unknown" and _query_uses_active_gene_reference(query)):
        return False

    return not any(marker in normalized for marker in _CORRELATION_DISAMBIGUATORS)


def _is_ambiguous_cis_dataset_query(
    query: str,
    requested_genes: List[str],
    requested_identifiers: List[str],
    active_gene: Optional[str] = None,
) -> bool:
    """Return True when a cross-omics cis query should query both CPTAC and TCGA."""
    normalized = re.sub(r"\s+", " ", (query or "").strip().lower())
    has_gene_context = bool(requested_genes or requested_identifiers)
    if not has_gene_context and not (active_gene and active_gene != "unknown" and _query_uses_active_gene_reference(query)):
        return False
    return _has_dual_cis_association_intent(normalized)


def _should_use_planner_for_query(
    query: str,
    requested_genes: List[str],
    requested_identifiers: List[str],
    active_gene: Optional[str] = None,
) -> bool:
    """
    Limit planner usage to ambiguity/clarification cases.

    Explicit scientific requests should stay on the deterministic routing path.
    """
    return (
        _is_vague_analysis_query(query, requested_genes)
        or _is_bare_gene_context_query(query, requested_genes, requested_identifiers, active_gene)
        or _is_ambiguous_correlation_query(query, requested_genes, requested_identifiers, active_gene)
    )


def _build_clarification_response(gene: str, session_id: str, query: str) -> Dict[str, Any]:
    """Return a pre-built clarification payload for vague analysis queries."""
    return {
        "success": True,
        "message": f"What would you like to know about **{gene}**?",
        "summary": f"What would you like to know about **{gene}**?",
        "clarification_options": [
            "Expression across cancers",
            "Survival analysis",
            "Drug targets",
            "Clinical trials",
            "Pathway enrichment",
            "Correlation analysis",
        ],
        "tool_sources": {},
        "visualizations": [],
        "session_id": session_id,
        "query": query,
        "confidence": "clarification",
        "_input_tokens": 0,
        "_output_tokens": 0,
    }


def _extract_pending_offer_from_text(text: Any) -> Optional[str]:
    """Extract a follow-up offer sentence and convert it into a reusable query."""
    if not isinstance(text, str) or not text.strip():
        return None
    matches = list(_PENDING_OFFER_RE.finditer(text.strip()))
    if not matches:
        return None
    offer = re.sub(r"\s+", " ", matches[-1].group(1)).strip().rstrip(".?!")
    if not offer:
        return None
    return offer[:1].upper() + offer[1:]


def _extract_pending_offer_from_response(response: Dict[str, Any]) -> Optional[str]:
    """Prefer the summary offer, then fall back to the full message."""
    if not isinstance(response, dict):
        return None
    return (
        _extract_pending_offer_from_text(response.get("summary"))
        or _extract_pending_offer_from_text(response.get("message"))
    )


def _parse_clarification_options(text: str) -> list:
    """Extract quick-reply options from **Options:** `A` · `B` · `C` format."""
    import re
    match = re.search(r'\*\*Options:\*\*\s*(.+)', text)
    if not match:
        return []
    return re.findall(r'`([^`]+)`', match.group(1))


def _strip_options_line(text: str) -> str:
    """Remove the **Options:** line from text — it's rendered as pills in the UI."""
    import re
    return re.sub(r'\n?\*\*Options:\*\*\s*.+', '', text).strip()


def _last_substantive_user_query(session: Dict[str, Any]) -> str:
    """Return the most recent non-shortcut user query from session history."""
    for item in reversed(session.get("history", [])):
        query = str((item or {}).get("query") or "").strip()
        if not query:
            continue
        normalized = query.casefold()
        if normalized.startswith("answer using general knowledge"):
            continue
        if normalized.startswith("show what linkedomicschat can analyze for"):
            continue
        return query
    return ""


_AFFIRMATIVE_OFFER_PHRASES = {
    "yes",
    "yes please",
    "yeah",
    "yeah please",
    "yep",
    "yep please",
    "yup",
    "sure",
    "sure thing",
    "ok",
    "okay",
    "ok please",
    "okay please",
    "alright",
    "all right",
    "absolutely",
    "definitely",
    "of course",
    "certainly",
    "do that",
    "do it",
    "please do",
    "go ahead",
    "please go ahead",
    "proceed",
    "please proceed",
    "sounds good",
    "sounds great",
    "that sounds good",
    "that sounds great",
    "works for me",
    "lets do it",
    "let's do it",
    "lets go ahead",
    "let's go ahead",
    "can you do that",
    "could you do that",
    "would you do that",
}

_AFFIRMATIVE_PREFIX_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|ok|okay|alright|all right|absolutely|definitely|of course|certainly)"
    r"(?: please)?(?:,?\s+(?:go ahead|do that|do it|proceed|please do|please proceed))?$",
    re.IGNORECASE,
)
_AFFIRMATIVE_IMPERATIVE_RE = re.compile(
    r"^(?:please\s+)?(?:go ahead|do that|do it|proceed|please do|please proceed|lets do it|let's do it|lets go ahead|let's go ahead)$",
    re.IGNORECASE,
)


def _looks_like_affirmative_offer_reply(normalized_query: str) -> bool:
    """Return True for short, acknowledgment-style acceptances of the pending offer."""
    if not normalized_query:
        return False
    if len(normalized_query.split()) > 8:
        return False
    if normalized_query in _AFFIRMATIVE_OFFER_PHRASES:
        return True
    return bool(
        _AFFIRMATIVE_PREFIX_RE.fullmatch(normalized_query)
        or _AFFIRMATIVE_IMPERATIVE_RE.fullmatch(normalized_query)
    )


def _expand_contextual_shortcuts(query: str, session: Dict[str, Any]) -> str:
    """Expand bare quick-reply shortcuts into context-aware prompts for the LLM."""
    stripped = (query or "").strip()
    normalized = re.sub(r"\s+", " ", stripped.casefold()).strip(" ?!.,")
    context = session.get("context") or {}
    pending_offer = str(context.get("pending_offer") or "").strip()

    if normalized == "answer using general knowledge":
        previous_query = _last_substantive_user_query(session)
        if previous_query:
            return (
                "Answer using general knowledge about the user's previous question: "
                f"{previous_query}"
            )

    if pending_offer and _looks_like_affirmative_offer_reply(normalized):
        return pending_offer

    return stripped


# ─────────────────────────────────────────────────────────────────────────────
# Query Planner
# ─────────────────────────────────────────────────────────────────────────────

_AVAILABLE_ANALYSES = (
    "Expression across cancers · Survival analysis · Drug targets · Clinical trials · "
    "Pathway enrichment · Correlation analysis · FunMap interactions · Literature search"
)

_VALID_TOOL_SCOPES = (
    "none", "expression", "survival", "tcga_survival", "targets", "trials",
    "literature", "funmap", "tcga_cis", "cis_dual", "correlation", "pathway", "full",
)

_PLANNER_PROMPT = """\
You are the planning layer for LinkedOmicsChat, a cancer multi-omics research assistant.

Before the analyst answers, analyze the user query and decide the best approach.

Available analyses: {available_analyses}
Active gene: {active_gene}

Recent conversation context:
{history}

Current query: {query}

Decide ALL of the following:

1. Does this query need clarification before answering?
   Set needs_clarification=true ONLY for bare gene/protein names with no analysis specified \
(e.g. "TP53", "analyze BRCA1", "tell me about MYC", "what about EGFR").
   Set needs_clarification=false for: specific analysis requests, follow-up questions, \
conversational questions, platform/capability questions, queries that mention a specific analysis type.
   If true: write a short clarification_question and list 2–5 relevant clarification_options.

2. State the user's actual intent in one sentence (intent field).

3. Suggest the analyst's approach in 1–2 sentences (approach field).

4. Choose the best tool_scope from this exact list:
   "none"        → conversational, meta, or platform questions (no data tools needed)
   "literature"  → mechanism, pathway biology, background, paper search
   "expression"  → gene expression levels across cancer types
   "survival"    → overall survival / prognosis analysis
   "tcga_survival" → TCGA-specific survival analysis
   "correlation" → gene-gene or omics correlations
   "pathway"     → pathway enrichment analysis
   "targets"     → drug targets
   "trials"      → clinical trials
   "funmap"      → protein interaction network (FunMap)
   "tcga_cis"    → TCGA cis-association analysis
   "cis_dual"    → both CPTAC cis-correlations and TCGA cis-association
   "full"        → multiple analysis types or unclear — give the agent all tools

Be conservative — most queries should proceed directly (needs_clarification=false).
"""


class QueryPlan(BaseModel):
    needs_clarification: bool
    clarification_question: str = ""
    clarification_options: List[str] = []
    intent: str
    approach: str
    tool_scope: str = "full"  # one of the _TOOL_SCOPE_MAP keys or "full"


async def _call_planner(llm, *, query: str, history_str: str, active_gene: str) -> QueryPlan:
    """
    Run the planner LLM call and return a QueryPlan.

    Runs BEFORE the graph is built so the recommended tool_scope can be used
    to filter which tools the agent receives.
    """
    fallback = QueryPlan(
        needs_clarification=False,
        intent=query,
        approach="Proceed with the query as stated.",
        tool_scope="full",
    )
    try:
        planner_llm = llm.with_structured_output(QueryPlan)
    except Exception:
        return fallback

    prompt_text = _PLANNER_PROMPT.format(
        available_analyses=_AVAILABLE_ANALYSES,
        active_gene=active_gene,
        history=history_str,
        query=query,
    )
    started = time.perf_counter()
    try:
        plan: QueryPlan = await planner_llm.ainvoke([
            SystemMessage(content="You are a query planning assistant. Output valid JSON only."),
            HumanMessage(content=prompt_text),
        ])
        # Validate tool_scope against known values
        if plan.tool_scope not in _VALID_TOOL_SCOPES:
            plan.tool_scope = "full"
    except Exception as e:
        logger.warning("[LangGraph] Planner failed (%s), proceeding without plan", e)
        return fallback

    latency_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "[LangGraph] Planner | latency_ms=%s | needs_clarification=%s | tool_scope=%s | intent=%s",
        latency_ms,
        plan.needs_clarification,
        plan.tool_scope,
        plan.intent[:80],
    )
    return plan


def build_graph(llm, tools: List[BaseTool], system_prompt: str):
    """
    Build and compile the LangGraph StateGraph.

    Graph structure:
        agent ──(has tool_calls)──▶ tools ──▶ agent ──▶ END
    """
    llm_with_tools = llm.bind_tools(tools) if tools else llm

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", _make_agent_node(llm_with_tools, system_prompt))
    workflow.add_node("tools", _make_tool_node(tools))
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
    workflow.add_edge("tools", "agent")

    return workflow.compile()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_content(content: Any) -> str:
    """
    Normalize an AIMessage.content value to a plain string.

    Gemini (and some other providers) return content as a list of parts, e.g.:
        [{'type': 'text', 'text': 'Hello'}, ...]
    LangChain also sometimes wraps text in a plain list of strings.
    This mirrors the logic in LLMFactory.invoke_async.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
            else:
                parts.append(str(part))
        return "".join(parts)
    return str(content)


def _iter_stream_chunks(text: str, target_size: int = 72) -> List[str]:
    """
    Split text into readable chunks for SSE fallback streaming.

    LangGraph token streaming is not always available when the agent node wraps
    the model in a custom async function. In that case we still emit small text
    chunks so the UI renders incrementally instead of all at once.
    """
    if not text:
        return []

    chunks: List[str] = []
    current = ""
    for token in re.findall(r"\S+\s*|\n", text):
        if token == "\n":
            if current:
                chunks.append(current)
                current = ""
            chunks.append("\n")
            continue
        if current and len(current) + len(token) > target_size:
            chunks.append(current)
            current = token
        else:
            current += token
    if current:
        chunks.append(current)
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# LangGraphOrchestrator (public API matches MCPOrchestrator)
# ─────────────────────────────────────────────────────────────────────────────

class LangGraphOrchestrator:
    """
    Drop-in replacement for MCPOrchestrator that uses LangGraph for
    chained / parallel / conditional tool execution.

    Public interface is identical to MCPOrchestrator so no API or frontend
    changes are required.
    """

    # Reuse the biological guidelines from the original orchestrator
    BIO_GUIDELINES = """\
### BIOLOGICAL REASONING GUIDELINES:
1. **Statistical Significance**: p-value < 0.05 is typically significant.
2. **Omics Vocabulary**:
   - 'mRNA/RNA' = gene expression levels.
   - 'Protein' = proteomic abundance.
   - 'Log Ratio / Fold Change' = relative expression (positive = up, negative = down).
3. **Cross-Omics Synthesis**: If you have expression + survival data, explain how they relate.
4. **Context Matters**: LinkedOmics data comes from specific CPTAC/TCGA cohorts. Mention cancer type when known.
"""

    SYSTEM_PROMPT_TEMPLATE = """\
You are a Senior Multi-Omics Bioinformatics Analyst for LinkedOmicsChat.

{bio_guidelines}

{data_access}

PLANNING RULES:
- Use tools only when specific research data is needed. For greetings, general chat, and platform questions, reply directly.
- Prefer the smallest tool set that fully answers the request:
  * Single-aspect query (survival, expression, enrichment, etc.) -> 1–2 relevant tools only.
  * Explicit comparison -> parallel calls of the same analysis across the requested genes.
  * Broad profile / overview explicitly requested -> up to 4 distinct tools.
- Do not proactively chain extra analyses. Only call additional tools when the user explicitly asks.
- For survival questions: call only survival tools (`overall_survival_per_cancer`, `tcga_survival_analysis`). Do NOT call `cancer_gene_expression` or `clinical_trial_information` unless the user explicitly asks about expression levels or drugs/treatments.
- For expression questions: call only expression tools (`cancer_gene_expression`). Do NOT call survival or clinical trial tools unless explicitly asked.
- Clinical trial tools are only relevant when the user asks about drugs, treatments, or clinical trials — never call them for survival or expression queries. Use the right tool for the question:
  - Single gene → which drugs/studies predict response: `clinical_trial_information`
  - Multiple genes → use `batch_clinical_trial_information` instead of calling `clinical_trial_information` repeatedly
  - Pathway/gene set → drug sensitivity/resistance: `gene_set_trial_information`
  - Study details/abstract: `get_study_info`
  - Which studies exist for a drug/cancer: `filter_clinical_trials`
  - Top gene biomarkers across studies (treatment-centric): `meta_analysis_predictive_genes`
  - Top pathway biomarkers across studies (treatment-centric): `meta_analysis_predictive_gene_sets`
  - Gene rankings within one specific study: `get_study_predictive_genes`
  - Pathway rankings within one specific study: `get_study_predictive_gene_sets`
  - Workflow — study-specific analysis: call `filter_clinical_trials` first to find matching studies, then `get_study_predictive_genes` or `get_study_predictive_gene_sets` on a specific study ID, then optionally `get_study_info` for context
- For cross-study biomarker discovery, match the modality exactly:
  - If the user asks for genes / biomarkers / markers, call only `meta_analysis_predictive_genes`.
  - If the user asks for pathways / gene sets / signatures, call only `meta_analysis_predictive_gene_sets`.
  - Do NOT call both unless the user explicitly asks for both genes and pathways/signatures.
- IMPORTANT — drug name resolution: when the user specifies a broad or nested treatment class, use the `treatment_category` parameter (not `drugs`) in `filter_clinical_trials`, `meta_analysis_predictive_genes`, and `meta_analysis_predictive_gene_sets`. The tool accepts convenience aliases and ClinicalOmicsDB treatment-tree labels, then expands them to the correct treatment labels automatically.
  - "chemotherapy" / "chemo" / "cytotoxic" → treatment_category="Chemotherapy"
  - "targeted therapy" / "targeted" → treatment_category="Targeted Therapy"
  - "immune checkpoint inhibitor" / "checkpoint inhibitor" / "immune checkpoint" / "ICI" / "immunotherapy" / "PD-1" / "PD-L1" / "CTLA-4" → treatment_category="Immune Checkpoint Inhibitor"
  - "combination" / "combo" / "combination therapy" → treatment_category="Combinations"
  - Nested treatment classes should stay specific: "antibody" → `treatment_category="Antibody"`, "small molecule inhibitor" → `treatment_category="Small Molecule Inhibitor"`, "HER2 inhibitor" → `treatment_category="HER2 Inhibitor"`
  - Specific drug name (e.g. "paclitaxel", "nivolumab") → use `drugs=["paclitaxel"]` as before
- For `rank_targets`, separate tier eligibility from ranking intent:
  - "approved", "validated", "clinically established", "most druggable" → `ranking_mode="established"`
  - "exploratory", "discovery-stage", "frontier", "most novel" → `ranking_mode="exploratory"`
  - "not approved" / "non-approved" usually means restrict eligibility to `tiers=["T3","T4","T5"]`, but if the user does not state a readiness preference then keep `ranking_mode="balanced"`
- If the user refers to "it", "this", or "the gene", resolve that to the active gene: '{active_gene}'.
- For platform questions like "what can you analyze?", "what cancer types are available?", or "what data do you have access to?", answer from the AVAILABLE DATA section and do not treat the active gene as the target.

DATA GROUNDING:
- For claims about expression, survival, drug targets, pathway enrichment, literature, or available data coverage, use tools.
- If the needed capability is unavailable, say so plainly. Do not answer that data question from training knowledge.
- If any tool result contains an "error" key, stop and report the error instead of continuing.
- If a tool result begins with [NO DATA] or [NO SIGNIFICANT RESULTS FOUND], explicitly tell the user that no data was available for that query — do NOT summarize, extrapolate, or fill the gap with training knowledge.
- When results are sparse or limited, say so clearly before interpreting them. Uncertainty is more useful than false confidence.

GENE IDENTIFIERS:
- Accepted inputs may be HGNC symbols, Ensembl gene IDs (ENSG...), or UniProt accessions.
- Never silently replace one gene / protein / identifier with a different symbol based on memory or guesswork. Use the exact user-provided token unless `resolve_gene_identifier` returns a validated `hgnc_symbol` for that exact token.
- If the user provides Ensembl or UniProt identifiers, call `resolve_gene_identifier` first and use the returned `hgnc_symbol`.
- For multi-gene comparisons, resolve every gene before running analysis. If any gene fails, stop and report all failures; do not return partial comparisons.
- If an identifier does not plausibly match HGNC / ENSG / UniProt format, ask the user to double-check it instead of calling tools.
- Treat ambiguous English words like impact, set, met, or clock as genes only when they are clearly used as literal gene symbols.

SURVIVAL ROUTING:
CPTAC cohorts (RNA + protein only): BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC.

Decision rules — apply the first matching rule:
1. User specifies a cohort NOT in the CPTAC list above (e.g. ACC, KIPAN, MESO, SKCM) → call `tcga_survival_analysis` only.
2. User specifies an omics type not in CPTAC (methylation, miRNA, SCNA, copy number) → call `tcga_survival_analysis` only.
3. User explicitly restricts to TCGA → call `tcga_survival_analysis` only.
4. User explicitly restricts to CPTAC → call `overall_survival_per_cancer` only.
5. No cohort specified, or cohort is in the CPTAC list, and omics is RNA/protein/unspecified → call BOTH `tcga_survival_analysis` AND `overall_survival_per_cancer` (they cover complementary datasets and together give a complete picture).

If neither dataset is likely to have data (e.g. unsupported omics + unsupported cohort), call the closest matching tool and let it return the error naturally.

`tcga_survival_analysis` requires at least TWO of (cohort, gene, omics). Always specify `omics` when doing a pan-cancer query (no cohort): infer from the query ("expression" or unspecified → "RNAseq", "protein" → "RPPA", "methylation" → "Methylation", "miRNA" → "miRNASeq", "copy number" → "SCNA").

CIS ASSOCIATION ROUTING:
- Treat RNA, mRNA, RNAseq, and RNA-seq as equivalent RNA-layer wording.
- If the user asks a generic within-gene cross-omics association/correlation question without saying TCGA or CPTAC (e.g. "Is EGFR RNAseq associated with protein in LUAD?"), call BOTH `get_cis_correlations` and `tcga_cis_association_analysis`. Do not ask the user to choose a dataset.
- Use `get_cis_correlations` when the user explicitly asks for CPTAC cis-correlations. That tool is CPTAC-only.
- Use `tcga_cis_association_analysis` when the user asks about within-gene cross-omics correlations in TCGA data — e.g. "Is ESR1 methylation associated with its RNA expression?", "Which genes show SCNA-to-RNAseq cis associations in BRCA?", "How does TP53 copy number correlate with protein across TCGA cohorts?"
- Parameter inference for TCGA: map "methylation" → source_omics="Methylation", "RNA/expression/RNAseq" → "RNAseq", "protein/RPPA" → "RPPA", "copy number/SCNA" → "SCNA".
- Mode is inferred automatically from the parameters provided — omit parameters not mentioned by the user.

SPECIAL MODES:
- If the user's message starts with "Answer using general knowledge", answer from training knowledge and put `[GENERAL_KNOWLEDGE]` on the first line.
- If the user's message starts with "Show what LinkedOmicsChat can analyze for", call `cancer_gene_expression`, `overall_survival_per_cancer`, `tcga_survival_analysis`, and `clinical_trial_information`.
- If the question is outside current tool scope, explain that briefly, state the supported scope, and then offer:
  **Options:** `Answer using general knowledge` · `Show what LinkedOmicsChat can analyze for [GENE]`
  Omit the second option if no gene is mentioned.
CLARIFICATION — ask BEFORE running tools when the query is under-specified:
- A gene name alone with no analysis type (e.g. "what about TP53?" / "look at BRCA1" / "can you analyze EGFR?") → respond: "What would you like to know about **GENE**?" then add **Options:** listing only the analysis types that are meaningful for this gene given the available tools. Choose from: `Expression across cancers` · `Survival analysis` · `Drug targets` · `Clinical trials` · `Pathway enrichment` · `Correlation analysis` · `FunMap interactions` · `Literature search`. Omit any option that clearly does not apply.
- An analysis type missing a critical parameter (e.g. "compare expression" without specifying genes or cancers) → ask for the missing piece. Use **Options:** if the missing piece is a finite closed choice.
- A request that maps to two or more very different workflows (e.g. "how does MYC correlate?" could mean cis-omics, FunMap network, or clinical-trial correlation) → ask which type using **Options:**.
- Do NOT ask for clarification when the query is already specific — e.g. "survival analysis for TP53 in BRCA", "drug targets for EGFR", "expression of MYC across cancers".
- **Options:** format: `**Options:** \`Choice A\` · \`Choice B\` · \`Choice C\``

RESPONSE STYLE:
- Be concise, analytical, and easy to follow.
- Never dump raw JSON, Python objects, or raw tool output.
- Close with **one** brief, specific follow-up suggestion grounded in what was actually found — but ONLY when all of the following are true: (1) the response contains specific positive findings from tool results (expression values, survival stats, drug rankings, enriched pathways, etc.); (2) you are not asking the user a clarification question; (3) the result is not `[NO DATA]`, `[NO SIGNIFICANT RESULTS FOUND]`, or an error; (4) the response is not conversational or general-knowledge mode. When any of those conditions fail, omit the suggestion entirely. When included, weave it in as a natural closing sentence — no generic headers like "You might also want to ask:".
- INLINE CITATIONS: After each factual claim that comes from a tool result, add a short inline source tag using this exact format: [Source](#source:KEY) where KEY is one of: linkedomics, pubmed, funmap, webgestalt, cptac, targets, trials. Use the key that matches the tool you called. For example: "TP53 is significantly overexpressed in LUAD [Source](#source:linkedomics)." Only cite sources that were actually queried — do not cite sources for general knowledge statements.

MARKDOWN FORMATTING — always apply these rules:
- Use **bold** for gene names, cancer types, key statistics (p-values, correlation coefficients, hazard ratios), and notable findings.
- Use bullet lists (`-`) for enumerating multiple genes, associations, or data points — never run them together in prose.
- Use `###` headers to separate distinct sections when the response covers more than one topic or data category (e.g., `### Expression`, `### Survival`, `### Key Associations`).
- For tool-based responses: open with one sentence framing what was found, then present findings as structured bullets with bold stats, then close with 1–2 sentences of biological interpretation.
- For conversational or general-knowledge responses: use short paragraphs with **bold** for key terms; use bullet lists when listing features, functions, or comparisons.
- Numbers and statistical values should always appear in context: prefer "**FDR < 1e-285**" over bare numbers.
- Never write a wall of plain prose when bullet points would be clearer.
"""

    DIRECT_RESPONSE_PROMPT_TEMPLATE = """\
You are LinkedOmicsChat, a concise multi-omics research assistant.

{data_access}

DIRECT RESPONSE RULES:
- Do not call tools in this mode.
- For greetings and brief chat, respond naturally and briefly.
- For platform questions like "what can you analyze?" or "what data do you have?", answer from the AVAILABLE DATA section only.
- If the user's message starts with "Answer using general knowledge", answer from training knowledge and put `[GENERAL_KNOWLEDGE]` on the first line.
- If the question is outside current tool scope, say that briefly, state the supported scope, and then offer:
  **Options:** `Answer using general knowledge` · `Show what LinkedOmicsChat can analyze for [GENE]`
  Omit the second option if no gene is mentioned.
- If the request depends on recent conversation context, use the recent history provided.
- Do NOT invent unsupported datasets or capabilities.
- For conversational or platform-explanation responses, do not add follow-up suggestions.
"""

    def __init__(self, parent_orchestrator=None):
        """
        Args:
            parent_orchestrator: The MCPOrchestrator instance that created this object.
                When provided, sessions and DB methods are shared so chat history
                persists and the API endpoints continue to work unchanged.
        """
        self._parent = parent_orchestrator

        if parent_orchestrator is not None:
            # Share the parent's MCP aggregator, LLM, and sessions dict
            self.mcp_aggregator = parent_orchestrator.mcp_aggregator
            self.llm = parent_orchestrator.llm
            self.sessions = parent_orchestrator.sessions  # shared reference!
        else:
            # Standalone mode (testing / direct instantiation)
            self.mcp_aggregator = MCPAggregator()
            self.llm = LLMFactory.create_llm(
                model=settings.DEFAULT_LLM_MODEL,
                temperature=0.3,
            )
            self.sessions: Dict[str, Any] = {}

        self._graph = None
        self._tools: List[BaseTool] = []
        self._tool_scope: str = "full"
        self._workflow: str = "broad_full"

    async def initialize(self):
        """Initialize MCP connections (if standalone) and build the LangGraph."""
        logger.info("[LangGraph] Initializing LangGraphOrchestrator...")
        if self._parent is None:
            # Only init aggregator in standalone mode; parent already did it.
            await self.mcp_aggregator.initialize()
        self._rebuild_graph()
        logger.info(f"[LangGraph] Ready with {len(self._tools)} tools.")

    def _build_data_access_section(self, *, compact: bool = False) -> str:
        """Generate a data access section based on which MCP servers are actually enabled."""
        available = self.mcp_aggregator.list_tools()
        servers = set(info["server"] for info in available.values())

        lines = ["AVAILABLE DATA (only what the enabled tools can access):"]
        if "linkedomics" in servers:
            if compact:
                lines.append(
                    "- LinkedOmics / CPTAC: tumor-vs-normal expression, cis-correlations, FunMap, targets, trials, and CPTAC survival for BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, and UCEC."
                )
                lines.append(
                    "- LinkedOmics / TCGA: multi-omics survival analysis across 35+ cohorts via `tcga_survival_analysis`; "
                    "multi-omics cis associations (Methylation, RNAseq, RPPA, SCNA, miRNA) across 35+ cohorts via `tcga_cis_association_analysis`."
                )
            else:
                lines.append(
                    "- LinkedOmics / CPTAC: gene expression (RNA + protein), cis-correlations, FunMap networks, "
                    "drug targets, clinical trials, and CPTAC survival via `overall_survival_per_cancer` "
                    "for BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, and UCEC."
                )
                lines.append(
                    "- LinkedOmics / TCGA: survival associations across 35+ cohorts and multiple omics layers "
                    "via `tcga_survival_analysis`."
                )
                lines.append(
                    "- LinkedOmics / TCGA cis associations: within-gene cross-omics correlations "
                    "(Methylation ↔ RNAseq, SCNA ↔ RNAseq, SCNA ↔ RPPA, etc.) across 35+ TCGA cohorts "
                    "via `tcga_cis_association_analysis`. Supports single-gene/cohort/pair lookups, "
                    "all-omics-pairs for a gene, pan-cancer comparisons, and genome-wide scans."
                )
        if "gene_utils" in servers:
            lines.append(
                "- Gene utilities: resolve HGNC / Ensembl / UniProt gene identifiers."
            )
        if "literature" in servers:
            lines.append(
                "- PubMed: live literature search and abstract retrieval."
            )
        if not servers:
            lines.append("- (No data tools are currently enabled.)")
        if compact:
            lines.append(
                "\nOUT OF SCOPE UNLESS A TOOL EXPLICITLY SUPPORTS IT:\n"
                "- Raw mutation tables, single-cell data, protein 3D structure, variant pathogenicity, GWAS, immune infiltration, sequence analysis, and other unlisted sources."
            )
        else:
            lines.append(
                "\nOUT OF SCOPE UNLESS A TOOL EXPLICITLY SUPPORTS IT:\n"
                "- Raw GDC mutation counts, raw TCGA genomics tables, single-cell data, protein 3D structure, "
                "variant pathogenicity, GWAS, immune infiltration, sequence analysis, and other unlisted data sources."
            )
        return "\n".join(lines)

    def _build_scope_constraint(self, tool_scope: str) -> str:
        """Return an explicit tool restriction line for non-full scopes."""
        if tool_scope in ("full", "none"):
            return ""
        allowed = _TOOL_SCOPE_MAP.get(tool_scope, ())
        if not allowed:
            return ""
        bare_names = [t.split("::")[-1] for t in allowed if "::" in t]
        if not bare_names:
            return ""
        return (
            f"\nTOOL RESTRICTION: For this query you are bound exclusively to: "
            f"{', '.join(f'`{n}`' for n in bare_names)}. "
            "Do NOT call any tool outside this list — if the query would require a different tool, "
            "explain what you cannot answer in this context and offer `Answer using general knowledge` "
            "or redirect the user.\n"
        )

    def _build_workflow_constraint(
        self,
        workflow: str,
        *,
        force_identifier_resolution: bool = False,
        pre_resolved_identifiers: Optional[Dict[str, str]] = None,
    ) -> str:
        """Return workflow-specific guidance layered on top of tool_scope."""
        workflow_notes = {
            "platform_question": (
                "WORKFLOW ROUTING: This is a platform/capability question. Answer from the AVAILABLE DATA section only.\n"
            ),
            "out_of_scope_structure": (
                "WORKFLOW ROUTING: The user is asking about protein 3D structure, which is outside LinkedOmicsChat's "
                "supported data scope. Do not call tools. Briefly explain that 3D structure is unsupported here, "
                "then redirect to supported analyses or offer `Answer using general knowledge`.\n"
            ),
            "capability_overview": (
                "WORKFLOW ROUTING: This is a capability-overview turn. Follow the special mode for "
                "`Show what LinkedOmicsChat can analyze for ...`.\n"
            ),
            "expression_analysis": (
                "WORKFLOW ROUTING: This is an expression-analysis query. Stay within the expression tools.\n"
            ),
            "survival_dual_dataset": (
                "WORKFLOW ROUTING: This is a dual-dataset survival query. Use BOTH "
                "`overall_survival_per_cancer` and `tcga_survival_analysis` unless one is clearly inapplicable "
                "or errors.\n"
            ),
            "survival_tcga_only": (
                "WORKFLOW ROUTING: This is a TCGA-only survival query. Use `tcga_survival_analysis` and do NOT "
                "call `overall_survival_per_cancer`.\n"
            ),
            "survival_cptac_only": (
                "WORKFLOW ROUTING: This is a CPTAC-only survival query. Use `overall_survival_per_cancer` and do NOT "
                "call `tcga_survival_analysis`.\n"
            ),
            "target_lookup": (
                "WORKFLOW ROUTING: This query is about targetability. Prefer `get_target`, `batch_get_target`, "
                "`search_targets`, or `rank_targets`. Do not drift into PubMed unless the user explicitly asks "
                "for literature.\n"
            ),
            "clinical_trials": (
                "WORKFLOW ROUTING: This query is about treatment response or clinical studies. Stay within the "
                "clinical-trial tool family.\n"
            ),
            "clinical_trials_gene_biomarkers": (
                "WORKFLOW ROUTING: This is a cross-study gene-biomarker query. Use "
                "`meta_analysis_predictive_genes` only; do NOT add pathway/gene-set tools unless the user "
                "explicitly asks for pathways or signatures too.\n"
            ),
            "clinical_trials_pathway_biomarkers": (
                "WORKFLOW ROUTING: This is a cross-study pathway/signature biomarker query. Use "
                "`meta_analysis_predictive_gene_sets` only; do NOT add gene-level biomarker tools unless the user "
                "explicitly asks for genes too.\n"
            ),
            "literature_search": (
                "WORKFLOW ROUTING: This is a literature query. Stay within the PubMed tools.\n"
            ),
            "funmap_neighborhood": (
                "WORKFLOW ROUTING: This query maps to FunMap. Use `funmap_neighborhood` for a pan-cancer "
                "co-functional neighborhood. Do not describe it as a co-expression network.\n"
            ),
            "cptac_cis_correlation": (
                "WORKFLOW ROUTING: This query maps to CPTAC cis-correlation. Use `get_cis_correlations` or "
                "`batch_get_cis_correlations`, not `tcga_cis_association_analysis`.\n"
            ),
            "tcga_cis_association": (
                "WORKFLOW ROUTING: This query maps to TCGA cis-association. Use `tcga_cis_association_analysis`, "
                "not `get_cis_correlations`.\n"
            ),
            "cis_dual_dataset": (
                "WORKFLOW ROUTING: This generic cross-omics cis query can be answered from both CPTAC and TCGA. "
                "Use BOTH `get_cis_correlations` (or `batch_get_cis_correlations` for multiple genes) and "
                "`tcga_cis_association_analysis`; do not ask the user to choose a dataset. Treat RNA, mRNA, "
                "RNAseq, and RNA-seq as the same RNA layer. For TCGA, map generic protein to `RPPA`; for CPTAC, "
                "map generic protein to `Protein`.\n"
            ),
            "pathway_enrichment": (
                "WORKFLOW ROUTING: This is a pathway/enrichment query. Use `webgestalt` only when the user explicitly "
                "asks for pathway or gene-set analysis.\n"
            ),
        }
        note = workflow_notes.get(workflow, "")
        if pre_resolved_identifiers:
            pairs = ", ".join(
                f"{identifier} -> {symbol}"
                for identifier, symbol in pre_resolved_identifiers.items()
                if identifier and symbol
            )
            if pairs:
                note += (
                    "PRE-RESOLVED IDENTIFIERS: "
                    f"{pairs}. Use the resolved `hgnc_symbol` values in downstream tools.\n"
                )
        if force_identifier_resolution:
            note += (
                "IDENTIFIER WORKFLOW: The user provided an Ensembl or UniProt identifier. Your first tool call must "
                "be `resolve_gene_identifier`. Do NOT call downstream analysis tools until you have the returned "
                "`hgnc_symbol`.\n"
            )
        return f"\n{note}" if note else ""

    def _build_system_prompt(
        self,
        active_gene: str = "unknown",
        *,
        tool_scope: str = "full",
        workflow: str = "broad_full",
        multi_gene: bool = False,
        active_cancer_type: Optional[str] = None,
        session_goal: Optional[str] = None,
        force_identifier_resolution: bool = False,
        pre_resolved_identifiers: Optional[Dict[str, str]] = None,
    ) -> str:
        """Build a scope-aware system prompt."""
        workflow_constraint = self._build_workflow_constraint(
            workflow,
            force_identifier_resolution=force_identifier_resolution,
            pre_resolved_identifiers=pre_resolved_identifiers,
        )
        if tool_scope == "none":
            return self.DIRECT_RESPONSE_PROMPT_TEMPLATE.format(
                data_access=self._build_data_access_section(compact=True),
            ) + workflow_constraint
        scope_constraint = self._build_scope_constraint(tool_scope)
        base = self.SYSTEM_PROMPT_TEMPLATE.format(
            bio_guidelines=self.BIO_GUIDELINES,
            active_gene=active_gene or "unknown",
            data_access=self._build_data_access_section(),
        )
        prompt = base + scope_constraint + workflow_constraint
        if session_goal or active_cancer_type:
            parts: List[str] = []
            if session_goal:
                parts.append(f"research goal: {session_goal}")
            if active_cancer_type:
                parts.append(f"cancer type: {active_cancer_type}")
            prompt += f"\nSESSION CONTEXT: {'; '.join(parts)}. Keep this context in mind across all turns.\n"
        if active_cancer_type:
            prompt += (
                f"Prefer tools and cohorts relevant to {active_cancer_type} when applicable.\n"
            )
        if multi_gene:
            prompt += (
                "\nMULTI-GENE QUERY DETECTED: The user is asking about multiple genes. "
                "Use batch variants of tools (e.g. `batch_cancer_gene_expression`, "
                "`batch_overall_survival_per_cancer`, `batch_clinical_trial_information`, "
                "`batch_get_target`, `batch_get_cis_correlations`) instead of calling "
                "single-gene tools repeatedly. A single batch call is preferred over "
                "multiple sequential single-gene calls.\n"
            )
        return prompt

    def _rebuild_graph(
        self,
        active_gene: str = "unknown",
        *,
        tool_scope: str = "full",
        workflow: str = "broad_full",
        multi_gene: bool = False,
        active_cancer_type: Optional[str] = None,
        session_goal: Optional[str] = None,
        force_identifier_resolution: bool = False,
        pre_resolved_identifiers: Optional[Dict[str, str]] = None,
    ):
        """(Re)build the compiled LangGraph with current MCP tools."""
        if not self.llm:
            logger.warning("[LangGraph] No LLM available, graph not built.")
            return
        scoped_tool_ids = _TOOL_SCOPE_MAP.get(tool_scope)
        self._tool_scope = tool_scope
        self._workflow = workflow
        self._tools = build_mcp_tools(self.mcp_aggregator, allowed_tool_ids=scoped_tool_ids)
        system_prompt = self._build_system_prompt(
            active_gene=active_gene, tool_scope=tool_scope, workflow=workflow, multi_gene=multi_gene,
            active_cancer_type=active_cancer_type, session_goal=session_goal,
            force_identifier_resolution=force_identifier_resolution,
            pre_resolved_identifiers=pre_resolved_identifiers,
        )
        self._graph = build_graph(self.llm, self._tools, system_prompt)
        logger.info(
            "[LangGraph] Rebuilt graph | scope=%s | workflow=%s | multi_gene=%s | bound_tools=%s",
            tool_scope,
            workflow,
            multi_gene,
            [tool.name.replace("__", "::") for tool in self._tools],
        )

    async def cleanup(self):
        """Cleanup MCP connections (only in standalone mode)."""
        if self._parent is None:
            await self.mcp_aggregator.cleanup()
            self.sessions.clear()
        logger.info("[LangGraph] Cleaned up.")

    # ── Session helpers ───────────────────────────────────────────────────────

    async def _get_session(self, session_id: Optional[str], user_id: str, client_ip: Optional[str] = None) -> Dict[str, Any]:
        """Get or create a session, delegating to parent's DB-backed method when available."""
        if self._parent is not None:
            return await self._parent._get_or_create_session(session_id, user_id, client_ip=client_ip)
        # Standalone fallback: in-memory only
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        import uuid
        sid = session_id or str(uuid.uuid4())
        session = {"id": sid, "user_id": user_id, "history": [], "context": {}}
        self.sessions[sid] = session
        return session

    def _build_clarification_response(
        self, query: str, session: Dict[str, Any], plan: "QueryPlan"
    ) -> Dict[str, Any]:
        """Build a standard response payload for a planner clarification request."""
        return {
            "success": True,
            "message": plan.clarification_question or "Could you clarify what you'd like to know?",
            "summary": "",
            "query": query,
            "confidence": "clarification",
            "no_collapse": True,
            "is_general_knowledge": False,
            "tools_used": [],
            "raw_results": {},
            "visualizations": [],
            "analyses": [],
            "suggestions": [],
            "datasets": [],
            "papers": [],
            "clarification_options": plan.clarification_options or [],
            "tool_sources": {},
            "execution_trace": [],
            "_input_tokens": 0,
            "_output_tokens": 0,
            "_model": settings.DEFAULT_LLM_MODEL,
        }

    @staticmethod
    def _build_rich_turn_summary(
        query: str,
        response: Dict[str, Any],
        session_context: Dict[str, Any],
    ) -> str:
        """
        Build a structured turn summary that preserves key context for history injection.

        Captures gene, cancer type, analysis performed, and key finding so that
        follow-up queries have meaningful context rather than 1-2 truncated sentences.
        """
        lines: List[str] = []

        gene = session_context.get("active_gene")
        if gene and gene != "unknown":
            lines.append(f"Gene: {gene}")

        cancer = session_context.get("active_cancer_type")
        if cancer:
            lines.append(f"Cancer: {cancer}")

        tools_used = response.get("tools_used") or []
        if tools_used:
            categories = sorted({t.split("::")[0].replace("_", " ") for t in tools_used})
            lines.append(f"Analysis: {', '.join(categories)}")

        content = (response.get("summary") or response.get("message") or "").strip()
        if content:
            clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", content)
            clean = re.sub(r"\[Source\]\([^)]+\)", "", clean).strip()
            sentences = re.split(r"(?<=[.!?])\s+", clean)
            first = sentences[0][:300] if sentences else clean[:300]
            lines.append(f"Finding: {first}")

        if lines:
            return "\n".join(lines)
        # Fallback
        return LangGraphOrchestrator._extract_turn_summary(content or query)

    async def _save_query(self, session: Dict[str, Any], query: str, response: Dict[str, Any]) -> Optional[int]:
        """Persist query+response to DB (via parent) or fall back to memory."""
        turn_summary = self._build_rich_turn_summary(query, response, session.get("context", {}))
        if self._parent is not None:
            return await self._parent._update_session(
                session, query, {**response, "turn_summary": turn_summary}
            )
        else:
            session.setdefault("history", []).append({
                "query": query,
                "response": response,
                "turn_summary": turn_summary,
                "timestamp": time.time(),
            })
            return None

    @staticmethod
    def _extract_turn_summary(content: str, max_chars: int = 600) -> str:
        """
        Extract a compact summary for history injection.

        Priority:
        1. First 2 complete sentences (preserves key findings better than char-truncation)
        2. Hard truncation at max_chars if sentences can't be split cleanly
        """
        if not content:
            return ""
        if len(content) <= max_chars:
            return content
        # Try to grab the first 2 sentences (ending in .!?)
        parts = re.split(r'(?<=[.!?])\s+', content.strip())
        summary = " ".join(parts[:2]) if len(parts) >= 2 else parts[0]
        if len(summary) <= max_chars:
            return summary + " [...]"
        # Fall back to char limit
        return content[:max_chars] + "... (truncated)"

    def _format_history(self, session: Dict[str, Any], limit: int = 10) -> List[BaseMessage]:
        """Convert session history into LangChain messages for graph input.

        Uses stored `turn_summary` when available (generated at save time),
        otherwise extracts a compact summary from the response text.
        A synthetic context message is prepended when session goal or cancer type
        are known, so early-turn context survives the 10-turn window.
        """
        messages: List[BaseMessage] = []
        for item in session.get("history", [])[-limit:]:
            q = item.get("query", "")
            resp = item.get("response", {})
            # Prefer an explicit turn_summary stored at save time
            content = item.get("turn_summary", "")
            if not content:
                if isinstance(resp, dict):
                    raw = resp.get("summary") or resp.get("message") or ""
                elif isinstance(resp, str):
                    raw = resp
                else:
                    raw = ""
                content = self._extract_turn_summary(raw)
            if q:
                messages.append(HumanMessage(content=q))
            if content:
                messages.append(AIMessage(content=content))
        return messages

    def _history_limit_for_scope(self, tool_scope: str) -> int:
        """Use less history for obvious no-tool turns to lower prompt cost."""
        if tool_scope == "none":
            return 2
        return 10

    async def _pre_resolve_external_identifiers(
        self,
        requested_identifiers: Sequence[str],
        *,
        log_prefix: str,
    ) -> tuple[Dict[str, Any], Dict[str, str], List[Dict[str, Any]]]:
        """
        Resolve external gene identifiers before graph execution.

        This gives deterministic routes a concrete HGNC symbol to work with and
        seeds raw_results so downstream integrity checks can trust the mapping.
        """
        if "gene_utils::resolve_gene_identifier" not in self.mcp_aggregator.list_tools():
            return {}, {}, []

        preloaded_results: Dict[str, Any] = {}
        resolved_map: Dict[str, str] = {}
        trace_metrics: List[Dict[str, Any]] = []
        count = 0
        for identifier in requested_identifiers:
            normalized = _normalize_identifier_token(identifier)
            if not _is_external_gene_identifier(normalized):
                continue
            started = time.perf_counter()
            try:
                raw = await self.mcp_aggregator.call_tool(
                    "gene_utils::resolve_gene_identifier",
                    {"identifier": normalized},
                )
                latency_ms = int((time.perf_counter() - started) * 1000)
            except Exception as exc:
                latency_ms = int((time.perf_counter() - started) * 1000)
                logger.warning(
                    "%s Failed to pre-resolve identifier %s: %s",
                    log_prefix,
                    normalized,
                    exc,
                )
                raw = {"error": str(exc)}

            if isinstance(raw, dict):
                result_dict = raw
            elif isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    result_dict = parsed if isinstance(parsed, dict) else {"raw": parsed}
                except Exception:
                    result_dict = {"raw": raw}
            else:
                result_dict = {"raw": raw}
            data_status = _classify_tool_result_payload(
                "gene_utils__resolve_gene_identifier",
                result_dict,
            )
            trace_metrics.append(
                {
                    "tool": "gene_utils::resolve_gene_identifier",
                    "latency_ms": latency_ms,
                    "status": data_status,
                }
            )
            unique_key = f"gene_utils::resolve_gene_identifier#{count}"
            count += 1
            preloaded_results[unique_key] = {
                "_gene": None,
                "_args": {"identifier": normalized},
                "_result": result_dict,
                "_data_status": data_status,
            }

            hgnc_symbol = _normalize_identifier_token(
                result_dict.get("hgnc_symbol") if isinstance(result_dict, dict) else None
            )
            if hgnc_symbol and not result_dict.get("error"):
                resolved_map[normalized] = hgnc_symbol

        if resolved_map:
            logger.info(
                "%s Pre-resolved external identifiers: %s",
                log_prefix,
                resolved_map,
            )
        execution_trace = []
        if trace_metrics:
            execution_trace.append(
                {
                    "node": "tools",
                    "step": 0,
                    "latency_ms": sum(item["latency_ms"] for item in trace_metrics),
                    "tool_calls": trace_metrics,
                }
            )
        return preloaded_results, resolved_map, execution_trace

    async def _prepare_execution_context(
        self,
        query: str,
        user_id: str,
        session_id: Optional[str],
        client_ip: Optional[str],
        *,
        log_prefix: str,
    ) -> tuple[Dict[str, Any], str, str, Optional[AgentState], Optional[QueryPlan]]:
        """Load session context, rebuild the graph, and prepare the initial state."""
        session = await self._get_session(session_id, user_id, client_ip=client_ip)
        effective_query = _expand_contextual_shortcuts(query, session)
        if effective_query != query:
            logger.info(f"{log_prefix} Expanded contextual shortcut for query processing.")

        # Persist session goal (first substantive query) and cancer type
        ctx = session.setdefault("context", {})
        if not ctx.get("session_goal") and query.strip() and not _looks_conversational(query):
            ctx["session_goal"] = query.strip()[:200]
        detected_cancer = _extract_cancer_type(effective_query)
        if detected_cancer:
            ctx["active_cancer_type"] = detected_cancer

        active_gene = ctx.get("active_gene", "unknown")
        requested_genes = _extract_query_genes(effective_query)
        requested_identifiers = _extract_query_identifiers(effective_query)
        allow_active_gene_reference = _query_uses_active_gene_reference(effective_query)
        active_cancer_type = ctx.get("active_cancer_type")
        session_goal = ctx.get("session_goal", "")
        preloaded_tool_results: Dict[str, Any] = {}
        pre_resolved_identifiers: Dict[str, str] = {}
        preloaded_execution_trace: List[Dict[str, Any]] = []

        if any(_is_external_gene_identifier(token) for token in requested_identifiers):
            (
                preloaded_tool_results,
                pre_resolved_identifiers,
                preloaded_execution_trace,
            ) = await self._pre_resolve_external_identifiers(
                requested_identifiers,
                log_prefix=log_prefix,
            )
            for resolved_symbol in pre_resolved_identifiers.values():
                if resolved_symbol and resolved_symbol not in requested_genes:
                    requested_genes.append(resolved_symbol)

        multi_gene = len(requested_genes) >= 2
        effective_active_gene = active_gene
        if effective_active_gene == "unknown" and len(pre_resolved_identifiers) == 1:
            effective_active_gene = next(iter(pre_resolved_identifiers.values()))

        # Build history messages so the planner has real conversation context
        history_messages = self._format_history(session, limit=10)
        history_str = "\n".join(
            f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {str(m.content)[:300]}"
            for m in history_messages
        )

        route_decision = _infer_route_decision(
            effective_query, effective_active_gene if effective_active_gene != "unknown" else None
        )
        keyword_scope = route_decision.tool_scope
        query_plan: Optional[QueryPlan] = None
        if _is_ambiguous_cis_dataset_query(
            effective_query,
            requested_genes,
            requested_identifiers,
            effective_active_gene if effective_active_gene != "unknown" else None,
        ):
            route_decision = RouteDecision(tool_scope="cis_dual", workflow="cis_dual_dataset")
            keyword_scope = route_decision.tool_scope

        should_use_planner = (
            settings.USE_PLANNER
            and self.llm is not None
            and _should_use_planner_for_query(
                effective_query,
                requested_genes,
                requested_identifiers,
                effective_active_gene if effective_active_gene != "unknown" else None,
            )
        )

        if should_use_planner:
            query_plan = await _call_planner(
                self.llm,
                query=effective_query,
                history_str=history_str or "(none)",
                active_gene=effective_active_gene,
            )

        # If the planner wants clarification, bail out before building the graph
        if query_plan and query_plan.needs_clarification:
            return session, effective_query, active_gene, None, query_plan

        # Deterministic routing stays authoritative for explicit scientific queries.
        tool_scope = keyword_scope
        workflow = route_decision.workflow
        force_identifier_resolution = any(
            _is_external_gene_identifier(token) for token in requested_identifiers
        )

        self._rebuild_graph(
            active_gene=effective_active_gene, tool_scope=tool_scope, workflow=workflow, multi_gene=multi_gene,
            active_cancer_type=active_cancer_type,
            session_goal=session_goal or None,
            force_identifier_resolution=force_identifier_resolution,
            pre_resolved_identifiers=pre_resolved_identifiers or None,
        )

        history_limit = self._history_limit_for_scope(tool_scope)
        history_messages = self._format_history(session, limit=history_limit)
        initial_messages = history_messages + [HumanMessage(content=effective_query)]
        initial_state: AgentState = {
            "messages": initial_messages,
            "tool_results": preloaded_tool_results,
            "active_gene": effective_active_gene if effective_active_gene != "unknown" else None,
            "steps": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "execution_trace": preloaded_execution_trace,
            "requested_genes": requested_genes,
            "requested_identifiers": requested_identifiers,
            "allow_active_gene_reference": allow_active_gene_reference,
            "tool_scope": tool_scope,
            "workflow": workflow,
            "query_plan": query_plan.model_dump() if query_plan else None,
        }
        return session, effective_query, active_gene, initial_state, query_plan

    def _extract_final_state_context(
        self,
        final_state: AgentState,
        active_gene: str,
        session: Dict[str, Any],
        *,
        log_prefix: str,
        original_query: str,
    ) -> tuple[str, bool, Dict[str, Any], List[str], Dict[str, Any], List[Dict[str, Any]]]:
        """Normalize the final graph state into a response-building context."""
        final_messages = final_state.get("messages", [])
        final_ai_msg = next(
            (m for m in reversed(final_messages) if isinstance(m, AIMessage) and not m.tool_calls),
            None,
        )
        llm_summary = _normalize_content(final_ai_msg.content) if final_ai_msg else ""

        is_general_knowledge = llm_summary.startswith("[GENERAL_KNOWLEDGE]")
        if is_general_knowledge:
            llm_summary = llm_summary[len("[GENERAL_KNOWLEDGE]"):].lstrip("\n").strip()

        raw_results = final_state.get("tool_results", {})
        new_active_gene = final_state.get("active_gene") or active_gene
        # If no tool ran to update active_gene, fall back to the first gene the user explicitly
        # mentioned in this query.  This keeps context correct even for direct-answer turns.
        if (not new_active_gene or new_active_gene == active_gene) and not raw_results:
            fallback_genes = list(final_state.get("requested_genes") or [])
            if fallback_genes:
                new_active_gene = fallback_genes[0]
        tools_used = [k.rsplit("#", 1)[0] for k in raw_results.keys()]
        execution_trace = list(final_state.get("execution_trace", []))
        usage_tracker = {
            "input_tokens": final_state.get("input_tokens", 0),
            "output_tokens": final_state.get("output_tokens", 0),
            "model": getattr(self.llm, "model_name", None) or getattr(self.llm, "model", None) or settings.DEFAULT_LLM_MODEL,
        }

        if "context" not in session:
            session["context"] = {}
        if new_active_gene and new_active_gene != "unknown":
            session["context"]["active_gene"] = new_active_gene

        logger.info(
            "%s Execution summary | query=%r | steps=%s | tool_calls=%s | tools=%s | input_tokens=%s | output_tokens=%s | trace=%s",
            log_prefix,
            original_query[:120],
            final_state.get("steps", 0),
            len(raw_results),
            tools_used,
            usage_tracker["input_tokens"],
            usage_tracker["output_tokens"],
            _format_execution_trace(execution_trace),
        )
        return llm_summary, is_general_knowledge, raw_results, tools_used, usage_tracker, execution_trace

    async def _ensure_dual_survival_results(
        self,
        *,
        raw_results: Dict[str, Any],
        execution_trace: List[Dict[str, Any]],
        final_state: AgentState,
        query: str,
        log_prefix: str,
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Backfill a missing survival dataset when deterministic routing chose dual survival."""
        if final_state.get("workflow") != "survival_dual_dataset":
            return raw_results, execution_trace

        available_tools = self.mcp_aggregator.list_tools()
        requested_genes = [
            _normalize_identifier_token(gene)
            for gene in (final_state.get("requested_genes") or [])
            if _normalize_identifier_token(gene)
        ]
        if not requested_genes:
            requested_genes = list(_resolved_identifier_map(raw_results).values())
        gene = next((g for g in requested_genes if g), "")
        if not gene:
            return raw_results, execution_trace

        cohort_codes = _extract_cancer_codes(query)
        cohort = cohort_codes[0] if cohort_codes else ""
        present_tools = {key.rsplit("#", 1)[0] for key in raw_results}
        missing_calls: list[tuple[str, Dict[str, Any]]] = []

        def _has_tcga_all_omics_for_gene_cohort() -> bool:
            if not cohort:
                return "linkedomics::tcga_survival_analysis" in present_tools
            for key, wrapped in raw_results.items():
                if key.rsplit("#", 1)[0] != "linkedomics::tcga_survival_analysis":
                    continue
                if not isinstance(wrapped, dict):
                    continue
                args = wrapped.get("_args") or {}
                payload = wrapped.get("_result") or {}
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                query_meta = payload.get("query") if isinstance(payload, dict) else {}
                if not isinstance(query_meta, dict):
                    query_meta = {}
                existing_gene = _normalize_identifier_token(
                    query_meta.get("gene") or args.get("gene") or wrapped.get("_gene")
                )
                existing_cohort = _normalize_identifier_token(query_meta.get("cohort") or args.get("cohort"))
                existing_omics = query_meta.get("omics") or args.get("omics")
                if existing_gene == gene and existing_cohort == cohort and (
                    payload.get("mode") == 2 or not existing_omics
                ):
                    return True
            return False

        if (
            "linkedomics::overall_survival_per_cancer" not in present_tools
            and "linkedomics::overall_survival_per_cancer" in available_tools
        ):
            missing_calls.append(("linkedomics::overall_survival_per_cancer", {"protein": gene}))

        if (
            (
                "linkedomics::tcga_survival_analysis" not in present_tools
                or not _has_tcga_all_omics_for_gene_cohort()
            )
            and "linkedomics::tcga_survival_analysis" in available_tools
        ):
            tcga_args: Dict[str, Any] = {"gene": gene}
            if cohort:
                tcga_args["cohort"] = cohort
            else:
                tcga_args["omics"] = "RNAseq"
            missing_calls.append(("linkedomics::tcga_survival_analysis", tcga_args))

        if not missing_calls:
            return raw_results, execution_trace

        updated_results = dict(raw_results)
        call_counts: Dict[str, int] = {}
        for existing_key in updated_results:
            base_key, sep, suffix = existing_key.rpartition("#")
            normalized_key = base_key if sep and suffix.isdigit() else existing_key
            next_count = int(suffix) + 1 if sep and suffix.isdigit() else 1
            call_counts[normalized_key] = max(call_counts.get(normalized_key, 0), next_count)

        trace_metrics: List[Dict[str, Any]] = []
        started = time.perf_counter()
        for tool_id, args in missing_calls:
            tool_started = time.perf_counter()
            try:
                raw = await self.mcp_aggregator.call_tool(tool_id, args)
                latency_ms = int((time.perf_counter() - tool_started) * 1000)
            except Exception as exc:
                latency_ms = int((time.perf_counter() - tool_started) * 1000)
                logger.warning("%s Failed to backfill %s: %s", log_prefix, tool_id, exc)
                raw = {"error": str(exc)}

            if isinstance(raw, dict):
                result_dict = raw
            elif isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    result_dict = parsed if isinstance(parsed, dict) else {"raw": parsed}
                except Exception:
                    result_dict = {"raw": raw}
            else:
                result_dict = {"raw": raw}

            data_status = _classify_tool_result_payload(tool_id.replace("::", "__"), result_dict)
            count = call_counts.get(tool_id, 0)
            unique_key = f"{tool_id}#{count}"
            call_counts[tool_id] = count + 1
            updated_results[unique_key] = {
                "_gene": gene,
                "_args": args,
                "_result": result_dict,
                "_data_status": data_status,
            }
            trace_metrics.append(
                {
                    "tool": tool_id,
                    "latency_ms": latency_ms,
                    "status": data_status,
                }
            )

        updated_trace = list(execution_trace)
        if trace_metrics:
            updated_trace.append(
                {
                    "node": "tools",
                    "step": final_state.get("steps", 0),
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "tool_calls": trace_metrics,
                    "backfilled": True,
                }
            )
        return updated_results, updated_trace

    async def _ensure_dual_cis_results(
        self,
        *,
        raw_results: Dict[str, Any],
        execution_trace: List[Dict[str, Any]],
        final_state: AgentState,
        query: str,
        log_prefix: str,
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Backfill CPTAC or TCGA cis results when deterministic routing chose both."""
        if final_state.get("workflow") != "cis_dual_dataset":
            return raw_results, execution_trace

        available_tools = self.mcp_aggregator.list_tools()
        requested_genes = [
            _normalize_identifier_token(gene)
            for gene in (final_state.get("requested_genes") or [])
            if _normalize_identifier_token(gene)
        ]
        if not requested_genes:
            requested_genes = list(_resolved_identifier_map(raw_results).values())
        gene = next((g for g in requested_genes if g), "")
        if not gene:
            return raw_results, execution_trace

        present_tools = {key.rsplit("#", 1)[0] for key in raw_results}
        cptac_args, tcga_args = _infer_dual_cis_tool_args(query, gene)
        missing_calls: list[tuple[str, Dict[str, Any]]] = []
        has_cptac_cis = bool(
            {
                "linkedomics::get_cis_correlations",
                "linkedomics::batch_get_cis_correlations",
            }
            & present_tools
        )

        if (
            not has_cptac_cis
            and "linkedomics::get_cis_correlations" in available_tools
        ):
            missing_calls.append(("linkedomics::get_cis_correlations", cptac_args))

        if (
            "linkedomics::tcga_cis_association_analysis" not in present_tools
            and "linkedomics::tcga_cis_association_analysis" in available_tools
        ):
            missing_calls.append(("linkedomics::tcga_cis_association_analysis", tcga_args))

        if not missing_calls:
            return raw_results, execution_trace

        updated_results = dict(raw_results)
        call_counts: Dict[str, int] = {}
        for existing_key in updated_results:
            base_key, sep, suffix = existing_key.rpartition("#")
            normalized_key = base_key if sep and suffix.isdigit() else existing_key
            next_count = int(suffix) + 1 if sep and suffix.isdigit() else 1
            call_counts[normalized_key] = max(call_counts.get(normalized_key, 0), next_count)

        trace_metrics: List[Dict[str, Any]] = []
        started = time.perf_counter()
        for tool_id, args in missing_calls:
            tool_started = time.perf_counter()
            try:
                raw = await self.mcp_aggregator.call_tool(tool_id, args)
                latency_ms = int((time.perf_counter() - tool_started) * 1000)
            except Exception as exc:
                latency_ms = int((time.perf_counter() - tool_started) * 1000)
                logger.warning("%s Failed to backfill %s: %s", log_prefix, tool_id, exc)
                raw = {"error": str(exc)}

            if isinstance(raw, dict):
                result_dict = raw
            elif isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    result_dict = parsed if isinstance(parsed, dict) else {"raw": parsed}
                except Exception:
                    result_dict = {"raw": raw}
            else:
                result_dict = {"raw": raw}

            data_status = _classify_tool_result_payload(tool_id.replace("::", "__"), result_dict)
            count = call_counts.get(tool_id, 0)
            unique_key = f"{tool_id}#{count}"
            call_counts[tool_id] = count + 1
            updated_results[unique_key] = {
                "_gene": gene,
                "_args": args,
                "_result": result_dict,
                "_data_status": data_status,
            }
            trace_metrics.append(
                {
                    "tool": tool_id,
                    "latency_ms": latency_ms,
                    "status": data_status,
                }
            )

        updated_trace = list(execution_trace)
        if trace_metrics:
            updated_trace.append(
                {
                    "node": "tools",
                    "step": final_state.get("steps", 0),
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "tool_calls": trace_metrics,
                    "backfilled": True,
                }
            )
        return updated_results, updated_trace

    async def _build_response_from_final_state(
        self,
        *,
        query: str,
        effective_query: str,
        session: Dict[str, Any],
        active_gene: str,
        final_state: AgentState,
        log_prefix: str,
        include_stream_metadata: bool = False,
    ) -> Dict[str, Any]:
        """Convert the final LangGraph state into the API response payload."""
        (
            llm_summary,
            is_general_knowledge,
            raw_results,
            tools_used,
            usage_tracker,
            execution_trace,
        ) = self._extract_final_state_context(
            final_state,
            active_gene,
            session,
            log_prefix=log_prefix,
            original_query=query,
        )
        raw_results, execution_trace = await self._ensure_dual_survival_results(
            raw_results=raw_results,
            execution_trace=execution_trace,
            final_state=final_state,
            query=effective_query,
            log_prefix=log_prefix,
        )
        raw_results, execution_trace = await self._ensure_dual_cis_results(
            raw_results=raw_results,
            execution_trace=execution_trace,
            final_state=final_state,
            query=effective_query,
            log_prefix=log_prefix,
        )
        tools_used = [key.rsplit("#", 1)[0] for key in raw_results.keys()]

        clarification_options_from_llm = _parse_clarification_options(llm_summary)
        if clarification_options_from_llm:
            llm_summary = _strip_options_line(llm_summary)

        rich_message = llm_summary
        suggestions: List[str] = []

        async def _format():
            if clarification_options_from_llm:
                return llm_summary, llm_summary, tools_used, raw_results, []
            if raw_results and self._parent is not None:
                try:
                    formatted = await self._parent._generate_response(
                        effective_query, raw_results, session, intent="research", usage_tracker=usage_tracker
                    )
                    _msg = formatted.get("message") or ""
                    _summary = formatted.get("summary") or ""
                    _placeholder = {"", "No LinkedOmics results.", "No response generated."}
                    msg_out = _msg if _msg.strip() and _msg.strip() not in _placeholder else llm_summary
                    if not msg_out.strip() and raw_results:
                        lines = ["Here are the results from the tools that were called:\n"]
                        for key, val in raw_results.items():
                            tool_name = key.rsplit("#", 1)[0].replace("::", " › ")
                            gene = val.get("_gene", "")
                            result = val.get("_result", {})
                            if isinstance(result, dict) and result.get("error"):
                                lines.append(f"**{tool_name}**{' (' + gene + ')' if gene else ''}: ⚠️ {result['error']}")
                            elif isinstance(result, dict):
                                keys = [k for k in result if not k.startswith("_")][:5]
                                lines.append(f"**{tool_name}**{' (' + gene + ')' if gene else ''}: returned {len(keys)} fields ({', '.join(keys)})")
                            else:
                                lines.append(f"**{tool_name}**{' (' + gene + ')' if gene else ''}: completed")
                        msg_out = "\n".join(lines)
                    summary_out = _summary.strip() or llm_summary
                    formatted_tools = formatted.get("tools_used") or []
                    return (
                        msg_out,
                        summary_out,
                        _ordered_unique_strings([*tools_used, *formatted_tools]),
                        formatted.get("raw_results") or raw_results,
                        formatted.get("visualizations") or [],
                    )
                except Exception as e:
                    logger.warning(f"{log_prefix} _generate_response failed: {e}")
            return llm_summary, llm_summary, tools_used, raw_results, []

        async def _suggest():
            # Suggestions are now embedded inline in the LLM response; pills disabled.
            return []

        (rich_message, display_summary, tools_used_final, raw_results_final, visualizations), suggestions = await asyncio.gather(
            _format(), _suggest()
        )

        clarification_options: List[str] = []
        tool_sources: Dict[str, str] = {}
        if clarification_options_from_llm:
            display_summary = _strip_options_line(display_summary)
            rich_message = _strip_options_line(rich_message)
        rich_message = _normalize_duplicate_markdown_headings(rich_message)
        display_summary = _normalize_duplicate_markdown_headings(display_summary)
        rich_message = _ensure_webgestalt_enrichment_summary(rich_message, raw_results_final, section=True)
        display_summary = _ensure_webgestalt_enrichment_summary(display_summary, raw_results_final)
        display_summary = _ensure_tool_result_coverage_summary(display_summary, raw_results_final, effective_query)
        if include_stream_metadata:
            clarification_options = clarification_options_from_llm
            rich_message = _inlineize_source_blockquotes(rich_message)
            rich_message = _strip_invalid_source_citations(rich_message, tools_used_final)
            rich_message = _ensure_inline_source_citations(rich_message, tools_used_final)
            tool_sources = _build_tool_sources(raw_results_final)

        is_literature_only = bool(tools_used_final) and all(
            t.startswith("literature::") for t in tools_used_final
        )
        any_errors = bool(raw_results_final) and any(
            isinstance(v.get("_result"), dict) and "error" in v.get("_result", {})
            for v in raw_results_final.values()
        )
        result_data_statuses = [
            (v.get("_data_status") if isinstance(v, dict) else None) or _classify_tool_result_payload(
                key,
                v.get("_result") if isinstance(v, dict) else v,
            )
            for key, v in raw_results_final.items()
        ]
        results_with_data = sum(1 for status in result_data_statuses if status == "ok")
        no_data_only = bool(raw_results_final) and results_with_data == 0

        # Confidence: measure how much data the tools actually returned
        if clarification_options_from_llm:
            confidence = "clarification"
        elif is_general_knowledge:
            confidence = "general_knowledge"
        elif not raw_results_final:
            confidence = "general_knowledge"
        elif any_errors and results_with_data == 0:
            confidence = "low"
        else:
            total_results = len(raw_results_final)
            if results_with_data == total_results:
                confidence = "high"
            elif results_with_data > 0:
                confidence = "partial"
            else:
                confidence = "low"

        if no_data_only:
            explicit_no_data = _build_no_data_message(
                raw_results_final, tool_scope=final_state.get("tool_scope")
            )
            rich_message = explicit_no_data
            display_summary = "No matching data was returned by the requested tools."
            suggestions = []

        show_summary = bool(
            not no_data_only
            and raw_results_final
            and rich_message.strip()
            and display_summary.strip()
            and rich_message.strip() != display_summary.strip()
        )
        input_tokens = usage_tracker.get("input_tokens", 0)
        output_tokens = usage_tracker.get("output_tokens", 0)
        model_name = usage_tracker.get("model") or settings.DEFAULT_LLM_MODEL

        formatted_response = {
            "success": True,
            "summary": display_summary if show_summary else "",
            "message": rich_message,
            "query": query,
            "tools_used": _ordered_unique_strings(tools_used_final),
            "raw_results": raw_results_final,
            "visualizations": visualizations,
            "analyses": [],
            "suggestions": suggestions,
            "datasets": [],
            "papers": [],
            "no_collapse": is_literature_only,
            "is_general_knowledge": is_general_knowledge,
            "confidence": confidence,
            "execution_trace": execution_trace,
            "_input_tokens": input_tokens,
            "_output_tokens": output_tokens,
            "_model": model_name,
        }
        if include_stream_metadata:
            formatted_response["clarification_options"] = clarification_options
            formatted_response["tool_sources"] = tool_sources

        pending_offer = _extract_pending_offer_from_response(formatted_response)
        if pending_offer:
            session["context"]["pending_offer"] = pending_offer
        else:
            session["context"].pop("pending_offer", None)

        return formatted_response

    # ── Main entry point ───────────────────────────────────────────────────────

    async def process_query(
        self,
        query: str,
        user_id: str,
        session_id: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a user query using the LangGraph agent.

        Matches the MCPOrchestrator.process_query return schema.
        """
        try:
            logger.info(f"[LangGraph] Processing query: {query}")

            session, effective_query, active_gene, initial_state, query_plan = await self._prepare_execution_context(
                query,
                user_id,
                session_id,
                client_ip,
                log_prefix="[LangGraph]",
            )

            # Planner requested clarification — no graph execution needed
            if initial_state is None:
                formatted_response = self._build_clarification_response(query, session, query_plan)
                turn_id = await self._save_query(session, query, formatted_response)
                return {**formatted_response, "session_id": session["id"], "turn_id": turn_id}

            if not self._graph:
                return {
                    "success": False,
                    "message": "LangGraph not available (no LLM configured).",
                    "query": query,
                    "session_id": session["id"],
                }

            # Run the LangGraph agent
            logger.info("[LangGraph] Starting agent graph execution...")
            final_state = await self._graph.ainvoke(initial_state)
            formatted_response = await self._build_response_from_final_state(
                query=query,
                effective_query=effective_query,
                session=session,
                active_gene=active_gene,
                final_state=final_state,
                log_prefix="[LangGraph]",
                include_stream_metadata=True,
            )

            # Persist to DB (or memory in standalone mode)
            turn_id = await self._save_query(session, query, formatted_response)

            return {
                **formatted_response,
                "session_id": session["id"],
                "turn_id": turn_id,
            }

        except Exception as e:
            logger.error(f"[LangGraph] Error processing query: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Error processing query: {str(e)}",
                "query": query,
            }

    async def process_query_stream(
        self,
        query: str,
        user_id: str,
        session_id: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Process a query and yield execution status chunks for Server-Sent Events (SSE).
        Yields SSE-formatted lines whose JSON payloads look like:
          {"type": "status", "content": "..."}
          {"type": "final", "content": {...}}
        """

        try:
            logger.info(f"[LangGraph Stream] Processing query: {query}")
            yield f"data: {json.dumps({'type': 'status', 'content': 'Initializing session...'})}\n\n"

            session, effective_query, active_gene, initial_state, query_plan = await self._prepare_execution_context(
                query,
                user_id,
                session_id,
                client_ip,
                log_prefix="[LangGraph Stream]",
            )

            # Planner requested clarification — emit final event and exit
            if initial_state is None:
                formatted_response = self._build_clarification_response(query, session, query_plan)
                turn_id = await self._save_query(session, query, formatted_response)
                payload = {**formatted_response, "session_id": session["id"], "turn_id": turn_id}
                yield f"data: {json.dumps({'type': 'final', 'content': payload})}\n\n"
                return

            if not self._graph:
                yield f"data: {json.dumps({'type': 'final', 'content': {'success': False, 'message': 'LangGraph not available.', 'query': query, 'session_id': session['id']}})}\n\n"
                return

            logger.info("[LangGraph Stream] Starting execution...")
            yield f"data: {json.dumps({'type': 'status', 'content': 'Analyzing query requirements...'})}\n\n"

            # Stream using "values" mode only for status signals.
            # Raw LLM token streaming is intentionally skipped here — the
            # post-processed rich_message and display_summary are streamed
            # below after _build_response_from_final_state completes, so the
            # user always sees content that matches the final rendered result.
            final_state = None
            _tool_streaming_started = False

            async for stream_mode_key, chunk in self._graph.astream(
                initial_state,
                stream_mode=["values"],
            ):
                if stream_mode_key == "values":
                    # Full state snapshot — use for status signals
                    current_state = chunk
                    final_state = current_state
                    messages = current_state.get("messages", [])
                    if not messages:
                        continue
                    last_msg = messages[-1]
                    if isinstance(last_msg, AIMessage):
                        if last_msg.tool_calls:
                            _tool_streaming_started = False
                            for idx, tc in enumerate(last_msg.tool_calls):
                                tool_name = tc.get("name", "tool").split("#")[0]
                                if idx == 0:
                                    yield f"data: {json.dumps({'type': 'status', 'content': f'Running {tool_name}...'})}\n\n"
                    elif isinstance(last_msg, ToolMessage):
                        yield f"data: {json.dumps({'type': 'status', 'content': 'Analyzing tool results...'})}\n\n"

            if not final_state:
                yield f"data: {json.dumps({'type': 'final', 'content': {'success': False, 'message': 'No output generated.', 'query': query}})}\n\n"
                return

            # --- POST-PROCESSING (Same as process_query) ---
            yield f"data: {json.dumps({'type': 'status', 'content': 'Formatting response...'})}\n\n"
            formatted_response = await self._build_response_from_final_state(
                query=query,
                effective_query=effective_query,
                session=session,
                active_gene=active_gene,
                final_state=final_state,
                log_prefix="[LangGraph Stream]",
                include_stream_metadata=True,
            )

            # Stream the final formatted message content (rich_message).
            # This always matches what ends up in the final event, so the user
            # never sees a jarring replacement after streaming completes.
            # Use 30 ms between chunks so the typewriter effect is clearly
            # visible (≈ 1–3 s for a typical response).
            rich_text = (formatted_response.get("message") or "").strip()
            if rich_text:
                yield f"data: {json.dumps({'type': 'status', 'content': 'Drafting final analysis...'})}\n\n"
                rich_chunks = _iter_stream_chunks(rich_text)
                for idx, text_chunk in enumerate(rich_chunks):
                    yield f"data: {json.dumps({'type': 'text_delta', 'content': text_chunk})}\n\n"
                    if idx < len(rich_chunks) - 1:
                        await asyncio.sleep(0.030)

            # Stream the summary separately so it populates the summary box
            # incrementally without conflicting with the main message content.
            display_summary = (formatted_response.get("summary") or "").strip()
            if display_summary:
                yield f"data: {json.dumps({'type': 'status', 'content': 'Generating summary...'})}\n\n"
                summary_chunks = _iter_stream_chunks(display_summary)
                for idx, chunk in enumerate(summary_chunks):
                    yield f"data: {json.dumps({'type': 'summary_delta', 'content': chunk})}\n\n"
                    if idx < len(summary_chunks) - 1:
                        await asyncio.sleep(0.030)

            turn_id = await self._save_query(session, query, formatted_response)
            
            payload = {
                **formatted_response,
                "session_id": session["id"],
                "turn_id": turn_id,
            }
            
            yield f"data: {json.dumps({'type': 'final', 'content': payload})}\n\n"

        except Exception as e:
            logger.error(f"[LangGraph Stream] Error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'final', 'content': {'success': False, 'message': f'Error: {str(e)}', 'query': query}})}\n\n"
