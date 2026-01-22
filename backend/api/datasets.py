"""
Datasets API endpoints
Browse and search available datasets
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
import logging

from models.schemas import DatasetInfo

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[DatasetInfo])
async def list_datasets(
    cancer_type: Optional[str] = Query(None, description="Filter by cancer type"),
    data_type: Optional[str] = Query(None, description="Filter by data type"),
    source: Optional[str] = Query(None, description="Filter by source")
):
    """
    List available datasets with optional filters
    
    Args:
        cancer_type: Filter by cancer type
        data_type: Filter by data type (rna_seq, proteomics, etc.)
        source: Filter by source (TCGA, CPTAC, etc.)
        
    Returns:
        List of datasets matching filters
    """
    try:
        # Mock data - in production, this would query a database
        datasets = [
            DatasetInfo(
                id="tcga_brca",
                name="TCGA Breast Cancer",
                description="Comprehensive molecular characterization of breast cancer",
                cancer_type="breast cancer",
                sample_count=1098,
                feature_count=20530,
                data_types=["rna_seq", "clinical", "mutation", "methylation"],
                publication="Nature 2012",
                source="TCGA"
            ),
            DatasetInfo(
                id="tcga_luad",
                name="TCGA Lung Adenocarcinoma",
                description="Molecular profiling of lung adenocarcinoma",
                cancer_type="lung cancer",
                sample_count=517,
                feature_count=20530,
                data_types=["rna_seq", "clinical", "mutation", "methylation"],
                publication="Nature 2014",
                source="TCGA"
            ),
            DatasetInfo(
                id="cptac_brca",
                name="CPTAC Breast Cancer",
                description="Proteogenomic characterization of breast cancer",
                cancer_type="breast cancer",
                sample_count=122,
                feature_count=12000,
                data_types=["proteomics", "rna_seq", "clinical"],
                publication="Nature 2016",
                source="CPTAC"
            )
        ]
        
        # Apply filters
        if cancer_type:
            datasets = [
                d for d in datasets
                if cancer_type.lower() in d.cancer_type.lower()
            ]
        
        if data_type:
            datasets = [
                d for d in datasets
                if data_type in d.data_types
            ]
        
        if source:
            datasets = [
                d for d in datasets
                if source.upper() in d.source.upper()
            ]
        
        return datasets
        
    except Exception as e:
        logger.error(f"Error listing datasets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{dataset_id}", response_model=DatasetInfo)
async def get_dataset(dataset_id: str):
    """
    Get detailed information about a specific dataset
    
    Args:
        dataset_id: Dataset identifier
        
    Returns:
        Dataset information
    """
    try:
        # Mock implementation
        datasets = {
            "tcga_brca": DatasetInfo(
                id="tcga_brca",
                name="TCGA Breast Cancer",
                description="Comprehensive molecular characterization of breast cancer",
                cancer_type="breast cancer",
                sample_count=1098,
                feature_count=20530,
                data_types=["rna_seq", "clinical", "mutation", "methylation"],
                publication="Nature 2012",
                source="TCGA"
            )
        }
        
        if dataset_id not in datasets:
            raise HTTPException(status_code=404, detail="Dataset not found")
        
        return datasets[dataset_id]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting dataset: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search")
async def search_datasets(query: dict):
    """
    Search datasets using natural language query
    
    Args:
        query: Search query with 'text' field
        
    Returns:
        Relevant datasets
    """
    try:
        search_text = query.get("text", "")
        
        if not search_text:
            raise HTTPException(
                status_code=400,
                detail="Missing 'text' in search query"
            )
        
        # In production, this would use vector search or agent-based search
        datasets = await list_datasets()
        
        # Simple keyword matching for demo
        search_lower = search_text.lower()
        results = [
            d for d in datasets
            if (search_lower in d.name.lower() or
                search_lower in d.description.lower() or
                search_lower in d.cancer_type.lower())
        ]
        
        return {
            "query": search_text,
            "results": results,
            "count": len(results)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching datasets: {e}")
        raise HTTPException(status_code=500, detail=str(e))
