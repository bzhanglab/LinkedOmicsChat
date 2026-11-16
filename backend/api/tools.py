from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Dict, Any, List, Optional
from collections import defaultdict, deque
from pydantic import BaseModel
import logging

from api.chat import _check_rate_limit, _client_ip
from core.config import settings
from core.dependencies import get_current_user_optional, is_admin_user
from models.database import User
from services.mcp_orchestrator import MCPOrchestrator

router = APIRouter()
logger = logging.getLogger(__name__)

# Global orchestrator reference (set by main.py)
orchestrator: Optional[MCPOrchestrator] = None

# Sliding-window logs for direct tool runs, kept separate from the chat quotas.
_guest_tool_log: Dict[str, deque] = defaultdict(deque)
_user_tool_log: Dict[str, deque] = defaultdict(deque)


def _check_tool_rate_limit(http_request: Request, current_user: Optional[User]) -> None:
    """Raise HTTP 429 when a guest IP or user exceeds its hourly tool-run limit (admins exempt)."""
    if not settings.TOOL_RATE_LIMIT_ENABLED or is_admin_user(current_user):
        return
    if current_user is None:
        _check_rate_limit(
            _client_ip(http_request), _guest_tool_log,
            settings.TOOL_GUEST_RATE_LIMIT_PER_HOUR, "guest", unit="tool runs",
        )
    else:
        _check_rate_limit(
            str(current_user.id), _user_tool_log,
            settings.TOOL_USER_RATE_LIMIT_PER_HOUR, "user", unit="tool runs",
        )

class ToolExecutionRequest(BaseModel):
    tool_id: str
    arguments: Dict[str, Any]

class ToolListResponse(BaseModel):
    tools: Dict[str, Any]

@router.get("/", response_model=ToolListResponse)
async def list_tools():
    """List all available MCP tools."""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="MCP Orchestrator not initialized")
    
    try:
        tools = orchestrator.mcp_aggregator.list_tools()
        return {"tools": tools}
    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/execute")
async def execute_tool(
    request: ToolExecutionRequest,
    http_request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Execute a specific MCP tool directly."""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="MCP Orchestrator not initialized")
    _check_tool_rate_limit(http_request, current_user)

    try:
        logger.info(f"Direct tool execution request: {request.tool_id}")
        result = await orchestrator.mcp_aggregator.call_tool(request.tool_id, request.arguments)
        
        # Check if result is a raw string JSON (MCP aggregator returns this for complex content)
        # We parse it here so the frontend gets a proper object
        if isinstance(result, str):
            try:
                import json
                # Heuristic: if it looks like a JSON object/array, try to parse
                clean = result.strip()
                if (clean.startswith("{") and clean.endswith("}")) or (clean.startswith("[") and clean.endswith("]")):
                    result = json.loads(result)
            except Exception:
                # If parsing fails, keep as string
                pass

        return {
            "success": True,
            "tool_id": request.tool_id,
            "result": result
        }
    except Exception as e:
        logger.error(f"Error executing tool {request.tool_id}: {e}")
        return {
            "success": False,
            "tool_id": request.tool_id,
            "error": str(e)
        }
