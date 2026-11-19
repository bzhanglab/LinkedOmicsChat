"""The open MCP service: the app's tools for any AI assistant or agent, at /api/v1/mcp.

Outside assistants connect over MCP's streamable HTTP transport and call the same tool servers
the chat uses. Their own model does the reasoning, so no model runs here. Results go out as the
chat agent sees them (compacted), because raw results can run to megabytes.

The PubMed tools are left out: outside assistants have their own literature search, and PubMed
calls from this server count against NCBI's per-address limit. Access is open and limited per
client address. Calls to each tool run a few at a time across all clients, so outside use cannot
overload the lab's services or slow the chat. The usage log keeps a salted hash of the address,
never the address.
"""
import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from core.config import settings
from core.database import SessionLocal
from models.database import McpToolCall

logger = logging.getLogger(__name__)

EXCLUDED_SERVERS = {"literature"}
# The TCGA service fails (HTTP 500, dropped connections) with more than a couple of these at once
_CONCURRENCY = {"analyze_tcga_survival_associations": 2, "analyze_tcga_cis_associations": 2}
_DEFAULT_CONCURRENCY = 6
_WINDOW_SECONDS = 3600.0
CONNECT_PAGE = "https://chat.linkedomics.org/docs#mcp"

INSTRUCTIONS = (
    "Tools for cancer multi-omics from the Zhang lab's public resources: CPTAC proteogenomics (LinkedOmicsKB), "
    "TCGA (LinkedOmics), treatment response in clinical-trial cohorts (ClinicalOmicsDB), drug targets "
    "(LinkedOmics Targets), the FunMap functional network, and WebGestalt enrichment. Each result names the "
    "resource it came from; cite LinkedOmicsChat and that resource. Gene arguments take HGNC symbols; "
    "resolve_gene_identifier converts Ensembl, UniProt, and old names. Results are compacted to fit an "
    f"assistant's context. Limits and citation: {CONNECT_PAGE}"
)


def _client_ip(request: Any) -> str:
    """As in api/chat.py: nginx sets X-Real-IP in production; locally, the socket peer."""
    if request is None:
        return "unknown"
    return request.headers.get("X-Real-IP") or (request.client.host if request.client else "unknown")


def client_id(ip: str) -> str:
    """The client ID the usage log keeps: a salted hash of the address."""
    return hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest()[:16]


def _error(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], isError=True)


class McpService:
    def __init__(self, aggregator: Any):
        self.aggregator = aggregator
        self.server = Server("linkedomics", instructions=INSTRUCTIONS, website_url="https://chat.linkedomics.org")
        self._calls: Dict[str, Deque[float]] = defaultdict(deque)
        self._running: Dict[str, asyncio.Semaphore] = {}
        self.server.list_tools()(self._list_tools)
        self.server.call_tool()(self._call_tool)
        # Stateless: every request stands alone, so it works behind any number of backend workers
        self.manager = StreamableHTTPSessionManager(app=self.server, stateless=True)

    def _tool_ids(self) -> Dict[str, str]:
        """Public tool name (the bare name) -> the aggregator's tool ID."""
        return {
            info["name"]: tool_id for tool_id, info in self.aggregator.list_tools().items()
            if info.get("server") not in EXCLUDED_SERVERS
        }

    async def _list_tools(self) -> list[types.Tool]:
        tools = self.aggregator.list_tools()
        return [
            types.Tool(name=name, description=tools[tool_id].get("description") or "",
                       inputSchema=tools[tool_id].get("inputSchema") or {"type": "object"})
            for name, tool_id in sorted(self._tool_ids().items())
        ]

    def _over_limit(self, client: str) -> Optional[str]:
        """A message when the client has used its hourly calls; records the call otherwise."""
        now = time.time()
        calls = self._calls[client]
        while calls and now - calls[0] > _WINDOW_SECONDS:
            calls.popleft()
        if len(calls) >= settings.MCP_RATE_LIMIT_PER_HOUR:
            minutes = max(1, int((_WINDOW_SECONDS - (now - calls[0])) // 60) + 1)
            return (f"This service allows {settings.MCP_RATE_LIMIT_PER_HOUR} tool calls an hour from one address; "
                    f"try again in about {minutes} minute{'s' if minutes != 1 else ''}. Need more? See {CONNECT_PAGE}.")
        calls.append(now)
        return None

    async def _call_tool(self, name: str, arguments: Dict[str, Any]) -> types.CallToolResult:
        if not settings.MCP_SERVICE_ENABLED:
            return _error("The LinkedOmics MCP service is switched off at the moment.")
        tool_id = self._tool_ids().get(name)
        if tool_id is None:
            return _error(f"Unknown tool: {name}")
        try:
            request = self.server.request_context.request
        except LookupError:
            request = None
        ip = _client_ip(request)
        client = client_id(ip)
        blocked = {c.strip() for c in settings.MCP_BLOCKED_CLIENTS.split(",") if c.strip()}
        if ip in blocked or client in blocked:
            return _error("This address is blocked from the LinkedOmics MCP service.")
        message = self._over_limit(client)
        if message:
            return _error(message)

        from services.langgraph_orchestrator import _compact_tool_message  # avoids an import cycle

        started = time.perf_counter()
        ok = False
        try:
            async with self._running.setdefault(name, asyncio.Semaphore(_CONCURRENCY.get(name, _DEFAULT_CONCURRENCY))):
                raw = await self.aggregator.call_tool(tool_id, arguments or {})
            text = raw if isinstance(raw, str) else json.dumps(raw, default=str)
            if text.startswith("Error executing tool"):
                return _error(text)
            ok = True
            return types.CallToolResult(content=[types.TextContent(type="text", text=_compact_tool_message(tool_id, text))])
        except Exception as exc:
            logger.warning("[MCP service] %s failed: %s", name, exc)
            return _error(f"The tool failed: {exc}")
        finally:
            await self._log(client, name, ok, int((time.perf_counter() - started) * 1000))

    async def _log(self, client: str, tool: str, ok: bool, duration_ms: int) -> None:
        row = McpToolCall(client=client, tool=tool, ok=ok, duration_ms=duration_ms, timestamp=time.time())
        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                db = SessionLocal()
                try:
                    db.add(row)
                    db.commit()
                finally:
                    db.close()
            else:
                async with SessionLocal() as db:
                    db.add(row)
                    await db.commit()
        except Exception as exc:  # the log never blocks a call
            logger.warning("[MCP service] usage log failed: %s", exc)


class McpEndpoint:
    """The ASGI app for /api/v1/mcp; it answers once the service is created at startup."""

    service: Optional[McpService] = None

    async def __call__(self, scope, receive, send) -> None:
        if self.service is None or not settings.MCP_SERVICE_ENABLED:
            body = b'{"detail": "The MCP service is not available."}'
            await send({"type": "http.response.start", "status": 503,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.service.manager.handle_request(scope, receive, send)


endpoint = McpEndpoint()
