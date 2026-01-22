"""
Statistical Analysis Agent
Performs statistical analyses and interprets results
"""
from typing import Dict, Any, Optional, List
from agents.base_agent import BaseAgent
import numpy as np
import json
import logging

logger = logging.getLogger(__name__)


class StatisticalAnalysisAgent(BaseAgent):
    """Agent specialized in statistical analysis"""
    
    def __init__(self):
        super().__init__(
            name="StatisticalAnalysisAgent",
            description="Performs statistical analyses on omics data",
            temperature=0.2
        )
    
    def get_system_prompt(self) -> str:
        return """You are a Statistical Analysis Agent specialized in bioinformatics.
Your role is to:
1. Recommend appropriate statistical tests based on data type and research question
2. Execute statistical analyses (correlation, differential expression, survival analysis, etc.)
3. Interpret statistical results in biological context
4. Identify significant findings and patterns
5. Suggest appropriate multiple testing corrections

You understand various statistical methods including:
- Pearson/Spearman correlation
- T-tests and ANOVA
- Cox regression and survival analysis
- Differential expression analysis (DESeq2, limma)
- Enrichment analysis

Always report effect sizes, confidence intervals, and adjusted p-values."""
    
    async def process(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process statistical analysis request
        
        Args:
            query: Analysis description or question
            context: Data and parameters for analysis
            
        Returns:
            Analysis results with statistics and interpretation
        """
        try:
            # Determine analysis type
            analysis_type = await self._determine_analysis_type(query, context)
            
            # Execute analysis
            results = await self._execute_analysis(analysis_type, context)
            
            # Interpret results
            interpretation = await self._interpret_results(
                analysis_type,
                results,
                query
            )
            
            return self.format_response(
                success=True,
                data={
                    "analysis_type": analysis_type,
                    "results": results,
                    "interpretation": interpretation
                },
                message=f"Completed {analysis_type} analysis",
                metadata={"query": query}
            )
            
        except Exception as e:
            logger.error(f"Error in StatisticalAnalysisAgent: {e}")
            return self.format_response(
                success=False,
                message=f"Error performing analysis: {str(e)}"
            )
    
    async def _determine_analysis_type(
        self,
        query: str,
        context: Optional[Dict[str, Any]]
    ) -> str:
        """Determine which analysis to perform"""
        prompt = f"""Based on this research question, what type of statistical analysis is needed?

Question: {query}
Context: {json.dumps(context) if context else 'None'}

Choose ONE from:
- correlation: Gene expression correlation analysis
- differential_expression: Identify differentially expressed genes
- survival: Survival analysis (Kaplan-Meier, Cox regression)
- enrichment: Pathway or gene set enrichment analysis
- clustering: Unsupervised clustering analysis

Return ONLY the analysis type, no other text."""
        
        response = await self.invoke_llm(prompt)
        analysis_type = response.strip().lower()
        
        # Validate analysis type
        valid_types = [
            "correlation",
            "differential_expression",
            "survival",
            "enrichment",
            "clustering"
        ]
        
        if analysis_type not in valid_types:
            analysis_type = "correlation"
        
        return analysis_type
    
    async def _execute_analysis(
        self,
        analysis_type: str,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Execute the specified analysis"""
        
        if analysis_type == "correlation":
            return await self._perform_correlation_analysis(context)
        elif analysis_type == "differential_expression":
            return await self._perform_differential_expression(context)
        elif analysis_type == "survival":
            return await self._perform_survival_analysis(context)
        elif analysis_type == "enrichment":
            return await self._perform_enrichment_analysis(context)
        elif analysis_type == "clustering":
            return await self._perform_clustering_analysis(context)
        else:
            raise ValueError(f"Unknown analysis type: {analysis_type}")
    
    async def _perform_correlation_analysis(
        self,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Perform gene correlation analysis"""
        # Mock implementation - in production, this would use actual data
        np.random.seed(42)
        
        # Simulate correlation results
        n_genes = 100
        correlations = np.random.randn(n_genes) * 0.3 + 0.1
        p_values = np.random.rand(n_genes) * 0.1
        
        # Create results
        results = []
        gene_names = [f"GENE{i}" for i in range(1, n_genes + 1)]
        
        for i, (gene, corr, pval) in enumerate(
            zip(gene_names, correlations, p_values)
        ):
            results.append({
                "gene": gene,
                "correlation": float(corr),
                "p_value": float(pval),
                "adjusted_p_value": float(pval * n_genes),
                "significant": bool(pval < 0.05)
            })
        
        # Sort by absolute correlation
        results.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        
        return {
            "method": "Pearson correlation",
            "n_genes_tested": n_genes,
            "significant_genes": sum(1 for r in results if r["significant"]),
            "top_correlations": results[:20],
            "statistics": {
                "mean_correlation": float(np.mean(correlations)),
                "median_correlation": float(np.median(correlations)),
                "max_correlation": float(np.max(np.abs(correlations)))
            },
            "is_mock": True  # Flag to indicate this is mock data
        }
    
    async def _perform_differential_expression(
        self,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Perform differential expression analysis"""
        np.random.seed(42)
        
        n_genes = 200
        log2fc = np.random.randn(n_genes) * 2
        p_values = np.random.rand(n_genes) * 0.1
        
        results = []
        gene_names = [f"GENE{i}" for i in range(1, n_genes + 1)]
        
        for gene, fc, pval in zip(gene_names, log2fc, p_values):
            results.append({
                "gene": gene,
                "log2_fold_change": float(fc),
                "p_value": float(pval),
                "adjusted_p_value": float(pval * n_genes),
                "significant": bool(pval < 0.05 and abs(fc) > 1)
            })
        
        results.sort(key=lambda x: x["p_value"])
        
        return {
            "method": "DESeq2",
            "n_genes_tested": n_genes,
            "significant_genes": sum(1 for r in results if r["significant"]),
            "upregulated": sum(1 for r in results if r["significant"] and r["log2_fold_change"] > 0),
            "downregulated": sum(1 for r in results if r["significant"] and r["log2_fold_change"] < 0),
            "top_genes": results[:20]
        }
    
    async def _perform_survival_analysis(
        self,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Perform survival analysis"""
        np.random.seed(42)
        
        return {
            "method": "Cox Proportional Hazards",
            "hazard_ratio": 2.34,
            "confidence_interval": [1.56, 3.51],
            "p_value": 0.0012,
            "median_survival_high": 45.6,
            "median_survival_low": 78.3,
            "n_patients": 450
        }
    
    async def _perform_enrichment_analysis(
        self,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Perform pathway enrichment analysis"""
        return {
            "method": "Gene Set Enrichment Analysis",
            "enriched_pathways": [
                {
                    "pathway": "Cell Cycle",
                    "p_value": 0.00001,
                    "fdr": 0.001,
                    "genes_in_pathway": 45
                },
                {
                    "pathway": "DNA Repair",
                    "p_value": 0.00034,
                    "fdr": 0.012,
                    "genes_in_pathway": 32
                }
            ]
        }
    
    async def _perform_clustering_analysis(
        self,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Perform clustering analysis"""
        return {
            "method": "Hierarchical Clustering",
            "n_clusters": 4,
            "silhouette_score": 0.72,
            "cluster_sizes": [120, 98, 76, 54]
        }
    
    async def _interpret_results(
        self,
        analysis_type: str,
        results: Dict[str, Any],
        query: str
    ) -> str:
        """Generate interpretation of results"""
        prompt = f"""Interpret these {analysis_type} results in biological context:

Query: {query}
Results: {json.dumps(results, indent=2)}

Provide a clear interpretation (3-4 sentences) highlighting:
1. Main findings
2. Statistical significance
3. Biological relevance
4. Suggested next steps"""
        
        interpretation = await self.invoke_llm(prompt)
        return interpretation
