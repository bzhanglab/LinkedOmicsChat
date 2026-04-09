"""
Chat API endpoints
Handles conversational interactions with the agent system
"""
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse
from typing import Optional, Any, Dict
from collections import defaultdict, deque
import logging
import time
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import select, or_, cast, Text as SAText
from models.schemas import ChatRequest, ChatResponse, TurnTruncateRequest, FeedbackRequest
from models.database import User, ChatSession, ChatMessage as DBChatMessage, MessageFeedback
from services.mcp_orchestrator import MCPOrchestrator
from core.config import settings
from core.database import SessionLocal
from core.dependencies import get_current_user, get_current_user_optional

from core.artifacts import resolve_visualization_paths

# ── In-memory sliding-window rate limiters ─────────────────────────────────
# Guest limiter: keyed by client IP address.
# User limiter:  keyed by authenticated user ID.
# Each stores a deque of request timestamps; entries outside the 1-hour window
# are evicted on every check.
_guest_request_log: Dict[str, deque] = defaultdict(deque)
_user_request_log: Dict[str, deque] = defaultdict(deque)

_RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds


def _check_rate_limit(
    key: str,
    log: Dict[str, deque],
    limit: int,
    label: str,
    signup_hint: bool = False,
) -> None:
    """Shared sliding-window rate-limit checker.

    Raises HTTP 429 when ``key`` has reached ``limit`` requests within the last
    hour.  ``label`` is used in the error message; ``signup_hint`` appends the
    account creation suggestion (for guest users).
    """
    now = time.time()
    timestamps = log[key]

    # Evict timestamps outside the sliding window
    while timestamps and now - timestamps[0] > _RATE_LIMIT_WINDOW:
        timestamps.popleft()

    if len(timestamps) >= limit:
        oldest = timestamps[0]
        retry_after = int(_RATE_LIMIT_WINDOW - (now - oldest)) + 1
        minutes = (retry_after + 59) // 60
        wait_msg = f"in about {minutes} minute{'s' if minutes != 1 else ''}" if minutes > 1 else "shortly"
        detail = f"You've reached the limit of {limit} queries per hour. You can try again {wait_msg}."
        if signup_hint:
            detail = (
                f"You've used all {limit} free queries for this hour. "
                f"You can try again {wait_msg}, or create a free account for unlimited access."
            )
        raise HTTPException(
            status_code=429,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )

    timestamps.append(now)


def _check_guest_rate_limit(ip: str) -> None:
    """Raise HTTP 429 if the guest IP has exceeded GUEST_RATE_LIMIT_PER_HOUR.

    Does nothing when GUEST_RATE_LIMIT_ENABLED=False (e.g. NAR review period).
    """
    from core.config import settings
    if not settings.GUEST_RATE_LIMIT_ENABLED:
        return
    _check_rate_limit(ip, _guest_request_log, settings.GUEST_RATE_LIMIT_PER_HOUR, "guest", signup_hint=True)


def _check_user_rate_limit(user_id: str) -> None:
    """Raise HTTP 429 if the authenticated user has exceeded USER_RATE_LIMIT_PER_HOUR.

    Does nothing when USER_RATE_LIMIT_ENABLED=False (default).
    """
    from core.config import settings
    if not settings.USER_RATE_LIMIT_ENABLED:
        return
    _check_rate_limit(str(user_id), _user_request_log, settings.USER_RATE_LIMIT_PER_HOUR, "user")


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
    else:
        _check_user_rate_limit(user_id)

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
            clarification_options=result.get("clarification_options", []),
            tool_sources=result.get("tool_sources", {}),
            tools_used=result.get("tools_used", []),
            no_collapse=result.get("no_collapse"),
            is_general_knowledge=result.get("is_general_knowledge"),
            execution_trace=result.get("execution_trace", []),
            confidence=result.get("confidence"),
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
    else:
        _check_user_rate_limit(user_id)

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
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
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

            return StreamingResponse(
                fake_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
            
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


@router.api_route("/trial-plot", methods=["GET", "POST"])
async def get_trial_plot(request: Request, gene: str = Query(...), study: str = Query(default=""), treatment: str = Query(default=""), plot_type: str = Query(default="gene")):
    """Fetch clinical trial plot data from LinkedOmics Trials and generate matplotlib plots.

    GET (gene / gene_set): fetches per-study boxplot + ROC curve.
    POST (treatment_gene): body must contain {study_list: [...]}, generates grouped strip plot across studies.
    """
    import re, io, base64, httpx

    # ── treatment_gene / treatment_gene_set: POST to /api/plots/treatment_gene[_set] ──
    if plot_type in ("treatment_gene", "treatment_gene_set"):
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", gene):
            raise HTTPException(status_code=400, detail="Invalid gene")
        body = await request.json()
        study_list: list[str] = body.get("study_list", [])
        if not study_list:
            raise HTTPException(status_code=400, detail="study_list required for treatment_gene plots")

        endpoint = (
            "https://trials.linkedomics.org/api/plots/treatment_gene_set"
            if plot_type == "treatment_gene_set"
            else "https://trials.linkedomics.org/api/plots/treatment_gene"
        )
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                endpoint,
                json={"analyte": gene.upper(), "study_list": study_list},
            )
        if r.status_code != 200:
            raise HTTPException(status_code=404, detail="Plot data not available")
        data = r.json()

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        from collections import defaultdict
        from matplotlib.patches import Patch

        violin_raw = data.get("violin_plot", {})
        resp_x = violin_raw.get("responder", {}).get("x", [])
        resp_y = [float(v) for v in violin_raw.get("responder", {}).get("y", []) if v is not None]
        nonresp_x = violin_raw.get("nonresponder", {}).get("x", [])
        nonresp_y = [float(v) for v in violin_raw.get("nonresponder", {}).get("y", []) if v is not None]

        study_names = data.get("study_names", [])
        auc_values = [float(v) for v in data.get("auc_values", []) if v is not None]
        p_values   = [float(v) for v in data.get("p_values", []) if v is not None]

        plots: list[dict] = []

        def _png(fig) -> str:
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
            buf.seek(0)
            b64 = base64.b64encode(buf.read()).decode()
            plt.close(fig)
            return b64

        if not (resp_y or nonresp_y or auc_values):
            pass  # falls through to the 404 below
        else:
            all_studies = study_names if study_names else sorted(set(resp_x + nonresp_x))
            n = len(all_studies)

            resp_by  = defaultdict(list)
            nresp_by = defaultdict(list)
            for xi, yi in zip(resp_x, resp_y):
                resp_by[xi].append(yi)
            for xi, yi in zip(nonresp_x, nonresp_y):
                nresp_by[xi].append(yi)

            has_pvals = len(p_values) == n and n > 0
            has_auc   = len(auc_values) == n and n > 0

            # Sort studies by signed −log(p) from low to high.
            # AUROC plot uses the same order (no re-sort).
            if has_pvals:
                sort_order = sorted(range(n), key=lambda i: p_values[i])
                all_studies = [all_studies[i] for i in sort_order]
                p_values    = [p_values[i]    for i in sort_order]
                if has_auc:
                    auc_values = [auc_values[i] for i in sort_order]

            xlabels = [s.removesuffix(".csv") for s in all_studies]

            # ── single figure: top row = bar charts, bottom row = violin ─────
            fig_w = max(10, n * 1.8 + 2)
            fig = plt.figure(figsize=(fig_w, 9), facecolor="white")
            gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.4], hspace=0.65, wspace=0.28,
                                  left=0.07, right=0.97, top=0.93, bottom=0.10)

            ax_p   = fig.add_subplot(gs[0, 0])
            ax_auc = fig.add_subplot(gs[0, 1])
            ax_vio = fig.add_subplot(gs[1, :])

            bar_w = max(0.3, min(0.65, 4.0 / max(n, 1)))
            auc_colors = ["#f97316" if v > 0.5 else "#3b82f6" for v in auc_values]
            p_colors   = ["#f97316" if v > 0 else "#3b82f6" for v in p_values]

            # p-value bars
            if has_pvals:
                ax_p.bar(range(n), p_values, color=p_colors, alpha=0.8, width=bar_w)
            ax_p.axhline(0, color="black", linewidth=0.8)
            ax_p.set_xticks(range(n))
            ax_p.set_xticklabels(xlabels, fontsize=max(5, min(8, 60 // max(n, 1))),
                                 rotation=0 if n <= 6 else 45, ha="center" if n <= 6 else "right")
            ax_p.set_xlabel("", fontsize=9)
            ax_p.set_ylabel("−log(|p|)×sign(p)", fontsize=9)
            ax_p.set_title(f"P-value ranked based on {gene}", fontsize=10)
            ax_p.yaxis.grid(True, linewidth=0.4, alpha=0.5)
            ax_p.set_axisbelow(True)
            for sp in ("top", "right"): ax_p.spines[sp].set_visible(False)

            # AUROC bars centered at the no-signal baseline (0.5):
            # values < 0.5 extend downward, values > 0.5 extend upward.
            if has_auc:
                auc_centered = [v - 0.5 for v in auc_values]
                ax_auc.bar(
                    range(n),
                    auc_centered,
                    bottom=0.5,
                    color=auc_colors,
                    alpha=0.8,
                    width=bar_w,
                )
            ax_auc.axhline(0.5, color="black", linewidth=1)
            ax_auc.set_xticks(range(n))
            ax_auc.set_xticklabels(xlabels, fontsize=max(5, min(8, 60 // max(n, 1))),
                                   rotation=0 if n <= 6 else 45, ha="center" if n <= 6 else "right")
            ax_auc.set_xlabel("", fontsize=9)
            ax_auc.set_ylabel("AUROC", fontsize=9)
            ax_auc.set_title(f"AUROC ranked based on {gene}", fontsize=10)
            if has_auc:
                max_delta = max(abs(v - 0.5) for v in auc_values)
                margin = max(0.03, max_delta * 0.18)
                span = min(0.5, max_delta + margin)
                ax_auc.set_ylim(0.5 - span, 0.5 + span)
            ax_auc.yaxis.grid(True, linewidth=0.4, alpha=0.5)
            ax_auc.set_axisbelow(True)
            for sp in ("top", "right"): ax_auc.spines[sp].set_visible(False)

            # violin + embedded boxplot
            offset = 0.22
            vio_w  = max(0.18, min(0.38, 1.6 / max(n, 1)))
            box_w  = vio_w * 0.45

            vio_kw = dict(showmedians=False, showextrema=False)
            box_kw = dict(
                patch_artist=True, manage_ticks=False, widths=box_w,
                medianprops={"color": "black", "linewidth": 1.8},
                whiskerprops={"linewidth": 1.0, "color": "black"},
                capprops={"linewidth": 1.0, "color": "black"},
                flierprops={"marker": "o", "markersize": 2, "alpha": 0.4,
                            "markeredgewidth": 0, "markerfacecolor": "gray"},
                boxprops={"linewidth": 0.8},
            )

            for sn, pos in zip(all_studies, [i - offset for i in range(n)]):
                vals = resp_by.get(sn, [])
                if len(vals) >= 3:
                    parts = ax_vio.violinplot([vals], positions=[pos], widths=vio_w * 2, **vio_kw)
                    for pc in parts["bodies"]:
                        pc.set_facecolor("#3b82f6"); pc.set_alpha(0.55)
                if vals:
                    bp = ax_vio.boxplot([vals or [np.nan]], positions=[pos], **box_kw)
                    for patch in bp["boxes"]:
                        patch.set_facecolor("white"); patch.set_alpha(0.6)

            for sn, pos in zip(all_studies, [i + offset for i in range(n)]):
                vals = nresp_by.get(sn, [])
                if len(vals) >= 3:
                    parts = ax_vio.violinplot([vals], positions=[pos], widths=vio_w * 2, **vio_kw)
                    for pc in parts["bodies"]:
                        pc.set_facecolor("#f97316"); pc.set_alpha(0.55)
                if vals:
                    bp = ax_vio.boxplot([vals or [np.nan]], positions=[pos], **box_kw)
                    for patch in bp["boxes"]:
                        patch.set_facecolor("white"); patch.set_alpha(0.6)

            ax_vio.set_xticks(range(n))
            ax_vio.set_xticklabels(xlabels, fontsize=max(5, min(8, 60 // max(n, 1))),
                                   rotation=0 if n <= 6 else 30, ha="center" if n <= 6 else "right")
            ax_vio.set_xlim(-0.65, n - 0.35)
            ax_vio.set_ylabel("Gene Expression", fontsize=9)
            ax_vio.yaxis.grid(True, linewidth=0.4, alpha=0.5)
            ax_vio.set_axisbelow(True)
            for sp in ("top", "right"): ax_vio.spines[sp].set_visible(False)

            legend_handles = [
                Patch(facecolor="#3b82f6", alpha=0.7, label="Responder"),
                Patch(facecolor="#f97316", alpha=0.7, label="Non-responder"),
            ]
            ax_vio.legend(handles=legend_handles, fontsize=9, frameon=False, loc="upper right")

            plots.append({"png_b64": _png(fig), "title": f"{gene} — Expression & Statistics"})

        if not plots:
            raise HTTPException(status_code=404, detail="No plottable data in response")
        return {"plots": plots, "gene": gene, "study": gene}

    # ── gene / gene_set (existing GET path) ──────────────────────────────────
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", gene) or not re.fullmatch(r"[A-Za-z0-9_\-\.]+", study):
        raise HTTPException(status_code=400, detail="Invalid gene or study")

    study_bare = study.removesuffix(".csv")
    api_segment = "gene_set" if plot_type == "gene_set" else "gene"

    async def _fetch_plot(client: httpx.AsyncClient, study_id_bare: str) -> dict | None:
        """Fetch plot JSON for a given study ID stem. Returns None if empty or failed."""
        # Encode the dot so the server treats the whole name as a path segment, not a file
        url = f"https://trials.linkedomics.org/api/plots/{api_segment}/{gene}/{study_id_bare}%2Ecsv"
        try:
            r = await client.get(url, headers={"Accept": "application/json"})
        except Exception:
            return None
        if r.status_code != 200:
            return None
        try:
            d = r.json()
        except Exception:
            return None
        # Treat response as empty if both plot arrays are empty
        if not d.get("boxplot", {}).get("responder") and not d.get("aucplot", {}).get("x"):
            return None
        return d

    async def _resolve_study_ids(client: httpx.AsyncClient, series: str) -> list[str]:
        """Look up all study_ids sharing this series name, sorted by treatment similarity."""
        try:
            table_url = (
                f"https://trials.linkedomics.org/api/table/gene_set/{gene}"
                if plot_type == "gene_set"
                else f"https://trials.linkedomics.org/api/table/gene/{gene}"
            )
            r = await client.get(table_url, timeout=15)
            if r.status_code != 200:
                return [series]
            rows = r.json()
            candidates = [
                row for row in rows
                if isinstance(row, dict)
                and row.get("series") == series
                and row.get("study_id")
            ]
            if not candidates:
                return [series]
            # Sort by treatment similarity: exact match wins, then token overlap.
            # This correctly disambiguates e.g. "...trebananib" vs "...veliparib"
            # even when they share a long common prefix.
            if treatment:
                treat_norm = treatment.lower().replace(",", " ")
                treat_tokens = set(treat_norm.split())
                def _score(row: dict) -> tuple[int, int]:
                    row_treat = (row.get("treatment") or "").lower().replace(",", " ")
                    exact = 1 if treat_norm == row_treat else 0
                    overlap = len(treat_tokens & set(row_treat.split()))
                    return (exact, overlap)
                candidates.sort(key=_score, reverse=True)
            return [row["study_id"].removesuffix(".csv") for row in candidates]
        except Exception:
            return [series]

    async with httpx.AsyncClient(timeout=30) as client:
        data = await _fetch_plot(client, study_bare)

        # If no data, look up all study_ids that share this series name and try each one.
        # This handles both bare series names (e.g. "GSE20271") and full IDs that happen
        # to return empty data.
        if data is None:
            study_ids = await _resolve_study_ids(client, study_bare)
            for sid in study_ids:
                if sid != study_bare:
                    data = await _fetch_plot(client, sid)
                    if data is not None:
                        study_bare = sid
                        break

    if data is None:
        raise HTTPException(status_code=404, detail="Plot data not available")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plots: list[dict] = []

    def _png(fig) -> str:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode()
        plt.close(fig)
        return b64

    # ── Box plot: responder vs non-responder expression ───────────────────────
    bp_data = data.get("boxplot", {})
    responder = [float(v) for v in bp_data.get("responder", []) if v is not None]
    nonresponder = [float(v) for v in bp_data.get("nonresponder", []) if v is not None]

    if responder or nonresponder:
        groups = []
        tick_labels = []
        colors = []
        if responder:
            groups.append(responder)
            tick_labels.append(f"Responder\n(n={len(responder)})")
            colors.append("#3b82f6")
        if nonresponder:
            groups.append(nonresponder)
            tick_labels.append(f"Non-responder\n(n={len(nonresponder)})")
            colors.append("#f97316")

        fig, ax = plt.subplots(figsize=(5, 5))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")
        bp = ax.boxplot(groups, labels=tick_labels, patch_artist=True, widths=0.5,
                        medianprops={"color": "black", "linewidth": 2},
                        whiskerprops={"linewidth": 1.2},
                        capprops={"linewidth": 1.2},
                        flierprops={"marker": "o", "markersize": 3, "alpha": 0.4, "markeredgewidth": 0})
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)
        ax.set_title(f"{gene} expression\n{study_bare}", fontsize=10, pad=8)
        ax.set_ylabel("Expression level", fontsize=9)
        ax.tick_params(axis="x", labelsize=9)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout()
        plots.append({"png_b64": _png(fig), "title": "Expression by Response"})

    # ── ROC / AUC curve ───────────────────────────────────────────────────────
    auc_data = data.get("aucplot", {})
    x_vals = [float(v) for v in auc_data.get("x", []) if v is not None]
    y_vals = [float(v) for v in auc_data.get("y", []) if v is not None]

    if len(x_vals) > 1 and len(y_vals) > 1:
        auc_score = float(np.trapz(y_vals, x_vals)) if len(x_vals) == len(y_vals) else None
        auc_label = f"AUC = {abs(auc_score):.3f}" if auc_score is not None else ""
        fig, ax = plt.subplots(figsize=(5, 5))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")
        ax.fill_between(x_vals, y_vals, alpha=0.12, color="#6366f1")
        ax.plot(x_vals, y_vals, color="#6366f1", linewidth=2, label=auc_label)
        ax.plot([0, 1], [0, 1], "--", color="#9ca3af", linewidth=1)
        ax.set_title(f"ROC Curve\n{study_bare}", fontsize=10, pad=8)
        ax.set_xlabel("1 − Specificity", fontsize=9)
        ax.set_ylabel("Sensitivity", fontsize=9)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        if auc_label:
            ax.legend(fontsize=9, frameon=False, loc="lower right")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout()
        plots.append({"png_b64": _png(fig), "title": "ROC Curve"})

    if not plots:
        raise HTTPException(status_code=404, detail="No plottable data in response")

    return {"plots": plots, "gene": gene, "study": study_bare, "resolved_study_id": study_bare}


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

    # JSON-backed interactive visualizations
    if json_data.get("type") in ("drug_target_grid", "target_search_table", "predictive_results_table"):
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


@router.post("/feedback")
async def submit_feedback(
    feedback: FeedbackRequest,
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Record thumbs-up / thumbs-down feedback on an assistant response."""
    if feedback.rating not in (1, -1):
        raise HTTPException(status_code=422, detail="rating must be 1 (up) or -1 (down)")

    db: Session = SessionLocal()
    try:
        record = MessageFeedback(
            turn_id=feedback.turn_id,
            session_id=feedback.session_id,
            user_id=current_user.id if current_user else None,
            rating=feedback.rating,
            reason=feedback.reason,
            timestamp=time.time(),
        )
        db.add(record)
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving feedback: {e}")
        raise HTTPException(status_code=500, detail="Failed to save feedback")
    finally:
        db.close()
