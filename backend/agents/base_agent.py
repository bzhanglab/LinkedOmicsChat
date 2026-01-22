"""
Base Agent class for all specialized agents
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_community.llms import Ollama
from langchain.schema import HumanMessage, SystemMessage, AIMessage
from core.config import settings
import logging

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all agents"""
    
    def __init__(
        self,
        name: str,
        description: str,
        model: str = "gpt-4-turbo-preview",
        temperature: float = 0.7
    ):
        self.name = name
        self.description = description
        self.model = model
        self.temperature = temperature
        self.llm = self._initialize_llm()
        logger.info(f"Initialized {name} agent")
    
    def _initialize_llm(self):
        """Initialize the language model"""
        # In mock mode, we don't need a real LLM
        if settings.MOCK_LLM:
            return None
        
        # Check for Ollama (local LLM)
        if settings.USE_OLLAMA:
            logger.info(f"Using Ollama with model: {settings.OLLAMA_MODEL}")
            return Ollama(
                model=settings.OLLAMA_MODEL,
                temperature=self.temperature
            )
            
        # Use cloud LLMs
        if "claude" in self.model.lower():
            return ChatAnthropic(
                model=self.model,
                temperature=self.temperature,
                anthropic_api_key=settings.ANTHROPIC_API_KEY
            )
        else:
            return ChatOpenAI(
                model=self.model,
                temperature=self.temperature,
                openai_api_key=settings.OPENAI_API_KEY
            )
    
    @abstractmethod
    async def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Process a query and return results
        
        Args:
            query: User query or task description
            context: Additional context for processing
            
        Returns:
            Dictionary containing results and metadata
        """
        pass
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent"""
        pass
    
    async def invoke_llm(
        self,
        prompt: str,
        system_prompt: Optional[str] = None
    ) -> str:
        """Invoke the language model with a prompt"""
        
        # MOCK MODE: Return canned responses for testing without API key
        if settings.MOCK_LLM:
            logger.info(f"MOCK MODE: Returning canned response for {self.name}")
            return self._get_mock_response(prompt)
        
        messages = []
        
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        else:
            messages.append(SystemMessage(content=self.get_system_prompt()))
        
        messages.append(HumanMessage(content=prompt))
        
        try:
            # Ollama returns string directly, not a message object
            if isinstance(self.llm, Ollama):
                # Convert messages to simple prompt for Ollama
                prompt_parts = []
                for msg in messages:
                    if isinstance(msg, SystemMessage):
                        prompt_parts.append(f"System: {msg.content}")
                    elif isinstance(msg, HumanMessage):
                        prompt_parts.append(f"Human: {msg.content}")
                full_prompt = "\n\n".join(prompt_parts)
                response = await self.llm.ainvoke(full_prompt)
                return response if isinstance(response, str) else response.content
            else:
                response = await self.llm.ainvoke(messages)
                return response.content
        except Exception as e:
            logger.error(f"Error invoking LLM in {self.name}: {e}")
            raise
    
    def _get_mock_response(self, prompt: str) -> str:
        """Generate mock responses for testing without API key"""
        prompt_lower = prompt.lower()
        
        # Data Curation Agent responses
        if "DataCuration" in self.name:
            if "breast" in prompt_lower or "brca" in prompt_lower:
                return """{"cancer_types": ["breast cancer"], "genes": [], "data_types": ["rna_seq"], "analysis_types": ["correlation"]}"""
            elif "lung" in prompt_lower:
                return """{"cancer_types": ["lung cancer"], "genes": [], "data_types": ["rna_seq"], "analysis_types": ["survival"]}"""
            else:
                return """{"cancer_types": [], "genes": [], "data_types": ["rna_seq"], "analysis_types": []}"""
        
        # Statistical Analysis Agent responses
        elif "Analysis" in self.name:
            if "analysis type" in prompt_lower or "what type" in prompt_lower:
                if "survival" in prompt_lower:
                    return "survival"
                elif "differential" in prompt_lower:
                    return "differential_expression"
                else:
                    return "correlation"
            else:
                return """Completed analysis successfully. Found significant results with p-value < 0.05. 
Statistical tests applied with appropriate corrections. Key findings identified and ready for interpretation."""
        
        # Visualization Agent responses
        elif "Visualization" in self.name:
            if "visualization type" in prompt_lower or "what visual" in prompt_lower:
                return """["scatter", "heatmap"]"""
            else:
                return """Generated visualizations successfully. Created publication-ready figures 
with appropriate labels, legends, and statistical annotations."""
        
        # Literature Mining Agent responses
        elif "Literature" in self.name:
            if "search terms" in prompt_lower or "extract" in prompt_lower:
                return """["TP53", "breast cancer", "gene expression"]"""
            else:
                return """Found relevant literature supporting these findings. Multiple studies confirm 
the biological significance. Established pathways and mechanisms identified in published research."""
        
        # Default response
        return f"Mock response from {self.name}: Analysis completed successfully."
    
    def format_response(
        self,
        success: bool,
        data: Any = None,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Format agent response in standard structure"""
        return {
            "agent": self.name,
            "success": success,
            "data": data,
            "message": message,
            "metadata": metadata or {}
        }
