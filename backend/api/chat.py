"""
Chat API endpoints
Handles conversational interactions with the agent system
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
import logging
from sqlalchemy.orm import Session

from models.schemas import ChatRequest, ChatResponse
from services.agent_orchestrator import AgentOrchestrator
from core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()
orchestrator = AgentOrchestrator()


@router.post("/query", response_model=ChatResponse)
async def chat_query(request: ChatRequest):
    """
    Process a chat query through the agent system
    
    Args:
        request: Chat request with message and optional session_id
        
    Returns:
        ChatResponse with agent results and visualizations
    """
    try:
        # Initialize orchestrator if needed
        if not orchestrator.agents:
            await orchestrator.initialize()
        
        # Process query
        result = await orchestrator.process_query(
            query=request.message,
            user_id="default_user",
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
async def list_sessions():
    """
    List all chat sessions with metadata from database
    
    Returns:
        List of sessions with titles and timestamps
    """
    try:
        sessions_list = await orchestrator._load_all_sessions_from_db()
        
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
async def get_session(session_id: str):
    """
    Get session history from database
    
    Args:
        session_id: Session identifier
        
    Returns:
        Session history and context
    """
    try:
        # Try memory cache first
        if session_id in orchestrator.sessions:
            session = orchestrator.sessions[session_id]
        else:
            # Load from database
            session = orchestrator._load_session_from_db(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
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
async def update_session_title(session_id: str, request: dict):
    """
    Update session title
    
    Args:
        session_id: Session identifier
        request: JSON with "title" field
        
    Returns:
        Updated session info
    """
    try:
        # Load session if not in memory
        if session_id not in orchestrator.sessions:
            session = orchestrator._load_session_from_db(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            orchestrator.sessions[session_id] = session
        
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
async def clear_session(session_id: str):
    """
    Clear a session from both memory and database
    
    Args:
        session_id: Session identifier
        
    Returns:
        Success message
    """
    try:
        # Delete from memory
        if session_id in orchestrator.sessions:
            del orchestrator.sessions[session_id]
        
        # Delete from database
        orchestrator._delete_session_from_db(session_id)
        
        return {"message": "Session cleared", "session_id": session_id}
        
    except Exception as e:
        logger.error(f"Error clearing session: {e}")
        raise HTTPException(status_code=500, detail=str(e))
