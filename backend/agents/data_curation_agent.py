"""
Data Curation Agent
Discovers and validates relevant datasets based on research questions
"""
from typing import Dict, Any, Optional, List
from agents.base_agent import BaseAgent
import json
import logging

logger = logging.getLogger(__name__)


class DataCurationAgent(BaseAgent):
    """Agent specialized in dataset discovery and curation"""
    
    def __init__(self):
        super().__init__(
            name="DataCurationAgent",
            description="Discovers relevant datasets and validates data quality",
            temperature=0.3
        )
        self.available_datasets = self._load_available_datasets()
    
    def get_system_prompt(self) -> str:
        return """You are a Data Curation Agent specialized in bioinformatics datasets.
Your role is to:
1. Understand research questions and identify relevant datasets
2. Extract key entities (cancer types, genes, data types) from queries
3. Recommend appropriate datasets based on research goals
4. Suggest data preprocessing steps
5. Validate data quality and compatibility

You have access to multi-omics datasets from TCGA, CPTAC, and other sources.
Always consider sample size, data completeness, and publication quality."""
    
    def _load_available_datasets(self) -> List[Dict[str, Any]]:
        """Load available datasets metadata"""
        # In production, this would query a database
        return [
            {
                "id": "tcga_brca",
                "name": "TCGA Breast Cancer",
                "cancer_type": "breast cancer",
                "sample_count": 1098,
                "data_types": ["rna_seq", "clinical", "mutation", "methylation"],
                "description": "Comprehensive molecular characterization of breast cancer",
                "source": "TCGA"
            },
            {
                "id": "tcga_luad",
                "name": "TCGA Lung Adenocarcinoma",
                "cancer_type": "lung cancer",
                "sample_count": 517,
                "data_types": ["rna_seq", "clinical", "mutation", "methylation"],
                "description": "Molecular profiling of lung adenocarcinoma",
                "source": "TCGA"
            },
            {
                "id": "cptac_brca",
                "name": "CPTAC Breast Cancer",
                "cancer_type": "breast cancer",
                "sample_count": 122,
                "data_types": ["proteomics", "rna_seq", "clinical"],
                "description": "Proteogenomic characterization of breast cancer",
                "source": "CPTAC"
            }
        ]
    
    async def process(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process data curation request
        
        Args:
            query: Research question or data request
            context: Additional context (selected genes, filters, etc.)
            
        Returns:
            Recommended datasets and metadata
        """
        try:
            # Extract entities from query
            entities = await self._extract_entities(query)
            
            # Find matching datasets
            matching_datasets = self._match_datasets(entities)
            
            # Rank datasets by relevance
            ranked_datasets = self._rank_datasets(matching_datasets, entities)
            
            # Generate recommendations
            recommendations = await self._generate_recommendations(
                query,
                ranked_datasets,
                entities
            )
            
            return self.format_response(
                success=True,
                data={
                    "datasets": ranked_datasets[:5],
                    "entities": entities,
                    "recommendations": recommendations
                },
                message=f"Found {len(ranked_datasets)} relevant datasets",
                metadata={"query": query}
            )
            
        except Exception as e:
            logger.error(f"Error in DataCurationAgent: {e}")
            return self.format_response(
                success=False,
                message=f"Error processing data curation request: {str(e)}"
            )
    
    async def _extract_entities(self, query: str) -> Dict[str, List[str]]:
        """Extract key entities from query using LLM"""
        prompt = f"""Extract key entities from this research question:
        
Query: {query}

Return a JSON object with:
- cancer_types: list of cancer types mentioned
- genes: list of specific genes mentioned
- data_types: list of data types needed (rna_seq, proteomics, clinical, etc.)
- analysis_types: list of analysis types (correlation, survival, differential expression, etc.)

Return ONLY valid JSON, no other text."""
        
        response = await self.invoke_llm(prompt)
        
        try:
            entities = json.loads(response)
            return entities
        except json.JSONDecodeError:
            # Fallback to simple parsing
            query_lower = query.lower()
            return {
                "cancer_types": [ct for ct in ["breast cancer", "lung cancer", "colon cancer"] 
                               if ct in query_lower],
                "genes": [],
                "data_types": ["rna_seq"] if "rna" in query_lower or "expression" in query_lower else [],
                "analysis_types": []
            }
    
    def _match_datasets(self, entities: Dict[str, List[str]]) -> List[Dict[str, Any]]:
        """Match datasets based on extracted entities"""
        matching = []
        
        for dataset in self.available_datasets:
            score = 0
            
            # Match cancer type
            if entities.get("cancer_types"):
                for cancer_type in entities["cancer_types"]:
                    if cancer_type.lower() in dataset["cancer_type"].lower():
                        score += 10
            
            # Match data types
            if entities.get("data_types"):
                for data_type in entities["data_types"]:
                    if data_type in dataset["data_types"]:
                        score += 5
            
            if score > 0:
                dataset_copy = dataset.copy()
                dataset_copy["relevance_score"] = score
                matching.append(dataset_copy)
        
        return matching
    
    def _rank_datasets(
        self,
        datasets: List[Dict[str, Any]],
        entities: Dict[str, List[str]]
    ) -> List[Dict[str, Any]]:
        """Rank datasets by relevance"""
        return sorted(
            datasets,
            key=lambda x: (x.get("relevance_score", 0), x["sample_count"]),
            reverse=True
        )
    
    async def _generate_recommendations(
        self,
        query: str,
        datasets: List[Dict[str, Any]],
        entities: Dict[str, List[str]]
    ) -> str:
        """Generate natural language recommendations"""
        if not datasets:
            return "No datasets found matching your criteria. Please refine your query."
        
        dataset_summary = "\n".join([
            f"- {d['name']}: {d['sample_count']} samples, {', '.join(d['data_types'])}"
            for d in datasets[:3]
        ])
        
        prompt = f"""Given this research question and matching datasets, provide recommendations:

Research Question: {query}

Matching Datasets:
{dataset_summary}

Provide a brief recommendation (2-3 sentences) on which dataset(s) to use and why."""
        
        recommendations = await self.invoke_llm(prompt)
        return recommendations
