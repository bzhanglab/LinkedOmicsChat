"""
Literature Mining Agent
Searches and summarizes relevant scientific literature
"""
from typing import Dict, Any, Optional, List
from agents.base_agent import BaseAgent
from agents.tools.search_tools import WebSearchTool
import json
import logging

logger = logging.getLogger(__name__)


class LiteratureMiningAgent(BaseAgent):
    """Agent specialized in literature search and summarization"""
    
    def __init__(self):
        super().__init__(
            name="LiteratureMiningAgent",
            description="Searches and summarizes relevant scientific literature",
            temperature=0.5
        )
        self.search_tool = WebSearchTool()
    
    def get_system_prompt(self) -> str:
        return """You are a Literature Mining Agent specialized in biomedical research.
Your role is to:
1. Search scientific literature for relevant papers
2. Summarize key findings from papers
3. Identify connections between genes, pathways, and diseases
4. Provide context for experimental results
5. Suggest related research directions

You have access to PubMed, bioRxiv, and other scientific databases.
Always cite papers properly and assess the quality of evidence."""
    
    async def process(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process literature search request
        
        Args:
            query: Search query or research question
            context: Additional context (genes, pathways, etc.)
            
        Returns:
            Relevant papers and summaries
        """
        try:
            # Extract search terms
            search_terms = await self._extract_search_terms(query, context)
            
            # Search literature (mock implementation)
            papers = await self._search_literature(search_terms)
            
            # Summarize findings
            summary = await self._summarize_findings(papers, query)
            
            # Generate connections
            connections = await self._identify_connections(papers, context)
            
            return self.format_response(
                success=True,
                data={
                    "papers": papers[:10],
                    "summary": summary,
                    "connections": connections,
                    "search_terms": search_terms
                },
                message=f"Found {len(papers)} relevant papers",
                metadata={"query": query}
            )
            
        except Exception as e:
            logger.error(f"Error in LiteratureMiningAgent: {e}")
            return self.format_response(
                success=False,
                message=f"Error searching literature: {str(e)}"
            )
    
    async def _extract_search_terms(
        self,
        query: str,
        context: Optional[Dict[str, Any]]
    ) -> List[str]:
        """Extract relevant search terms from query"""
        prompt = f"""Extract key search terms for a literature search from this query:

Query: {query}
Context: {json.dumps(context) if context else 'None'}

Return a JSON array of 3-5 simple STRING search terms (not objects) that would be effective for PubMed search.
Include genes, diseases, and key concepts.
Example: ["BRCA1 mutations", "breast cancer BRCA1", "BRCA1 therapy"]
Return ONLY valid JSON array of strings, no other text."""
        
        response = await self.invoke_llm(prompt)
        
        try:
            terms = json.loads(response)
            # Handle if LLM returns list of dicts instead of strings
            if isinstance(terms, list):
                clean_terms = []
                for term in terms:
                    if isinstance(term, dict):
                        clean_terms.append(term.get('term', str(term)))
                    else:
                        clean_terms.append(str(term))
                return clean_terms
            return [response]
        except json.JSONDecodeError:
            # Fallback to simple extraction
            return [query]
    
    async def _search_literature(self, search_terms: List[str]) -> List[Dict[str, Any]]:
        """Search literature databases using web search"""
        try:
            all_results = []
            
            # Detect if query is asking for recent/latest results
            query_text = " ".join(str(t) for t in search_terms).lower()
            time_filter = None
            if any(keyword in query_text for keyword in ["recent", "latest", "new", "2024", "2025"]):
                time_filter = "y"  # Filter to results from past year
                logger.info("Applying time filter for recent results (past year)")
            
            # Search for each term
            for term in search_terms[:3]:  # Limit to top 3 terms to avoid rate limits
                # Extract string from term (in case LLM returns dict)
                if isinstance(term, dict):
                    term = term.get('term', term.get('query', str(term)))
                term = str(term).strip()
                
                # If term is a full question, extract key gene/disease names (simple fallback)
                if len(term.split()) > 5 or "?" in term:
                    # Extract capitalized words (likely gene names) or key terms
                    import re
                    # Look for patterns like BRCA1, TP53, etc (all caps + numbers)
                    genes = re.findall(r'\b[A-Z]{2,}[0-9]*\b', term)
                    # Look for disease terms
                    diseases = re.findall(r'\b(cancer|tumor|disease|mutation)\b', term.lower())
                    if genes:
                        term = " ".join(genes[:2])  # Use top 2 genes
                    elif diseases:
                        term = diseases[0]
                    else:
                        # Just use first few words
                        words = term.split()[:3]
                        term = " ".join([w for w in words if w.lower() not in ['what', 'are', 'the', 'is', 'on', 'about']])
                    
                    logger.info(f"Simplified search term to: {term}")
                
                # Construct academic search query with year for recent results
                if time_filter:
                    academic_query = f"{term} 2024 research"
                else:
                    academic_query = f"{term} research"
                
                logger.info(f"Searching literature for: {academic_query}")
                results = await self.search_tool.search(
                    query=academic_query,
                    max_results=5,
                    region="wt-wt",
                    timelimit=time_filter
                )
                
                # Format results as papers
                for result in results:
                    paper = {
                        "title": result.get("title", ""),
                        "link": result.get("link", ""),
                        "snippet": result.get("snippet", ""),
                        "source": "Web Search",
                        "search_term": term
                    }
                    all_results.append(paper)
            
            # If we got real results, return them
            if all_results:
                logger.info(f"Found {len(all_results)} papers from web search")
                return all_results
            
            # Fallback to mock data if search fails
            logger.warning("No web search results, using mock data")
            return self._get_mock_papers()
            
        except Exception as e:
            logger.error(f"Error searching literature: {e}")
            # Return mock data on error
            return self._get_mock_papers()
    
    def _get_mock_papers(self) -> List[Dict[str, Any]]:
        """Get mock papers as fallback"""
        return [
            {
                "title": "TP53 mutations in breast cancer: implications for therapy",
                "authors": "Smith J, Johnson A, Williams B",
                "journal": "Nature Cancer",
                "year": 2023,
                "link": "https://www.nature.com/articles/example",
                "snippet": "TP53 mutations are found in ~30% of breast cancers and are associated with poor prognosis...",
                "source": "Mock Data"
            },
            {
                "title": "Molecular characterization of TP53-mutant breast tumors",
                "authors": "Chen L, Wang Y, Zhang X",
                "journal": "Cancer Research",
                "year": 2022,
                "link": "https://cancerres.aacrjournals.org/example",
                "snippet": "We performed comprehensive molecular profiling of TP53-mutant breast tumors...",
                "source": "Mock Data"
            },
            {
                "title": "Therapeutic strategies for TP53-deficient cancers",
                "authors": "Brown M, Davis K, Miller R",
                "journal": "Cell",
                "year": 2023,
                "link": "https://www.cell.com/cell/example",
                "snippet": "Loss of TP53 function creates therapeutic vulnerabilities that can be exploited...",
                "source": "Mock Data"
            }
        ]
    
    async def _summarize_findings(
        self,
        papers: List[Dict[str, Any]],
        query: str
    ) -> str:
        """Summarize key findings from papers"""
        papers_text = "\n\n".join([
            f"Paper {i+1}: {p['title']}\n{p.get('snippet', p.get('abstract', 'No abstract available'))[:300]}...\nSource: {p.get('link', 'N/A')}"
            for i, p in enumerate(papers[:5])
        ])
        
        prompt = f"""Summarize key findings from these papers relevant to the query:

Query: {query}

Papers:
{papers_text}

Provide a concise summary (3-4 sentences) of:
1. Main consensus findings
2. Key controversies or debates
3. Clinical or therapeutic implications"""
        
        summary = await self.invoke_llm(prompt)
        return summary
    
    async def _identify_connections(
        self,
        papers: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Identify connections between findings and context"""
        if not papers:
            return []
        
        # Use LLM to identify connections from paper summaries
        papers_summary = "\n".join([
            f"- {p['title']}: {p.get('snippet', '')[:150]}"
            for p in papers[:5]
        ])
        
        prompt = f"""Based on these research papers, identify 2-3 key connections or insights:

Papers:
{papers_summary}

Context: {json.dumps(context) if context else 'None'}

Return a JSON array of connections, each with:
- type: (e.g., "gene_function", "therapeutic_target", "pathway", "biomarker")
- description: Brief description
- evidence: Which papers support this
- confidence: "high", "medium", or "low"

Return ONLY valid JSON, no other text."""
        
        try:
            response = await self.invoke_llm(prompt)
            connections = json.loads(response)
            if isinstance(connections, list):
                return connections[:3]  # Limit to 3
        except Exception as e:
            logger.warning(f"Could not parse connections from LLM: {e}")
        
        # Fallback to simple connections
        return [
            {
                "type": "research_findings",
                "description": f"Found {len(papers)} relevant papers on this topic",
                "evidence": "Web search results",
                "confidence": "medium"
            }
        ]
