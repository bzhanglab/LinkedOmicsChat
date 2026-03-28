"""
Chat API endpoints
Handles conversational interactions with the agent system
"""
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse
from typing import Optional, Any, Dict, List
from collections import defaultdict, deque
import logging
import time
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import select, or_, cast, Text as SAText

from core.artifacts import resolve_visualization_paths

# ── In-memory guest rate limiter (sliding window, per IP) ──────────────────
# Stores a deque of request timestamps per IP address.
# On each request we drop timestamps older than 1 hour, then check the count.
_guest_request_log: Dict[str, deque] = defaultdict(deque)

def _check_guest_rate_limit(ip: str) -> None:
    """Raise HTTP 429 if the guest IP has exceeded GUEST_RATE_LIMIT_PER_HOUR.

    Does nothing when GUEST_RATE_LIMIT_ENABLED=False (e.g. NAR review period).
    """
    from core.config import settings
    if not settings.GUEST_RATE_LIMIT_ENABLED:
        return

    now = time.time()
    window = 3600  # 1 hour in seconds
    timestamps = _guest_request_log[ip]

    # Evict timestamps outside the sliding window
    while timestamps and now - timestamps[0] > window:
        timestamps.popleft()

    if len(timestamps) >= settings.GUEST_RATE_LIMIT_PER_HOUR:
        oldest = timestamps[0]
        retry_after = int(window - (now - oldest)) + 1
        minutes = (retry_after + 59) // 60  # round up to nearest minute
        wait_msg = f"in about {minutes} minute{'s' if minutes != 1 else ''}" if minutes > 1 else "shortly"
        raise HTTPException(
            status_code=429,
            detail=(
                f"You've used all {settings.GUEST_RATE_LIMIT_PER_HOUR} free queries for this hour. "
                f"You can try again {wait_msg}, or create a free account for unlimited access."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    timestamps.append(now)

from models.schemas import ChatRequest, ChatResponse, TurnTruncateRequest
from models.database import User, ChatSession, ChatMessage as DBChatMessage
from services.mcp_orchestrator import MCPOrchestrator
from core.config import settings
from core.database import get_db, SessionLocal
from core.dependencies import get_current_user, get_current_user_optional

logger = logging.getLogger(__name__)

router = APIRouter()


def _sanitize_response_for_history(resp: Any) -> Any:
    """Minimize response payload for chat history rendering."""
    try:
        if not isinstance(resp, dict):
            return resp

        new_resp = dict(resp)
        # Always drop heavy fields that UI doesn't need for rendering history.
        new_resp.pop("raw_results", None)
        # Keep lightweight viz metadata (type/id/title) — binary was already stripped
        # before DB save so this is safe. Frontend uses the IDs to load plot files.
        vizs = new_resp.get("visualizations") or []
        lean_vizs = [{k: v for k, v in viz.items() if k not in ("png_b64", "svg", "csv")} for viz in vizs]
        new_resp["visualizations"] = lean_vizs if lean_vizs else []
        new_resp["has_visualizations"] = bool(lean_vizs)
        # These can be extremely large and will freeze the UI when rendering history.
        # They are fetched on-demand via /messages/{message_id}.
        new_resp.pop("analyses", None)
        new_resp.pop("papers", None)
        new_resp.pop("datasets", None)
        new_resp.pop("suggestions", None)
        # Sometimes nested
        meta = new_resp.get("metadata")
        if isinstance(meta, dict):
            meta = dict(meta)
            meta.pop("papers", None)
            meta.pop("datasets", None)
            new_resp["metadata"] = meta

        # Create a lightweight preview + flags (used for collapsed rendering)
        # We must sanitize BOTH "message" and "summary" because sometimes the summary 
        # contains the full plot (which can be 5MB+ of base64 data).
        
        has_images = False
        was_sanitized = False
        import re

        for field in ["message", "summary"]:
            val = new_resp.get(field)
            if isinstance(val, str) and val:
                # Detect inline images
                if "data:image" in val:
                    has_images = True
                    was_sanitized = True
                    # Replace large inline base64 images with placeholder
                    # This dramaticly reduces payload size for history lists
                    val = re.sub(
                        r"!\[[^\]]*\]\(data:image/[^)]+\)",
                        "_(Plot attached — load details to view.)_",
                        val,
                        flags=re.IGNORECASE,
                    )
                    new_resp[field] = val
                # Other markdown images (standard URLs/paths)
                elif "![" in val and "](" in val:
                    has_images = True

        new_resp["has_images"] = has_images
        
        # Determine if we should collapse the message for performance
        msg = new_resp.get("message")
        if isinstance(msg, str) and msg:
            if len(msg) > 1200 or was_sanitized:
                # Message is large or has heavy attachments, store a preview and mark as partial
                new_resp["message_preview"] = (msg[:1200] + "\n…") if len(msg) > 1200 else msg
                new_resp["has_full_content"] = False
                # Omit the full message from history to keep payload small.
                new_resp.pop("message", None)
            else:
                # Simple text message, keep as is
                new_resp["has_full_content"] = True
        else:
            # If no message but has summary (rare for history), treat as full if small
            new_resp["has_full_content"] = True
        
        return new_resp
    except Exception:
        return resp

# Set by main.py during startup to the active MCPOrchestrator instance
orchestrator: MCPOrchestrator = None  # type: ignore


@router.post("/query", response_model=ChatResponse)
async def chat_query(
    request: ChatRequest,
    http_request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Process a chat query through the agent system.
    Accepts both authenticated users and unauthenticated guests (when GUEST_MODE_ENABLED=True).
    Guest sessions are stored in memory only and are not persisted to the database.
    """
    if not settings.GUEST_MODE_ENABLED and current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_id = current_user.id if current_user else "guest"
    client_ip: Optional[str] = None

    if user_id == "guest":
        client_ip = http_request.headers.get("X-Forwarded-For", http_request.client.host).split(",")[0].strip()
        _check_guest_rate_limit(client_ip)

    try:
        # Get active orchestrator (MCP if enabled, otherwise legacy)
        active_orchestrator = orchestrator

        result = await active_orchestrator.process_query(
            query=request.message,
            user_id=user_id,
            session_id=request.session_id,
            client_ip=client_ip,
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=result.get("message", "Query processing failed")
            )
        
        # Convert agent_results dict to list for response
        agent_results = result.get("agent_results", {})
        agent_responses_list = [v for k, v in agent_results.items() if isinstance(v, dict)]
        
        return ChatResponse(
            # Full tool output / formatted response (can include markdown images)
            message=result.get("message", "") or result.get("summary", ""),
            # Short LLM summary shown above the full response
            summary=result.get("summary", "") or None,
            session_id=result.get("session_id", ""),
            turn_id=result.get("turn_id"),
            agent_responses=agent_responses_list,
            visualizations=result.get("visualizations", []),
            analyses=result.get("analyses", []),  # Include analysis results
            suggestions=result.get("suggestions", []),
            metadata={
                "datasets": result.get("datasets", []),
                "papers": result.get("papers", [])
            }
        )
        
        
    except Exception as e:
        logger.error(f"Error processing chat query: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    http_request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Process a chat query and return a Server-Sent Events (SSE) stream.
    Accepts both authenticated users and unauthenticated guests (when GUEST_MODE_ENABLED=True).
    Guest sessions are stored in memory only and are not persisted to the database.
    """
    if not settings.GUEST_MODE_ENABLED and current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_id = current_user.id if current_user else "guest"
    client_ip: Optional[str] = None

    if user_id == "guest":
        client_ip = http_request.headers.get("X-Forwarded-For", http_request.client.host).split(",")[0].strip()
        _check_guest_rate_limit(client_ip)

    try:
        active_orchestrator = orchestrator

        # If the orchestrator supports streaming (i.e. LangGraphOrchestrator)
        if hasattr(active_orchestrator, "process_query_stream"):
            return StreamingResponse(
                active_orchestrator.process_query_stream(
                    query=request.message,
                    user_id=user_id,
                    session_id=request.session_id,
                    client_ip=client_ip,
                ),
                media_type="text/event-stream"
            )
        else:
            # Fallback for legacy orchestrator that doesn't support streaming
            async def fake_stream():
                import json
                yield f"data: {json.dumps({'type': 'status', 'content': 'Processing query (Legacy mode)...'})}\n\n"
                result = await active_orchestrator.process_query(
                    query=request.message,
                    user_id=user_id,
                    session_id=request.session_id
                )
                yield f"data: {json.dumps({'type': 'final', 'content': result})}\n\n"

            return StreamingResponse(fake_stream(), media_type="text/event-stream")
            
    except Exception as e:
        logger.error(f"Error starting chat stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def list_sessions(
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    List all chat sessions for the authenticated user
    
    Args:
        current_user: Authenticated user (from JWT token)
    
    Returns:
        List of sessions with titles and timestamps
    """
    try:
        # Guests have no persistent sessions
        if current_user is None:
            return {"sessions": []}

        # Use the active orchestrator (set by main.py)
        active_orchestrator = orchestrator  # This is set by main.py to MCP or legacy
        sessions_list = await active_orchestrator._load_all_sessions_from_db(user_id=current_user.id)
        
        # Sort by last updated (most recent first)
        sessions_list.sort(key=lambda x: x.get("last_updated", 0), reverse=True)
        
        # Convert to API format
        formatted_sessions = []
        for session in sessions_list:
            formatted_sessions.append({
                "session_id": session["id"],
                "title": session.get("title", "New Chat"),
                "created_at": session.get("created_at", 0) * 1000,  # Convert to milliseconds for JavaScript
                "last_updated": session.get("last_updated", 0) * 1000,  # Convert to milliseconds
                "message_count": session.get("message_count", 0)
            })
        
        return {"sessions": formatted_sessions}
        
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get session history from database
    
    Args:
        session_id: Session identifier
        current_user: Authenticated user (from JWT token)
        
    Returns:
        Session history and context
    """
    try:
        # Use the active orchestrator (set by main.py)
        active_orchestrator = orchestrator  # This is set by main.py to MCP or legacy
        # Try memory cache first
        if session_id in active_orchestrator.sessions:
            session = active_orchestrator.sessions[session_id]
            # Verify session belongs to user
            if session.get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
        else:
            # Load from database
            session = await active_orchestrator._load_session_from_db(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            # Verify session belongs to user
            if session.get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
            # Cache in memory
            active_orchestrator.sessions[session_id] = session
        
        return {
            "session_id": session_id,
            "title": session.get("title", "New Chat"),
            "history": session.get("history", []),
            "context": session.get("context", {}),
            "created_at": session.get("created_at", 0),
            "last_updated": session.get("last_updated", 0)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}/history")
async def get_session_history_page(
    session_id: str,
    limit: int = Query(20, ge=1, le=100),
    before: Optional[float] = Query(None, description="Return messages with timestamp < before (unix seconds)."),
    current_user: User = Depends(get_current_user),
):
    """
    Get a paginated slice of session history (for infinite scroll).

    Returns the newest `limit` messages by default. If `before` is provided,
    returns up to `limit` messages older than that timestamp.
    """
    try:
        # Verify session belongs to user
        if settings.DATABASE_URL.startswith("sqlite"):
            db = SessionLocal()
            try:
                db_session = (
                    db.query(ChatSession)
                    .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
                    .first()
                )
                if not db_session:
                    raise HTTPException(status_code=404, detail="Session not found")

                q = db.query(DBChatMessage).filter(DBChatMessage.session_id == session_id)
                if before is not None:
                    q = q.filter(DBChatMessage.timestamp < before)
                # Fetch newest first, then reverse for chronological rendering
                msgs = q.order_by(DBChatMessage.timestamp.desc()).limit(limit + 1).all()
                has_more = len(msgs) > limit
                msgs = msgs[:limit]
                msgs.reverse()

                history = [
                    {
                        "id": m.id,
                        "query": m.query,
                        "response": _sanitize_response_for_history(m.response),
                        "timestamp": m.timestamp,
                    }
                    for m in msgs
                ]
                next_before = history[0]["timestamp"] if history else None
                return {
                    "session_id": session_id,
                    "title": db_session.title or "New Chat",
                    "history": history,
                    "has_more": has_more,
                    "next_before": next_before,
                }
            finally:
                db.close()
        else:
            # PostgreSQL async
            async with SessionLocal() as db:
                result = await db.execute(
                    select(ChatSession).filter(
                        ChatSession.id == session_id, ChatSession.user_id == current_user.id
                    )
                )
                db_session = result.scalar_one_or_none()
                if not db_session:
                    raise HTTPException(status_code=404, detail="Session not found")

                stmt = select(DBChatMessage).filter(DBChatMessage.session_id == session_id)
                if before is not None:
                    stmt = stmt.filter(DBChatMessage.timestamp < before)
                stmt = stmt.order_by(DBChatMessage.timestamp.desc()).limit(limit + 1)
                msgs_result = await db.execute(stmt)
                msgs = list(msgs_result.scalars().all())
                has_more = len(msgs) > limit
                msgs = msgs[:limit]
                msgs.reverse()

                history = [
                    {
                        "id": m.id,
                        "query": m.query,
                        "response": _sanitize_response_for_history(m.response),
                        "timestamp": m.timestamp,
                    }
                    for m in msgs
                ]
                next_before = history[0]["timestamp"] if history else None
                return {
                    "session_id": session_id,
                    "title": db_session.title or "New Chat",
                    "history": history,
                    "has_more": has_more,
                    "next_before": next_before,
                }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session history page: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages/{message_id}")
async def get_chat_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
):
    """
    Fetch a single chat_messages row (query + full response) after verifying ownership.
    Used to lazy-load full tool outputs on demand.
    """
    try:
        if settings.DATABASE_URL.startswith("sqlite"):
            db = SessionLocal()
            try:
                msg = db.query(DBChatMessage).filter(DBChatMessage.id == message_id).first()
                if not msg:
                    raise HTTPException(status_code=404, detail="Message not found")

                # Verify ownership via session.user_id
                sess = (
                    db.query(ChatSession)
                    .filter(ChatSession.id == msg.session_id, ChatSession.user_id == current_user.id)
                    .first()
                )
                if not sess:
                    raise HTTPException(status_code=403, detail="Access denied")

                return {
                    "id": msg.id,
                    "session_id": msg.session_id,
                    "query": msg.query,
                    "response": msg.response,
                    "timestamp": msg.timestamp,
                }
            finally:
                db.close()
        else:
            async with SessionLocal() as db:
                # Load msg
                res = await db.execute(select(DBChatMessage).filter(DBChatMessage.id == message_id))
                msg = res.scalar_one_or_none()
                if not msg:
                    raise HTTPException(status_code=404, detail="Message not found")

                # Verify ownership
                res2 = await db.execute(
                    select(ChatSession).filter(
                        ChatSession.id == msg.session_id, ChatSession.user_id == current_user.id
                    )
                )
                sess = res2.scalar_one_or_none()
                if not sess:
                    raise HTTPException(status_code=403, detail="Access denied")

                return {
                    "id": msg.id,
                    "session_id": msg.session_id,
                    "query": msg.query,
                    "response": msg.response,
                    "timestamp": msg.timestamp,
                }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting chat message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _search_excerpt(q_lower: str, text: str, window: int = 120) -> str:
    """Return a snippet of text centered on the first occurrence of q_lower."""
    idx = text.lower().find(q_lower)
    if idx == -1:
        return text[:200]
    start = max(0, idx - window)
    end = min(len(text), idx + len(q_lower) + window)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


def _build_result(q_lower: str, msg, sess) -> dict | None:
    """
    Return a search result dict only if q_lower appears in the user query or the
    assistant's plain-text message — not in raw JSON structure, base64 blobs, etc.
    """
    resp = msg.response or {}
    response_text = resp.get("message") or ""

    in_query    = q_lower in (msg.query or "").lower()
    in_response = q_lower in response_text.lower()

    if not in_query and not in_response:
        return None   # DB matched JSON junk — discard

    # Prefer showing context from wherever the match actually lives
    if in_query:
        excerpt = _search_excerpt(q_lower, msg.query or "")
    else:
        excerpt = _search_excerpt(q_lower, response_text)

    return {
        "message_id":    msg.id,
        "session_id":    sess.id,
        "session_title": sess.title or "Untitled",
        "query":         msg.query,
        "excerpt":       excerpt,
        "timestamp":     msg.timestamp,
    }


@router.get("/search")
async def search_messages(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(20, le=50),
    current_user: User = Depends(get_current_user),
):
    """
    Search across all chat sessions for a user.
    Searches user queries and assistant response text (not raw JSON metadata).
    Returns up to `limit` results with a contextual excerpt around the match.
    """
    try:
        q_lower = q.strip().lower()
        term = f"%{q}%"
        results = []
        # Fetch more rows than needed to account for post-filtering of JSON false positives
        db_limit = limit * 5

        if settings.DATABASE_URL.startswith("sqlite"):
            db = SessionLocal()
            try:
                rows = (
                    db.query(DBChatMessage, ChatSession)
                    .join(ChatSession, DBChatMessage.session_id == ChatSession.id)
                    .filter(
                        ChatSession.user_id == current_user.id,
                        or_(
                            DBChatMessage.query.ilike(term),
                            cast(DBChatMessage.response, SAText).ilike(term),
                        ),
                    )
                    .order_by(DBChatMessage.timestamp.desc())
                    .limit(db_limit)
                    .all()
                )
                for msg, sess in rows:
                    row = _build_result(q_lower, msg, sess)
                    if row:
                        results.append(row)
                    if len(results) >= limit:
                        break
            finally:
                db.close()
        else:
            async with SessionLocal() as db:
                res = await db.execute(
                    select(DBChatMessage, ChatSession)
                    .join(ChatSession, DBChatMessage.session_id == ChatSession.id)
                    .filter(
                        ChatSession.user_id == current_user.id,
                        or_(
                            DBChatMessage.query.ilike(term),
                            cast(DBChatMessage.response, SAText).ilike(term),
                        ),
                    )
                    .order_by(DBChatMessage.timestamp.desc())
                    .limit(db_limit)
                )
                for msg, sess in res.all():
                    row = _build_result(q_lower, msg, sess)
                    if row:
                        results.append(row)
                    if len(results) >= limit:
                        break

        return {"results": results, "query": q, "count": len(results)}

    except Exception as e:
        logger.error(f"Error searching messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drugtargets/{gene}/{plot_id}")
async def proxy_drugtarget_image(gene: str, plot_id: str):
    """Proxy a drug-target boxplot PNG from targets.linkedomics.org."""
    import re, httpx
    from fastapi.responses import Response
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", gene) or not re.fullmatch(r"[A-Za-z0-9_\-]+", plot_id):
        raise HTTPException(status_code=400, detail="Invalid gene or plot_id")
    url = f"https://targets.linkedomics.org/{gene}/{plot_id}.png"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return Response(content=r.content, media_type="image/png")
    except Exception:
        pass
    raise HTTPException(status_code=404, detail="Plot not found")


@router.get("/visualizations/{viz_id}/png")
async def get_visualization_png(viz_id: str):
    """Serve a plot PNG directly (no auth — IDs are random UUIDs, used by shared session pages)."""
    from fastapi.responses import FileResponse
    paths = resolve_visualization_paths(viz_id)
    png_path = paths.get("png") if paths else None
    if not png_path or not png_path.exists():
        raise HTTPException(status_code=404, detail="Visualization not found")
    return FileResponse(png_path, media_type="image/png")


@router.get("/visualizations/{viz_id}")
async def get_visualization(viz_id: str):
    """Return saved plot data for a visualization ID. No auth required — IDs are random UUIDs."""
    import base64 as _b64
    import json as _json

    paths = resolve_visualization_paths(viz_id)
    if not paths:
        raise HTTPException(status_code=404, detail="Visualization not found")

    json_path = paths.get("json")
    json_data: dict = {}
    if json_path and json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            json_data = _json.load(f)

    # Drug target grid or target search table: all data stored in JSON sidecar
    if json_data.get("type") in ("drug_target_grid", "target_search_table"):
        return {"id": viz_id, **json_data}

    # Network plot: nodes + edges stored in JSON sidecar
    if json_data.get("type") == "network_plot":
        csv = ""
        csv_path = paths.get("csv")
        if csv_path and csv_path.exists():
            with open(csv_path, encoding="utf-8") as f:
                csv = f.read()
        return {
            "type": "network_plot",
            "id": viz_id,
            "title": json_data.get("title", ""),
            "nodes": json_data.get("nodes", []),
            "edges": json_data.get("edges", []),
            "csv": csv,
        }

    # Static plot: PNG required
    png_path = paths.get("png")
    if not png_path or not png_path.exists():
        raise HTTPException(status_code=404, detail="Visualization not found")

    with open(png_path, "rb") as f:
        png_b64 = _b64.b64encode(f.read()).decode()

    title = json_data.get("title", "")

    svg = ""
    svg_path = paths.get("svg")
    if svg_path and svg_path.exists():
        with open(svg_path, encoding="utf-8") as f:
            svg = f.read()

    csv = ""
    csv_path = paths.get("csv")
    if csv_path and csv_path.exists():
        with open(csv_path, encoding="utf-8") as f:
            csv = f.read()

    return {"type": "static_plot", "id": viz_id, "title": title, "png_b64": png_b64, "svg": svg, "csv": csv}


@router.patch("/sessions/{session_id}/title")
async def update_session_title(
    session_id: str,
    request: dict,
    current_user: User = Depends(get_current_user)
):
    """
    Update session title
    
    Args:
        session_id: Session identifier
        request: JSON with "title" field
        current_user: Authenticated user (from JWT token)
        
    Returns:
        Updated session info
    """
    try:
        # Use the active orchestrator (set by main.py)
        active_orchestrator = orchestrator  # This is set by main.py to MCP or legacy
        # Load session if not in memory
        if session_id not in active_orchestrator.sessions:
            session = await active_orchestrator._load_session_from_db(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            # Verify session belongs to user
            if session.get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
            active_orchestrator.sessions[session_id] = session
        else:
            # Verify session belongs to user
            if active_orchestrator.sessions[session_id].get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
        
        new_title = request.get("title", "").strip()
        if not new_title:
            raise HTTPException(status_code=400, detail="Title cannot be empty")
        
        active_orchestrator.sessions[session_id]["title"] = new_title
        
        # Save to database
        active_orchestrator._save_session_to_db(active_orchestrator.sessions[session_id])
        
        return {
            "message": "Title updated",
            "session_id": session_id,
            "title": new_title
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating session title: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def clear_session(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Clear a session from both memory and database
    
    Args:
        session_id: Session identifier
        current_user: Authenticated user (from JWT token)
        
    Returns:
        Success message
    """
    try:
        # Use the active orchestrator (set by main.py)
        active_orchestrator = orchestrator  # This is set by main.py to MCP or legacy
        # Verify session belongs to user before deleting
        if session_id in active_orchestrator.sessions:
            if active_orchestrator.sessions[session_id].get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
            del active_orchestrator.sessions[session_id]
        else:
            # Load from DB to verify ownership
            session = await active_orchestrator._load_session_from_db(session_id)
            if session and session.get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
        
        # Delete from database
        await active_orchestrator._delete_session_from_db(session_id)
        
        return {"message": "Session cleared", "session_id": session_id}

    except Exception as e:
        logger.error(f"Error clearing session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/truncate")
async def truncate_session_from_turn(
    session_id: str,
    request: TurnTruncateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Delete the specified turn and all later turns in a session.
    Intended for "edit and resubmit from here" UX.
    """
    try:
        active_orchestrator = orchestrator

        if session_id in active_orchestrator.sessions:
            if active_orchestrator.sessions[session_id].get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
        else:
            session = await active_orchestrator._load_session_from_db(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if session.get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
            active_orchestrator.sessions[session_id] = session

        stats = await active_orchestrator._truncate_session_from_message(session_id, request.message_id)
        refreshed = await active_orchestrator._load_session_from_db(session_id)
        if refreshed:
            active_orchestrator.sessions[session_id] = refreshed
        elif session_id in active_orchestrator.sessions:
            del active_orchestrator.sessions[session_id]

        return {
            "message": "Session truncated",
            "session_id": session_id,
            **stats,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error truncating session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/share")
async def share_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Generate a public share token for a session.
    Returns a shareable URL that anyone can view without logging in.
    """
    try:
        db = SessionLocal()
        try:
            sess = (
                db.query(ChatSession)
                .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
                .first()
            )
            if not sess:
                raise HTTPException(status_code=404, detail="Session not found")

            if not sess.shared_token:
                sess.shared_token = str(uuid.uuid4())
                db.commit()

            return {"shared_token": sess.shared_token}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sharing session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/shared/{token}")
async def get_shared_session(token: str):
    """
    Public endpoint — returns session messages for a shared token.
    No authentication required.
    """
    try:
        db = SessionLocal()
        try:
            sess = db.query(ChatSession).filter(ChatSession.shared_token == token).first()
            if not sess:
                raise HTTPException(status_code=404, detail="Shared session not found")

            msgs = (
                db.query(DBChatMessage)
                .filter(DBChatMessage.session_id == sess.id)
                .order_by(DBChatMessage.timestamp.asc())
                .all()
            )
            history = [
                {
                    "id": m.id,
                    "query": m.query,
                    "response": m.response,
                    "timestamp": m.timestamp,
                }
                for m in msgs
            ]
            return {
                "session_id": sess.id,
                "title": sess.title or "Shared Research Session",
                "history": history,
                "created_at": sess.created_at,
            }
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching shared session: {e}")
        raise HTTPException(status_code=500, detail=str(e))
