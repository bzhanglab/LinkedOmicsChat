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
import json
import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Type

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


def build_mcp_tools(aggregator: MCPAggregator) -> List[BaseTool]:
    """
    Convert every registered MCP tool into a LangChain StructuredTool.

    Tool names use '__' instead of '::' because LangChain tool names must be
    valid Python identifiers (no colons).  The mapping is reversed when
    calling call_tool on the aggregator.
    """
    tools: List[BaseTool] = []
    for tool_id, meta in aggregator.list_tools().items():
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

    logger.info(f"[LangGraph] Built {len(tools)} MCP tools for LangGraph agent")
    return tools


# ─────────────────────────────────────────────────────────────────────────────
# Graph nodes
# ─────────────────────────────────────────────────────────────────────────────

MAX_STEPS = 8  # Safety cap on tool-call iterations


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


def _make_agent_node(llm_with_tools, system_prompt: str):
    """Return an async agent node function closed over the bound LLM."""
    async def agent_node(state: AgentState) -> Dict[str, Any]:
        # Prepend system message on every call so it's always in context
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = await llm_with_tools.ainvoke(messages)

        # Accumulate token usage from this LLM call
        usage = getattr(response, "usage_metadata", None) or {}
        in_tok = usage.get("input_tokens", 0) or 0
        out_tok = usage.get("output_tokens", 0) or 0

        return {
            "messages": [response],
            "steps": state["steps"] + 1,
            "input_tokens": state.get("input_tokens", 0) + in_tok,
            "output_tokens": state.get("output_tokens", 0) + out_tok,
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


def _make_tool_node(tools: List[BaseTool]):
    """
    Return an async tool node that executes all tool_calls from the last AIMessage,
    collects raw results, and updates tool_results + active_gene in the state.
    """
    tool_map = {t.name: t for t in tools}

    async def tool_node(state: AgentState) -> Dict[str, Any]:
        last_ai: AIMessage = state["messages"][-1]
        tool_messages: List[ToolMessage] = []
        new_results = dict(state.get("tool_results") or {})
        active_gene = state.get("active_gene")
        call_counts: Dict[str, int] = {}

        for tc in last_ai.tool_calls:
            tool_name = tc["name"]
            args = tc["args"]
            call_id = tc["id"]

            tool = tool_map.get(tool_name)
            if not tool:
                content = json.dumps({"error": f"Unknown tool: {tool_name}"})
            else:
                try:
                    raw = await tool.coroutine(**args)
                    content = json.dumps(raw) if not isinstance(raw, str) else raw
                    # Truncate abstracts so the LLM summarises instead of reproducing
                    if tool_name in ("literature__search_pubmed", "literature__get_pubmed_abstract"):
                        content = _compact_literature(content)
                except Exception as e:
                    logger.error(f"[LangGraph] Tool {tool_name} error: {e}")
                    content = json.dumps({"error": str(e)})

            # Track result with unique key (mirrors mcp_orchestrator convention)
            mcp_tool_id = tool_name.replace("__", "::")
            count = call_counts.get(mcp_tool_id, 0)
            unique_key = f"{mcp_tool_id}#{count}"
            call_counts[mcp_tool_id] = count + 1

            # Parse content back to dict for raw_results
            try:
                result_dict = json.loads(content)
            except Exception:
                result_dict = {"raw": content}

            # Extract gene from args (protein or gene_symbol)
            gene_arg = args.get("protein") or args.get("gene_symbol")
            if gene_arg and isinstance(gene_arg, str) and gene_arg.lower() not in {"it", "its", "it's"}:
                active_gene = gene_arg.upper()

            new_results[unique_key] = {
                "_gene": gene_arg,
                "_args": args,
                "_result": result_dict,
            }

            tool_messages.append(
                ToolMessage(content=content, tool_call_id=call_id, name=tool_name)
            )
            logger.info(f"[LangGraph] Tool {mcp_tool_id} executed → stored as {unique_key}")

        return {
            "messages": tool_messages,
            "tool_results": new_results,
            "active_gene": active_gene,
        }

    return tool_node


# ─────────────────────────────────────────────────────────────────────────────
# Graph builder
# ─────────────────────────────────────────────────────────────────────────────

# Maps bare tool names → inline source key (used in #source:X hrefs)
_TOOL_SOURCE_KEY: dict = {
    "cancer_gene_expression":      "linkedomics",
    "get_cis_correlations":        "linkedomics",
    "get_trans_correlations":      "linkedomics",
    "overall_survival_per_cancer": "linkedomics",
    "clinical_trial_information":  "trials",
    "funmap_neighborhood":         "funmap",
    "get_target":                  "targets",
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
    """Return the actual API URL that was called for a given tool + args."""
    gene = args.get("protein") or args.get("gene_symbol") or args.get("gene")
    gene = str(gene).upper() if gene else None
    _TEMPLATES: Dict[str, Any] = {
        "cancer_gene_expression":      lambda g: f"https://kb.linkedomics.org/data/tn/gene?gene={g}&sort=metap&order=asc&offset=0&limit=10",
        "get_cis_correlations":        lambda g: f"https://kb.linkedomics.org/gene/{g}",
        "get_trans_correlations":      lambda g: f"https://kb.linkedomics.org/gene/{g}",
        "overall_survival_per_cancer": lambda g: f"https://kb.linkedomics.org/data/associations/phenotype/gene?phenotype=clinical__overall_survival&gene={g}",
        "funmap_neighborhood":         lambda g: f"https://funmap.linkedomics.org/data/dag/gene/{g}.json",
        "get_target":                  lambda g: f"https://targets.linkedomics.org/{g}/",
        "clinical_trial_information":  lambda g: f"https://trials.linkedomics.org/api/table/gene/{g}",
        "webgestalt":                  lambda _: "https://www.webgestalt.org",
        "search_literature":           lambda _: "https://pubmed.ncbi.nlm.nih.gov",
        "search_pubmed":               lambda _: "https://pubmed.ncbi.nlm.nih.gov",
    }
    builder = _TEMPLATES.get(bare_tool_name)
    if not builder:
        return None
    try:
        return builder(gene) if gene else builder(None)
    except Exception:
        return None


def _build_tool_sources(raw_results: dict) -> Dict[str, str]:
    """Build a {source_key: actual_api_url} map from raw tool results."""
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


def _expand_contextual_shortcuts(query: str, session: Dict[str, Any]) -> str:
    """Expand bare quick-reply shortcuts into context-aware prompts for the LLM."""
    stripped = (query or "").strip()
    normalized = stripped.casefold()

    if normalized == "answer using general knowledge":
        previous_query = _last_substantive_user_query(session)
        if previous_query:
            return (
                "Answer using general knowledge about the user's previous question: "
                f"{previous_query}"
            )

    return stripped


def build_graph(llm, tools: List[BaseTool], system_prompt: str):
    """
    Build and compile the LangGraph StateGraph.

    Graph structure:
        agent ──(has tool_calls)──▶ tools ──▶ agent
              ──(no tool_calls) ──▶ END
    """
    llm_with_tools = llm.bind_tools(tools)

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
You are a Senior Multi-Omics Bioinformatics Analyst with access to a suite of research tools.

{bio_guidelines}

{data_access}

RULES:
- Only call tools when research data is genuinely needed. For greetings or general questions, reply directly.
- TOOL ECONOMY: Call ONLY the tools directly needed to answer the question asked. Match the number of tool calls to the scope of the request:
  * Single-aspect queries ("expression of TP53", "survival for BRCA1") → 1 tool.
  * Explicit comparison queries ("compare TP53 and EGFR expression") → 1 tool per gene, same analysis.
  * Broad profile requests ("tell me everything about TP53", "full profile", "overview") → up to 4 tools covering distinct aspects.
  * Chained follow-up ("now do pathway enrichment on those neighbors") → only when the user's phrasing explicitly requests it.
- Do NOT proactively chain tools or add unrequested analyses. If you think a follow-up would be valuable, mention it briefly in prose ("You may also want to explore pathway enrichment on these results") but do not call the tool unless asked.
- If the user asks about a gene using 'it', 'this', or 'the gene', resolve to the currently active gene: '{active_gene}'.
- GENE IDENTIFIERS: Users may provide genes as HGNC symbols (TP53), Ensembl Gene IDs (ENSG00000141510), or UniProt accessions (P04637). All tools accept any of these formats and convert automatically.
  CRITICAL: NEVER convert a gene identifier yourself using your training knowledge. When the user provides an Ensembl Gene ID (starts with ENSG) or UniProt accession, call `resolve_gene_identifier` FIRST. If it returns an "error" key, stop immediately and report the error — do not call any other tools. If it succeeds, use the returned "hgnc_symbol" for all subsequent tool calls.
  MULTI-GENE QUERIES: When the query mentions two or more genes (e.g., "compare TP53 and FAKEGENE"), call `resolve_gene_identifier` for EACH gene before calling any analysis tool. If ANY gene fails resolution, STOP immediately and report all failures — do NOT proceed with analysis for the valid genes. Partial results for a comparison are meaningless and must not be returned.
  BEFORE calling any gene analysis tool, verify only that the identifier looks plausible in format:
  * HGNC symbols: letters, numbers, and hyphens only; typically 2–8 characters (e.g., TP53, BRCA1, ESR1, EGFR).
  * Ensembl Gene IDs: "ENSG" followed by digits only (e.g., ENSG00000141510).
  * UniProt accessions: exactly 6 alphanumeric characters matching [A-Z][0-9][A-Z][A-Z0-9]{{2}}[0-9] or [OPQ][0-9][A-Z0-9]{{3}}[0-9] (e.g., P04637, Q9Y6K9).
  If the identifier does NOT match any of these patterns (e.g., "P04637ABCDFD", "hello123xyz"), do NOT call any tool. Ask: "I don't recognize '[identifier]' as a valid gene symbol, Ensembl ID, or UniProt accession. Could you double-check the gene name?"
  If a tool returns an "error" key in its result, STOP immediately — do not call any more tools. Report the error to the user and ask them to provide a valid identifier.
- CAUTION ON AMBIGUOUS GENES: Words like "impact", "set", "met", and "clock" are valid human genes, but usually used as regular English words by users.
   * If the word is used in a conversational or analytical context (e.g., "does it have an impact on survival?"), DO NOT treat it as a gene. The gene is '{active_gene}'.
   * If the word is explicitly capitalized by itself (e.g., "Tell me about IMPACT"), or used explicitly as a subject of omics inquiry (e.g., "What is the expression of SET?"), treat it as the literal gene symbol.
- Structure your final answer with: **Direct Answer**, **Key Findings**, **Analytical Synthesis**.
- DATA GROUNDING (critical): For any question requiring specific data — mutation rates, expression levels, survival associations, available cancer types/samples, drug targets, pathway enrichment — you MUST use a tool. NEVER answer such questions from your training knowledge. If no relevant tool is available, respond: "I don't currently have access to [data type] data. This requires the [tool name] capability which is not enabled."
- It is better to say "I don't have access to that data" than to give an answer from training knowledge that may be outdated, incorrect, or untraceable.
- OUT-OF-SCOPE DETECTION: If the user's question is about a topic that none of the available tools can address (e.g., cell type specificity, single-cell RNA-seq, protein 3D structure, variant pathogenicity, GWAS, drug mechanism of action, sequence alignment, immune infiltration, epigenetic editing), do NOT answer from training knowledge. Instead:
  1. In 1–2 sentences, acknowledge the question and note that this data type is outside LinkedOmicsChat's current scope.
  2. Briefly state what LinkedOmicsChat specializes in: TCGA-based cancer multi-omics — gene expression (tumor vs normal), survival associations, FunMap protein interaction networks, clinical trial/drug targets, cis-correlations, and pathway enrichment.
  3. On a new line, offer two choices exactly as: **Options:** `Answer using general knowledge` · `Show what LinkedOmicsChat can analyze for [GENE]`
     (Replace [GENE] with the gene from the query, or omit that option if no gene is mentioned.)
- GENERAL KNOWLEDGE MODE: If the user's message starts with "Answer using general knowledge", answer helpfully from your training knowledge. Start your response with the single token [GENERAL_KNOWLEDGE] on its very first line (the UI uses this to show a disclaimer). After answering, do NOT add a caveat — the UI handles it.
- REDIRECT TO TOOLS: If the user's message starts with "Show what LinkedOmicsChat can analyze for", extract the gene name and call cancer_gene_expression, overall_survival_per_cancer, and clinical_trial_information to provide a comprehensive profile of that gene in LinkedOmicsChat.
- CLARIFICATION: If the query is genuinely ambiguous and you cannot reasonably infer the user's intent, ask ONE focused clarification question instead of calling tools. Only ask when truly necessary; proceed directly if you can make a reasonable inference.
  * Use **Options:** `A` · `B` · `C` format ONLY when choices are finite and exhaustive — e.g., analysis type ("Survival" / "Expression" / "Mutation frequency"), or data layer ("RNA" / "Protein" / "Both"). Place options on their own line.
  * Do NOT use **Options:** for open-ended inputs like gene names — users are not limited to any list. Just ask plainly: "Which gene would you like to explore?"
- PLATFORM QUESTIONS: Questions like "What cancer types are available?", "What can you do?", "What data do you have access to?" are meta questions about the platform — they are NOT about the active gene '{active_gene}'. Do NOT call gene-analysis tools (e.g. cancer_gene_expression, overall_survival_per_cancer) in response to these. Answer directly from the AVAILABLE DATA section above — do not invent or add data sources not listed there.

FORMATTING RULES (strictly enforced):
- NEVER reproduce raw tool output (dicts, JSON, Python objects) in your response. Always interpret and summarize the data.
- Present lists of cancer types, genes, or results as a **markdown table** (| Column | Column |) or a concise bulleted list.
- For mutation frequency data: use a table with columns | Cancer Type | Cancer Name | Mutated Cases | Total Cases | Frequency |
- For expression data: summarize direction and significance per cancer type in prose or a table.
- For gene lists (e.g., functional neighbors): present as a comma-separated inline list or a short bullet list, not a Python array.
- For literature results: format each article as a numbered entry with **bold title** (linked to pubmed_url), authors, journal + year, and 1–2 sentence abstract summary. Do NOT dump the full abstract verbatim — summarize it. Example:
  1. **[Title](https://pubmed.ncbi.nlm.nih.gov/PMID/)** — Author et al., *Journal* (Year)
     Brief 1-sentence summary of findings. PMID: XXXXX
- Always add brief biological interpretation after presenting numbers (e.g., "This confirms TP53 is a major tumor suppressor...").
- INLINE CITATIONS: After each sentence or data point that came from a specific tool, add an inline source link using this exact markdown format immediately after the period: [LinkedOmics](#source:linkedomics), [FunMap](#source:funmap), [WebGestalt](#source:webgestalt), [CPTAC](#source:cptac). Use the source that matches the tool. Do not add citations after every sentence — only where data was retrieved from a tool. Do NOT add [PubMed] inline — literature results already have per-article PMID links embedded in the numbered list titles.
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

    async def initialize(self):
        """Initialize MCP connections (if standalone) and build the LangGraph."""
        logger.info("[LangGraph] Initializing LangGraphOrchestrator...")
        if self._parent is None:
            # Only init aggregator in standalone mode; parent already did it.
            await self.mcp_aggregator.initialize()
        self._rebuild_graph()
        logger.info(f"[LangGraph] Ready with {len(self._tools)} tools.")

    def _build_data_access_section(self) -> str:
        """Generate a data access section based on which MCP servers are actually enabled."""
        available = self.mcp_aggregator.list_tools()
        servers = set(info["server"] for info in available.values())

        lines = ["AVAILABLE DATA (strictly what you can access via tools — nothing else):"]
        if "linkedomics" in servers:
            lines.append(
                "- CPTAC proteogenomics (via LinkedOmics tools): Gene expression (RNA + protein levels), "
                "survival analysis, cis-correlations, functional protein networks (FunMap), drug targets, "
                "clinical trials. Cohorts: BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC."
            )
        if "literature" in servers:
            lines.append(
                "- PubMed literature (via literature tools): Real-time search of peer-reviewed biomedical "
                "publications via NCBI E-utilities. Returns titles, authors, journal, year, abstract, PMID, "
                "and DOI. Use search_pubmed for queries; use get_pubmed_abstract when a specific PMID is given."
            )
        if not servers:
            lines.append("- (No data tools are currently enabled.)")
        lines.append(
            "\nNOT AVAILABLE (do not answer these from training knowledge — say you don't have access):\n"
            "- TCGA raw genomics data (GDC): RNA-seq counts, somatic mutation frequencies, CNV, methylation from GDC portal.\n"
            "  NOTE: CPTAC and TCGA are different datasets. CPTAC adds proteomics to some TCGA cancer types, "
            "but raw TCGA genomic data (mutation rates, RNA-seq HTSeq counts) is NOT accessible via any tool.\n"
            "- Any data source not explicitly listed above.\n"
            "\nIf a user asks about TCGA specifically, say: "
            "'I don't have access to TCGA/GDC data. I can access CPTAC proteogenomics data via LinkedOmics.'"
        )
        return "\n".join(lines)

    def _rebuild_graph(self, active_gene: str = "unknown"):
        """(Re)build the compiled LangGraph with current MCP tools."""
        if not self.llm:
            logger.warning("[LangGraph] No LLM available, graph not built.")
            return
        self._tools = build_mcp_tools(self.mcp_aggregator)
        system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(
            bio_guidelines=self.BIO_GUIDELINES,
            active_gene=active_gene or "unknown",
            data_access=self._build_data_access_section(),
        )
        self._graph = build_graph(self.llm, self._tools, system_prompt)

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

    async def _save_query(self, session: Dict[str, Any], query: str, response: Dict[str, Any]):
        """Persist query+response to DB (via parent) or fall back to memory."""
        if self._parent is not None:
            await self._parent._update_session(session, query, response)
        else:
            session.setdefault("history", []).append({
                "query": query,
                "response": response,
                "timestamp": time.time(),
            })

    def _format_history(self, session: Dict[str, Any], limit: int = 10) -> List[BaseMessage]:
        """Convert session history into LangChain messages for graph input."""
        messages: List[BaseMessage] = []
        for item in session.get("history", [])[-limit:]:
            q = item.get("query", "")
            resp = item.get("response", {})
            content = ""
            if isinstance(resp, dict):
                content = resp.get("summary") or resp.get("message") or ""
            elif isinstance(resp, str):
                content = resp
            if len(content) > 800:
                content = content[:800] + "... (truncated)"
            if q:
                messages.append(HumanMessage(content=q))
            if content:
                messages.append(AIMessage(content=content))
        return messages

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

            session = await self._get_session(session_id, user_id, client_ip=client_ip)
            effective_query = _expand_contextual_shortcuts(query, session)
            if effective_query != query:
                logger.info("[LangGraph] Expanded contextual shortcut for query processing.")
            active_gene = session.get("context", {}).get("active_gene", "unknown")

            # Rebuild graph with current active_gene in system prompt
            self._rebuild_graph(active_gene=active_gene)

            if not self._graph:
                return {
                    "success": False,
                    "message": "LangGraph not available (no LLM configured).",
                    "query": query,
                    "session_id": session["id"],
                }

            # Build input state: history messages + current query
            history_messages = self._format_history(session)
            initial_messages = history_messages + [HumanMessage(content=effective_query)]

            initial_state: AgentState = {
                "messages": initial_messages,
                "tool_results": {},
                "active_gene": active_gene if active_gene != "unknown" else None,
                "steps": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }

            # Run the LangGraph agent
            logger.info("[LangGraph] Starting agent graph execution...")
            final_state = await self._graph.ainvoke(initial_state)

            # Extract the LLM's analytical summary from the last AI message
            final_messages = final_state.get("messages", [])
            final_ai_msg = next(
                (m for m in reversed(final_messages) if isinstance(m, AIMessage) and not m.tool_calls),
                None,
            )
            llm_summary = _normalize_content(final_ai_msg.content) if final_ai_msg else ""

            # Detect [GENERAL_KNOWLEDGE] marker — LLM uses this when answering out-of-scope
            # questions with training knowledge after user confirms.
            is_general_knowledge = llm_summary.startswith("[GENERAL_KNOWLEDGE]")
            if is_general_knowledge:
                llm_summary = llm_summary[len("[GENERAL_KNOWLEDGE]"):].lstrip("\n").strip()

            # Collect raw_results (structured as {"tool_id#N": {"_gene": ..., "_result": ...}})
            raw_results = final_state.get("tool_results", {})
            new_active_gene = final_state.get("active_gene") or active_gene
            tools_used = [k.rsplit("#", 1)[0] for k in raw_results.keys()]
            input_tokens = final_state.get("input_tokens", 0)
            output_tokens = final_state.get("output_tokens", 0)

            # Update session context
            if "context" not in session:
                session["context"] = {}
            if new_active_gene and new_active_gene != "unknown":
                session["context"]["active_gene"] = new_active_gene

            # ── Rich formatting + suggestions (run concurrently) ─────────────
            # _generate_response formats tool outputs into rich markdown.
            # _generate_suggestions asks the LLM for 3 follow-up questions.
            # Both are independent so we run them in parallel.
            rich_message = llm_summary  # fallback
            suggestions: List[str] = []

            async def _format():
                if raw_results and self._parent is not None:
                    try:
                        formatted = await self._parent._generate_response(
                            effective_query, raw_results, session, intent="research"
                        )
                        _msg = formatted.get("message") or ""
                        _placeholder = {"", "No LinkedOmics results.", "No response generated."}
                        msg_out = _msg if _msg.strip() and _msg.strip() not in _placeholder else llm_summary
                        # Last resort: build a plain-text summary from raw results so the
                        # user never sees "Analysis completed. See results below." with nothing below.
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
                        return msg_out, \
                               formatted.get("tools_used") or tools_used, \
                               formatted.get("raw_results") or raw_results
                    except Exception as e:
                        logger.warning(f"[LangGraph] _generate_response failed: {e}")
                return llm_summary, tools_used, raw_results

            async def _suggest():
                if self._parent is not None:
                    try:
                        return await self._parent._generate_suggestions(
                            effective_query, llm_summary, session, n=3
                        )
                    except Exception as e:
                        logger.warning(f"[LangGraph] _generate_suggestions failed: {e}")
                return []

            (rich_message, tools_used, raw_results), suggestions = await asyncio.gather(
                _format(), _suggest()
            )

            # Literature responses are always shown in full — never collapsed.
            is_literature_only = bool(tools_used) and all(
                t.startswith("literature::") for t in tools_used
            )

            # Suppress summary when any tool call returned an error (e.g. invalid gene,
            # partial multi-gene failure) — LLM narrative already covers the explanation.
            any_errors = bool(raw_results) and any(
                isinstance(v.get("_result"), dict) and "error" in v.get("_result", {})
                for v in raw_results.values()
            )
            show_summary = bool(
                not any_errors
                and raw_results
                and rich_message.strip()
                and llm_summary.strip()
                and rich_message.strip() != llm_summary.strip()
            )

            formatted_response = {
                "success": True,
                "summary": llm_summary if show_summary else "",
                "message": rich_message,
                "query": query,
                "tools_used": list(set(tools_used)),
                "raw_results": raw_results,
                "visualizations": [],
                "analyses": [],
                "suggestions": suggestions,
                "datasets": [],
                "papers": [],
                "no_collapse": is_literature_only,  # frontend: never show "Show details"
                "is_general_knowledge": is_general_knowledge,
                "_input_tokens": input_tokens,
                "_output_tokens": output_tokens,
            }

            # Persist to DB (or memory in standalone mode)
            await self._save_query(session, query, formatted_response)

            return {
                **formatted_response,
                "session_id": session["id"],
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
        Yields JSON strings:
          {"type": "status", "content": "..."}
          {"type": "final", "content": {...}}
        """
        import json
        
        try:
            logger.info(f"[LangGraph Stream] Processing query: {query}")
            yield f"data: {json.dumps({'type': 'status', 'content': 'Initializing session...'})}\n\n"

            session = await self._get_session(session_id, user_id, client_ip=client_ip)
            effective_query = _expand_contextual_shortcuts(query, session)
            if effective_query != query:
                logger.info("[LangGraph Stream] Expanded contextual shortcut for query processing.")
            active_gene = session.get("context", {}).get("active_gene", "unknown")

            # Rebuild graph
            self._rebuild_graph(active_gene=active_gene)

            if not self._graph:
                yield f"data: {json.dumps({'type': 'final', 'content': {'success': False, 'message': 'LangGraph not available.', 'query': query, 'session_id': session['id']}})}\n\n"
                return

            # Build input state
            history_messages = self._format_history(session)
            initial_messages = history_messages + [HumanMessage(content=effective_query)]
            initial_state: AgentState = {
                "messages": initial_messages,
                "tool_results": {},
                "active_gene": active_gene if active_gene != "unknown" else None,
                "steps": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }

            logger.info("[LangGraph Stream] Starting execution...")
            yield f"data: {json.dumps({'type': 'status', 'content': 'Analyzing query requirements...'})}\n\n"

            # Stream the execution graph state completely
            final_state = None
            # Using stream_mode="values" yields the FULL state after every node executes.
            async for current_state in self._graph.astream(initial_state, stream_mode="values"):
                final_state = current_state
                
                # We can determine what just happened by looking at the last message
                messages = current_state.get("messages", [])
                if not messages:
                    continue
                    
                last_msg = messages[-1]
                if isinstance(last_msg, AIMessage):
                    if last_msg.tool_calls:
                        for idx, tc in enumerate(last_msg.tool_calls):
                            tool_name = tc.get("name", "tool").split("#")[0]
                            # Only emit status for the first tool call in a parallel batch to avoid spam
                            if idx == 0:
                                yield f"data: {json.dumps({'type': 'status', 'content': f'Running {tool_name}...'})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'status', 'content': 'Drafting final analysis...'})}\n\n"
                        
                elif isinstance(last_msg, HumanMessage):
                    # Initial state
                    pass
                elif isinstance(last_msg, ToolMessage):
                    yield f"data: {json.dumps({'type': 'status', 'content': 'Analyzing tool results...'})}\n\n"
            
            if not final_state:
                yield f"data: {json.dumps({'type': 'final', 'content': {'success': False, 'message': 'No output generated.', 'query': query}})}\n\n"
                return

            # --- POST-PROCESSING (Same as process_query) ---
            yield f"data: {json.dumps({'type': 'status', 'content': 'Formatting response...'})}\n\n"
            
            final_messages = final_state.get("messages", [])
            final_ai_msg = next(
                (m for m in reversed(final_messages) if isinstance(m, AIMessage) and not m.tool_calls),
                None,
            )
            llm_summary = _normalize_content(final_ai_msg.content) if final_ai_msg else ""

            # Detect [GENERAL_KNOWLEDGE] marker
            is_general_knowledge = llm_summary.startswith("[GENERAL_KNOWLEDGE]")
            if is_general_knowledge:
                llm_summary = llm_summary[len("[GENERAL_KNOWLEDGE]"):].lstrip("\n").strip()

            raw_results = final_state.get("tool_results", {})
            new_active_gene = final_state.get("active_gene") or active_gene
            tools_used = [k.rsplit("#", 1)[0] for k in raw_results.keys()]
            input_tokens = final_state.get("input_tokens", 0)
            output_tokens = final_state.get("output_tokens", 0)

            if "context" not in session:
                session["context"] = {}
            if new_active_gene and new_active_gene != "unknown":
                session["context"]["active_gene"] = new_active_gene

            rich_message = llm_summary
            suggestions: List[str] = []

            async def _format():
                if raw_results and self._parent is not None:
                    try:
                        formatted = await self._parent._generate_response(
                            effective_query, raw_results, session, intent="research"
                        )
                        _msg = formatted.get("message") or ""
                        _placeholder = {"", "No LinkedOmics results.", "No response generated."}
                        return _msg if _msg.strip() and _msg.strip() not in _placeholder else llm_summary, \
                               formatted.get("tools_used") or tools_used, \
                               formatted.get("raw_results") or raw_results
                    except Exception as e:
                        logger.warning(f"[LangGraph Stream] _generate_response failed: {e}")
                return llm_summary, tools_used, raw_results

            async def _suggest():
                if self._parent is not None:
                    try:
                        return await self._parent._generate_suggestions(
                            effective_query, llm_summary, session, n=3
                        )
                    except Exception as e:
                        logger.warning(f"[LangGraph Stream] _generate_suggestions failed: {e}")
                return []

            (rich_message, tools_used_post, raw_results_post), suggestions = await asyncio.gather(
                _format(), _suggest()
            )

            is_literature_only = bool(tools_used_post) and all(
                t.startswith("literature::") for t in tools_used_post
            )

            clarification_options = _parse_clarification_options(llm_summary)
            if clarification_options:
                llm_summary = _strip_options_line(llm_summary)
                rich_message = _strip_options_line(rich_message)
            rich_message = _strip_invalid_source_citations(rich_message, tools_used_post)
            tool_sources = _build_tool_sources(raw_results_post)

            # Only include a separate summary when rich_message is genuinely different
            # from the LLM narrative (i.e. _generate_response produced richer content).
            # When they're the same text the frontend would duplicate the content.
            # Also suppress when any tool call returned an error (e.g. invalid gene,
            # partial multi-gene failure) — LLM narrative already covers the explanation.
            any_errors_post = bool(raw_results_post) and any(
                isinstance(v.get("_result"), dict) and "error" in v.get("_result", {})
                for v in raw_results_post.values()
            )
            show_summary = bool(
                not any_errors_post
                and raw_results_post
                and rich_message.strip()
                and llm_summary.strip()
                and rich_message.strip() != llm_summary.strip()
            )

            formatted_response = {
                "success": True,
                "summary": llm_summary if show_summary else "",
                "message": rich_message,
                "query": query,
                "tools_used": list(set(tools_used_post)),
                "raw_results": raw_results_post,
                "visualizations": [],
                "analyses": [],
                "suggestions": suggestions,
                "clarification_options": clarification_options,
                "tool_sources": tool_sources,
                "datasets": [],
                "papers": [],
                "no_collapse": is_literature_only,
                "is_general_knowledge": is_general_knowledge,
                "_input_tokens": input_tokens,
                "_output_tokens": output_tokens,
            }

            await self._save_query(session, query, formatted_response)
            
            payload = {
                **formatted_response,
                "session_id": session["id"],
            }
            
            yield f"data: {json.dumps({'type': 'final', 'content': payload})}\n\n"

        except Exception as e:
            logger.error(f"[LangGraph Stream] Error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'final', 'content': {'success': False, 'message': f'Error: {str(e)}', 'query': query}})}\n\n"
