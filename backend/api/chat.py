"""
Chat API endpoints
Handles conversational interactions with the agent system
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
import logging
from sqlalchemy.orm import Session

from models.schemas import ChatRequest, ChatResponse
from models.database import User
from services.agent_orchestrator import AgentOrchestrator
from core.database import get_db
from core.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()
orchestrator = AgentOrchestrator()


@router.post("/query", response_model=ChatResponse)
async def chat_query(
    request: ChatRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Process a chat query through the agent system
    
    Args:
        request: Chat request with message and optional session_id
        current_user: Authenticated user (from JWT token)
        
    Returns:
        ChatResponse with agent results and visualizations
    """
    try:
        # Initialize orchestrator if needed
        if not orchestrator.agents:
            await orchestrator.initialize()
        
        # Process query with authenticated user_id
        result = await orchestrator.process_query(
            query=request.message,
            user_id=current_user.id,
            session_id=request.session_id
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
            message=result.get("summary", ""),
            session_id=result.get("session_id", ""),
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


@router.get("/sessions")
async def list_sessions(
    current_user: User = Depends(get_current_user)
):
    """
    List all chat sessions for the authenticated user
    
    Args:
        current_user: Authenticated user (from JWT token)
    
    Returns:
        List of sessions with titles and timestamps
    """
    try:
        sessions_list = await orchestrator._load_all_sessions_from_db(user_id=current_user.id)
        
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
        # Try memory cache first
        if session_id in orchestrator.sessions:
            session = orchestrator.sessions[session_id]
            # Verify session belongs to user
            if session.get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
        else:
            # Load from database
            session = await orchestrator._load_session_from_db(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            # Verify session belongs to user
            if session.get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
            # Cache in memory
            orchestrator.sessions[session_id] = session
        
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
        # Load session if not in memory
        if session_id not in orchestrator.sessions:
            session = await orchestrator._load_session_from_db(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            # Verify session belongs to user
            if session.get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
            orchestrator.sessions[session_id] = session
        else:
            # Verify session belongs to user
            if orchestrator.sessions[session_id].get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
        
        new_title = request.get("title", "").strip()
        if not new_title:
            raise HTTPException(status_code=400, detail="Title cannot be empty")
        
        orchestrator.sessions[session_id]["title"] = new_title
        
        # Save to database
        orchestrator._save_session_to_db(orchestrator.sessions[session_id])
        
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
        # Verify session belongs to user before deleting
        if session_id in orchestrator.sessions:
            if orchestrator.sessions[session_id].get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
            del orchestrator.sessions[session_id]
        else:
            # Load from DB to verify ownership
            session = await orchestrator._load_session_from_db(session_id)
            if session and session.get("user_id") != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
        
        # Delete from database
        await orchestrator._delete_session_from_db(session_id)
        
        return {"message": "Session cleared", "session_id": session_id}
        
    except Exception as e:
        logger.error(f"Error clearing session: {e}")
        raise HTTPException(status_code=500, detail=str(e))
