"""
Admin dashboard API endpoints.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select

from core.config import settings
from core.database import SessionLocal
from core.dependencies import get_current_admin_user
from models.database import (
    ChatMessage as DBChatMessage,
    ChatSession,
    GuestTokenUsage,
    MessageFeedback,
    TokenUsage,
    User,
)
from models.schemas import AdminDashboardResponse

router = APIRouter()

_NO_DATA_PREFIX = "No matching data was returned by the requested tools."


def _date_key(timestamp: float) -> str:
    return datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")


def _short_preview(text: str, max_chars: int = 120) -> str:
    stripped = (text or "").strip().replace("\n", " ")
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 1].rstrip() + "..."


def _normalized_tool_name(tool: str) -> str:
    base = (tool or "").replace("__", "::").rsplit("#", 1)[0]
    return base.split("::")[-1] if "::" in base else base


def _response_payload(message: DBChatMessage) -> Dict[str, Any]:
    return message.response if isinstance(message.response, dict) else {}


def _build_dashboard_payload(
    *,
    users: List[User],
    sessions: List[ChatSession],
    messages: List[DBChatMessage],
    token_usage_rows: List[TokenUsage],
    guest_usage_rows: List[GuestTokenUsage],
    feedback_rows: List[MessageFeedback],
) -> Dict[str, Any]:
    users_by_id = {user.id: user for user in users}
    sessions_by_id = {session.id: session for session in sessions}
    messages_by_id = {message.id: message for message in messages}

    overview_input_tokens = sum(int(row.input_tokens or 0) for row in token_usage_rows + guest_usage_rows)
    overview_output_tokens = sum(int(row.output_tokens or 0) for row in token_usage_rows + guest_usage_rows)
    positive_feedback = sum(1 for row in feedback_rows if row.rating == 1)
    negative_feedback = sum(1 for row in feedback_rows if row.rating == -1)
    total_feedback = len(feedback_rows)

    quality_counts = {
        "low_confidence_responses": 0,
        "partial_confidence_responses": 0,
        "general_knowledge_responses": 0,
        "no_data_responses": 0,
    }
    tool_counter: Counter[str] = Counter()

    daily_rollup: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "active_users": set(),
            "registered_queries": 0,
            "guest_queries": 0,
            "feedback_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "registered_input_tokens": 0,
            "registered_output_tokens": 0,
            "guest_input_tokens": 0,
            "guest_output_tokens": 0,
        }
    )

    user_rollup: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "queries": 0,
            "sessions": set(),
            "input_tokens": 0,
            "output_tokens": 0,
            "last_seen_at": None,
        }
    )

    for message in messages:
        session = sessions_by_id.get(message.session_id)
        payload = _response_payload(message)
        day_key = _date_key(float(message.timestamp or 0))
        daily_rollup[day_key]["registered_queries"] += 1
        if session and session.user_id:
            daily_rollup[day_key]["active_users"].add(session.user_id)
            rollup = user_rollup[session.user_id]
            rollup["queries"] += 1
            rollup["sessions"].add(message.session_id)
            rollup["last_seen_at"] = max(
                float(message.timestamp or 0),
                float(rollup["last_seen_at"] or 0),
            )

        confidence = payload.get("confidence")
        if confidence == "low":
            quality_counts["low_confidence_responses"] += 1
        elif confidence == "partial":
            quality_counts["partial_confidence_responses"] += 1
        if confidence == "general_knowledge" or payload.get("is_general_knowledge") is True:
            quality_counts["general_knowledge_responses"] += 1

        message_text = str(payload.get("message") or "")
        if message_text.startswith(_NO_DATA_PREFIX):
            quality_counts["no_data_responses"] += 1

        for tool in payload.get("tools_used") or []:
            tool_counter[_normalized_tool_name(str(tool))] += 1

    model_rollup: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"queries": 0, "input_tokens": 0, "output_tokens": 0}
    )

    for row in token_usage_rows:
        day_key = _date_key(float(row.timestamp or 0))
        daily_rollup[day_key]["input_tokens"] += int(row.input_tokens or 0)
        daily_rollup[day_key]["output_tokens"] += int(row.output_tokens or 0)
        daily_rollup[day_key]["registered_input_tokens"] += int(row.input_tokens or 0)
        daily_rollup[day_key]["registered_output_tokens"] += int(row.output_tokens or 0)
        model_name = str(row.model or "unknown")
        model_rollup[model_name]["queries"] += 1
        model_rollup[model_name]["input_tokens"] += int(row.input_tokens or 0)
        model_rollup[model_name]["output_tokens"] += int(row.output_tokens or 0)
        if row.user_id:
            rollup = user_rollup[row.user_id]
            rollup["input_tokens"] += int(row.input_tokens or 0)
            rollup["output_tokens"] += int(row.output_tokens or 0)
            rollup["last_seen_at"] = max(
                float(row.timestamp or 0),
                float(rollup["last_seen_at"] or 0),
            )

    for row in guest_usage_rows:
        day_key = _date_key(float(row.timestamp or 0))
        daily_rollup[day_key]["guest_queries"] += 1
        daily_rollup[day_key]["input_tokens"] += int(row.input_tokens or 0)
        daily_rollup[day_key]["output_tokens"] += int(row.output_tokens or 0)
        daily_rollup[day_key]["guest_input_tokens"] += int(row.input_tokens or 0)
        daily_rollup[day_key]["guest_output_tokens"] += int(row.output_tokens or 0)
        model_name = str(row.model or "unknown")
        model_rollup[model_name]["queries"] += 1
        model_rollup[model_name]["input_tokens"] += int(row.input_tokens or 0)
        model_rollup[model_name]["output_tokens"] += int(row.output_tokens or 0)

    feedback_by_query: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"positive_count": 0, "negative_count": 0, "total_count": 0}
    )
    latest_feedback_by_turn: Dict[int, MessageFeedback] = {}

    for row in sorted(feedback_rows, key=lambda item: float(item.timestamp or 0)):
        day_key = _date_key(float(row.timestamp or 0))
        daily_rollup[day_key]["feedback_count"] += 1

        if row.turn_id is not None:
            latest_feedback_by_turn[row.turn_id] = row

        linked_message = messages_by_id.get(row.turn_id) if row.turn_id is not None else None
        query_text = _short_preview(linked_message.query if linked_message else "Unlinked turn", max_chars=140)
        aggregate = feedback_by_query[query_text]
        aggregate["total_count"] += 1
        if row.rating == 1:
            aggregate["positive_count"] += 1
        elif row.rating == -1:
            aggregate["negative_count"] += 1

    recent_feedback = []
    for row in sorted(feedback_rows, key=lambda item: float(item.timestamp or 0), reverse=True)[:12]:
        linked_message = messages_by_id.get(row.turn_id) if row.turn_id is not None else None
        payload = _response_payload(linked_message) if linked_message else {}
        user = users_by_id.get(row.user_id) if row.user_id else None
        if user is None and linked_message is not None:
            session = sessions_by_id.get(linked_message.session_id)
            if session:
                user = users_by_id.get(session.user_id)
        recent_feedback.append(
            {
                "id": row.id,
                "timestamp": float(row.timestamp or 0),
                "rating": int(row.rating or 0),
                "reason": row.reason,
                "turn_id": row.turn_id,
                "session_id": row.session_id or (linked_message.session_id if linked_message else None),
                "username": user.username if user else None,
                "email": user.email if user else None,
                "query_preview": _short_preview(linked_message.query if linked_message else "Unlinked turn"),
                "message_preview": _short_preview(str(payload.get("summary") or payload.get("message") or "")),
            }
        )

    top_feedback_targets = [
        {"query": query, **counts}
        for query, counts in sorted(
            feedback_by_query.items(),
            key=lambda item: (item[1]["negative_count"], item[1]["total_count"]),
            reverse=True,
        )[:10]
    ]

    recent_turns = []
    for message in sorted(messages, key=lambda item: float(item.timestamp or 0), reverse=True)[:12]:
        payload = _response_payload(message)
        session = sessions_by_id.get(message.session_id)
        user = users_by_id.get(session.user_id) if session else None
        latest_feedback = latest_feedback_by_turn.get(message.id)
        recent_turns.append(
            {
                "turn_id": message.id,
                "timestamp": float(message.timestamp or 0),
                "username": user.username if user else None,
                "email": user.email if user else None,
                "query_preview": _short_preview(message.query, max_chars=140),
                "message_preview": _short_preview(str(payload.get("summary") or payload.get("message") or "")),
                "confidence": payload.get("confidence"),
                "tools_used": [_normalized_tool_name(str(tool)) for tool in (payload.get("tools_used") or [])],
                "feedback_rating": latest_feedback.rating if latest_feedback else None,
            }
        )

    top_users = []
    for user in users:
        rollup = user_rollup[user.id]
        top_users.append(
            {
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "queries": int(rollup["queries"]),
                "sessions": len(rollup["sessions"]),
                "input_tokens": int(rollup["input_tokens"]),
                "output_tokens": int(rollup["output_tokens"]),
                "total_tokens": int(rollup["input_tokens"]) + int(rollup["output_tokens"]),
                "last_seen_at": float(rollup["last_seen_at"]) if rollup["last_seen_at"] else None,
            }
        )
    top_users.sort(key=lambda item: (item["total_tokens"], item["queries"]), reverse=True)

    model_usage = []
    for model, counts in sorted(
        model_rollup.items(),
        key=lambda item: item[1]["input_tokens"] + item[1]["output_tokens"],
        reverse=True,
    ):
        model_usage.append(
            {
                "model": model,
                "queries": counts["queries"],
                "input_tokens": counts["input_tokens"],
                "output_tokens": counts["output_tokens"],
                "total_tokens": counts["input_tokens"] + counts["output_tokens"],
            }
        )

    sorted_days = sorted(daily_rollup.items())
    daily_activity = []
    for day, values in sorted_days:
        daily_activity.append(
            {
                "date": day,
                "active_users": len(values["active_users"]),
                "registered_queries": values["registered_queries"],
                "guest_queries": values["guest_queries"],
                "feedback_count": values["feedback_count"],
                "input_tokens": values["input_tokens"],
                "output_tokens": values["output_tokens"],
                "registered_input_tokens": values["registered_input_tokens"],
                "registered_output_tokens": values["registered_output_tokens"],
                "guest_input_tokens": values["guest_input_tokens"],
                "guest_output_tokens": values["guest_output_tokens"],
            }
        )

    overview = {
        "total_users": len(users),
        "active_users": sum(1 for user in users if user.is_active),
        "total_sessions": len(sessions),
        "total_messages": len(messages),
        "total_registered_queries": len(messages),
        "total_guest_queries": len(guest_usage_rows),
        "total_queries": len(messages) + len(guest_usage_rows),
        "total_feedback": total_feedback,
        "positive_feedback": positive_feedback,
        "negative_feedback": negative_feedback,
        "positive_feedback_rate": round((positive_feedback / total_feedback) * 100, 1) if total_feedback else 0.0,
        "total_input_tokens": overview_input_tokens,
        "total_output_tokens": overview_output_tokens,
        "total_tokens": overview_input_tokens + overview_output_tokens,
    }

    return {
        "generated_at": datetime.utcnow().timestamp(),
        "overview": overview,
        "quality_signals": quality_counts,
        "daily_activity": daily_activity,
        "model_usage": model_usage[:10],
        "top_users": top_users[:10],
        "recent_feedback": recent_feedback,
        "top_feedback_targets": top_feedback_targets,
        "tool_usage": [{"tool": tool, "count": count} for tool, count in tool_counter.most_common(12)],
        "recent_turns": recent_turns,
    }


async def _load_all_rows_async() -> Dict[str, List[Any]]:
    async with SessionLocal() as db:
        users = list((await db.execute(select(User))).scalars().all())
        sessions = list((await db.execute(select(ChatSession))).scalars().all())
        messages = list((await db.execute(select(DBChatMessage))).scalars().all())
        token_usage_rows = list((await db.execute(select(TokenUsage))).scalars().all())
        guest_usage_rows = list((await db.execute(select(GuestTokenUsage))).scalars().all())
        feedback_rows = list((await db.execute(select(MessageFeedback))).scalars().all())
    return {
        "users": users,
        "sessions": sessions,
        "messages": messages,
        "token_usage_rows": token_usage_rows,
        "guest_usage_rows": guest_usage_rows,
        "feedback_rows": feedback_rows,
    }


def _load_all_rows_sync() -> Dict[str, List[Any]]:
    db = SessionLocal()
    try:
        return {
            "users": list(db.query(User).all()),
            "sessions": list(db.query(ChatSession).all()),
            "messages": list(db.query(DBChatMessage).all()),
            "token_usage_rows": list(db.query(TokenUsage).all()),
            "guest_usage_rows": list(db.query(GuestTokenUsage).all()),
            "feedback_rows": list(db.query(MessageFeedback).all()),
        }
    finally:
        db.close()


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def get_admin_dashboard(
    _: User = Depends(get_current_admin_user),
):
    """Return read-only usage, feedback, and quality metrics for admins."""
    if settings.DATABASE_URL.startswith("sqlite"):
        rows = _load_all_rows_sync()
    else:
        rows = await _load_all_rows_async()
    return _build_dashboard_payload(**rows)
