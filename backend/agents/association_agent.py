"""
Association Agent
Finds associations between genes and clinical features (LinkFinder-like functionality)
"""
from typing import Dict, Any, Optional
from agents.base_agent import BaseAgent
from agents.tools.analysis_tools import AnalysisTools
from services.tcga_service import TCGAService
from services.cptac_service import CPTACService
import json
import logging

logger = logging.getLogger(__name__)


class AssociationAgent(BaseAgent):
    """Agent specialized in finding gene associations"""

    def __init__(self):
        super().__init__(
            name="AssociationAgent",
            description="Finds genes correlated with target genes or clinical features",
            temperature=0.3
        )
        self.analysis_tools = AnalysisTools()
        self.tcga_service = TCGAService()
        self.cptac_service = CPTACService()

    def get_system_prompt(self) -> str:
        return """You are an Association Agent specialized in finding correlations
        and associations in multi-omics data.

        Your role is to:
        1. Understand queries about gene associations (e.g., "Find genes correlated with TP53")
        2. Extract key parameters: target gene, cancer type, data source (TCGA or CPTAC), data type
        3. Execute correlation analysis using TCGA or CPTAC data
        4. Interpret results in biological context
        5. Suggest follow-up analyses

        You work with both TCGA and CPTAC datasets:
        - TCGA: Large sample sizes, RNA-seq, clinical, mutation data
        - CPTAC: Proteomics data, phosphoproteomics, smaller but deeper datasets

        You can analyze:
        - Gene-gene correlations (RNA-seq or proteomics)
        - Protein-protein correlations (CPTAC proteomics)
        - Gene-clinical feature associations
        - Multi-omics associations

        Always report statistical significance (p-values, FDR) and biological relevance."""

    async def process(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process association analysis request

        Args:
            query: Natural language query (e.g., "Find genes correlated with TP53 in BRCA")
            context: Additional context (previously selected genes, filters, etc.)

        Returns:
            Dictionary with association results
        """
        try:
            query_lower = query.lower()
            
            # Check if this is a standalone pathway enrichment query (no correlation)
            is_pathway_only = any(
                word in query_lower
                for word in ["pathway", "enrichment", "enriched", "biological process", "go", "kegg"]
            ) and not any(
                word in query_lower
                for word in ["correlat", "associate", "find genes", "genes correlated"]
            )
            
            # If pathway-only query, extract gene list and perform enrichment directly
            if is_pathway_only:
                gene_list = self._extract_gene_list_from_query(query)
                if not gene_list or len(gene_list) < 3:
                    return self.format_response(
                        success=False,
                        message=f"Could not extract enough genes from query. "
                        f"Found {len(gene_list) if gene_list else 0} genes. "
                        f"Please provide at least 3 genes (e.g., 'TP53, BRCA1, BRCA2, EGFR')."
                    )
                
                logger.info(f"Standalone pathway enrichment requested for {len(gene_list)} genes")
                
                # Determine gene set database from query
                gene_set = "GO_Biological_Process_2021"  # Default
                if "kegg" in query_lower:
                    gene_set = "KEGG_2021_Human"
                elif "reactome" in query_lower:
                    gene_set = "Reactome_2022"
                elif "hallmark" in query_lower or "msigdb" in query_lower:
                    gene_set = "MSigDB_Hallmark_2020"
                elif "molecular function" in query_lower or "mf" in query_lower:
                    gene_set = "GO_Molecular_Function_2021"
                elif "cellular component" in query_lower or "cc" in query_lower:
                    gene_set = "GO_Cellular_Component_2021"
                
                # Perform pathway enrichment
                pathway_results = self.analysis_tools.pathway_enrichment(
                    gene_list=gene_list,
                    gene_set=gene_set,
                    top_n=20
                )
                
                if pathway_results is None or pathway_results.empty:
                    return self.format_response(
                        success=False,
                        message=f"No enriched pathways found for the provided genes. "
                        f"This could mean the genes are not significantly associated with any pathways, "
                        f"or the gene symbols may be incorrect."
                    )
                
                # Format pathway results
                pathways_list = pathway_results.head(20).to_dict("records")
                
                # Generate interpretation
                interpretation = await self._interpret_pathway_results(
                    gene_list, pathway_results, query
                )
                
                # Return pathway-only results
                # Format to match frontend expectations
                return self.format_response(
                    success=True,
                    data={
                        "analysis_type": "pathway_enrichment",
                        "pathway_enrichment": {
                            "gene_set": gene_set,
                            "total_pathways": len(pathway_results),
                            "pathways": pathways_list,
                            "top_pathways": pathways_list[:10],
                            "genes": gene_list
                        },
                        "interpretation": interpretation
                    },
                    message=f"Found {len(pathway_results)} enriched pathways for {len(gene_list)} genes."
                )
            
            # Extract parameters from query (for correlation analysis)
            params = await self._extract_parameters(query, context)

            # Validate target gene
            target_gene = params.get("target_gene", "").strip().upper()
            
            # Reject dataset names as genes
            dataset_names = {"CPTAC", "TCGA"}
            if target_gene in dataset_names:
                logger.warning(
                    f"Rejected dataset name '{target_gene}' as target gene. "
                    f"Please specify a gene symbol (e.g., 'TP53', 'BRCA1')."
                )
                return self.format_response(
                    success=False,
                    message=f"'{target_gene}' appears to be a dataset name, not a gene. "
                    "Please specify a gene symbol (e.g., 'TP53', 'BRCA1', 'EGFR')."
                )
            
            if not target_gene:
                return self.format_response(
                    success=False,
                    message="Could not identify target gene from query. "
                    "Please specify a gene (e.g., 'TP53', 'BRCA1')."
                )
            
            params["target_gene"] = target_gene

            # Determine data source and get expression data
            data_source = params.get("data_source", "TCGA").upper()
            
            if data_source == "CPTAC":
                # Use CPTAC service
                expression_data = await self.cptac_service.get_expression_data(
                    cancer_type=params["cancer_type"],
                    data_type=params.get("data_type", "proteomics")
                )
                source_name = "CPTAC"
            else:
                # Default to TCGA
                expression_data = await self.tcga_service.get_expression_data(
                    cancer_type=params["cancer_type"],
                    data_type=params.get("data_type", "RNA-seq")
                )
                source_name = "TCGA"

            # Check if target gene exists
            target_gene = params.get("target_gene", "").strip()
            logger.info(
                f"Looking for target gene '{target_gene}' in {source_name} "
                f"{params.get('cancer_type')} dataset (index length: {len(expression_data.index)})"
            )
            
            if target_gene not in expression_data.index:
                # Try case-insensitive search
                gene_matches = [
                    g for g in expression_data.index
                    if str(g).upper() == target_gene.upper()
                ]
                if gene_matches:
                    params["target_gene"] = gene_matches[0]
                    logger.info(
                        f"Matched '{target_gene}' to '{gene_matches[0]}' (case-insensitive)"
                    )
                else:
                    # Log first 20 genes for debugging
                    sample_genes = list(expression_data.index[:20])
                    logger.warning(
                        f"Gene '{target_gene}' not found. Sample genes in dataset: {sample_genes}"
                    )
                    entity_type = "protein" if source_name == "CPTAC" and params.get("data_type") == "proteomics" else "gene"
                    return self.format_response(
                        success=False,
                        message=f"{entity_type.capitalize()} {target_gene} not found in "
                        f"{params['cancer_type']} {source_name} dataset. "
                        f"Available {entity_type}s: {len(expression_data)}."
                    )
            else:
                logger.info(f"✅ Found target gene '{target_gene}' in dataset index")

            # Perform correlation analysis
            correlation_results = self.analysis_tools.correlation_analysis(
                expression_data=expression_data,
                target_gene=params["target_gene"],
                method=params.get("correlation_method", "pearson"),
                min_abs_correlation=params.get("min_correlation", 0.3)
            )

            if correlation_results.empty:
                return self.format_response(
                    success=True,
                    data={
                        "target_gene": params["target_gene"],
                        "cancer_type": params["cancer_type"],
                        "results": [],
                        "total_results": 0
                    },
                    message=f"No genes found with correlation >= "
                    f"{params.get('min_correlation', 0.3)} "
                    f"for {params['target_gene']} in {params['cancer_type']}"
                )

            # Convert results to list of dicts
            results_list = correlation_results.head(100).to_dict("records")

            # Check if pathway enrichment is requested
            query_lower = query.lower()
            perform_pathway_enrichment = any(
                word in query_lower
                for word in ["pathway", "enrichment", "enriched", "biological process", "go", "kegg"]
            )

            pathway_results = None
            if perform_pathway_enrichment and len(correlation_results) > 0:
                # Get top correlated genes/proteins for enrichment
                # Get unique gene names (in case of duplicates)
                # Use more genes if available (up to 100) to ensure we have enough for enrichment
                max_genes_for_enrichment = min(100, len(correlation_results))
                top_identifiers = correlation_results.head(max_genes_for_enrichment)["gene"].unique().tolist()
                logger.info(
                    f"Selected {len(top_identifiers)} unique genes/proteins for pathway enrichment "
                    f"(from top {max_genes_for_enrichment} correlations)"
                )
                
                # Check if identifiers are already gene symbols or need conversion
                # Since we now use real gene names in mock data, most should be gene symbols
                if source_name.upper() == "CPTAC" and params.get("data_type") == "proteomics":
                    # Check if identifiers look like gene symbols (not UniProt IDs)
                    import re
                    uniprot_pattern = r'^[PQOA][0-9A-Z]{5,9}$'
                    gene_symbol_count = sum(
                        1 for ident in top_identifiers
                        if not re.match(uniprot_pattern, ident.upper())
                    )
                    
                    # If most identifiers are already gene symbols, use them directly
                    if gene_symbol_count >= len(top_identifiers) * 0.5:  # At least 50% are gene symbols
                        logger.info(
                            f"Most identifiers ({gene_symbol_count}/{len(top_identifiers)}) "
                            "are already gene symbols, using them directly"
                        )
                        top_genes = [ident.upper() for ident in top_identifiers]
                    else:
                        # Try to convert protein IDs to gene symbols
                        logger.info(
                            f"Converting {len(top_identifiers)} protein IDs to gene symbols for pathway enrichment"
                        )
                        top_genes = self._convert_protein_ids_to_gene_symbols(top_identifiers)
                        if not top_genes or len(top_genes) < 3:
                            logger.warning(
                                f"Could not convert protein IDs to gene symbols (got {len(top_genes) if top_genes else 0} genes). "
                                "Trying to use identifiers as-is..."
                            )
                            # Fallback: use identifiers that look like gene symbols
                            top_genes = [
                                ident.upper() for ident in top_identifiers
                                if not re.match(uniprot_pattern, ident.upper())
                            ]
                            if len(top_genes) < 3:
                                logger.warning(
                                    f"Only {len(top_genes)} gene symbols found, skipping pathway enrichment"
                                )
                                pathway_results = None
                            else:
                                logger.info(
                                    f"Using {len(top_genes)} gene symbols from identifiers"
                                )
                        else:
                            logger.info(
                                f"Converted to {len(top_genes)} gene symbols for enrichment"
                            )
                else:
                    # Already gene symbols for TCGA data
                    top_genes = top_identifiers
                
                if top_genes:
                    logger.info(
                        f"Performing pathway enrichment on {len(top_genes)} genes"
                    )
                    
                    # Determine gene set database from query
                    gene_set = "GO_Biological_Process_2021"  # Default
                    if "kegg" in query_lower:
                        gene_set = "KEGG_2021_Human"
                    elif "reactome" in query_lower:
                        gene_set = "Reactome_2022"
                    elif "hallmark" in query_lower or "msigdb" in query_lower:
                        gene_set = "MSigDB_Hallmark_2020"
                    elif "molecular function" in query_lower or "mf" in query_lower:
                        gene_set = "GO_Molecular_Function_2021"
                    elif "cellular component" in query_lower or "cc" in query_lower:
                        gene_set = "GO_Cellular_Component_2021"
                    
                    pathway_results = self.analysis_tools.pathway_enrichment(
                        gene_list=top_genes,
                        gene_set=gene_set,
                        top_n=20
                    )
                    
                    if pathway_results is not None and not pathway_results.empty:
                        logger.info(
                            f"Found {len(pathway_results)} enriched pathways"
                        )
                    else:
                        logger.warning("No enriched pathways found - pathway_results is None or empty")
                else:
                    logger.warning("No genes available for pathway enrichment (top_genes is empty)")
                    pathway_results = None

            # Generate interpretation
            interpretation = await self._interpret_results(
                params["target_gene"],
                params["cancer_type"],
                correlation_results,
                query,
                pathway_results=pathway_results
            )

            # Prepare response data
            response_data = {
                "target_gene": params["target_gene"],
                "cancer_type": params["cancer_type"],
                "data_source": source_name,
                "data_type": params.get("data_type", "RNA-seq" if source_name == "TCGA" else "proteomics"),
                "correlation_method": params.get(
                    "correlation_method", "pearson"
                ),
                "results": results_list,
                "total_results": len(correlation_results),
                "significant_results": int(
                    correlation_results["significant"].sum()
                ),
                "top_correlations": results_list[:10],
                "interpretation": interpretation
            }

            # Add pathway enrichment results if available
            if pathway_results is not None and not pathway_results.empty:
                pathway_list = pathway_results.head(20).to_dict("records")
                response_data["pathway_enrichment"] = {
                    "gene_set": gene_set,
                    "total_pathways": len(pathway_results),
                    "pathways": pathway_list,
                    "top_pathways": pathway_list[:10]
                }
                message = (
                    f"Found {len(correlation_results)} {'proteins' if source_name == 'CPTAC' and params.get('data_type') == 'proteomics' else 'genes'} correlated "
                    f"with {params['target_gene']} in {params['cancer_type']} "
                    f"({source_name} dataset, {correlation_results['significant'].sum()} significant). "
                    f"Identified {len(pathway_results)} enriched pathways."
                )
            else:
                message = (
                    f"Found {len(correlation_results)} {'proteins' if source_name == 'CPTAC' and params.get('data_type') == 'proteomics' else 'genes'} correlated "
                    f"with {params['target_gene']} in {params['cancer_type']} "
                    f"({source_name} dataset, {correlation_results['significant'].sum()} significant)"
                )

            return self.format_response(
                success=True,
                data=response_data,
                message=message
            )

        except Exception as e:
            logger.error(f"Error in AssociationAgent: {e}", exc_info=True)
            return self.format_response(
                success=False,
                message=f"Error performing association analysis: {str(e)}"
            )

    async def _extract_parameters(
        self,
        query: str,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Extract analysis parameters from query using LLM with fallback"""
        # Try LLM extraction first
        try:
            prompt = f"""Extract parameters from this association analysis query:

Query: {query}
Context: {json.dumps(context) if context else 'None'}

Extract and return a JSON object with:
- target_gene: Gene/protein symbol (e.g., "TP53", "BRCA1")
- cancer_type: Cancer type code (e.g., "BRCA", "LUAD"). Default to "BRCA" if not specified.
- data_source: "TCGA" or "CPTAC". Use "CPTAC" if query mentions "CPTAC", "proteomics", or "protein". Default to "TCGA".
- data_type: Data type ("RNA-seq", "proteomics", "miRNA", "Protein"). 
  If data_source is CPTAC and not specified, default to "proteomics".
  If data_source is TCGA and not specified, default to "RNA-seq".
- correlation_method: "pearson" or "spearman". Default to "pearson".
- min_correlation: Minimum correlation threshold (0.0 to 1.0). Default to 0.3.

Return ONLY valid JSON, no other text."""

            response = await self.invoke_llm(prompt)
            
            # Check if response contains error
            if response and ("chunk" in response.lower() or "too big" in response.lower() or "error" in response.lower()):
                logger.warning("LLM returned error in parameter extraction, using fallback")
                return self._extract_parameters_fallback(query, context)

            try:
                params = json.loads(response)
            except json.JSONDecodeError:
                logger.warning(
                    f"Failed to parse LLM response, using fallback: {response[:100]}"
                )
                return self._extract_parameters_fallback(query, context)
                
        except Exception as e:
            error_msg = str(e).lower()
            if "chunk" in error_msg or "too big" in error_msg or "context" in error_msg:
                logger.warning(f"Ollama context error in parameter extraction: {e}. Using fallback.")
                return self._extract_parameters_fallback(query, context)
            logger.warning(f"Error in parameter extraction: {e}. Using fallback.")
            return self._extract_parameters_fallback(query, context)
        
        # If we got here, we have params from LLM
        # Continue with validation...

        # Set defaults
        params.setdefault("cancer_type", "BRCA")
        params.setdefault("data_source", "TCGA")
        params.setdefault("correlation_method", "pearson")
        params.setdefault("min_correlation", 0.3)
        
        # Set data_type based on source if not specified
        data_source = params.get("data_source", "TCGA").upper()
        if "data_type" not in params:
            if data_source == "CPTAC":
                params["data_type"] = "proteomics"
            else:
                params["data_type"] = "RNA-seq"

        # Validate cancer type based on data source
        if data_source == "CPTAC":
            available_datasets = self.cptac_service.list_available_datasets()
            cancer_codes = [ds["code"] for ds in available_datasets]
        else:
            available_types = self.tcga_service.list_available_cancer_types()
            cancer_codes = [ct["code"] for ct in available_types]
        
        if params["cancer_type"].upper() not in cancer_codes:
            logger.warning(
                f"Invalid cancer type {params['cancer_type']} for {data_source}, "
                f"defaulting to BRCA"
            )
            params["cancer_type"] = "BRCA"

        return params
    
    def _extract_parameters_fallback(
        self,
        query: str,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Fallback parameter extraction without LLM - uses simple keyword matching"""
        import re
        
        query_lower = query.lower()
        params = {}
        
        # Known dataset names to exclude from gene matching
        dataset_names = {"CPTAC", "TCGA", "BRCA", "LUAD", "COAD", "OV", "GBM", "PDAC"}
        
        # Extract target gene (common gene symbols)
        # Look for patterns like TP53, BRCA1, EGFR, etc.
        gene_pattern = r'\b([A-Z]{2,}[0-9]*[A-Z]*)\b'
        gene_matches = re.findall(gene_pattern, query)
        if gene_matches:
            # Filter out dataset names and prioritize gene symbols
            for match in gene_matches:
                match_upper = match.upper()
                # Skip if it's a known dataset name
                if match_upper in dataset_names:
                    continue
                # Skip if it's a cancer type code (usually 3-4 letters)
                if len(match) <= 4 and match_upper in {"BRCA", "LUAD", "COAD", "OV", "GBM", "PDAC"}:
                    continue
                # Take the first valid gene symbol
                if len(match) >= 2 and match[0].isupper():
                    params["target_gene"] = match_upper
                    logger.info(f"Fallback extracted target gene: {match_upper}")
                    break
        
        # Detect data source
        if "cptac" in query_lower or ("proteomics" in query_lower and "protein" in query_lower):
            params["data_source"] = "CPTAC"
            params["data_type"] = "proteomics"
        else:
            params["data_source"] = "TCGA"
            params["data_type"] = "RNA-seq"
        
        # Extract cancer type (common codes)
        cancer_types = {
            "breast": "BRCA", "brca": "BRCA",
            "lung": "LUAD", "luad": "LUAD",
            "colon": "COAD", "coad": "COAD",
            "ovarian": "OV", "ov": "OV",
            "glioblastoma": "GBM", "gbm": "GBM",
            "pancreatic": "PDAC", "pdac": "PDAC"
        }
        
        for keyword, code in cancer_types.items():
            if keyword in query_lower:
                params["cancer_type"] = code
                break
        
        # Set defaults
        params.setdefault("cancer_type", "BRCA")
        params.setdefault("data_source", "TCGA")
        params.setdefault("correlation_method", "pearson")
        params.setdefault("min_correlation", 0.3)
        
        # Set data_type based on source if not specified
        data_source = params.get("data_source", "TCGA").upper()
        if "data_type" not in params:
            if data_source == "CPTAC":
                params["data_type"] = "proteomics"
            else:
                params["data_type"] = "RNA-seq"
        
        # Validate cancer type
        if data_source == "CPTAC":
            available_datasets = self.cptac_service.list_available_datasets()
            cancer_codes = [ds["code"] for ds in available_datasets]
        else:
            available_types = self.tcga_service.list_available_cancer_types()
            cancer_codes = [ct["code"] for ct in available_types]
        
        if params["cancer_type"].upper() not in cancer_codes:
            params["cancer_type"] = "BRCA"
        
        logger.info(f"Fallback parameter extraction: {params}")
        return params

    def _extract_gene_list_from_query(self, query: str) -> list[str]:
        """Extract a list of gene symbols from a query"""
        import re
        
        # Known dataset names and cancer types to exclude
        excluded_keywords = {
            "CPTAC", "TCGA", "BRCA", "LUAD", "COAD", "OV", "GBM", "PDAC",
            "RNA", "SEQ", "PROTEOMICS", "PROTEIN", "GENE", "GENES"
        }
        
        # Pattern to match gene symbols (2-10 uppercase letters, may include numbers)
        # Common format: TP53, BRCA1, EGFR, etc.
        gene_pattern = r'\b([A-Z]{2,}[0-9]*[A-Z]*)\b'
        matches = re.findall(gene_pattern, query)
        
        # Filter out excluded keywords and duplicates
        gene_list = []
        seen = set()
        for match in matches:
            match_upper = match.upper()
            if match_upper not in excluded_keywords and match_upper not in seen:
                # Additional validation: should start with a letter
                if match[0].isalpha() and len(match) >= 2:
                    gene_list.append(match_upper)
                    seen.add(match_upper)
        
        logger.info(f"Extracted {len(gene_list)} genes from query: {gene_list[:10]}")
        return gene_list

    async def _interpret_pathway_results(
        self,
        gene_list: list[str],
        pathway_results: Any,  # pd.DataFrame
        original_query: str
    ) -> str:
        """Generate AI interpretation of pathway enrichment results"""
        try:
            top_pathways = pathway_results.head(5)
            
            summary = f"""Pathway enrichment analysis for {len(gene_list)} genes found {len(pathway_results)} enriched pathways.
Top 5 enriched pathways:
"""
            for idx, row in top_pathways.iterrows():
                pathway_name = row.get('pathway', 'Unknown')
                p_val = row.get('adjusted_p_value', row.get('p_value', 0))
                odds_ratio = row.get('odds_ratio', 0)
                summary += (
                    f"- {pathway_name}: "
                    f"p={p_val:.2e}, OR={odds_ratio:.2f}\n"
                )
            
            summary += "\nThese pathways are significantly enriched, suggesting the input genes are functionally related."
            
            # Use LLM for more detailed interpretation if available
            try:
                prompt = f"""Interpret these pathway enrichment results in biological context:

Genes analyzed: {', '.join(gene_list[:10])}
Total enriched pathways: {len(pathway_results)}

Top 5 pathways:
{summary}

Provide a brief (2-3 sentence) biological interpretation of what these enriched pathways suggest about the functional relationships between these genes."""
                
                interpretation = await self.invoke_llm(prompt)
                if interpretation and len(interpretation) > 50:
                    return interpretation
            except Exception as e:
                logger.warning(f"LLM interpretation failed: {e}, using summary")
            
            return summary
            
        except Exception as e:
            logger.error(f"Error interpreting pathway results: {e}")
            return f"Found {len(pathway_results)} enriched pathways for {len(gene_list)} genes."

    async def _interpret_results(
        self,
        target_gene: str,
        cancer_type: str,
        results: Any,  # pd.DataFrame
        original_query: str,
        pathway_results: Optional[Any] = None  # pd.DataFrame
    ) -> str:
        """Generate AI interpretation of correlation results"""
        try:
            # Only use top 5 results to keep prompt small
            top_results = results.head(5)

            summary = f"""Found {len(results)} correlations with {target_gene} in {cancer_type}.
Top 5 correlations:
"""
            for idx, row in top_results.iterrows():
                summary += (
                    f"- {row['gene']}: r={row['correlation']:.3f}, "
                    f"p={row['adjusted_p_value']:.2e}"
                )
                if row['significant']:
                    summary += " (significant)"
                summary += "\n"

            # Add pathway enrichment info if available
            if pathway_results is not None and not pathway_results.empty:
                top_pathways = pathway_results.head(5)
                summary += "\nEnriched Pathways (top 5):\n"
                for idx, row in top_pathways.iterrows():
                    pathway_name = row.get('pathway', 'Unknown')
                    p_val = row.get('adjusted_p_value', row.get('p_value', 0))
                    summary += f"- {pathway_name}: p={p_val:.2e}\n"

            # Limit summary length
            if len(summary) > 500:
                summary = summary[:500] + "... [truncated]"

            prompt = f"""Interpret these correlation analysis results in biological context:

Target: {target_gene}
Cancer: {cancer_type}

Results:
{summary}

Provide a brief interpretation (2-3 sentences) highlighting main findings and biological significance."""

            # Limit total prompt size
            if len(prompt) > 1000:
                prompt = prompt[:1000] + "... [truncated]"

            interpretation = await self.invoke_llm(prompt)
            
            # Check if interpretation contains error
            if interpretation and ("chunk" in interpretation.lower() or "error" in interpretation.lower()):
                logger.warning("LLM returned error in interpretation, using fallback")
                return self._generate_fallback_interpretation(target_gene, cancer_type, results)
            
            return interpretation
            
        except Exception as e:
            error_msg = str(e).lower()
            if "chunk" in error_msg or "too big" in error_msg or "context" in error_msg:
                logger.error(f"Ollama context error in interpretation: {e}. Using fallback.")
                return self._generate_fallback_interpretation(target_gene, cancer_type, results)
            logger.error(f"Error generating interpretation: {e}")
            return self._generate_fallback_interpretation(target_gene, cancer_type, results)
    
    def _generate_fallback_interpretation(
        self,
        target_gene: str,
        cancer_type: str,
        results: Any  # pd.DataFrame
    ) -> str:
        """Generate a simple interpretation without LLM"""
        top_3 = results.head(3)
        top_genes = ", ".join([row['gene'] for _, row in top_3.iterrows()])
        
        return (
            f"Found {len(results)} correlations with {target_gene} in {cancer_type}. "
            f"Top correlated: {top_genes}. "
            f"{results['significant'].sum()} correlations are statistically significant (FDR < 0.05)."
        )
    
    def _convert_protein_ids_to_gene_symbols(
        self,
        protein_ids: list[str]
    ) -> list[str]:
        """
        Convert UniProt protein IDs to gene symbols using mygene.
        
        Args:
            protein_ids: List of protein identifiers (UniProt IDs like P07963, or gene symbols)
        
        Returns:
            List of gene symbols (validated and converted)
        """
        try:
            import mygene
            import re
            
            # Filter out identifiers that are already gene symbols (not UniProt format)
            # UniProt IDs typically start with P, Q, O, A, or are 6-10 alphanumeric characters
            uniprot_pattern = r'^[PQOA][0-9A-Z]{5,9}$'
            
            protein_ids_to_convert = []
            gene_symbols = []
            
            for identifier in protein_ids:
                # Check if it's already a gene symbol (not matching UniProt pattern)
                if not re.match(uniprot_pattern, identifier.upper()):
                    # Likely already a gene symbol (e.g., TP53, BRCA1)
                    gene_symbols.append(identifier.upper())
                else:
                    # UniProt ID - needs conversion
                    protein_ids_to_convert.append(identifier)
            
            if not protein_ids_to_convert:
                # All were already gene symbols
                logger.info(f"All {len(gene_symbols)} identifiers are already gene symbols")
                return gene_symbols
            
            logger.info(
                f"Converting {len(protein_ids_to_convert)} UniProt IDs to gene symbols "
                f"({len(gene_symbols)} already gene symbols)"
            )
            
            # Use mygene to query UniProt IDs
            mg = mygene.MyGeneInfo()
            # Query with UniProt IDs
            results = mg.querymany(
                protein_ids_to_convert,
                scopes='uniprot',
                fields='symbol',
                species='human',
                returnall=True
            )
            
            # Extract gene symbols from results
            for result in results['out']:
                if 'symbol' in result and result['symbol']:
                    gene_symbol = result['symbol']
                    if isinstance(gene_symbol, list):
                        gene_symbol = gene_symbol[0]  # Take first if multiple
                    gene_symbols.append(gene_symbol.upper())
                elif 'query' in result:
                    # If conversion failed, check if query is already a gene symbol
                    query = result['query']
                    # If it doesn't match UniProt pattern, it might be a gene symbol
                    if not re.match(uniprot_pattern, query.upper()):
                        gene_symbols.append(query.upper())
                    # For fake UniProt IDs that can't be converted, skip them
            
            # Remove duplicates and None values
            gene_symbols = list(set([g for g in gene_symbols if g]))
            
            # If we have very few converted genes, try to use identifiers that look like gene symbols
            if len(gene_symbols) < 3:
                logger.warning(
                    f"Only {len(gene_symbols)} genes converted. "
                    "Trying to extract gene symbols from identifiers that don't match UniProt pattern..."
                )
                # Check all original identifiers for ones that look like gene symbols
                for identifier in protein_ids:
                    identifier_upper = identifier.upper()
                    # Skip if it matches UniProt pattern (fake IDs)
                    if not re.match(uniprot_pattern, identifier_upper):
                        # Looks like a gene symbol (e.g., TP53, BRCA1)
                        if identifier_upper not in gene_symbols:
                            gene_symbols.append(identifier_upper)
            
            # Remove duplicates again
            gene_symbols = list(set([g for g in gene_symbols if g]))
            
            logger.info(
                f"Successfully converted to {len(gene_symbols)} unique gene symbols "
                f"(from {len(protein_ids)} input identifiers)"
            )
            
            return gene_symbols
            
        except ImportError:
            logger.error("mygene not installed. Install with: pip install mygene")
            # Fallback: try to use identifiers as-is (some might already be gene symbols)
            return [pid.upper() for pid in protein_ids if pid]
        except Exception as e:
            logger.error(f"Error converting protein IDs to gene symbols: {e}", exc_info=True)
            # Fallback: return identifiers as-is
            return [pid.upper() for pid in protein_ids if pid]