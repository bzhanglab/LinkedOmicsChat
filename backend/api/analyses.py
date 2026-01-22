"""
Analyses API endpoints
Create and manage analysis jobs
"""
from fastapi import APIRouter, HTTPException
from typing import List, Optional
import logging
from datetime import datetime
import uuid

from models.schemas import AnalysisRequest, AnalysisResult

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory storage for demo (use database in production)
analyses_store = {}


@router.post("/", response_model=AnalysisResult)
async def create_analysis(request: AnalysisRequest):
    """
    Create a new analysis job
    
    Args:
        request: Analysis request with type, datasets, and parameters
        
    Returns:
        Analysis result with ID
    """
    try:
        analysis_id = str(uuid.uuid4())
        
        # Mock analysis execution
        result = AnalysisResult(
            id=analysis_id,
            analysis_type=request.analysis_type,
            status="completed",
            results={
                "summary": f"Completed {request.analysis_type} analysis",
                "datasets": request.dataset_ids,
                "parameters": request.parameters
            },
            visualizations=[
                {
                    "type": "scatter",
                    "title": f"{request.analysis_type} Results"
                }
            ],
            statistics={
                "n_samples": 100,
                "n_features": 1000,
                "significant_features": 50
            },
            created_at=datetime.now(),
            completed_at=datetime.now()
        )
        
        analyses_store[analysis_id] = result
        return result
        
    except Exception as e:
        logger.error(f"Error creating analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{analysis_id}", response_model=AnalysisResult)
async def get_analysis(analysis_id: str):
    """
    Get analysis results by ID
    
    Args:
        analysis_id: Analysis identifier
        
    Returns:
        Analysis results
    """
    try:
        if analysis_id not in analyses_store:
            raise HTTPException(status_code=404, detail="Analysis not found")
        
        return analyses_store[analysis_id]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=List[AnalysisResult])
async def list_analyses(
    status: Optional[str] = None,
    analysis_type: Optional[str] = None
):
    """
    List all analyses with optional filters
    
    Args:
        status: Filter by status
        analysis_type: Filter by analysis type
        
    Returns:
        List of analyses
    """
    try:
        results = list(analyses_store.values())
        
        if status:
            results = [r for r in results if r.status == status]
        
        if analysis_type:
            results = [r for r in results if r.analysis_type == analysis_type]
        
        return results
        
    except Exception as e:
        logger.error(f"Error listing analyses: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{analysis_id}")
async def delete_analysis(analysis_id: str):
    """
    Delete an analysis
    
    Args:
        analysis_id: Analysis identifier
        
    Returns:
        Success message
    """
    try:
        if analysis_id not in analyses_store:
            raise HTTPException(status_code=404, detail="Analysis not found")
        
        del analyses_store[analysis_id]
        return {"message": "Analysis deleted", "id": analysis_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))
