"""
MCP-based Orchestrator
When settings.USE_LANGGRAPH=True (default), delegates to LangGraphOrchestrator
for chained / parallel / conditional tool execution via LangGraph.
Falls back to the legacy single-shot planner when USE_LANGGRAPH=False.
"""
from typing import Dict, Any, Optional, List, AsyncGenerator
import logging
import time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.llm_factory import LLMFactory
from core.database import SessionLocal
from models.database import ChatSession, ChatMessage as DBChatMessage, TokenUsage, GuestTokenUsage
from services.mcp_aggregator import MCPAggregator

logger = logging.getLogger(__name__)


class MCPOrchestrator:
    """Orchestrator that uses MCP tools instead of direct agent calls"""
    
    def __init__(self):
        self.mcp_aggregator = MCPAggregator()
        self.llm = LLMFactory.create_llm(
            model=settings.DEFAULT_LLM_MODEL,
            temperature=0.3
        )
        self.sessions = {}

        # LangGraph delegate (initialised lazily in initialize())
        self._langgraph_orch = None
        if settings.USE_LANGGRAPH:
            try:
                from services.langgraph_orchestrator import LangGraphOrchestrator
                # Pass self so LangGraph shares our sessions dict and DB session
                # methods — this ensures chat history persists and the chat API
                # (GET /sessions/{id}, etc.) continues to work unchanged.
                self._langgraph_orch = LangGraphOrchestrator(parent_orchestrator=self)
                logger.info("LangGraphOrchestrator created — will be used for process_query.")
            except Exception as e:
                logger.warning(f"Could not create LangGraphOrchestrator: {e}. Falling back to legacy planner.")

        
        # Try to load valid genes for strict validation
        self.valid_genes = set()
        try:
            import os
            # Assume valid_genes.txt is in the project root (2 levels up from services/)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            valid_genes_path = os.path.join(project_root, "valid_genes.txt")
            if os.path.exists(valid_genes_path):
                with open(valid_genes_path, "r") as f:
                    self.valid_genes = {line.strip().upper() for line in f if line.strip()}
                logger.info(f"Loaded {len(self.valid_genes)} valid genes from {valid_genes_path}")
            else:
                logger.warning(f"valid_genes.txt not found at {valid_genes_path}, falling back to loose validation")
        except Exception as e:
            logger.error(f"Failed to load valid_genes.txt: {e}")
        
        # Expert guidelines for biological reasoning
        self.BIO_GUIDELINES = """
### BIOLOGICAL REASONING GUIDELINES:
1. **Statistical Significance**: A p-value < 0.05 is typically significant. For survival curves (Kaplan-Meier), a lower p-value indicates a stronger correlation.
2. **Omics Vocabulary**: 
   - 'mRNA/RNA' refers to gene expression levels. 
   - 'Protein' refers to proteomic abundance.
   - 'Log Ratio' or 'Fold Change' indicates relative expression (positive = upregulated, negative = downregulated).
3. **Cross-Omics Synthesis**: If you have information about both expression and survival, explain how they relate (e.g., "High expression of MYC correlates with poor survival outcomes, suggesting oncogenic potential").
4. **Context Matters**: LinkedOmics data comes from specific CPTAC and TCGA cohorts. Always mention the cancer type (e.g., GBM, BRCA) if known.
"""
    
    async def initialize(self):
        """Initialize MCP connections (and the LangGraph agent if enabled)."""
        logger.info("Initializing MCP Orchestrator...")
        await self.mcp_aggregator.initialize()
        logger.info("MCP Orchestrator initialized")
        if self._langgraph_orch:
            try:
                await self._langgraph_orch.initialize()
                logger.info("LangGraphOrchestrator initialized successfully.")
            except Exception as e:
                logger.warning(f"LangGraphOrchestrator init failed: {e}. Falling back to legacy planner.")
                self._langgraph_orch = None
    
    async def cleanup(self):
        """Cleanup resources."""
        if self._langgraph_orch:
            await self._langgraph_orch.cleanup()
        await self.mcp_aggregator.cleanup()
        self.sessions.clear()
        logger.info("MCP Orchestrator cleaned up")
    
    async def process_query_stream(
        self,
        query: str,
        user_id: str,
        session_id: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream the execution progress using Server-Sent Events (SSE).
        Delegates to LangGraph if enabled.
        """
        if self._langgraph_orch:
            # We must use 'async for' to yield chunks from the delegated generator
            async for chunk in self._langgraph_orch.process_query_stream(query, user_id, session_id, client_ip=client_ip):
                yield chunk
        else:
            import json
            yield f"data: {json.dumps({'type': 'status', 'content': 'Processing query (Legacy mode)...'})}\n\n"
            result = await self.process_query(query, user_id, session_id)
            yield f"data: {json.dumps({'type': 'final', 'content': result})}\n\n"

    async def process_query(
        self,
        query: str,
        user_id: str,
        session_id: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a user query using MCP tools

        Args:
            query: User's research question
            user_id: User identifier
            session_id: Optional session ID for context
            client_ip: Client IP for guest token tracking

        Returns:
            Response with data from MCP tools
        """
        # Delegate to LangGraph when available
        if self._langgraph_orch:
            return await self._langgraph_orch.process_query(query, user_id, session_id, client_ip=client_ip)

        # ── Legacy single-shot planner (fallback) ───────────────────────────
        try:
            logger.info(f"Processing query via MCP (legacy planner): {query}")

            # Get or create session
            session = await self._get_or_create_session(session_id, user_id, client_ip=client_ip)
            
            # Simple intent classification
            intent = await self._classify_intent(query, session)
            logger.info(f"Query intent: {intent}")
            
            # Use LLM to determine which tools to call
            tools_to_call = await self._determine_tools(query, intent, session)
            
            # Execute tools
            results = {}
            active_gene = session.get("context", {}).get("active_gene")
            
            # Track tool call counts to generate unique keys for duplicate tools
            tool_call_counts = {}
            
            for tool_call in tools_to_call:
                tool_id = tool_call["tool"]
                args = tool_call["arguments"]
                
                # Generate unique key for this tool call
                if tool_id in tool_call_counts:
                    tool_call_counts[tool_id] += 1
                    unique_key = f"{tool_id}#{tool_call_counts[tool_id]}"
                else:
                    tool_call_counts[tool_id] = 0
                    unique_key = f"{tool_id}#0"
                
                # Update active gene tracking from tool arguments
                # Most genomic tools use 'protein' or 'gene_symbol'
                gene_arg = args.get("protein") or args.get("gene_symbol")
                if gene_arg and isinstance(gene_arg, str) and gene_arg.lower() not in ["it", "its", "it's"]:
                    active_gene = gene_arg.upper()
                
                try:
                    result = await self.mcp_aggregator.call_tool(tool_id, args)
                    # Wrap result with metadata for formatting
                    results[unique_key] = {
                        "_gene": gene_arg,  # Store gene name for display
                        "_result": result
                    }
                    logger.info(f"Tool {tool_id} executed successfully (stored as {unique_key})")
                except Exception as e:
                    logger.error(f"Error calling tool {tool_id}: {e}")
                    results[unique_key] = {
                        "_gene": gene_arg,
                        "_result": {"error": str(e)}
                    }
            
            # Update session context with last used gene
            if not active_gene:
                # If no tools were called or no gene found in args, try to extract from query
                gene_symbols = self._extract_gene_symbols(query)
                active_gene = gene_symbols[0] if gene_symbols else None
                
            if "context" not in session:
                session["context"] = {}
            if active_gene:
                session["context"]["active_gene"] = active_gene
            
            # Generate final response using LLM (pass intent to avoid gene extraction for conversational queries)
            final_response = await self._generate_response(query, results, session, intent)
            
            # Format response to match expected API structure (before saving)
            formatted_response = {
                "success": final_response.get("success", True),
                "summary": final_response.get("summary", ""),
                "message": final_response.get("message", ""),  # Keep for backward compatibility
                "query": query,
                "tools_used": final_response.get("tools_used", []),
                "raw_results": final_response.get("raw_results", {}),
                "visualizations": [],
                "analyses": [],
                "suggestions": [],
                "datasets": [],
                "papers": []
            }
            
            # Update session
            await self._update_session(session, query, formatted_response)
            
            # Return with session_id
            return {
                **formatted_response,
                "session_id": session["id"]
            }
            
        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Error processing query: {str(e)}",
                "query": query
            }
    
    async def _get_or_create_session(
        self,
        session_id: Optional[str],
        user_id: str,
        client_ip: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get or create a session. Guest sessions (user_id='guest') are in-memory only."""
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]

        # Guest sessions: skip DB entirely, create in-memory session only
        if user_id == "guest":
            sid = session_id or f"guest-{time.time()}"
            session = {
                "id": sid,
                "user_id": "guest",
                "client_ip": client_ip,
                "title": "Guest Session",
                "context": {},
                "history": [],
                "created_at": time.time(),
                "last_updated": time.time(),
            }
            self.sessions[sid] = session
            return session

        # Load from database or create new
        if settings.DATABASE_URL.startswith("sqlite"):
            db = SessionLocal()
            try:
                if session_id:
                    db_session = db.query(ChatSession).filter(
                        ChatSession.id == session_id,
                        ChatSession.user_id == user_id
                    ).first()
                    if db_session:
                        # Load history as well
                        messages = db.query(DBChatMessage).filter(
                            DBChatMessage.session_id == session_id
                        ).order_by(DBChatMessage.timestamp.asc()).all()
                        
                        history = [
                            {"query": m.query, "response": m.response, "timestamp": m.timestamp}
                            for m in messages
                        ]
                        
                        session = {
                            "id": db_session.id,
                            "user_id": db_session.user_id,
                            "title": db_session.title,
                            "context": db_session.context or {},
                            "history": history,
                            "created_at": db_session.created_at,
                            "last_updated": db_session.last_updated
                        }
                        self.sessions[session_id] = session
                        return session
                
                # Create new session
                new_session = ChatSession(
                    id=session_id or str(time.time()),
                    user_id=user_id,
                    title="New Chat",
                    created_at=time.time(),
                    last_updated=time.time(),
                    context={}
                )
                db.add(new_session)
                db.commit()
                
                session = {
                    "id": new_session.id,
                    "user_id": new_session.user_id,
                    "title": new_session.title,
                    "context": new_session.context or {},
                    "history": [],
                    "created_at": new_session.created_at,
                    "last_updated": new_session.last_updated
                }
                self.sessions[session["id"]] = session
                return session
            finally:
                db.close()
        else:
            # PostgreSQL async
            async with SessionLocal() as db:
                if session_id:
                    result = await db.execute(
                        select(ChatSession).filter(
                            ChatSession.id == session_id,
                            ChatSession.user_id == user_id
                        )
                    )
                    db_session = result.scalar_one_or_none()
                    if db_session:
                        # Load history (async)
                        messages_result = await db.execute(
                            select(DBChatMessage).filter(
                                DBChatMessage.session_id == session_id
                            ).order_by(DBChatMessage.timestamp.asc())
                        )
                        messages = messages_result.scalars().all()
                        
                        history = [
                            {"query": m.query, "response": m.response, "timestamp": m.timestamp}
                            for m in messages
                        ]
                        
                        session = {
                            "id": db_session.id,
                            "user_id": db_session.user_id,
                            "title": db_session.title,
                            "context": db_session.context or {},
                            "history": history,
                            "created_at": db_session.created_at,
                            "last_updated": db_session.last_updated
                        }
                        self.sessions[session_id] = session
                        return session
                
                # Create new session
                new_session = ChatSession(
                    id=session_id or str(time.time()),
                    user_id=user_id,
                    title="New Chat",
                    created_at=time.time(),
                    last_updated=time.time(),
                    context={}
                )
                db.add(new_session)
                await db.commit()
                
                session = {
                    "id": new_session.id,
                    "user_id": new_session.user_id,
                    "title": new_session.title,
                    "context": new_session.context or {},
                    "history": [],
                    "created_at": new_session.created_at,
                    "last_updated": new_session.last_updated
                }
                self.sessions[session["id"]] = session
                return session
    
    async def _classify_intent(self, query: str, session: Dict[str, Any]) -> str:
        """Classify query intent using LLM for robust, context-aware categorization"""
        
        # Fast path: very short queries are likely conversational
        if len(query.strip()) <= 3:
            return "conversational"
        
        # Use LLM for intent classification if available
        if self.llm and not settings.MOCK_LLM:
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                
                # Get recent conversation context
                history_str = self._format_recent_history(session, limit=5)
                
                system_prompt = """You are an intent classifier for a bioinformatics research assistant.

Your task: Classify the user's query into ONE of these categories:

1. **conversational**: Greetings, thanks, general chat, questions about the assistant itself
   Examples: "hello", "thanks", "who are you", "what can you do", "ok", "why?"

2. **linkedomics_query**: Requests for omics data from LinkedOmics/CPTAC/TCGA databases
   Examples: survival analysis, expression data, correlations, clinical trials, FunMap neighborhoods
   Keywords: survival, expression, correlation, methylation, clinical trial, funmap, cis, trans

3. **gene_query**: Questions about specific genes/proteins (general information)
   Examples: "What is TP53?", "Tell me about BRCA1", "What does MYC do?"
   
4. **data_query**: Questions about datasets, data availability, or data sources
   Examples: "What datasets do you have?", "Show me TCGA data", "What's in CPTAC?"

5. **general**: Everything else (fallback category)

CRITICAL RULES:
- Output ONLY valid JSON: {"intent": "category_name", "reasoning": "brief explanation"}
- NO markdown, NO code blocks, NO extra text
- Consider conversation context when classifying
- If a query mentions a gene AND asks for omics data → linkedomics_query (not gene_query)
- If uncertain, prefer the most specific category that matches"""

                human_prompt = f"""Conversation History:
{history_str if history_str else "(No previous context)"}

Current User Query: "{query}"

Classify this query. Return JSON only."""

                response = await LLMFactory.invoke_async(
                    self.llm,
                    [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
                )
                
                # Parse LLM response
                parsed = self._extract_json_obj(response)
                if parsed and isinstance(parsed, dict) and "intent" in parsed:
                    intent = parsed["intent"]
                    reasoning = parsed.get("reasoning", "")
                    
                    # Validate intent is one of our known categories
                    valid_intents = {"conversational", "linkedomics_query", "gene_query", "data_query", "general"}
                    if intent in valid_intents:
                        logger.info(f"LLM Intent Classification: {intent} | Reasoning: {reasoning}")
                        return intent
                    else:
                        logger.warning(f"LLM returned invalid intent '{intent}', falling back to keyword-based")
                
            except Exception as e:
                logger.warning(f"LLM intent classification failed: {e}, falling back to keyword-based")
        
        # Fallback: keyword-based classification (legacy behavior)
        return self._classify_intent_keywords(query)
    
    def _classify_intent_keywords(self, query: str) -> str:
        """Fallback keyword-based intent classification (legacy)"""
        query_lower = query.lower()
        
        # Check for short conversational responses or common words first
        if query_lower in ["not", "why", "why not", "ok", "okay", "thanks", "thank you", "yes", "no", "sure"]:
            return "conversational"

        if any(word in query_lower for word in ["hello", "hi", "how are you", "who are you", "what can you do", "help"]):
            return "conversational"
        
        if any(
            word in query_lower
            for word in [
                "survival",
                "clinical trial",
                "trial",
                "funmap",
                "neighborhood",
                "linkedomics",
                "expression",
                "overexpress",
                "underexpress",
                "tumor vs normal",
                "tumour vs normal",
                "cis",
                "correlation",
                "methylation",
                "scnv",
                "copy number",
            ]
        ):
            return "linkedomics_query"
        if any(word in query_lower for word in ["gene", "protein", "tp53", "brca", "rb1", "egfr", "myc"]):
            return "gene_query"
        elif any(word in query_lower for word in ["data", "dataset", "tcga", "cptac"]):
            return "data_query"
        else:
            return "general"
    
    def _extract_gene_symbols(self, query: str) -> List[str]:
        """Extract all likely gene/protein symbols from the query using strict validation."""
        import re
        
        query_upper = query.upper()
        # Regex for gene-like tokens (2-10 chars, allowing digits)
        gene_pattern = r"\b([A-Z]{2,10}(?:\d+)?)\b"
        matches = re.findall(gene_pattern, query_upper)
        
        unique_genes = []
        seen = set()
        
        # If we have a valid gene list, use it for strict validation
        if self.valid_genes:
            # Denylist for common English words that happen to be valid HUGO gene symbols.
            # We want to ignore these unless explicitly capitalized by the user or 
            # if we have deeper NLP. For basic regex, it's safer to exclude them.
            ambiguous_genes = {"IMPACT", "SET", "MET", "FAT1", "FAT2", "FAT3", "FAT4", "CLOCK"}
            
            for match in matches:
                # Direct lookup in the valid genes set, but ignore ambiguous words
                if match in self.valid_genes and match not in seen and match not in ambiguous_genes:
                    unique_genes.append(match)
                    seen.add(match)
            return unique_genes
            
        # Fallback if valid_genes.txt couldn't be loaded (Keep minimal heuristcs)
        logger.warning("valid_genes.txt not loaded, using basic heuristics")
        skip_words = {
            "TELL", "ME", "ABOUT", "THE", "WHAT", "IS", "GENE", "PROTEIN",
            "INFORMATION", "DATA", "SHOW", "GIVE", "FIND", "SEARCH", "QUERY",
            "SURVIVAL", "CLINICAL", "TRIAL", "TRIALS", "PLOT",
            "CANCER", "TUMOR", "DISEASE", "PATIENT", "STUDY", "ANALYSIS",
            "BIOLOGY", "BIOINFORMATICS", "SCIENCE", "GENOMICS", "GENETICS"
        }
        
        for match in matches:
            if match not in skip_words and len(match) >= 3 and match not in seen:
                 unique_genes.append(match)
                 seen.add(match)
                 
        return unique_genes

    def _extract_cancer_type(self, query: str) -> Optional[str]:
        """Extract a cancer type abbreviation used by LinkedOmicsKB."""
        import re
        # Supported types in linkedomics_server.py docs
        allowed = {"CCRCC", "HNSCC", "LSCC", "LUAD", "PDAC", "BRCA", "COAD", "GBM", "OV", "UCEC"}
        tokens = re.findall(r"\b([A-Z]{2,10})\b", query.upper())
        for t in tokens:
            if t in allowed:
                return t
        return None

    def _extract_omic(self, query: str) -> str:
        q = query.lower()
        if "protein" in q:
            return "protein"
        return "RNA"

    def _compact_results_for_llm(self, results: Dict[str, Any]) -> str:
        """Create a compact, mostly-text representation of tool results for LLM summarization.

        Drops inline images/base64 blobs and caps size to avoid slow UI / huge prompts.
        """
        import json

        def _is_probably_base64(s: str) -> bool:
            # Heuristic: long strings with no whitespace are often base64
            if len(s) < 2000:
                return False
            if any(ch.isspace() for ch in s):
                return False
            return True

        def _sanitize_value(v: Any) -> Any:
            if isinstance(v, dict):
                out: Dict[str, Any] = {}
                for k, vv in v.items():
                    # Avoid heavy fields
                    if k in {"raw_results", "visualizations"}:
                        continue
                    if isinstance(vv, str) and vv.startswith("data:image/"):
                        out[k] = "<omitted: inline image data url>"
                        continue
                    if isinstance(vv, str) and _is_probably_base64(vv):
                        out[k] = f"<omitted: large base64 ({len(vv)} chars)>"
                        continue
                    out[k] = _sanitize_value(vv)
                return out
            if isinstance(v, list):
                return [_sanitize_value(x) for x in v[:50]]
            if isinstance(v, str):
                if v.startswith("data:image/"):
                    return "<omitted: inline image data url>"
                if _is_probably_base64(v):
                    return f"<omitted: large base64 ({len(v)} chars)>"
                if len(v) > 20_000:
                    return v[:20_000] + "\n...[truncated]..."
                return v
            return v

        compact: Dict[str, Any] = {}
        for tool_id, raw in (results or {}).items():
            # If aggregator returned structured JSON string, parse and strip image parts.
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict) and isinstance(parsed.get("parts"), list):
                        parsed["parts"] = [
                            p
                            for p in parsed["parts"]
                            if not (isinstance(p, dict) and p.get("type") == "image")
                        ]
                    compact[tool_id] = _sanitize_value(parsed)
                    continue
                except Exception:
                    compact[tool_id] = _sanitize_value(raw)
                    continue
            compact[tool_id] = _sanitize_value(raw)

        text = json.dumps(compact, indent=2)
        if len(text) > 80_000:
            text = text[:80_000] + "\n...[truncated]..."
        return text

    async def _llm_summarize_tool_results(self, query: str, results: Dict[str, Any]) -> str:
        """Ask the LLM to summarize tool outputs (short summary separate from full message)."""
        if not self.llm or settings.MOCK_LLM or not results:
            return ""

        try:
            from langchain_core.messages import SystemMessage, HumanMessage

            evidence = self._compact_results_for_llm(results)
            prompt = f"""User question:
{query}

Tool results (sanitized JSON):
{evidence}

CRITICAL: Your response must DIRECTLY ANSWER the user's question using the tool results above.

If the user is asking to:
- **Prioritize/Compare genes**: Provide a clear recommendation on which gene(s) to prioritize and why, based on the data.
- **Understand a gene**: Explain what the data reveals about the gene's role, expression patterns, and clinical relevance.
- **Explore relationships**: Connect the findings across different omics types and explain the biological significance.

Structure your response as:

**Direct Answer**
(2-3 sentences directly answering the user's question with a clear recommendation or conclusion)

**Key Findings**
- [3-5 bullet points highlighting the most important data points that support your answer]

**Analytical Synthesis**
(2-3 sentences connecting the datasets and explaining the biological/clinical implications)

Rules:
- Output ONLY the markdown text above.
- DO NOT use JSON, code blocks (```), or any preamble/metadata.
- Use ONLY the provided tool results.
- Be precise with biological terminology.
- DO NOT state your identity or use phrases like 'As a Senior Analyst'.
- MOST IMPORTANT: Directly answer what the user asked, don't just summarize data.
"""
            resp = await LLMFactory.invoke_async(
                self.llm,
                [
                    SystemMessage(
                        content=(
                            "You are a Senior Multi-Omics Bioinformatics Analyst.\n"
                            f"{self.BIO_GUIDELINES}"
                        )
                    ),
                    HumanMessage(content=prompt),
                ],
            )
            return (resp or "").strip()
        except Exception as e:
            logger.warning(f"LLM summarization failed: {e}")
            return ""

    async def _generate_suggestions(
        self,
        query: str,
        response_text: str,
        session: Dict[str, Any],
        n: int = 3,
    ) -> List[str]:
        """Generate n follow-up question suggestions using the LLM.

        Based on the current query, the assistant's response, and the recent
        chat history so the suggestions stay contextually relevant.
        """
        if not self.llm or settings.MOCK_LLM:
            return []
        try:
            from langchain_core.messages import SystemMessage, HumanMessage

            history_str = self._format_recent_history(session) if session else ""
            history_block = f"\nRecent conversation:\n{history_str}\n" if history_str else ""

            prompt = f"""{history_block}
The user just asked:
{query}

The assistant responded (excerpt):
{response_text[:800]}

Generate exactly {n} short, specific follow-up questions the user might naturally ask next.
Each question should be on its own line, numbered 1. 2. 3. etc.
Do NOT include any preamble or explanation — output only the numbered questions.

IMPORTANT — LinkedOmicsChat can ONLY answer questions that use one of these capabilities:
- Protein/gene interaction neighborhood from FunMap (functional co-expression network)
- Cancer gene expression levels (tumor vs normal) across TCGA cancer types
- Overall survival associations for a gene across cancer types
- Clinical trial information and drug targets for a gene
- Cis-correlations (DNA methylation ↔ mRNA co-expression) for a gene in a cancer type
- Pathway enrichment analysis (WebGestalt) on a list of genes
- Literature search for a gene or topic

Every suggestion MUST be answerable by one of the capabilities above.
Do NOT suggest questions about: general UniProt/Ensembl lookups, protein structure, sequence alignment, GWAS, variant annotation, drug mechanism of action, or anything else outside this list.
"""
            resp = await LLMFactory.invoke_async(
                self.llm,
                [
                    SystemMessage(content="You are LinkedOmicsChat, a specialized cancer multi-omics assistant. Generate concise follow-up questions that are answerable using LinkedOmics data (expression, survival, drug targets, pathway enrichment, FunMap interactions)."),
                    HumanMessage(content=prompt),
                ],
            )
            text = (resp or "").strip()
            # Parse numbered lines
            suggestions: List[str] = []
            for line in text.splitlines():
                line = line.strip()
                # Remove leading number + dot/paren
                import re as _re
                line = _re.sub(r"^\d+[\.\)]\s*", "", line).strip()
                if line and len(line) > 10:
                    suggestions.append(line)
            return suggestions[:n]
        except Exception as e:
            logger.warning(f"Suggestion generation failed: {e}")
            return []

    def _tool_catalog_for_prompt(self, available_tools: Dict[str, Dict[str, Any]]) -> str:
        """Build a compact tool catalog string for LLM prompting."""
        lines: List[str] = []
        for tool_id, meta in sorted(available_tools.items(), key=lambda kv: kv[0]):
            desc = (meta.get("description") or "").strip().replace("\n", " ")
            schema = meta.get("inputSchema") or {}
            props = schema.get("properties") or {}
            required = schema.get("required") or []

            # Compact signature: tool_id(args...)
            if props:
                parts: List[str] = []
                for k, v in props.items():
                    t = v.get("type")
                    enum = v.get("enum")
                    if enum and isinstance(enum, list) and len(enum) <= 8:
                        parts.append(f"{k}: enum{enum}")
                    elif t:
                        parts.append(f"{k}: {t}")
                    else:
                        parts.append(f"{k}")
                sig = ", ".join(parts)
            else:
                sig = ""

            req = f" required={required}" if required else ""
            lines.append(f"- {tool_id}({sig}){req} — {desc}".strip())

        return "\n".join(lines)

    def _extract_json_obj(self, text: Any) -> Optional[Any]:
        """Extract and parse first JSON object/array from a string."""
        if not text or not isinstance(text, str):
            return None
        import json

        s = text.strip()
        # Remove common markdown fences
        if s.startswith("```"):
            s = s.strip("`")
            # Sometimes includes a leading 'json'
            s = s.replace("json", "", 1).strip()

        # Fast path
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return json.loads(s)
            except Exception:
                pass

        # Heuristic: find first {...} or [...] span
        start = None
        open_ch = None
        for i, ch in enumerate(s):
            if ch in "{[":
                start = i
                open_ch = ch
                break
        if start is None:
            return None
        close_ch = "}" if open_ch == "{" else "]"
        end = s.rfind(close_ch)
        if end <= start:
            return None
        chunk = s[start : end + 1]
        try:
            return json.loads(chunk)
        except Exception:
            return None

    def _validate_tool_calls(
        self,
        parsed: Any,
        available_tools: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Validate LLM output schema and tool arguments."""
        if not isinstance(parsed, dict) or "calls" not in parsed:
            # logger.warning(f"LLM output is not a dict or missing 'calls' key: {parsed}")
            return []
            
        calls = []
        for call in parsed["calls"]:
            if not isinstance(call, dict):
                continue
                
            # Flexible field names
            tool_name = (
                call.get("tool") or 
                call.get("tool_name") or 
                call.get("tool_id")
            )
            args = (
                call.get("arguments") or 
                call.get("args") or 
                call.get("parameters") or 
                call.get("tool_input") or 
                {}
            )
            
            if not tool_name or tool_name not in available_tools:
                # logger.warning(f"LLM suggested unknown tool: {tool_name}")
                continue
                
            calls.append({"tool": tool_name, "arguments": args})
            
        return calls

    def _format_recent_history(self, session: Dict[str, Any], limit: int = 20) -> str:
        """Format recent conversation history for LLM context."""
        if not session or not session.get("history"):
            return ""
        
        history_text = []
        # Get last N messages
        recent = session["history"][-limit:]
        logger.info(f"Formatting history from {len(session['history'])} total messages. Using last {len(recent)}.")
        
        for item in recent:
            query = item.get("query", "")
            # Try to get summary first, then message, then empty
            resp = item.get("response", {})
            content = ""
            if isinstance(resp, dict):
                content = resp.get("summary") or resp.get("message") or ""
            elif isinstance(resp, str):
                content = resp
            
            # Truncate very long responses to save context window
            if len(content) > 800:
                content = content[:800] + "... (truncated)"
            
            if query:
                history_text.append(f"User: {query}")
            if content:
                history_text.append(f"Assistant: {content}")
                
        return "\n".join(history_text)

    def _resolve_pronouns_in_place(self, *args, **kwargs):
        """DEPRECATED: Pronoun resolution is now handled natively by the LLM with context injection."""
        pass

    async def _llm_plan_tools(
        self,
        query: str,
        available_tools: Dict[str, Dict[str, Any]],
        history_str: str,
        session: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Use LLM to produce a tool-call plan with arguments, validated by schema."""
        if not self.llm or not available_tools:
            return []

        from langchain_core.messages import SystemMessage, HumanMessage

        catalog = self._tool_catalog_for_prompt(available_tools)
        system = SystemMessage(
            content=(
                "You are a Senior Multi-Omics Bioinformatics Analyst. Your goal is to determine if tool calls are needed to answer a user's question.\n"
                f"{self.BIO_GUIDELINES}\n"
                "Rules:\n"
                "- Only use tools from the provided catalog.\n"
                "- Output must be valid JSON. No markdown, no explanations.\n"
                "- Output shape: {\"reasoning\": \"...\", \"calls\": [{\"tool\": \"tool_name\", \"arguments\": {\"arg\": \"val\"}}]}.\n"
                "- IMPORTANT: If the user is just saying hello, asking who you are, or asking a general question that doesn't require genomic data, output an EMPTY calls list: {\"reasoning\": \"...\", \"calls\": []}.\n"
                "- Do NOT force a tool call if the question is conversational.\n"
                f"- CONTEXT: The currently active gene of interest is '{session.get('context', {}).get('active_gene') or 'unknown'}'. Resolve 'it' or 'this' to this gene unless the user specifies otherwise.\n"
                "- If research data IS needed, use at most 3 calls.\n"
                "- PROMPT INSTRUCTION: Explain your reasoning first, including pronoun resolution from History.\n"
            )
        )

        human = HumanMessage(
            content=(
                f"Conversation History:\n{history_str}\n\n"
                f"Current User query:\n{query}\n\n"
                f"Tool catalog:\n{catalog}\n\n"
                "Return the JSON tool call plan now."
            )
        )
        
        logger.info(f"Planning tools. History len: {len(history_str)}. Query: {query}")
        if len(history_str) > 0:
            logger.info(f"History context preview: {history_str[:200]}...")

        # Attempt 1
        raw = await LLMFactory.invoke_async(self.llm, [system, human])
        # Log raw string content
        logger.info(f"Raw LLM Tool Plan: {raw}")
        parsed = self._extract_json_obj(raw)
        
        # CoT: Log the functioning to verify reasoning
        if isinstance(parsed, dict) and "reasoning" in parsed:
            logger.info(f"LLM Reasoning: {parsed['reasoning']}")

        calls = self._validate_tool_calls(parsed, available_tools)
        if calls:
            return calls

        # Attempt 2: provide a correction prompt with common failure modes
        human2 = HumanMessage(
            content=(
                f"Your previous output was invalid or missing required arguments.\n"
                f"Conversation History:\n{history_str}\n\n"
                f"User query:\n{query}\n\n"
                f"Tool catalog:\n{catalog}\n\n"
                "Return ONLY valid JSON in the required shape with correct tool ids and required arguments."
            )
        )
        raw2 = await LLMFactory.invoke_async(self.llm, [system, human2])
        logger.info(f"Raw LLM Tool Plan (Attempt 2): {raw2}")
        parsed2 = self._extract_json_obj(raw2)
        return self._validate_tool_calls(parsed2, available_tools)

    async def _determine_tools(self, query: str, intent: str, session: Dict[str, Any] = None) -> list:
        """Determine which MCP tools to call based on query.

        Tool selection is fully delegated to the LLM via _llm_plan_tools, which
        receives the live tool catalog from mcp_aggregator.list_tools(). This means
        any new tool added to the MCP server is automatically available — no changes
        needed here.
        """
        available_tools = self.mcp_aggregator.list_tools()

        if self.llm and available_tools:
            try:
                history_str = self._format_recent_history(session) if session else ""
                if session:
                    logger.info(f"Formatted history length: {len(history_str)}")
                else:
                    logger.warning("No session provided to _determine_tools")

                planned = await self._llm_plan_tools(query, available_tools, history_str, session)
                logger.info(f"LLM planned tools: {planned}")
                return planned  # trust LLM; empty list means no tools needed
            except Exception as e:
                logger.error(f"LLM tool planning failed: {e}", exc_info=True)
                return []

        # No LLM available — cannot determine tools
        logger.warning("No LLM available for tool planning; returning empty tool list.")
        return []
    
    async def _generate_response(
        self,
        query: str,
        results: Dict[str, Any],
        session: Dict[str, Any],
        intent: str = "general"
    ) -> Dict[str, Any]:
        """Generate final response from tool results"""
        if not results:
            # Use LLM to generate a natural response for conversational queries
            try:
                from langchain_core.messages import HumanMessage, SystemMessage
                history_str = self._format_recent_history(session)
                
                # Only extract gene symbols if the intent was actually a gene query
                # This prevents false positives like "ME" in "tell me a joke"
                gene_symbols = []
                if intent == "gene_query":
                    gene_symbols = self._extract_gene_symbols(query)
                
                if gene_symbols:
                    if len(gene_symbols) == 1:
                        gene_symbol = gene_symbols[0]
                        prompt = f"""Conversation History:
{history_str}

The user asks: "{query}"

This appears to be a question about the gene {gene_symbol}. Please provide a comprehensive answer about this gene using your general knowledge of molecular biology and genomics. Include:
- What the gene is and what it does
- Its biological function
- Its relevance in disease (if applicable)
- Any other important information

Be specific, accurate, and informative."""
                    else:
                        # Multi-gene comparison
                        genes_str = ", ".join(gene_symbols)
                        prompt = f"""Conversation History:
{history_str}

The user asks: "{query}"

This appears to be a request involving multiple genes: {genes_str}.
Please provide a comprehensive response that addresses these genes.
- If the user is asking to prioritize or compare them, analyze their relative importance, functions, or disease relevance.
- If the user is asking for information on all of them, provide a summary for each and any known connections between them.

Use your expert knowledge of molecular biology and genomics."""
                else:
                    prompt = f"""Conversation History:
{history_str}

The user says: "{query}"

Please provide a helpful, natural, and professional response. If they are just greeting you, greet them back as a Senior Multi-Omics Bioinformatics Analyst. If they are asking for help or about your capabilities, explain them clearly."""
                
                response = await LLMFactory.invoke_async(
                    self.llm,
                    [
                        SystemMessage(
                            content=(
                                "You are a Senior Multi-Omics Bioinformatics Analyst. You are helpful, professional, and precise. "
                                "CRITICAL RULE: Do not explicitly state your title (e.g., Avoid 'As a Senior Analyst...'). Just provide the response."
                            )
                        ),
                        HumanMessage(content=prompt)
                    ]
                )
                
                return {
                    "success": True,
                    "summary": "", # No summary needed for basic chat
                    "message": response,
                    "query": query,
                    "tools_used": [],
                    "raw_results": {}
                }
            except Exception as e:
                logger.error(f"Error generating conversational response: {e}", exc_info=True)
                return {
                    "success": True,
                    "message": f"I'm here to help, but I encountered an error: {str(e)}. How can I assist you today?",
                    "query": query
                }
        
        # Literature tools: the LangGraph agent already produced a formatted summary
        # in llm_summary; just return that rather than re-formatting raw JSON.
        if any(tool_id.startswith("literature::") for tool_id in results.keys()):
            # Pull the LLM's own summary out of the results wrapper if present,
            # otherwise fall back gracefully.
            return {
                "success": True,
                "summary": "",
                "message": None,   # sentinel → caller uses llm_summary instead
                "query": query,
                "tools_used": list(results.keys()),
                "raw_results": results,
            }

        # If LinkedOmics tools were used, format them nicely as markdown
        if any(tool_id.startswith("linkedomics::") for tool_id in results.keys()):
            try:
                message = self._format_linkedomics_results(results, query)
                summary = await self._llm_summarize_tool_results(query, results)
                return {
                    "success": True,
                    "summary": summary or "",
                    "message": message,
                    "query": query,
                    "tools_used": list(results.keys()),
                    "raw_results": results,
                }
            except Exception as e:
                logger.error(f"Error formatting LinkedOmics results: {e}", exc_info=True)

        # Format results for display - extract actual gene data
        gene_info = None
        for tool_id, result in results.items():
            if isinstance(result, str):
                # Try to parse JSON if it's a string
                try:
                    import json
                    parsed = json.loads(result)
                    if isinstance(parsed, dict) and "gene" in parsed:
                        gene_info = parsed
                        break
                except:
                    pass
        
        # Use LLM to generate natural language response with actual data
        if self.llm and gene_info:
            try:
                from langchain_core.messages import HumanMessage, SystemMessage
                
                # Build a clear prompt with the actual gene data
                gene_details = f"""
Gene: {gene_info.get('gene', 'Unknown')}
Description: {gene_info.get('description', 'N/A')}
Chromosome: {gene_info.get('chromosome', 'N/A')}
Function: {gene_info.get('function', 'N/A')}
"""
                
                # Format history for context
                history_str = self._format_recent_history(session)

                prompt = f"""Conversation History:
{history_str}

The user asked: "{query}"

Here is the information I found:
{gene_details}

Please provide a clear, informative response about this gene. Include the key details: what the gene is, what chromosome it's on, and its main function. Write in a natural, conversational way. Refer to previous context if relevant."""
                
                response = await LLMFactory.invoke_async(
                    self.llm,
                    [
                        SystemMessage(
                            content=(
                                "You are a Senior Multi-Omics Bioinformatics Analyst. When providing information about genes, "
                                "always include specific details from the data. Be clear, analytical, and professional.\n"
                                "CRITICAL RULE: Do not explicitly state your title or identity (e.g., Avoid 'As a Senior Analyst...'). Just provide the analysis.\n"
                                f"{self.BIO_GUIDELINES}"
                            )
                        ),
                        HumanMessage(content=prompt)
                    ]
                )
                
                # Ensure the response actually contains the information
                if response and len(response.strip()) > 20:
                    summary = await self._llm_summarize_tool_results(query, results)
                    return {
                        "success": True,
                        "summary": summary or "",
                        "message": response,
                        "query": query,
                        "tools_used": list(results.keys()),
                        "raw_results": results
                    }
                else:
                    # If response is too short or empty, it might be an error or a 429 fallback
                    if not any(tool_id.startswith("linkedomics::") for tool_id in results.keys()):
                         return {
                            "success": True,
                            "summary": "",
                            "message": response or "I'm here to help with your multi-omics research. What would you like to explore?",
                            "query": query,
                            "tools_used": [],
                            "raw_results": {}
                        }
            except Exception as e:
                logger.error(f"Error generating LLM response: {e}")
        
        # Fallback: format the gene info directly if LLM failed or no LLM
        if gene_info:
            message = f"""**{gene_info.get('gene', 'Gene')} Information:**

**Description:** {gene_info.get('description', 'N/A')}
**Chromosome:** {gene_info.get('chromosome', 'N/A')}
**Function:** {gene_info.get('function', 'N/A')}"""
        else:
            # Format raw results
            formatted_results = []
            for tool_id, result in results.items():
                if isinstance(result, str):
                    try:
                        import json
                        parsed = json.loads(result)
                        formatted_results.append(f"**{tool_id}**:\n{json.dumps(parsed, indent=2)}")
                    except:
                        formatted_results.append(f"**{tool_id}**:\n{result}")
                else:
                    formatted_results.append(f"**{tool_id}**:\n{result}")
            message = f"I found the following information:\n\n" + "\n\n".join(formatted_results)
        summary = await self._llm_summarize_tool_results(query, results)
        return {
            "success": True,
            "summary": summary or "",
            "message": message,
            "query": query,
            "tools_used": list(results.keys()),
            "raw_results": results
        }

    def _format_linkedomics_results(self, results: Dict[str, Any], query: str = "") -> str:
        """Format LinkedOmics MCP tool outputs into nice markdown for chat UI."""
        import json

        def _maybe_json(v: Any) -> Any:
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except Exception:
                    return v
            return v

        def _as_data_url(img_part: Dict[str, Any]) -> Optional[str]:
            data = img_part.get("data")
            mime = img_part.get("mimeType") or "image/png"
            if not data:
                return None
            # `data` from MCP ImageContent is already base64 in practice
            return f"data:{mime};base64,{data}"

        sections: List[str] = []

        for unique_key, wrapped_result in results.items():
            # Strip the #N suffix to get the actual tool_id
            tool_id = unique_key.split('#')[0] if '#' in unique_key else unique_key
            
            # Extract gene name and actual result from wrapper
            gene_name = ""
            if isinstance(wrapped_result, dict) and "_result" in wrapped_result:
                gene_name = wrapped_result.get("_gene", "")
                raw = wrapped_result["_result"]
            else:
                # Fallback for non-wrapped results (backward compatibility)
                raw = wrapped_result
                
            parsed = _maybe_json(raw)

            # Structured payload from MCPAggregator (images etc.)
            if isinstance(parsed, dict) and "mcp" in parsed and "parts" in parsed:
                parts = parsed.get("parts") or []
                text = (parsed.get("text") or "").strip()
                if tool_id.endswith("get_survival_plot"):
                    # Prefer image rendering
                    img_url = None
                    for p in parts:
                        if isinstance(p, dict) and p.get("type") == "image":
                            img_url = _as_data_url(p)
                            break
                    survival_title = f"Survival plot - {gene_name}" if gene_name else "Survival plot"
                    if img_url:
                        sections.append(f"## {survival_title}\n\n![Survival plot]({img_url})\n")
                    elif text:
                        sections.append(f"## {survival_title}\n\n{text}\n")
                    else:
                        sections.append(f"## {survival_title}\n\n(Plot unavailable)\n")
                else:
                    # Generic structured output: show text + any unknown parts
                    md = [f"## {tool_id.split('::',1)[1].replace('_',' ').title()}"]
                    if text:
                        md.append(text)
                    unknowns = [p for p in parts if isinstance(p, dict) and p.get("type") == "unknown"]
                    if unknowns:
                        md.append("\n\n```text\n" + "\n".join(u.get("repr","") for u in unknowns) + "\n```\n")
                    sections.append("\n\n".join(md) + "\n")
                continue

            # Tool-specific formatting for dict outputs
            if tool_id.endswith("funmap_neighborhood"):
                neigh = []
                if isinstance(parsed, dict):
                    neigh = parsed.get("neighborhood") or []
                
                funmap_title = f"FunMap neighborhood - {gene_name}" if gene_name else "FunMap neighborhood"
                md = [
                    f"## {funmap_title}",
                    f"**Nodes found:** {len(neigh)}",
                ]
                
                if neigh:
                    md.append("")  # For newline spacing
                    chunks = [neigh[i:i + 5] for i in range(0, len(neigh), 5)]
                    for chunk in chunks:
                        md.append("- " + ", ".join(f"{g}" for g in chunk))
                else:
                    md.append("\n_No neighborhood found._")
                
                sections.append("\n".join(md) + "\n")
                continue

            if tool_id.endswith("cancer_gene_expression") or tool_id.endswith("overall_survival_per_cancer"):
                # parsed: {"protein_level": {"status":..., "data": {...}}, "RNA_level": {...}}
                if not isinstance(parsed, dict):
                    sections.append(f"## {tool_id}\n\n```json\n{json.dumps(parsed, indent=2)}\n```\n")
                    continue
                
                prot = (parsed.get("protein_level") or {})
                rna = (parsed.get("RNA_level") or {})
                prot_data = prot.get("data") or {}
                rna_data = rna.get("data") or {}
                cancers = sorted(set(list(prot_data.keys()) + list(rna_data.keys())))
                
                base_title = "Cancer expression (Tumor vs Normal)" if tool_id.endswith("cancer_gene_expression") else "Overall survival associations"
                # Use gene_name from metadata wrapper
                title = f"{base_title} - {gene_name}" if gene_name else base_title

                lines = [f"## {title}", "", "| Cancer | RNA | Protein |", "|---|---|---|"]
                for c in cancers:
                    lines.append(f"| {c} | {rna_data.get(c,'-')} | {prot_data.get(c,'-')} |")
                sections.append("\n".join(lines) + "\n")
                continue

            if tool_id.endswith("clinical_trial_information"):
                if not isinstance(parsed, dict):
                    continue  # skip unrenderable result silently
                status = parsed.get("status", "unavailable")
                data = parsed.get("data") or {}
                trial_title = f"Clinical trial associations - {gene_name}" if gene_name else "Clinical trial associations"
                md = [f"## {trial_title}", f"**Status:** {status}"]
                for k, v in data.items():
                    md.append(f"\n### {k}")
                    if isinstance(v, list) and v:
                        for item in v[:10]:
                            if isinstance(item, dict):
                                md.append(f"- **{item.get('study','')}** — {item.get('treatment','')}")
                            else:
                                md.append(f"- {item}")
                    else:
                        md.append("_No results._")
                sections.append("\n".join(md) + "\n")
                continue

            if tool_id.endswith("get_cis_correlations"):
                if not isinstance(parsed, dict) or "data" not in parsed:
                    continue  # skip unrenderable result silently
                
                data = parsed.get("data", {})
                cis_title = f"Cis-Correlations - {gene_name}" if gene_name else "Cis-Correlations"
                md = [f"## {cis_title}"]
                
                if not data:
                    md.append("_No correlation data found._")
                else:
                     for cohort, records in data.items():
                         if not records: 
                             continue
                         md.append(f"\n### {cohort}")
                         # Assuming records is a list of dicts, take keys from first record
                         if isinstance(records, list) and len(records) > 0:
                             keys = list(records[0].keys())
                             header = "| " + " | ".join(keys) + " |"
                             separator = "| " + " | ".join(["---"] * len(keys)) + " |"
                             md.append(header)
                             md.append(separator)
                             for rec in records[:10]: # Limit to top 10 per cohort
                                 row = "| " + " | ".join(str(rec.get(k, "")) for k in keys) + " |"
                                 md.append(row)
                             if len(records) > 10:
                                 md.append(f"_(showing 10 of {len(records)} records)_")
                         else:
                             md.append("_No records._")

                sections.append("\n".join(md) + "\n")
                continue

            if tool_id.endswith("webgestalt"):
                rows = []
                if isinstance(parsed, dict):
                    rows = parsed.get("data") or []
                if not isinstance(rows, list):
                    rows = []
                enrich_title = f"Pathway / GO enrichment - {gene_name}" if gene_name else "Pathway / GO enrichment"
                md = [
                    f"## {enrich_title}",
                    "",
                    "| GO Term | Description | Enrichment Ratio | FDR |",
                    "|---|---|---|---|",
                ]
                for row in rows:
                    gs = row.get("geneSet", "")
                    desc = row.get("description", "")
                    er = row.get("enrichmentRatio", "")
                    fdr = row.get("FDR", "")
                    try:
                        er = f"{float(er):.2f}"
                    except Exception:
                        pass
                    try:
                        fdr = f"{float(fdr):.2e}"
                    except Exception:
                        pass
                    md.append(f"| {gs} | {desc} | {er} | {fdr} |")
                if not rows:
                    md.append("| — | No enriched terms found | — | — |")
                sections.append("\n".join(md) + "\n")
                continue

            # Fallback: tool has no specific renderer — skip raw output.
            # The LLM's analytical summary in the 'summary' field covers this.
            logger.debug(f"[format] No specific renderer for {tool_id}, skipping raw output.")

        # Add placeholder sections for genes that were requested but have no data.
        # Skip entirely if any tool returned an error (e.g. invalid gene resolution) —
        # in that case the LLM summary already explains what went wrong.
        any_errors = any(
            isinstance(v, dict) and isinstance(v.get("_result"), dict) and "error" in v["_result"]
            for v in results.values()
        )
        if query and not any_errors:
            requested_genes = self._extract_gene_symbols(query)
            if requested_genes:
                # Extract genes that already have data in the results
                genes_with_data = set()
                for unique_key, wrapped_result in results.items():
                    if isinstance(wrapped_result, dict) and "_gene" in wrapped_result:
                        genes_with_data.add(wrapped_result["_gene"])

                # Find genes without data
                genes_without_data = [g for g in requested_genes if g not in genes_with_data]

                # Add placeholder sections for genes without data
                for gene in genes_without_data:
                    # Determine which type of analysis was requested based on tool_ids
                    tool_types = [key.split('#')[0] for key in results.keys()]
                    
                    if any("cancer_gene_expression" in t for t in tool_types):
                        sections.append(f"## Cancer expression (Tumor vs Normal) - {gene}\n\nData unavailable\n")
                    elif any("overall_survival" in t for t in tool_types):
                        sections.append(f"## Overall survival associations - {gene}\n\nData unavailable\n")
                    elif any("get_survival_plot" in t for t in tool_types):
                        sections.append(f"## Survival plot - {gene}\n\nData unavailable\n")
                    else:
                        # Generic placeholder
                        sections.append(f"## Analysis - {gene}\n\nData unavailable\n")

        return "\n\n".join(sections).strip() or "No LinkedOmics results."
    
    async def _generate_session_title(self, first_query: str) -> str:
        """Generate a short title for the chat session based on first query"""
        if settings.MOCK_LLM:
            return first_query[:50] + ("..." if len(first_query) > 50 else "")
        
        try:
            prompt = f"""Generate a short, descriptive title (max 6 words) for a chat conversation that starts with this question:

"{first_query}"

Respond with ONLY the title, nothing else. Make it specific and informative."""
            
            from langchain_core.messages import HumanMessage
            response = await LLMFactory.invoke_async(self.llm, [HumanMessage(content=prompt)])
            title = response.strip().strip('"').strip("'")
            
            # Limit length
            if len(title) > 60:
                title = title[:57] + "..."
            
            return title
        except Exception as e:
            logger.error(f"Error generating title: {e}")
            return first_query[:50] + ("..." if len(first_query) > 50 else "")
    
    async def _update_session(
        self,
        session: Dict[str, Any],
        query: str,
        response: Dict[str, Any]
    ):
        """Update session with query and response. Guest sessions skip DB persistence."""
        import asyncio

        # Guest sessions: update in-memory + record token usage to DB
        if session.get("user_id") == "guest":
            session.setdefault("history", []).append({
                "query": query,
                "response": response,
                "timestamp": time.time(),
            })
            session["last_updated"] = time.time()

            in_tok = response.get("_input_tokens", 0) or 0
            out_tok = response.get("_output_tokens", 0) or 0
            if (in_tok or out_tok) and session.get("client_ip"):
                db = SessionLocal()
                try:
                    db.add(GuestTokenUsage(
                        ip_address=session["client_ip"],
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        model=settings.DEFAULT_LLM_MODEL,
                        timestamp=time.time(),
                    ))
                    db.commit()
                finally:
                    db.close()
            return

        if settings.DATABASE_URL.startswith("sqlite"):
            db = SessionLocal()
            session_id = session["id"]
            try:
                db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if db_session:
                    db_session.last_updated = time.time()
                    db_session.context = session.get("context", {})
                    
                    # Check if this is the first message (for title generation)
                    message_count = db.query(DBChatMessage).filter(
                        DBChatMessage.session_id == session_id
                    ).count()
                    is_first_message = message_count == 0
                    
                    # Add message (ChatMessage uses query/response format)
                    message = DBChatMessage(
                        session_id=session_id,
                        query=query,
                        response=response,
                        timestamp=time.time()
                    )
                    db.add(message)

                    # Record token usage if present (set by LangGraphOrchestrator)
                    in_tok = response.get("_input_tokens", 0) or 0
                    out_tok = response.get("_output_tokens", 0) or 0
                    if in_tok or out_tok:
                        if session.get("user_id") not in (None, "guest"):
                            db.add(TokenUsage(
                                user_id=session["user_id"],
                                session_id=session_id,
                                input_tokens=in_tok,
                                output_tokens=out_tok,
                                model=settings.DEFAULT_LLM_MODEL,
                                timestamp=time.time(),
                            ))
                        elif session.get("client_ip"):
                            db.add(GuestTokenUsage(
                                ip_address=session["client_ip"],
                                input_tokens=in_tok,
                                output_tokens=out_tok,
                                model=settings.DEFAULT_LLM_MODEL,
                                timestamp=time.time(),
                            ))

                    db.commit()
                    
                    # Update in-memory session if it exists
                    if session_id in self.sessions:
                        self.sessions[session_id]["last_updated"] = db_session.last_updated
                        if "history" not in self.sessions[session_id]:
                            self.sessions[session_id]["history"] = []
                        self.sessions[session_id]["history"].append({
                            "query": query,
                            "response": response,
                            "timestamp": message.timestamp
                        })
                        
                    # Generate title after first message
                    if is_first_message and db_session.title == "New Chat":
                        asyncio.create_task(self._update_session_title(session_id, query))
            finally:
                db.close()
        else:
            # PostgreSQL async
            async with SessionLocal() as db:
                session_id = session["id"]
                result = await db.execute(
                    select(ChatSession).filter(ChatSession.id == session_id)
                )
                db_session = result.scalar_one_or_none()
                if db_session:
                    db_session.last_updated = time.time()
                    db_session.context = session.get("context", {})
                    
                    # Check if this is the first message
                    msg_count_result = await db.execute(
                        select(DBChatMessage).filter(DBChatMessage.session_id == session_id)
                    )
                    message_count = len(msg_count_result.scalars().all())
                    is_first_message = message_count == 0
                    
                    # Add message (ChatMessage uses query/response, not role/content)
                    message = DBChatMessage(
                        session_id=session_id,
                        query=query,
                        response=response,
                        timestamp=time.time()
                    )
                    db.add(message)

                    # Record token usage if present (set by LangGraphOrchestrator)
                    in_tok = response.get("_input_tokens", 0) or 0
                    out_tok = response.get("_output_tokens", 0) or 0
                    if in_tok or out_tok:
                        if session.get("user_id") not in (None, "guest"):
                            db.add(TokenUsage(
                                user_id=session["user_id"],
                                session_id=session_id,
                                input_tokens=in_tok,
                                output_tokens=out_tok,
                                model=settings.DEFAULT_LLM_MODEL,
                                timestamp=time.time(),
                            ))
                        elif session.get("client_ip"):
                            db.add(GuestTokenUsage(
                                ip_address=session["client_ip"],
                                input_tokens=in_tok,
                                output_tokens=out_tok,
                                model=settings.DEFAULT_LLM_MODEL,
                                timestamp=time.time(),
                            ))

                    await db.commit()
                    
                    # Update in-memory session if it exists
                    if session_id in self.sessions:
                        self.sessions[session_id]["last_updated"] = db_session.last_updated
                        if "history" not in self.sessions[session_id]:
                            self.sessions[session_id]["history"] = []
                        self.sessions[session_id]["history"].append({
                            "query": query,
                            "response": response,
                            "timestamp": message.timestamp
                        })
                        
                    # Generate title after first message
                    if is_first_message and db_session.title == "New Chat":
                        asyncio.create_task(self._update_session_title(session_id, query))
    
    async def _update_session_title(self, session_id: str, first_query: str):
        """Async task to generate and update session title"""
        try:
            logger.info(f"Generating title for session {session_id} from query: {first_query[:50]}")
            title = await self._generate_session_title(first_query)
            
            # Update in memory cache if exists
            if session_id in self.sessions:
                self.sessions[session_id]["title"] = title
            
            # Update in database
            if settings.DATABASE_URL.startswith("sqlite"):
                db = SessionLocal()
                try:
                    db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if db_session:
                        db_session.title = title
                        db.commit()
                        logger.info(f"✅ Generated title for session {session_id}: {title}")
                finally:
                    db.close()
            else:
                # PostgreSQL async
                async with SessionLocal() as db:
                    result = await db.execute(
                        select(ChatSession).filter(ChatSession.id == session_id)
                    )
                    db_session = result.scalar_one_or_none()
                    if db_session:
                        db_session.title = title
                        await db.commit()
                        logger.info(f"✅ Generated title for session {session_id}: {title}")
        except Exception as e:
            logger.error(f"Error updating session title: {e}", exc_info=True)
            # Fallback to truncated query
            fallback_title = first_query[:50] + ("..." if len(first_query) > 50 else "")
            if settings.DATABASE_URL.startswith("sqlite"):
                db = SessionLocal()
                try:
                    db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if db_session:
                        db_session.title = fallback_title
                        db.commit()
                finally:
                    db.close()
            else:
                async with SessionLocal() as db:
                    result = await db.execute(
                        select(ChatSession).filter(ChatSession.id == session_id)
                    )
                    db_session = result.scalar_one_or_none()
                    if db_session:
                        db_session.title = fallback_title
                        await db.commit()
    
    async def _load_all_sessions_from_db(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Load all sessions from database, optionally filtered by user_id"""
        from typing import List
        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                # SQLite uses sync session
                db = SessionLocal()
                try:
                    query = db.query(ChatSession)
                    if user_id:
                        query = query.filter(ChatSession.user_id == user_id)
                    db_sessions = query.all()
                    sessions_list = []
                    
                    for db_session in db_sessions:
                        message_count = db.query(DBChatMessage).filter(
                            DBChatMessage.session_id == db_session.id
                        ).count()
                        
                        sessions_list.append({
                            "id": db_session.id,
                            "user_id": db_session.user_id,
                            "title": db_session.title,
                            "created_at": db_session.created_at,
                            "last_updated": db_session.last_updated,
                            "message_count": message_count
                        })
                    
                    return sessions_list
                finally:
                    db.close()
            else:
                # PostgreSQL uses async session
                async with SessionLocal() as db:
                    query = select(ChatSession)
                    if user_id:
                        query = query.filter(ChatSession.user_id == user_id)
                    result = await db.execute(query)
                    db_sessions = result.scalars().all()
                    
                    sessions_list = []
                    for db_session in db_sessions:
                        # Count messages
                        msg_result = await db.execute(
                            select(DBChatMessage).filter(DBChatMessage.session_id == db_session.id)
                        )
                        message_count = len(msg_result.scalars().all())
                        
                        sessions_list.append({
                            "id": db_session.id,
                            "user_id": db_session.user_id,
                            "title": db_session.title,
                            "created_at": db_session.created_at,
                            "last_updated": db_session.last_updated,
                            "message_count": message_count
                        })
                    
                    return sessions_list
        except Exception as e:
            logger.error(f"Error loading sessions from database: {e}")
            return []
    
    async def _load_session_from_db(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load a session from database"""
        def _sanitize_large_inline_images(resp: Any) -> Any:
            """
            Prevent huge stored responses (data URLs / raw_results base64) from freezing the UI.

            If a response contains a markdown image with a very large data:image/... URL,
            replace it with a short placeholder so the frontend stays responsive.
            """
            try:
                if not isinstance(resp, dict):
                    return resp

                msg = resp.get("message")
                if not isinstance(msg, str):
                    msg = ""

                import re
                import json

                new_resp = dict(resp)

                # Always drop heavy fields that the chat UI doesn't need for history rendering.
                # Keeping these can make some sessions too large to load smoothly.
                new_resp.pop("raw_results", None)
                new_resp.pop("visualizations", None)

                # 1) Only sanitize inline data URLs if they're large.
                # Small inline plots (tens of KB) should render fine and are useful in chat history.
                if "data:image" in msg and len(msg) > 200_000:
                    msg_sanitized = re.sub(
                        r"!\[[^\]]*\]\(data:image/[^)]+\)",
                        "_(Plot omitted for performance — please re-run the plot query to regenerate it.)_",
                        msg,
                        flags=re.IGNORECASE,
                    )
                    new_resp["message"] = msg_sanitized
                    if "summary" in new_resp and isinstance(new_resp.get("summary"), str):
                        new_resp["summary"] = msg_sanitized

                # 2) If the overall stored response is still huge, drop heavy fields (raw_results, etc.)
                try:
                    approx_size = len(json.dumps(new_resp, default=str))
                except Exception:
                    approx_size = 0

                if approx_size > 200_000:
                    # Keep only what the UI needs to render history.
                    keep_keys = {"success", "summary", "message", "query", "tools_used"}
                    compact = {k: new_resp.get(k) for k in keep_keys if k in new_resp}
                    # Preserve minimal structure expected elsewhere
                    compact.setdefault("success", True)
                    # Prefer already-sanitized message if present
                    compact.setdefault("message", new_resp.get("message", msg) or "")
                    compact.setdefault("summary", new_resp.get("summary", compact.get("message", "")))
                    compact["__note__"] = "Large fields omitted from history for performance."
                    return compact

                return new_resp
            except Exception:
                return resp

        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                # SQLite uses sync session
                db = SessionLocal()
                try:
                    db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if not db_session:
                        return None
                    
                    # Load messages
                    messages = db.query(DBChatMessage).filter(
                        DBChatMessage.session_id == session_id
                    ).order_by(DBChatMessage.timestamp).all()
                    
                    history = [
                        {
                            "query": msg.query,
                            "response": _sanitize_large_inline_images(msg.response),
                            "timestamp": msg.timestamp
                        }
                        for msg in messages
                    ]
                    
                    session = {
                        "id": db_session.id,
                        "user_id": db_session.user_id,
                        "title": db_session.title,
                        "history": history,
                        "context": db_session.context or {},
                        "created_at": db_session.created_at,
                        "last_updated": db_session.last_updated
                    }
                    
                    return session
                finally:
                    db.close()
            else:
                # PostgreSQL uses async session
                async with SessionLocal() as db:
                    result = await db.execute(
                        select(ChatSession).filter(ChatSession.id == session_id)
                    )
                    db_session = result.scalar_one_or_none()
                    if not db_session:
                        return None
                    
                    # Load messages
                    messages_result = await db.execute(
                        select(DBChatMessage)
                        .filter(DBChatMessage.session_id == session_id)
                        .order_by(DBChatMessage.timestamp)
                    )
                    messages = messages_result.scalars().all()
                    
                    history = [
                        {
                            "query": msg.query,
                            "response": _sanitize_large_inline_images(msg.response),
                            "timestamp": msg.timestamp
                        }
                        for msg in messages
                    ]
                    
                    session = {
                        "id": db_session.id,
                        "user_id": db_session.user_id,
                        "title": db_session.title,
                        "history": history,
                        "context": db_session.context or {},
                        "created_at": db_session.created_at,
                        "last_updated": db_session.last_updated
                    }
                    
                    return session
        except Exception as e:
            logger.error(f"Error loading session from database: {e}")
            return None
    
    def _save_session_to_db(self, session: Dict[str, Any]):
        """Save session to database (sync for SQLite compatibility)"""
        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                db = SessionLocal()
                try:
                    db_session = db.query(ChatSession).filter(ChatSession.id == session["id"]).first()
                    if db_session:
                        db_session.title = session.get("title", "New Chat")
                        db_session.last_updated = session.get("last_updated", time.time())
                        db_session.context = session.get("context", {})
                    else:
                        db_session = ChatSession(
                            id=session["id"],
                            user_id=session["user_id"],
                            title=session.get("title", "New Chat"),
                            created_at=session.get("created_at", time.time()),
                            last_updated=session.get("last_updated", time.time()),
                            context=session.get("context", {})
                        )
                        db.add(db_session)
                    db.commit()
                finally:
                    db.close()
            else:
                # For PostgreSQL, use async (but this is a sync method for compatibility)
                import asyncio
                asyncio.create_task(self._save_session_to_db_async(session))
        except Exception as e:
            logger.error(f"Error saving session to database: {e}")
    
    async def _save_session_to_db_async(self, session: Dict[str, Any]):
        """Async version for PostgreSQL"""
        try:
            async with SessionLocal() as db:
                result = await db.execute(
                    select(ChatSession).filter(ChatSession.id == session["id"])
                )
                db_session = result.scalar_one_or_none()
                
                if db_session:
                    db_session.title = session.get("title", "New Chat")
                    db_session.last_updated = session.get("last_updated", time.time())
                    db_session.context = session.get("context", {})
                else:
                    db_session = ChatSession(
                        id=session["id"],
                        user_id=session["user_id"],
                        title=session.get("title", "New Chat"),
                        created_at=session.get("created_at", time.time()),
                        last_updated=session.get("last_updated", time.time()),
                        context=session.get("context", {})
                    )
                    db.add(db_session)
                await db.commit()
        except Exception as e:
            logger.error(f"Error saving session to database (async): {e}")
    
    async def _delete_session_from_db(self, session_id: str):
        """Delete session from database"""
        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                db = SessionLocal()
                try:
                    # Delete messages first
                    db.query(DBChatMessage).filter(DBChatMessage.session_id == session_id).delete()
                    # Delete session
                    db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if db_session:
                        db.delete(db_session)
                    db.commit()
                finally:
                    db.close()
            else:
                # PostgreSQL async
                async with SessionLocal() as db:
                    # Delete messages
                    await db.execute(
                        select(DBChatMessage).filter(DBChatMessage.session_id == session_id)
                    )
                    result = await db.execute(
                        select(ChatSession).filter(ChatSession.id == session_id)
                    )
                    db_session = result.scalar_one_or_none()
                    if db_session:
                        await db.delete(db_session)
                        await db.commit()
        except Exception as e:
            logger.error(f"Error deleting session from database: {e}")
