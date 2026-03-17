"""
LLM Factory - Unified interface for different LLM providers
Allows easy switching between OpenAI, Anthropic, Ollama, etc.
"""
from typing import Optional, List
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.chat_models import ChatOllama
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from core.config import settings
import logging

logger = logging.getLogger(__name__)


class LLMFactory:
    """Factory for creating LLM instances based on configuration"""
    
    @staticmethod
    def create_llm(
        model: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ):
        """
        Create an LLM instance based on configuration
        
        Priority:
        1. USE_OLLAMA -> ChatOllama
        2. Model name contains "gemini" -> ChatGoogleGenerativeAI
        3. Model name contains "claude" -> ChatAnthropic
        4. Default -> ChatOpenAI
        
        Args:
            model: Model name (optional, uses DEFAULT_LLM_MODEL if not provided)
            temperature: Temperature setting
            **kwargs: Additional model-specific parameters
            
        Returns:
            LLM instance (ChatOpenAI, ChatAnthropic, or ChatOllama)
        """
        if settings.MOCK_LLM:
            return None
        
        # Use provided model or default
        model_name = model or settings.DEFAULT_LLM_MODEL
        
        # Check for Ollama first
        if settings.USE_OLLAMA:
            ollama_model = kwargs.get("ollama_model") or settings.OLLAMA_MODEL
            base_url = kwargs.get("base_url") or settings.OLLAMA_BASE_URL
            logger.info(f"Creating Ollama LLM: {ollama_model} at {base_url}")
            return ChatOllama(
                model=ollama_model,
                base_url=base_url,
                temperature=temperature,
                **{k: v for k, v in kwargs.items() if k not in ["ollama_model", "base_url"]}
            )
        
        # Check for Google/Gemini (only when model name explicitly says gemini)
        if "gemini" in model_name.lower():
            logger.info(f"Creating Google Gemini LLM: {model_name}")
            return ChatGoogleGenerativeAI(
                model=model_name,
                temperature=temperature,
                max_output_tokens=kwargs.get("max_tokens") or settings.MAX_TOKENS,
                google_api_key=settings.GOOGLE_API_KEY or kwargs.get("google_api_key"),
                **{k: v for k, v in kwargs.items() if k not in ["google_api_key", "ollama_model", "max_tokens"]}
            )
        
        # Check for Anthropic/Claude
        if "claude" in model_name.lower() or settings.ANTHROPIC_API_KEY:
            logger.info(f"Creating Anthropic LLM: {model_name}")
            return ChatAnthropic(
                model=model_name,
                temperature=temperature,
                max_tokens=kwargs.get("max_tokens") or settings.MAX_TOKENS,
                anthropic_api_key=settings.ANTHROPIC_API_KEY or kwargs.get("anthropic_api_key"),
                **{k: v for k, v in kwargs.items() if k not in ["anthropic_api_key", "ollama_model", "max_tokens"]}
            )
        
        # Default to OpenAI
        logger.info(f"Creating OpenAI LLM: {model_name}")
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            max_tokens=kwargs.get("max_tokens") or settings.MAX_TOKENS,
            openai_api_key=settings.OPENAI_API_KEY or kwargs.get("openai_api_key"),
            **{k: v for k, v in kwargs.items() if k not in ["openai_api_key", "ollama_model", "max_tokens"]}
        )
    
    @staticmethod
    async def invoke_async(
        llm_instance,
        messages: List[BaseMessage],
        **kwargs
    ) -> str:
        """
        Invoke LLM asynchronously and return text response
        
        Args:
            llm_instance: LLM instance from create_llm()
            messages: List of message objects
            **kwargs: Additional invocation parameters
            
        Returns:
            Text response from LLM
        """
        if llm_instance is None:
            return "Mock response (MOCK_LLM=True)"
        
        try:
            response = await llm_instance.ainvoke(messages, **kwargs)
            
            # Handle different response types
            if hasattr(response, 'content'):
                content = response.content
                if isinstance(content, list):
                    # Some models (like Gemini) return content as a list of parts
                    return "".join([str(part.get("text", "") if isinstance(part, dict) else part) for part in content])
                return str(content)
            elif isinstance(response, str):
                return response
            else:
                return str(response)
        except Exception as e:
            logger.error(f"Error invoking LLM: {e}")
            raise
    
    @staticmethod
    def invoke_sync(
        llm_instance,
        messages: List[BaseMessage],
        **kwargs
    ) -> str:
        """
        Invoke LLM synchronously and return text response
        
        Args:
            llm_instance: LLM instance from create_llm()
            messages: List of message objects
            **kwargs: Additional invocation parameters
            
        Returns:
            Text response from LLM
        """
        if llm_instance is None:
            return "Mock response (MOCK_LLM=True)"
        
        try:
            response = llm_instance.invoke(messages, **kwargs)
            
            # Handle different response types
            if hasattr(response, 'content'):
                content = response.content
                if isinstance(content, list):
                    return "".join([str(part.get("text", "") if isinstance(part, dict) else part) for part in content])
                return str(content)
            elif isinstance(response, str):
                return response
            else:
                return str(response)
        except Exception as e:
            logger.error(f"Error invoking LLM: {e}")
            raise
