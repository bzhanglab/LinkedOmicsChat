"""
LLM Factory - Unified interface for different LLM providers
Allows easy switching between OpenAI, Anthropic, Ollama, etc.
"""
from dataclasses import dataclass
from typing import Any, List, Optional
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.chat_models import ChatOllama
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from core.config import settings
import logging

logger = logging.getLogger(__name__)


@dataclass
class LLMInvocationResult:
    """Normalized text + usage metadata returned by a single LLM invocation."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: Optional[str] = None


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
    def _extract_text(response: Any) -> str:
        """Normalize a provider response object to plain text."""
        if hasattr(response, 'content'):
            content = response.content
            if isinstance(content, list):
                return "".join(
                    [
                        str(part.get("text", "") if isinstance(part, dict) else part)
                        for part in content
                    ]
                )
            return str(content)
        if isinstance(response, str):
            return response
        return str(response)

    @staticmethod
    def _extract_usage(response: Any, llm_instance=None) -> LLMInvocationResult:
        """Extract usage metadata from a LangChain response when available."""
        usage = getattr(response, "usage_metadata", None) or {}
        response_metadata = getattr(response, "response_metadata", None) or {}
        token_usage = response_metadata.get("token_usage") or response_metadata.get("usage") or {}

        def _pick_int(*values: Any) -> int:
            for value in values:
                if value is None or value == "":
                    continue
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
            return 0

        input_tokens = _pick_int(
            usage.get("input_tokens"),
            usage.get("prompt_tokens"),
            token_usage.get("input_tokens"),
            token_usage.get("prompt_tokens"),
            token_usage.get("prompt_token_count"),
            response_metadata.get("input_tokens"),
            response_metadata.get("prompt_tokens"),
            response_metadata.get("prompt_token_count"),
        )
        output_tokens = _pick_int(
            usage.get("output_tokens"),
            usage.get("completion_tokens"),
            token_usage.get("output_tokens"),
            token_usage.get("completion_tokens"),
            token_usage.get("candidates_token_count"),
            response_metadata.get("output_tokens"),
            response_metadata.get("completion_tokens"),
            response_metadata.get("candidates_token_count"),
        )

        model = (
            response_metadata.get("model_name")
            or response_metadata.get("model")
            or getattr(llm_instance, "model_name", None)
            or getattr(llm_instance, "model", None)
        )

        return LLMInvocationResult(
            text=LLMFactory._extract_text(response),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=str(model) if model else None,
        )

    @staticmethod
    async def invoke_async_with_metadata(
        llm_instance,
        messages: List[BaseMessage],
        **kwargs
    ) -> LLMInvocationResult:
        """
        Invoke LLM asynchronously and return normalized text + usage metadata.
        
        Args:
            llm_instance: LLM instance from create_llm()
            messages: List of message objects
            **kwargs: Additional invocation parameters
            
        Returns:
            LLMInvocationResult with text, token counts, and model name when available.
        """
        if llm_instance is None:
            return LLMInvocationResult(text="Mock response (MOCK_LLM=True)")
        
        try:
            response = await llm_instance.ainvoke(messages, **kwargs)
            return LLMFactory._extract_usage(response, llm_instance)
        except Exception as e:
            logger.error(f"Error invoking LLM: {e}")
            raise

    @staticmethod
    async def invoke_async(
        llm_instance,
        messages: List[BaseMessage],
        **kwargs
    ) -> str:
        """Invoke LLM asynchronously and return text response only."""
        result = await LLMFactory.invoke_async_with_metadata(llm_instance, messages, **kwargs)
        return result.text
    
    @staticmethod
    def invoke_sync_with_metadata(
        llm_instance,
        messages: List[BaseMessage],
        **kwargs
    ) -> LLMInvocationResult:
        """
        Invoke LLM synchronously and return normalized text + usage metadata.
        
        Args:
            llm_instance: LLM instance from create_llm()
            messages: List of message objects
            **kwargs: Additional invocation parameters
            
        Returns:
            LLMInvocationResult with text, token counts, and model name when available.
        """
        if llm_instance is None:
            return LLMInvocationResult(text="Mock response (MOCK_LLM=True)")
        
        try:
            response = llm_instance.invoke(messages, **kwargs)
            return LLMFactory._extract_usage(response, llm_instance)
        except Exception as e:
            logger.error(f"Error invoking LLM: {e}")
            raise

    @staticmethod
    def invoke_sync(
        llm_instance,
        messages: List[BaseMessage],
        **kwargs
    ) -> str:
        """Invoke LLM synchronously and return text response only."""
        result = LLMFactory.invoke_sync_with_metadata(llm_instance, messages, **kwargs)
        return result.text
