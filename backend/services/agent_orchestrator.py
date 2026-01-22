"""
Agent Orchestrator
Coordinates multiple agents to handle complex queries
"""
from typing import Dict, Any, Optional, List
from langchain.schema import HumanMessage, SystemMessage
import asyncio
import logging
import time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents import (
    DataCurationAgent,
    StatisticalAnalysisAgent,
    VisualizationAgent,
    LiteratureMiningAgent,
    AssociationAgent,
    DifferentialExpressionAgent
)
from agents.tools.search_tools import WebSearchTool
from core.config import settings
from core.llm_factory import LLMFactory
from core.database import SessionLocal
from models.database import ChatSession, ChatMessage as DBChatMessage

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Orchestrates multiple agents to handle research queries"""
    
    def __init__(self):
        self.agents = {}
        self.search_tool = WebSearchTool()  # Initialize web search tool
        # Initialize LLM using factory (supports OpenAI, Anthropic, Ollama)
        self.llm = LLMFactory.create_llm(
            model=settings.DEFAULT_LLM_MODEL,
            temperature=0.3
        )
        self.sessions = {}
    
    async def initialize(self):
        """Initialize all agents"""
        try:
            logger.info("Initializing agents...")
            self.agents = {
                "data": DataCurationAgent(),
                "analysis": StatisticalAnalysisAgent(),
                "visualization": VisualizationAgent(),
                "literature": LiteratureMiningAgent(),
                "association": AssociationAgent(),
                "differential_expression": DifferentialExpressionAgent()
            }
            logger.info("All agents initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing agents: {e}")
            raise
    
    async def cleanup(self):
        """Cleanup resources"""
        self.sessions.clear()
        logger.info("Agent orchestrator cleaned up")

    async def _save_session_to_db(self, session: Dict[str, Any]):
        """Save or update session in database"""
        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                # SQLite uses sync session
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
                    logger.info(f"Saved session {session['id']} to database")
                finally:
                    db.close()
            else:
                # PostgreSQL uses async session
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
                    logger.info(f"Saved session {session['id']} to database")
        except Exception as e:
            logger.error(f"Error saving session to database: {e}")

    async def _save_message_to_db(self, session_id: str, query: str, response: Dict[str, Any], timestamp: float):
        """Save chat message to database"""
        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                # SQLite uses sync session
                db = SessionLocal()
                try:
                    message = DBChatMessage(
                        session_id=session_id,
                        query=query,
                        response=response,
                        timestamp=timestamp
                    )
                    db.add(message)
                    db.commit()
                    logger.info(f"Saved message to session {session_id}")
                finally:
                    db.close()
            else:
                # PostgreSQL uses async session
                async with SessionLocal() as db:
                    message = DBChatMessage(
                        session_id=session_id,
                        query=query,
                        response=response,
                        timestamp=timestamp
                    )
                    db.add(message)
                    await db.commit()
                    logger.info(f"Saved message to session {session_id}")
        except Exception as e:
            logger.error(f"Error saving message to database: {e}")

    async def _load_session_from_db(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load session from database"""
        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                # SQLite uses sync session
                db = SessionLocal()
                try:
                    db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if not db_session:
                        return None
                    
                    messages = db.query(DBChatMessage).filter(
                        DBChatMessage.session_id == session_id
                    ).order_by(DBChatMessage.timestamp).all()
                    
                    history = [
                        {
                            "query": msg.query,
                            "response": msg.response,
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
                    
                    logger.info(f"Loaded session {session_id} from database with {len(history)} messages")
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
                            "response": msg.response,
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
                    
                    logger.info(f"Loaded session {session_id} from database with {len(history)} messages")
                    return session
        except Exception as e:
            logger.error(f"Error loading session from database: {e}")
            return None

    async def _load_all_sessions_from_db(self) -> List[Dict[str, Any]]:
        """Load all sessions from database"""
        try:
            if settings.DATABASE_URL.startswith("sqlite"):
                # SQLite uses sync session
                db = SessionLocal()
                try:
                    db_sessions = db.query(ChatSession).all()
                    sessions_list = []
                    
                    for db_session in db_sessions:
                        message_count = db.query(DBChatMessage).filter(
                            DBChatMessage.session_id == db_session.id
                        ).count()
                        
                        sessions_list.append({
                            "id": db_session.id,
                            "user_id": db_session.user_id,
                            "title": db_session.title,
                            "message_count": message_count,
                            "created_at": db_session.created_at,
                            "last_updated": db_session.last_updated
                        })
                    
                    logger.info(f"Loaded {len(sessions_list)} sessions from database")
                    return sessions_list
                finally:
                    db.close()
            else:
                # PostgreSQL uses async session
                async with SessionLocal() as db:
                    result = await db.execute(select(ChatSession))
                    db_sessions = result.scalars().all()
                    sessions_list = []
                    
                    for db_session in db_sessions:
                        # Count messages for this session
                        count_result = await db.execute(
                            select(DBChatMessage).filter(
                                DBChatMessage.session_id == db_session.id
                            )
                        )
                        message_count = len(count_result.scalars().all())
                        
                        sessions_list.append({
                            "id": db_session.id,
                            "user_id": db_session.user_id,
                            "title": db_session.title,
                            "message_count": message_count,
                            "created_at": db_session.created_at,
                            "last_updated": db_session.last_updated
                        })
                    
                    logger.info(f"Loaded {len(sessions_list)} sessions from database")
                    return sessions_list
        except Exception as e:
            logger.error(f"Error loading sessions from database: {e}")
            return []

    def _delete_session_from_db(self, session_id: str):
        """Delete session from database"""
        try:
            db = SessionLocal()
            try:
                db_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if db_session:
                    db.delete(db_session)
                    db.commit()
                    logger.info(f"Deleted session {session_id} from database")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error deleting session from database: {e}")
    
    async def process_query(
        self,
        query: str,
        user_id: str,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a user query by coordinating appropriate agents
        
        Args:
            query: User's research question
            user_id: User identifier
            session_id: Optional session ID for context
            
        Returns:
            Comprehensive response with data, analysis, and visualizations
        """
        try:
            logger.info(f"Processing query from user {user_id}: {query}")
            
            # Get or create session context
            session = await self._get_or_create_session(session_id, user_id)
            
            # Determine which agents to invoke
            agent_plan = await self._create_agent_plan(query, session)
            
            # Execute agents in order
            results = await self._execute_agent_plan(agent_plan, query, session)
            
            # Generate final response
            final_response = await self._generate_final_response(
                query,
                results,
                session
            )
            
            # Update session history with the actual session ID
            self._update_session(session["id"], query, final_response)
            
            return final_response
            
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            return {
                "success": False,
                "message": f"Error processing query: {str(e)}",
                "query": query
            }
    
    async def _get_or_create_session(
        self,
        session_id: Optional[str],
        user_id: str
    ) -> Dict[str, Any]:
        """Get existing session or create new one"""
        # Check memory cache first
        if session_id and session_id in self.sessions:
            logger.info(f"Found session in memory: {session_id}")
            return self.sessions[session_id]
        
        # Try to load from database
        if session_id:
            db_session = await self._load_session_from_db(session_id)
            if db_session:
                self.sessions[session_id] = db_session
                return db_session
        
        # Create new session
        import uuid
        new_session_id = session_id or str(uuid.uuid4())
        logger.info(f"Creating new session: {new_session_id}")
        now = time.time()
        session = {
            "id": new_session_id,
            "user_id": user_id,
            "title": "New Chat",
            "history": [],
            "context": {},
            "created_at": now,
            "last_updated": now
        }
        self.sessions[new_session_id] = session
        
        # Save to database
        await self._save_session_to_db(session)
        
        return session
    
    async def _classify_query_type(
        self,
        query: str,
        session: Dict[str, Any]
    ) -> str:
        """
        Use LLM to classify query type based on content and conversation history
        
        Returns:
            "informational" - Simple questions, definitions, explanations
            "analysis" - Requires data analysis, correlations, statistics
            "data_search" - Finding datasets
            "follow_up" - Continuation of previous conversation
        """
        if settings.MOCK_LLM:
            # Fallback for mock mode
            return "analysis"
        
        try:
            # Use LLM factory (works with any provider)
            llm = LLMFactory.create_llm(temperature=0.3)
            
            # Build conversation context
            history_text = ""
            if session.get("history"):
                recent = session["history"][-2:]
                for item in recent:
                    history_text += f"User: {item.get('query', '')}\n"
            
            prompt = f"""Classify this bioinformatics query into ONE category:

Categories:
- informational: Basic questions about definitions, concepts, or mechanisms (e.g., "What is BRCA1?", "How does TP53 work?")
- literature_search: Questions about RECENT research, papers, findings, studies, or publications (e.g., "What are recent findings?", "Find papers on...", "Latest research on...")
- analysis: Requests for data analysis, correlations, statistical tests
- data_search: Looking for specific datasets
- follow_up: Simple continuation like "tell me more" or "explain that"

IMPORTANT: If the query contains words like "recent", "findings", "papers", "studies", "research", "latest", "new", or asks for publications, classify as literature_search.

{"Previous conversation:" + history_text if history_text else ""}
Current query: {query}

Respond with ONLY one word: informational, literature_search, analysis, data_search, or follow_up"""
            
            messages = [HumanMessage(content=prompt)]
            response = await LLMFactory.invoke_async(llm, messages)
            classification = response.strip().lower()
            
            # Validate response
            valid_types = ["informational", "literature_search", "analysis", "data_search", "follow_up"]
            if classification in valid_types:
                logger.info(f"Query classified as: {classification}")
                return classification
            else:
                logger.warning(f"Invalid classification '{classification}', defaulting to informational")
                return "informational"
                
        except Exception as e:
            logger.error(f"Error classifying query: {e}")
            return "informational"  # Safe default
    
    async def _create_agent_plan(
        self,
        query: str,
        session: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Determine which agents to invoke and in what order
        
        Returns:
            List of agent steps to execute
        """
        # Use LLM to classify the query type
        query_type = await self._classify_query_type(query, session)
        
        # For informational queries and follow-ups, don't run agents
        if query_type in ["informational", "follow_up"]:
            logger.info(f"{query_type.capitalize()} query - using LLM knowledge only")
            return []
        
        # For literature search, use literature agent only
        if query_type == "literature_search":
            logger.info("Literature search query - using literature agent")
            return [
                {"agent": "literature", "action": query, "depends_on": []}
            ]
        
        # For analysis and data search, use agents
        # Check if this is a correlation/association query
        query_lower = query.lower()
        is_correlation_query = any(
            word in query_lower
            for word in [
                "correlated", "correlation", "associate", "association",
                "find genes", "genes correlated", "correlate with"
            ]
        )
        
        # Check if pathway enrichment is requested (can be combined with correlation)
        is_pathway_query = any(
            word in query_lower
            for word in [
                "pathway", "enrichment", "enriched", "biological process",
                "go", "kegg", "reactome"
            ]
        )

        # Check if this is a differential expression query
        is_differential_query = any(
            word in query_lower
            for word in [
                "differential", "differentially expressed", "different between",
                "upregulated", "downregulated", "fold change", "differentially",
                "vs", "versus", "compare groups", "between groups"
            ]
        ) and any(
            word in query_lower
            for word in [
                "stage", "grade", "mutant", "wildtype", "group", "treatment",
                "responder", "non-responder", "high", "low", "expression"
            ]
        )

        # Route to AssociationAgent for:
        # 1. Correlation queries
        # 2. Pathway enrichment queries (standalone or combined with correlation)
        if is_correlation_query or is_pathway_query:
            logger.info("Correlation/pathway query detected - using AssociationAgent")
            return [
                {"agent": "association", "action": query, "depends_on": []}
            ]

        # Route to DifferentialExpressionAgent for differential expression queries
        if is_differential_query:
            logger.info("Differential expression query detected - using DifferentialExpressionAgent")
            return [
                {"agent": "differential_expression", "action": query, "depends_on": []}
            ]

        prompt = f"""Analyze this research query and determine which agents should be invoked:

Query: {query}

Available agents:
- data: Discovers relevant datasets
- analysis: Performs statistical analyses
- association: Finds gene correlations and associations (use for "find genes correlated with X")
- visualization: Creates plots and figures
- literature: Searches relevant papers

Return a JSON array of agent steps in execution order. Each step should have:
- agent: agent name
- action: what the agent should do
- depends_on: array of previous step indices (empty if no dependencies)

Example: [{{"agent": "data", "action": "find breast cancer datasets", "depends_on": []}}, 
          {{"agent": "analysis", "action": "correlation analysis", "depends_on": [0]}}]

Return ONLY valid JSON, no other text."""
        
        try:
            # Mock mode or Ollama: return simple default plan for analysis queries
            if settings.MOCK_LLM or settings.USE_OLLAMA or not self.llm:
                logger.info("Analysis query: Using default agent plan")
                return [
                    {"agent": "data", "action": query, "depends_on": []},
                    {"agent": "analysis", "action": query, "depends_on": [0]},
                    {"agent": "visualization", "action": query, "depends_on": [1]}
                ]
            
            messages = [
                SystemMessage(content="You are an agent coordination planner."),
                HumanMessage(content=prompt)
            ]
            response = await self.llm.ainvoke(messages)
            
            import json
            plan = json.loads(response.content)
            
            if not isinstance(plan, list):
                plan = [plan]
            
            logger.info(f"Created agent plan: {len(plan)} steps")
            return plan
            
        except Exception as e:
            logger.error(f"Error creating agent plan: {e}")
            # Default plan for common query
            return [
                {
                    "agent": "data",
                    "action": "find relevant datasets",
                    "depends_on": []
                },
                {
                    "agent": "analysis",
                    "action": "perform analysis",
                    "depends_on": [0]
                },
                {
                    "agent": "visualization",
                    "action": "create visualizations",
                    "depends_on": [1]
                }
            ]
    
    async def _execute_agent_plan(
        self,
        plan: List[Dict[str, Any]],
        query: str,
        session: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute the agent plan"""
        results = {}
        
        for i, step in enumerate(plan):
            agent_name = step.get("agent")
            action = step.get("action")
            depends_on = step.get("depends_on", [])
            
            logger.info(f"Executing step {i}: {agent_name} - {action}")
            
            # Get dependencies results
            context = {
                "query": query,
                "session": session,
                "previous_results": {
                    dep_idx: results.get(f"step_{dep_idx}")
                    for dep_idx in depends_on
                }
            }
            
            # Execute agent
            if agent_name in self.agents:
                agent = self.agents[agent_name]
                result = await agent.process(action, context)
                results[f"step_{i}"] = result
                results[agent_name] = result
            else:
                logger.warning(f"Unknown agent: {agent_name}")
        
        return results
    
    async def _generate_final_response(
        self,
        query: str,
        results: Dict[str, Any],
        session: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate comprehensive final response"""
        
        # If no agents were run (simple query), answer directly with LLM
        if not results:
            summary = await self._answer_simple_query(query, session)
            return {
                "success": True,
                "session_id": session["id"],
                "query": query,
                "summary": summary,
                "datasets": [],
                "analyses": [],
                "visualizations": [],
                "papers": [],
                "agent_results": {},
                "suggestions": []
            }
        
        # Extract key information from results
        datasets = []
        analyses = []
        visualizations = []
        papers = []
        
        for key, result in results.items():
            if not isinstance(result, dict):
                continue
                
            # Check by agent key name (data, analysis, association, visualization, literature)
            if key == "data" and result.get("success"):
                data = result.get("data", {})
                datasets = data.get("datasets", [])
            elif key == "analysis" and result.get("success"):
                data = result.get("data", {})
                analyses.append(data)
            elif key == "association" and result.get("success"):
                data = result.get("data", {})
                analyses.append(data)  # Association results are also analyses
            elif key == "differential_expression" and result.get("success"):
                data = result.get("data", {})
                analyses.append(data)  # Differential expression results are also analyses
            elif key == "visualization" and result.get("success"):
                data = result.get("data", {})
                visualizations = data.get("visualizations", [])
            elif key == "literature" and result.get("success"):
                data = result.get("data", {})
                papers = data.get("papers", [])
        
        # Generate narrative summary
        summary = await self._generate_narrative_summary(
            query,
            results
        )
        
        return {
            "success": True,
            "session_id": session["id"],
            "query": query,
            "summary": summary,
            "datasets": datasets,
            "analyses": analyses,
            "visualizations": visualizations,
            "papers": papers[:5],
            "agent_results": results,
            "suggestions": await self._generate_suggestions(query, results)
        }
    
    async def _answer_simple_query(
        self,
        query: str,
        session: Dict[str, Any]
    ) -> str:
        """Answer informational queries using LLM with full conversation context"""
        
        if settings.MOCK_LLM:
            return "Please provide more details about what analysis you'd like me to perform."
        
        try:
            # Create LLM instance using factory
            llm = LLMFactory.create_llm(temperature=0.7)
            
            # Build conversation messages for natural context
            messages = []
            
            # Add system message
            messages.append(SystemMessage(content="""You are cpgAgent, an expert bioinformatics research assistant. You have deep knowledge of:
- Molecular biology, genetics, and genomics
- Gene functions, pathways, and interactions
- Cancer biology and disease mechanisms
- Multi-omics data analysis

Provide clear, accurate, conversational responses. When users ask follow-up questions, build on the previous context naturally."""))
            
            # Add conversation history
            if session.get("history"):
                recent_history = session["history"][-4:]  # Last 4 exchanges
                logger.info(f"Loading {len(recent_history)} history items for context")
                for item in recent_history:
                    user_query = item.get('query', '')
                    assistant_response = item.get('response', {}).get('summary', '')
                    if user_query and assistant_response:
                        logger.info(f"History - Q: {user_query[:50]}... A: {assistant_response[:50]}...")
                        messages.append(HumanMessage(content=user_query))
                        messages.append(SystemMessage(content=assistant_response))
            else:
                logger.info("No conversation history available")
            
            # Add current query
            messages.append(HumanMessage(content=query))
            
            # Get response using factory
            response = await LLMFactory.invoke_async(llm, messages)
            return response
                
        except Exception as e:
            logger.error(f"Error answering query: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return "I apologize, but I encountered an error processing your question. Please try again."
    
    async def _generate_narrative_summary(
        self,
        query: str,
        results: Dict[str, Any]
    ) -> str:
        """Generate a narrative summary of all results"""
        
        # Build a concise summary of results (truncate large data)
        results_summary_parts = []
        for key, result in results.items():
            if not isinstance(result, dict):
                continue
            
            # Skip failed results
            if not result.get("success", False):
                # Only include error message if it's not a "chunk too big" error
                message = result.get('message', '')
                if message and "chunk" not in message.lower() and "too big" not in message.lower():
                    # Truncate error messages
                    msg = message[:200] + "..." if len(message) > 200 else message
                    results_summary_parts.append(f"{key}: {msg}")
                continue
            
            message = result.get('message', 'No message')
            data = result.get('data', {})
            
            # For association results, extract key stats only (keep it concise)
            if key == "association" and data:
                entity_type = "proteins" if data.get('data_source') == 'CPTAC' and data.get('data_type') == 'proteomics' else "genes"
                summary = (
                    f"AssociationAgent: Found {data.get('total_results', 0)} {entity_type} "
                    f"correlated with {data.get('target_gene', 'target')} in "
                    f"{data.get('cancer_type', 'dataset')} ({data.get('data_source', 'TCGA')} dataset). "
                    f"{data.get('significant_results', 0)} are statistically significant."
                )
                # Only include top 2 to keep it short
                if data.get('top_correlations'):
                    top_2 = data['top_correlations'][:2]
                    top_items = ", ".join([f"{g['gene']} (r={g['correlation']:.2f})" for g in top_2])
                    summary += f" Top: {top_items}."
                
                # Add pathway enrichment info if available
                pathway_data = data.get('pathway_enrichment')
                if pathway_data and pathway_data.get('pathways'):
                    num_pathways = pathway_data.get('total_pathways', len(pathway_data.get('pathways', [])))
                    summary += f" Found {num_pathways} enriched pathways."
                    if pathway_data.get('top_pathways'):
                        top_pathways = pathway_data['top_pathways'][:2]
                        pathway_names = [p.get('pathway', 'Unknown') for p in top_pathways]
                        summary += f" Top pathways: {', '.join(pathway_names)}."
                
                results_summary_parts.append(summary)
            else:
                # For other agents, use message only (truncate if too long)
                # Filter out "chunk too big" errors
                if "chunk" in message.lower() or "too big" in message.lower():
                    continue
                msg = message[:500] + "..." if len(message) > 500 else message
                results_summary_parts.append(f"{key}: {msg}")
        
        results_summary = "\n\n".join(results_summary_parts)
        
        # Limit total summary length to avoid Ollama context issues
        if len(results_summary) > 2000:
            results_summary = results_summary[:2000] + "... [truncated]"
        
        # In mock mode, return simple summary
        if settings.MOCK_LLM:
            return "Analysis completed successfully. Found relevant datasets and performed requested analysis. Results are available in the detailed responses below."
        
        # Generate summary using LLM factory (works with any provider)
        try:
            llm = LLMFactory.create_llm(temperature=0.7)
            
            prompt = f"""You are a bioinformatics research assistant. Summarize these analysis results in a helpful, conversational way.

Original Query: {query}

Agent Results:
{results_summary}

Provide a clear, helpful response (3-4 sentences) that directly answers the user's question and highlights key findings."""
            
            messages = [HumanMessage(content=prompt)]
            response = await LLMFactory.invoke_async(llm, messages)
            
            # Check if response contains error indicators
            if response and ("chunk too big" in response.lower() or "error" in response.lower()):
                logger.warning("LLM returned error in response, using fallback")
                return self._generate_fallback_summary(query, results)
            
            return response
        except Exception as e:
            error_msg = str(e).lower()
            if "chunk" in error_msg or "too big" in error_msg or "context" in error_msg:
                logger.error(f"LLM context error: {e}. Using fallback summary.")
                return self._generate_fallback_summary(query, results)
            logger.error(f"Error generating summary: {e}")
            return self._generate_fallback_summary(query, results)
    
    def _generate_fallback_summary(
        self,
        query: str,
        results: Dict[str, Any]
    ) -> str:
        """Generate a fallback summary when LLM fails"""
        summary_parts = []
        
        for key, result in results.items():
            if not isinstance(result, dict):
                continue
            
            # Only process successful results
            if not result.get("success", False):
                continue
            
            data = result.get("data", {})
            message = result.get("message", "")
            
            # Filter out error messages
            if message and ("chunk" in message.lower() or "too big" in message.lower()):
                continue
            
            if key == "association" and data:
                # Determine entity type (proteins vs genes)
                entity_type = "proteins" if data.get('data_source') == 'CPTAC' and data.get('data_type') == 'proteomics' else "genes"
                data_source = data.get('data_source', 'TCGA')
                
                pathway_info = ""
                pathway_data = data.get('pathway_enrichment')
                if pathway_data and pathway_data.get('pathways'):
                    num_pathways = pathway_data.get('total_pathways', len(pathway_data.get('pathways', [])))
                    pathway_info = f" Identified {num_pathways} enriched pathways."
                
                summary_parts.append(
                    f"Found {data.get('total_results', 0)} {entity_type} correlated with "
                    f"{data.get('target_gene', 'target gene')} in {data.get('cancer_type', 'dataset')} "
                    f"({data_source} dataset). "
                    f"{data.get('significant_results', 0)} correlations are statistically significant."
                    f"{pathway_info}"
                )
            elif key == "differential_expression" and data:
                group1 = data.get('group1', 'group 1')
                group2 = data.get('group2', 'group 2')
                cancer_type = data.get('cancer_type', 'dataset')
                data_source = data.get('data_source', 'TCGA')
                
                summary_parts.append(
                    f"Found {data.get('total_results', 0)} genes tested between {group1} and {group2} "
                    f"in {cancer_type} ({data_source} dataset). "
                    f"{data.get('significant_results', 0)} genes are significantly differentially expressed "
                    f"({len(data.get('top_upregulated', []))} upregulated, "
                    f"{len(data.get('top_downregulated', []))} downregulated)."
                )
            elif message:
                summary_parts.append(message)
        
        if summary_parts:
            return " ".join(summary_parts)
        else:
            # If no successful results, provide a generic message
            return f"Analysis completed for: {query}. See detailed results below."
    
    async def _generate_suggestions(
        self,
        query: str,
        results: Dict[str, Any]
    ) -> List[str]:
        """Generate follow-up suggestions"""
        suggestions = [
            "Explore additional datasets for validation",
            "Perform pathway enrichment analysis on significant genes",
            "Check for clinical correlations with patient outcomes"
        ]
        return suggestions
    
    async def _generate_session_title(self, first_query: str) -> str:
        """Generate a short title for the chat session based on first query"""
        if settings.MOCK_LLM:
            return first_query[:50] + ("..." if len(first_query) > 50 else "")
        
        try:
            llm = LLMFactory.create_llm(temperature=0.3)
            
            prompt = f"""Generate a short, descriptive title (max 6 words) for a chat conversation that starts with this question:

"{first_query}"

Respond with ONLY the title, nothing else. Make it specific and informative."""
            
            messages = [HumanMessage(content=prompt)]
            response = await LLMFactory.invoke_async(llm, messages)
            title = response.strip().strip('"').strip("'")
            
            # Limit length
            if len(title) > 60:
                title = title[:57] + "..."
            
            return title
        except Exception as e:
            logger.error(f"Error generating title: {e}")
            return first_query[:50] + ("..." if len(first_query) > 50 else "")
    
    def _update_session(
        self,
        session_id: Optional[str],
        query: str,
        response: Dict[str, Any]
    ):
        """Update session history"""
        if session_id and session_id in self.sessions:
            now = time.time()
            
            self.sessions[session_id]["history"].append({
                "query": query,
                "response": response,
                "timestamp": now
            })
            self.sessions[session_id]["last_updated"] = now
            
            logger.info(f"Updated session {session_id}: now has {len(self.sessions[session_id]['history'])} history items")
            
            # Save message to database
            await self._save_message_to_db(session_id, query, response, now)
            
            # Update session in database
            await self._save_session_to_db(self.sessions[session_id])
            
            # Generate title after first message
            if len(self.sessions[session_id]["history"]) == 1 and self.sessions[session_id].get("title") == "New Chat":
                asyncio.create_task(self._update_session_title(session_id, query))
        else:
            logger.warning(f"Cannot update session {session_id}: not found in sessions dict")
    
    async def _update_session_title(self, session_id: str, first_query: str):
        """Async task to generate and update session title"""
        try:
            logger.info(f"Generating title for session {session_id} from query: {first_query[:50]}")
            title = await self._generate_session_title(first_query)
            if session_id in self.sessions:
                self.sessions[session_id]["title"] = title
                logger.info(f"✅ Generated title for session {session_id}: {title}")
                
                # Save updated title to database
                await self._save_session_to_db(self.sessions[session_id])
            else:
                logger.warning(f"Session {session_id} not found when updating title")
        except Exception as e:
            logger.error(f"Error updating session title: {e}", exc_info=True)
            # Fallback to truncated query
            if session_id in self.sessions:
                fallback_title = first_query[:50] + ("..." if len(first_query) > 50 else "")
                self.sessions[session_id]["title"] = fallback_title
                await self._save_session_to_db(self.sessions[session_id])
                logger.info(f"Using fallback title: {fallback_title}")