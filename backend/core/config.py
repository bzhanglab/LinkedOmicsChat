"""
Configuration settings for cpgAgent backend
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List, Union
import os
import json


class Settings(BaseSettings):
    """Application settings"""
    
    # API Keys
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    
    # Mock Mode
    MOCK_LLM: bool = True
    
    # Ollama (Local LLM)
    USE_OLLAMA: bool = False
    OLLAMA_MODEL: str = "llama3"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    
    # Database
    DATABASE_URL: str = "sqlite:///./cpgagent.db"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Vector Database
    PINECONE_API_KEY: str = ""
    PINECONE_ENVIRONMENT: str = "gcp-starter"
    
    # Application
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "change-this-in-production"
    
    # CORS
    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://localhost:3001"
    ]
    
    @field_validator('CORS_ORIGINS', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS_ORIGINS if it's a JSON string"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                # If parsing fails, treat as comma-separated string
                return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    
    # File Upload
    MAX_UPLOAD_SIZE_MB: int = 100
    
    # LinkedOmics API
    LINKEDOMICS_API_URL: str = "https://api.linkedomics.org"
    LINKEDOMICS_API_KEY: str = ""
    
    # Agent Configuration
    DEFAULT_LLM_MODEL: str = "gpt-4-turbo-preview"
    DEFAULT_TEMPERATURE: float = 0.7
    MAX_TOKENS: int = 4000
    
    # Timeouts
    AGENT_TIMEOUT_SECONDS: int = 300
    API_TIMEOUT_SECONDS: int = 30
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )


settings = Settings()
