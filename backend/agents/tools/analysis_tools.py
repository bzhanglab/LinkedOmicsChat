"""
Statistical Analysis Tools
Core functions for correlation, differential expression, survival analysis, etc.
"""
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np
from scipy import stats
from scipy.stats import pearsonr, spearmanr
import logging

logger = logging.getLogger(__name__)


class AnalysisTools:
    """Collection of statistical analysis functions"""

    @staticmethod
    def correlation_analysis(
        expression_data: pd.DataFrame,
        target_gene: str,
        method: str = "pearson",
        min_correlation: float = 0.0,
        min_abs_correlation: float = 0.0,
        adjust_pvalues: bool = True
    ) -> pd.DataFrame:
        """
        Find genes correlated with a target gene

        Args:
            expression_data: DataFrame with genes as rows, samples as columns
            target_gene: Gene symbol to find correlations for
            method: "pearson" or "spearman"
            min_correlation: Minimum correlation threshold (signed)
            min_abs_correlation: Minimum absolute correlation threshold
            adjust_pvalues: Whether to apply FDR correction

        Returns:
            DataFrame with columns: gene, correlation, p_value, adjusted_p_value,
            significant
        """
        try:
            if target_gene not in expression_data.index:
                logger.warning(
                    f"Target gene {target_gene} not found in expression data"
                )
                return pd.DataFrame()

            # Get target gene expression vector
            # Handle case where there might be duplicate gene names
            target_data = expression_data.loc[expression_data.index == target_gene]
            if target_data.empty:
                logger.error(
                    f"Target gene {target_gene} not found in expression data"
                )
                return pd.DataFrame()
            
            # If multiple rows match, take the first one
            if len(target_data) > 1:
                logger.warning(
                    f"Multiple entries found for {target_gene}, using first one"
                )
            target_expression = target_data.iloc[0].values

            # Calculate correlation for all genes
            results = []
            seen_genes = set()  # Track genes we've already processed
            for gene in expression_data.index:
                if gene == target_gene or gene in seen_genes:
                    continue
                seen_genes.add(gene)

                # Handle case where there might be duplicate gene names
                gene_data = expression_data.loc[expression_data.index == gene]
                if gene_data.empty:
                    continue
                # If multiple rows match, take the first one
                gene_expression = gene_data.iloc[0].values

                # Calculate correlation
                if method.lower() == "pearson":
                    corr, p_value = pearsonr(target_expression, gene_expression)
                elif method.lower() == "spearman":
                    corr, p_value = spearmanr(
                        target_expression, gene_expression
                    )
                else:
                    raise ValueError(
                        f"Unknown correlation method: {method}"
                    )

                # Check if correlation meets thresholds
                if abs(corr) < min_abs_correlation:
                    continue
                if corr < min_correlation:
                    continue

                results.append({
                    "gene": gene,
                    "correlation": float(corr),
                    "p_value": float(p_value),
                    "abs_correlation": float(abs(corr))
                })

            if not results:
                return pd.DataFrame(
                    columns=["gene", "correlation", "p_value",
                             "adjusted_p_value", "significant"]
                )

            results_df = pd.DataFrame(results)

            # Adjust p-values (FDR correction)
            if adjust_pvalues:
                from statsmodels.stats.multitest import multipletests
                _, adjusted_p, _, _ = multipletests(
                    results_df["p_value"].values,
                    method="fdr_bh"
                )
                results_df["adjusted_p_value"] = adjusted_p
            else:
                results_df["adjusted_p_value"] = results_df["p_value"]

            # Mark significant results
            results_df["significant"] = (
                results_df["adjusted_p_value"] < 0.05
            )

            # Sort by absolute correlation
            results_df = results_df.sort_values(
                "abs_correlation", ascending=False
            )

            # Remove helper column
            results_df = results_df.drop(columns=["abs_correlation"])

            logger.info(
                f"Found {len(results_df)} genes correlated with {target_gene} "
                f"({results_df['significant'].sum()} significant)"
            )

            return results_df

        except Exception as e:
            logger.error(f"Error in correlation analysis: {e}")
            raise

    @staticmethod
    def differential_expression(
        expression_data: pd.DataFrame,
        group1_samples: List[str],
        group2_samples: List[str],
        method: str = "t-test",
        log_transform: bool = True
    ) -> pd.DataFrame:
        """
        Find differentially expressed genes between two groups

        Args:
            expression_data: DataFrame with genes as rows, samples as columns
            group1_samples: List of sample IDs for group 1
            group2_samples: List of sample IDs for group 2
            method: "t-test" or "wilcoxon"
            log_transform: Whether to log-transform expression values

        Returns:
            DataFrame with columns: gene, log2_fold_change, p_value,
            adjusted_p_value, significant
        """
        try:
            # Filter to samples in both groups
            all_samples = group1_samples + group2_samples
            expression_data = expression_data[all_samples]

            # Log transform if requested
            if log_transform:
                expression_data = np.log2(expression_data + 1)

            results = []
            for gene in expression_data.index.unique():
                # Handle duplicate gene names (take first if DataFrame)
                gene_data = expression_data.loc[gene]
                if isinstance(gene_data, pd.DataFrame):
                    gene_data = gene_data.iloc[0]
                
                group1_values_raw = gene_data[group1_samples]
                group2_values_raw = gene_data[group2_samples]
                
                # Convert to numpy array, handling both Series and DataFrame
                if isinstance(group1_values_raw, pd.Series):
                    group1_values = group1_values_raw.values
                else:
                    group1_values = group1_values_raw.values.flatten()
                
                if isinstance(group2_values_raw, pd.Series):
                    group2_values = group2_values_raw.values
                else:
                    group2_values = group2_values_raw.values.flatten()

                # Calculate fold change
                mean1 = np.mean(group1_values)
                mean2 = np.mean(group2_values)
                log2_fc = mean1 - mean2

                # Statistical test
                if method == "t-test":
                    _, p_value = stats.ttest_ind(group1_values, group2_values)
                elif method == "wilcoxon":
                    _, p_value = stats.mannwhitneyu(
                        group1_values, group2_values, alternative="two-sided"
                    )
                else:
                    raise ValueError(f"Unknown method: {method}")

                results.append({
                    "gene": gene,
                    "log2_fold_change": float(log2_fc),
                    "p_value": float(p_value),
                    "mean_group1": float(mean1),
                    "mean_group2": float(mean2)
                })

            results_df = pd.DataFrame(results)

            # Adjust p-values
            from statsmodels.stats.multitest import multipletests
            _, adjusted_p, _, _ = multipletests(
                results_df["p_value"].values,
                method="fdr_bh"
            )
            results_df["adjusted_p_value"] = adjusted_p

            # Mark significant results (p < 0.05 and |log2FC| > 1)
            results_df["significant"] = (
                (results_df["adjusted_p_value"] < 0.05) &
                (results_df["log2_fold_change"].abs() > 1.0)
            )

            # Sort by p-value
            results_df = results_df.sort_values("p_value")

            logger.info(
                f"Found {results_df['significant'].sum()} "
                f"differentially expressed genes"
            )

            return results_df

        except Exception as e:
            logger.error(f"Error in differential expression: {e}")
            raise

    @staticmethod
    def survival_analysis(
        gene_expression: pd.Series,
        survival_data: pd.DataFrame,
        method: str = "cox"
    ) -> Dict[str, Any]:
        """
        Perform survival analysis based on gene expression

        Args:
            gene_expression: Series with sample IDs as index, expression as values
            survival_data: DataFrame with columns: sample_id, time, event
            method: "cox" (Cox regression) or "km" (Kaplan-Meier)

        Returns:
            Dictionary with survival analysis results
        """
        try:
            # Merge expression with survival data
            merged = pd.merge(
                gene_expression.to_frame("expression"),
                survival_data,
                left_index=True,
                right_on="sample_id"
            )

            if len(merged) == 0:
                return {
                    "success": False,
                    "error": "No overlapping samples"
                }

            # Split into high/low expression groups (median split)
            median_expr = merged["expression"].median()
            merged["group"] = (
                merged["expression"] > median_expr
            ).astype(int)

            if method == "cox":
                try:
                    from lifelines import CoxPHFitter

                    # Prepare data for Cox model
                    cox_data = merged[["time", "event", "group"]].copy()
                    cox_data = cox_data.rename(columns={"group": "expression_group"})

                    # Fit Cox model
                    cph = CoxPHFitter()
                    cph.fit(cox_data, duration_col="time", event_col="event")

                    # Get results
                    summary = cph.summary
                    hazard_ratio = np.exp(
                        summary.loc["expression_group", "coef"]
                    )
                    p_value = summary.loc["expression_group", "p"]

                    return {
                        "success": True,
                        "method": "Cox Proportional Hazards",
                        "hazard_ratio": float(hazard_ratio),
                        "p_value": float(p_value),
                        "n_samples": len(merged),
                        "median_expression": float(median_expr),
                        "high_group_n": int(merged["group"].sum()),
                        "low_group_n": int((~merged["group"].astype(bool)).sum())
                    }

                except ImportError:
                    logger.warning(
                        "lifelines not installed, using simple survival analysis"
                    )
                    # Fallback to simple analysis
                    return {
                        "success": True,
                        "method": "Simple (lifelines not available)",
                        "n_samples": len(merged),
                        "median_expression": float(median_expr)
                    }

            elif method == "km":
                # Kaplan-Meier analysis would go here
                # For now, return basic info
                return {
                    "success": True,
                    "method": "Kaplan-Meier (not yet implemented)",
                    "n_samples": len(merged)
                }

            else:
                raise ValueError(f"Unknown method: {method}")

        except Exception as e:
            logger.error(f"Error in survival analysis: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def calculate_basic_stats(
        expression_data: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Calculate basic statistics for expression data

        Args:
            expression_data: DataFrame with genes as rows, samples as columns

        Returns:
            Dictionary with statistics
        """
        return {
            "n_genes": len(expression_data),
            "n_samples": len(expression_data.columns),
            "mean_expression": float(expression_data.values.mean()),
            "median_expression": float(np.median(expression_data.values)),
            "std_expression": float(expression_data.values.std()),
            "missing_values": int(expression_data.isna().sum().sum())
        }

    @staticmethod
    def pathway_enrichment(
        gene_list: List[str],
        gene_set: str = "GO_Biological_Process_2021",
        organism: str = "human",
        min_size: int = 5,
        max_size: int = 2000,
        top_n: int = 20
    ) -> pd.DataFrame:
        """
        Perform pathway/gene set enrichment analysis

        Args:
            gene_list: List of gene symbols to test for enrichment
            gene_set: Gene set database to use:
                - "GO_Biological_Process_2021" (default)
                - "GO_Molecular_Function_2021"
                - "GO_Cellular_Component_2021"
                - "KEGG_2021_Human"
                - "Reactome_2022"
                - "MSigDB_Hallmark_2020"
            organism: Organism (default: "human")
            min_size: Minimum genes in pathway
            max_size: Maximum genes in pathway
            top_n: Number of top pathways to return

        Returns:
            DataFrame with columns: pathway, p_value, adjusted_p_value,
            odds_ratio, genes_in_pathway, genes_in_list, total_genes
        """
        try:
            import gseapy as gp
            
            if not gene_list or len(gene_list) < 3:
                logger.warning(
                    f"Gene list too small ({len(gene_list)} genes) for enrichment"
                )
                return pd.DataFrame(
                    columns=["pathway", "p_value", "adjusted_p_value",
                            "odds_ratio", "genes_in_pathway", "genes_in_list",
                            "total_genes", "gene_ratio", "enrichment_score"]
                )

            logger.info(
                f"Running pathway enrichment for {len(gene_list)} genes "
                f"using {gene_set}"
            )

            # Run enrichment analysis
            enr = gp.enrichr(
                gene_list=gene_list,
                gene_sets=gene_set,
                organism=organism,
                outdir=None,  # Don't save files
                cutoff=0.05,  # FDR cutoff
                no_plot=True
            )

            if enr is None or enr.results is None or len(enr.results) == 0:
                logger.warning("No enriched pathways found")
                return pd.DataFrame(
                    columns=["pathway", "p_value", "adjusted_p_value",
                            "odds_ratio", "genes_in_pathway", "genes_in_list",
                            "total_genes", "gene_ratio", "enrichment_score"]
                )

            # Extract results
            results = enr.results.copy()
            
            # Rename columns for consistency
            column_mapping = {
                "Term": "pathway",
                "P-value": "p_value",
                "Adjusted P-value": "adjusted_p_value",
                "Odds Ratio": "odds_ratio",
                "Combined Score": "enrichment_score"
            }
            
            for old_col, new_col in column_mapping.items():
                if old_col in results.columns:
                    results = results.rename(columns={old_col: new_col})

            # Ensure required columns exist
            required_cols = ["pathway", "p_value", "adjusted_p_value"]
            for col in required_cols:
                if col not in results.columns:
                    if col == "pathway" and "Term" in results.columns:
                        results["pathway"] = results["Term"]
                    elif col == "p_value" and "P-value" in results.columns:
                        results["p_value"] = results["P-value"]
                    elif col == "adjusted_p_value" and "Adjusted P-value" in results.columns:
                        results["adjusted_p_value"] = results["Adjusted P-value"]
                    else:
                        logger.warning(f"Column {col} not found in enrichment results")
                        results[col] = np.nan

            # Calculate gene ratio if not present
            if "gene_ratio" not in results.columns:
                if "Overlap" in results.columns:
                    # Parse "X/Y" format from Overlap column
                    def parse_overlap(overlap_str):
                        if pd.isna(overlap_str):
                            return np.nan
                        try:
                            parts = str(overlap_str).split("/")
                            if len(parts) == 2:
                                return float(parts[0]) / float(parts[1])
                        except:
                            pass
                        return np.nan
                    results["gene_ratio"] = results["Overlap"].apply(parse_overlap)
                else:
                    results["gene_ratio"] = np.nan

            # Extract gene counts if available
            if "Overlap" in results.columns:
                def extract_counts(overlap_str):
                    if pd.isna(overlap_str):
                        return (0, 0)
                    try:
                        parts = str(overlap_str).split("/")
                        if len(parts) == 2:
                            return (int(parts[0]), int(parts[1]))
                    except:
                        pass
                    return (0, 0)
                
                counts = results["Overlap"].apply(extract_counts)
                results["genes_in_list"] = [c[0] for c in counts]
                results["total_genes"] = [c[1] for c in counts]
                results["genes_in_pathway"] = results["total_genes"]

            # Filter by adjusted p-value
            if "adjusted_p_value" in results.columns:
                results = results[results["adjusted_p_value"] < 0.05].copy()

            # Sort by p-value and take top N
            if "p_value" in results.columns:
                results = results.sort_values("p_value").head(top_n)

            # Select and order columns
            output_cols = [
                "pathway", "p_value", "adjusted_p_value", "odds_ratio",
                "genes_in_pathway", "genes_in_list", "total_genes",
                "gene_ratio", "enrichment_score"
            ]
            
            # Only include columns that exist
            available_cols = [col for col in output_cols if col in results.columns]
            results = results[available_cols].copy()

            logger.info(
                f"Found {len(results)} enriched pathways "
                f"(FDR < 0.05, top {top_n})"
            )

            return results

        except ImportError:
            logger.error("gseapy not installed. Install with: pip install gseapy")
            return pd.DataFrame(
                columns=["pathway", "p_value", "adjusted_p_value",
                        "odds_ratio", "genes_in_pathway", "genes_in_list",
                        "total_genes", "gene_ratio", "enrichment_score"]
            )
        except Exception as e:
            logger.error(f"Error in pathway enrichment: {e}", exc_info=True)
            return pd.DataFrame(
                columns=["pathway", "p_value", "adjusted_p_value",
                        "odds_ratio", "genes_in_pathway", "genes_in_list",
                        "total_genes", "gene_ratio", "enrichment_score"]
            )
