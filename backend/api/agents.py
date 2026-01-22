"""
Agents API endpoints
Direct access to individual agents
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
import logging

from agents import (
    DataCurationAgent,
    StatisticalAnalysisAgent,
    VisualizationAgent,
    LiteratureMiningAgent
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize agents
agents = {
    "data": DataCurationAgent(),
    "analysis": StatisticalAnalysisAgent(),
    "visualization": VisualizationAgent(),
    "literature": LiteratureMiningAgent()
}


@router.get("/")
async def list_agents():
    """List available agents and their descriptions"""
    return {
        "agents": [
            {
                "id": "data",
                "name": agent.name,
                "description": agent.description
            }
            for agent_id, agent in agents.items()
        ]
    }


@router.post("/{agent_id}/process")
async def process_with_agent(
    agent_id: str,
    request: Dict[str, Any]
):
    """
    Process a request with a specific agent
    
    Args:
        agent_id: Agent identifier (data, analysis, visualization, literature)
        request: Request containing 'query' and optional 'context'
        
    Returns:
        Agent-specific response
    """
    try:
        if agent_id not in agents:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{agent_id}' not found"
            )
        
        agent = agents[agent_id]
        query = request.get("query")
        context = request.get("context")
        
        if not query:
            raise HTTPException(
                status_code=400,
                detail="Missing 'query' in request"
            )
        
        result = await agent.process(query, context)
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing with agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{agent_id}/status")
async def get_agent_status(agent_id: str):
    """Get status of a specific agent"""
    try:
        if agent_id not in agents:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{agent_id}' not found"
            )
        
        agent = agents[agent_id]
        return {
            "agent_id": agent_id,
            "name": agent.name,
            "status": "operational",
            "model": agent.model,
            "temperature": agent.temperature
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
