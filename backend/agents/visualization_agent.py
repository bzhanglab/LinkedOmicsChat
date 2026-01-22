"""
Visualization Agent
Creates publication-ready visualizations based on data and analysis type
"""
from typing import Dict, Any, Optional, List
from agents.base_agent import BaseAgent
import json
import logging
import base64
import io
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import plotly.io as pio

logger = logging.getLogger(__name__)


class VisualizationAgent(BaseAgent):
    """Agent specialized in data visualization"""
    
    def __init__(self):
        super().__init__(
            name="VisualizationAgent",
            description="Creates publication-ready visualizations",
            temperature=0.3
        )
    
    def get_system_prompt(self) -> str:
        return """You are a Visualization Agent specialized in scientific data visualization.
Your role is to:
1. Recommend appropriate visualization types based on data characteristics
2. Generate visualization specifications (chart type, axes, colors, etc.)
3. Create publication-ready figures with proper labels and legends
4. Ensure visualizations follow best practices for scientific communication
5. Adapt visualizations to the research question

You understand various plot types:
- Scatter plots and correlation matrices
- Heatmaps and clustergrams
- Box plots and violin plots
- Survival curves (Kaplan-Meier)
- Volcano plots and MA plots
- Network diagrams
- Interactive visualizations

Always prioritize clarity, accuracy, and scientific rigor."""
    
    async def process(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process visualization request
        
        Args:
            query: Description of desired visualization
            context: Data and analysis results to visualize
            
        Returns:
            Visualization specifications and configurations
        """
        try:
            # Determine visualization types
            viz_types = await self._determine_visualization_types(query, context)
            
            # Generate actual plots from analysis results
            plot_images = []
            visualizations = []
            
            for viz_type in viz_types:
                viz_spec = await self._generate_visualization_spec(
                    viz_type,
                    context
                )
                
                # Generate actual plot image if we have data
                plot_data = await self._generate_plot_image(viz_type, viz_spec, context)
                if plot_data:
                    viz_spec["plot_image"] = plot_data
                    plot_images.append(plot_data)
                
                visualizations.append(viz_spec)
            
            # Generate recommendations
            recommendations = await self._generate_recommendations(
                query,
                visualizations
            )
            
            return self.format_response(
                success=True,
                data={
                    "visualizations": visualizations,
                    "recommendations": recommendations,
                    "plot_images": plot_images,
                    "is_mock_data": context.get("previous_results", {}).get("analysis", {}).get("data", {}).get("is_mock", True) if context else True
                },
                message=f"Generated {len(visualizations)} visualizations with {len(plot_images)} plots",
                metadata={"query": query}
            )
            
        except Exception as e:
            logger.error(f"Error in VisualizationAgent: {e}")
            return self.format_response(
                success=False,
                message=f"Error generating visualizations: {str(e)}"
            )
    
    async def _determine_visualization_types(
        self,
        query: str,
        context: Optional[Dict[str, Any]]
    ) -> List[str]:
        """Determine appropriate visualization types"""
        prompt = f"""Based on this request and context, what visualizations should be created?

Request: {query}
Context: {json.dumps(context, indent=2) if context else 'None'}

Choose from:
- scatter: Scatter plot for correlations
- heatmap: Heatmap for expression patterns
- boxplot: Box plot for group comparisons
- survival: Kaplan-Meier survival curves
- volcano: Volcano plot for differential expression
- barplot: Bar plot for counts or enrichment
- network: Network diagram for interactions
- violin: Violin plot for distributions

Return a JSON array of visualization types, e.g. ["scatter", "heatmap"]
Return ONLY valid JSON, no other text."""
        
        response = await self.invoke_llm(prompt)
        
        try:
            viz_types = json.loads(response)
            return viz_types if isinstance(viz_types, list) else [viz_types]
        except json.JSONDecodeError:
            # Default visualization
            return ["scatter"]
    
    async def _generate_visualization_spec(
        self,
        viz_type: str,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate specification for a visualization"""
        
        if viz_type == "scatter":
            return self._create_scatter_spec(context)
        elif viz_type == "heatmap":
            return self._create_heatmap_spec(context)
        elif viz_type == "boxplot":
            return self._create_boxplot_spec(context)
        elif viz_type == "survival":
            return self._create_survival_spec(context)
        elif viz_type == "volcano":
            return self._create_volcano_spec(context)
        elif viz_type == "barplot":
            return self._create_barplot_spec(context)
        elif viz_type == "network":
            return self._create_network_spec(context)
        elif viz_type == "violin":
            return self._create_violin_spec(context)
        else:
            return self._create_default_spec(context)
    
    def _create_scatter_spec(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Create scatter plot specification"""
        return {
            "type": "scatter",
            "title": "Gene Expression Correlation",
            "config": {
                "x_axis": {
                    "label": "Gene A Expression",
                    "scale": "linear"
                },
                "y_axis": {
                    "label": "Gene B Expression",
                    "scale": "linear"
                },
                "points": {
                    "size": 4,
                    "color": "#3b82f6",
                    "alpha": 0.6
                },
                "regression_line": True,
                "show_r_squared": True
            },
            "data_requirements": {
                "x_values": "expression_gene_a",
                "y_values": "expression_gene_b"
            },
            "export_formats": ["pdf", "png", "svg"],
            "dimensions": {
                "width": 800,
                "height": 600
            }
        }
    
    def _create_heatmap_spec(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Create heatmap specification"""
        return {
            "type": "heatmap",
            "title": "Gene Expression Heatmap",
            "config": {
                "colormap": "RdBu_r",
                "clustering": {
                    "rows": True,
                    "columns": True,
                    "method": "ward"
                },
                "annotations": {
                    "show_values": False,
                    "show_dendrograms": True
                },
                "normalization": "z-score"
            },
            "data_requirements": {
                "matrix": "expression_matrix",
                "row_labels": "gene_names",
                "col_labels": "sample_ids"
            },
            "export_formats": ["pdf", "png"],
            "dimensions": {
                "width": 1000,
                "height": 800
            }
        }
    
    def _create_boxplot_spec(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Create box plot specification"""
        return {
            "type": "boxplot",
            "title": "Gene Expression by Group",
            "config": {
                "orientation": "vertical",
                "show_points": True,
                "colors": ["#3b82f6", "#ef4444"],
                "statistical_test": {
                    "method": "t-test",
                    "show_p_value": True
                }
            },
            "data_requirements": {
                "values": "expression_values",
                "groups": "sample_groups"
            },
            "export_formats": ["pdf", "png"],
            "dimensions": {
                "width": 600,
                "height": 800
            }
        }
    
    def _create_survival_spec(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Create survival curve specification"""
        return {
            "type": "survival",
            "title": "Kaplan-Meier Survival Curves",
            "config": {
                "curves": [
                    {"name": "High Expression", "color": "#ef4444"},
                    {"name": "Low Expression", "color": "#3b82f6"}
                ],
                "show_confidence_intervals": True,
                "show_risk_table": True,
                "show_p_value": True,
                "censoring_marks": True
            },
            "data_requirements": {
                "time": "survival_time",
                "event": "death_event",
                "groups": "expression_groups"
            },
            "export_formats": ["pdf", "png"],
            "dimensions": {
                "width": 800,
                "height": 700
            }
        }
    
    def _create_volcano_spec(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Create volcano plot specification"""
        return {
            "type": "volcano",
            "title": "Differential Expression Volcano Plot",
            "config": {
                "x_axis": {
                    "label": "log2 Fold Change",
                    "symmetric": True
                },
                "y_axis": {
                    "label": "-log10(p-value)"
                },
                "thresholds": {
                    "fold_change": 1.0,
                    "p_value": 0.05
                },
                "colors": {
                    "upregulated": "#ef4444",
                    "downregulated": "#3b82f6",
                    "not_significant": "#9ca3af"
                },
                "label_top_genes": 10
            },
            "data_requirements": {
                "log2fc": "log2_fold_change",
                "p_values": "p_values",
                "gene_names": "genes"
            },
            "export_formats": ["pdf", "png"],
            "dimensions": {
                "width": 900,
                "height": 800
            }
        }
    
    def _create_barplot_spec(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Create bar plot specification"""
        return {
            "type": "barplot",
            "title": "Pathway Enrichment",
            "config": {
                "orientation": "horizontal",
                "color": "#3b82f6",
                "sort": "descending",
                "error_bars": False
            },
            "data_requirements": {
                "categories": "pathway_names",
                "values": "enrichment_scores"
            },
            "export_formats": ["pdf", "png"],
            "dimensions": {
                "width": 800,
                "height": 600
            }
        }
    
    def _create_network_spec(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Create network diagram specification"""
        return {
            "type": "network",
            "title": "Gene Interaction Network",
            "config": {
                "layout": "force-directed",
                "node": {
                    "size_by": "degree",
                    "color_by": "cluster"
                },
                "edge": {
                    "width_by": "weight",
                    "color": "#9ca3af"
                },
                "interactive": True
            },
            "data_requirements": {
                "nodes": "gene_list",
                "edges": "interactions"
            },
            "export_formats": ["pdf", "png", "html"],
            "dimensions": {
                "width": 1000,
                "height": 1000
            }
        }
    
    def _create_violin_spec(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Create violin plot specification"""
        return {
            "type": "violin",
            "title": "Expression Distribution",
            "config": {
                "show_boxplot": True,
                "show_points": False,
                "colors": ["#3b82f6", "#ef4444", "#10b981"]
            },
            "data_requirements": {
                "values": "expression_values",
                "groups": "sample_groups"
            },
            "export_formats": ["pdf", "png"],
            "dimensions": {
                "width": 700,
                "height": 600
            }
        }
    
    def _create_default_spec(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Create default visualization specification"""
        return self._create_scatter_spec(context)
    
    async def _generate_recommendations(
        self,
        query: str,
        visualizations: List[Dict[str, Any]]
    ) -> str:
        """Generate recommendations for visualizations"""
        viz_summary = "\n".join([
            f"- {v['type']}: {v['title']}"
            for v in visualizations
        ])
        
        prompt = f"""Given this visualization request and generated plots, provide recommendations:

Request: {query}

Generated Visualizations:
{viz_summary}

Provide brief recommendations (2-3 sentences) on:
1. What insights each visualization reveals
2. Any additional visualizations that might be helpful"""
        
        recommendations = await self.invoke_llm(prompt)
        return recommendations
    
    async def _generate_plot_image(
        self,
        viz_type: str,
        viz_spec: Dict[str, Any],
        context: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Generate actual plot image from data"""
        try:
            # Get analysis results from context
            previous_results = context.get("previous_results", {}) if context else {}
            analysis_result = None
            
            # Find analysis results in previous workflow steps
            for step_id, result in previous_results.items():
                if isinstance(result, dict) and result.get("agent") == "StatisticalAnalysisAgent":
                    analysis_result = result.get("data", {})
                    break
            
            # If no analysis results, check direct context
            if not analysis_result and context:
                analysis_result = context.get("data", {})
            
            if viz_type == "scatter" and analysis_result:
                return await self._create_correlation_scatter_plot(analysis_result)
            elif viz_type == "heatmap" and analysis_result:
                return await self._create_correlation_heatmap(analysis_result)
            elif viz_type == "volcano" and analysis_result:
                return await self._create_volcano_plot(analysis_result)
            
            return None
        except Exception as e:
            logger.error(f"Error generating plot image: {e}")
            return None
    
    async def _create_correlation_scatter_plot(self, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create scatter plot from correlation analysis results"""
        try:
            results = analysis_data.get("results", {})
            top_correlations = results.get("top_correlations", [])
            
            if not top_correlations:
                return None
            
            # Extract data
            genes = [r["gene"] for r in top_correlations[:20]]
            correlations = [r["correlation"] for r in top_correlations[:20]]
            p_values = [r["p_value"] for r in top_correlations[:20]]
            
            # Create plot
            fig, ax = plt.subplots(figsize=(10, 6))
            
            # Color by significance
            colors = ['#ef4444' if p < 0.05 else '#9ca3af' for p in p_values]
            
            ax.scatter(range(len(genes)), correlations, c=colors, s=100, alpha=0.7)
            ax.axhline(y=0, color='black', linestyle='--', linewidth=0.5)
            ax.set_xlabel('Genes (ranked by correlation)', fontsize=12)
            ax.set_ylabel('Correlation Coefficient', fontsize=12)
            ax.set_title('Top Correlated Genes', fontsize=14, fontweight='bold')
            ax.set_xticks(range(len(genes)))
            ax.set_xticklabels(genes, rotation=45, ha='right', fontsize=8)
            ax.grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            # Convert to base64
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
            buffer.seek(0)
            image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            plt.close(fig)
            
            return {
                "type": "scatter",
                "format": "png",
                "data": f"data:image/png;base64,{image_base64}",
                "title": "Top Correlated Genes"
            }
        except Exception as e:
            logger.error(f"Error creating scatter plot: {e}")
            return None
    
    async def _create_correlation_heatmap(self, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create heatmap from correlation results"""
        try:
            results = analysis_data.get("results", {})
            top_correlations = results.get("top_correlations", [])
            
            if not top_correlations or len(top_correlations) < 5:
                return None
            
            # Create correlation matrix for top genes
            n = min(15, len(top_correlations))
            genes = [r["gene"] for r in top_correlations[:n]]
            correlations = [r["correlation"] for r in top_correlations[:n]]
            
            # Create a simple heatmap showing correlation values
            fig, ax = plt.subplots(figsize=(10, 8))
            
            # Create matrix (simplified - just showing correlation values)
            matrix = np.array(correlations).reshape(-1, 1)
            
            im = ax.imshow(matrix, cmap='RdBu_r', aspect='auto', vmin=-1, vmax=1)
            ax.set_yticks(range(len(genes)))
            ax.set_yticklabels(genes, fontsize=9)
            ax.set_xticks([0])
            ax.set_xticklabels(['Correlation'], fontsize=10)
            ax.set_title('Gene Correlation Values', fontsize=12, fontweight='bold')
            
            # Add colorbar
            plt.colorbar(im, ax=ax, label='Correlation Coefficient')
            
            plt.tight_layout()
            
            # Convert to base64
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
            buffer.seek(0)
            image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            plt.close(fig)
            
            return {
                "type": "heatmap",
                "format": "png",
                "data": f"data:image/png;base64,{image_base64}",
                "title": "Correlation Heatmap"
            }
        except Exception as e:
            logger.error(f"Error creating heatmap: {e}")
            return None
    
    async def _create_volcano_plot(self, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create volcano plot from differential expression results"""
        try:
            results = analysis_data.get("results", {})
            top_genes = results.get("top_genes", [])
            
            if not top_genes:
                return None
            
            # Extract data
            log2fc = [r.get("log2_fold_change", 0) for r in top_genes]
            p_values = [r.get("p_value", 1.0) for r in top_genes]
            neg_log10_p = [-np.log10(max(p, 1e-10)) for p in p_values]
            genes = [r.get("gene", "") for r in top_genes]
            
            # Create plot
            fig, ax = plt.subplots(figsize=(10, 8))
            
            # Color by significance
            colors = []
            for r in top_genes:
                if r.get("significant", False):
                    if r.get("log2_fold_change", 0) > 0:
                        colors.append('#ef4444')  # Red for upregulated
                    else:
                        colors.append('#3b82f6')  # Blue for downregulated
                else:
                    colors.append('#9ca3af')  # Gray for not significant
            
            ax.scatter(log2fc, neg_log10_p, c=colors, s=50, alpha=0.6)
            ax.axhline(y=-np.log10(0.05), color='black', linestyle='--', linewidth=1, label='p=0.05')
            ax.axvline(x=1, color='black', linestyle='--', linewidth=1)
            ax.axvline(x=-1, color='black', linestyle='--', linewidth=1)
            ax.set_xlabel('log2 Fold Change', fontsize=12)
            ax.set_ylabel('-log10(p-value)', fontsize=12)
            ax.set_title('Volcano Plot - Differential Expression', fontsize=14, fontweight='bold')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            # Convert to base64
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
            buffer.seek(0)
            image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            plt.close(fig)
            
            return {
                "type": "volcano",
                "format": "png",
                "data": f"data:image/png;base64,{image_base64}",
                "title": "Volcano Plot"
            }
        except Exception as e:
            logger.error(f"Error creating volcano plot: {e}")
            return None
