"""
Configuration settings for LinkedOmicsChat backend.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator
from typing import List, Union, Any
import os
import json


class Settings(BaseSettings):
    """Application settings"""
    
    # API Keys
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    
    # Mock Mode
    MOCK_LLM: bool = True
    
    # Ollama (Local LLM)
    USE_OLLAMA: bool = False
    OLLAMA_MODEL: str = "llama3"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    
    # Database
    DATABASE_URL: str = "sqlite:///./linkedomicsai.db"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Vector Database
    PINECONE_API_KEY: str = ""
    PINECONE_ENVIRONMENT: str = "gcp-starter"
    
    # Application
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "change-this-in-production"
    
    # Authentication
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ADMIN_EMAILS: Union[List[str], str] = "[]"
    
    # CORS - stored as string, will be parsed to list
    CORS_ORIGINS: Union[List[str], str] = '["http://localhost:3000","http://localhost:3001"]'

    @field_validator("ADMIN_EMAILS", mode="before")
    @classmethod
    def parse_admin_emails(cls, value: Any) -> List[str]:
        """Parse ADMIN_EMAILS from JSON or comma-separated env input."""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(item).strip().lower() for item in parsed if str(item).strip()]
            except (json.JSONDecodeError, TypeError):
                pass
            return [item.strip().lower() for item in raw.split(",") if item.strip()]
        return []
    
    @model_validator(mode='after')
    def parse_cors_origins(self):
        """Parse CORS_ORIGINS if it's a JSON string"""
        import logging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)
        logger.info(f"CORS_ORIGINS raw value: {self.CORS_ORIGINS}, type: {type(self.CORS_ORIGINS)}")
        
        if isinstance(self.CORS_ORIGINS, str):
            # Remove surrounding quotes if present
            v_clean = self.CORS_ORIGINS.strip().strip('"').strip("'")
            try:
                parsed = json.loads(v_clean)
                logger.info(f"CORS_ORIGINS parsed from JSON: {parsed}")
                self.CORS_ORIGINS = parsed
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Failed to parse CORS_ORIGINS as JSON: {e}, trying comma-separated")
                # If parsing fails, treat as comma-separated string
                parsed = [origin.strip() for origin in v_clean.split(",") if origin.strip()]
                logger.info(f"CORS_ORIGINS parsed as comma-separated: {parsed}")
                self.CORS_ORIGINS = parsed
        else:
            logger.info(f"CORS_ORIGINS already a list: {self.CORS_ORIGINS}")
        
        return self
    
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
    
    # NCBI / PubMed (E-utilities — free, email required by NCBI ToS)
    NCBI_EMAIL: str = ""
    NCBI_API_KEY: str = ""  # optional — raises rate limit from 3 to 10 req/s

    # Durable artifact root for session-scoped workspaces (plots, exports, attachments).
    # Defaults to ./data/artifacts relative to the backend working dir.
    ARTIFACT_ROOT: str = "./data/artifacts"

    # Legacy flat plot cache retained for backward compatibility with older messages.
    # New visualizations are stored in per-session workspaces under ARTIFACT_ROOT.
    PLOT_DIR: str = "./data/plots"

    # MCP Configuration (Phase 1 Migration)
    USE_MCP: bool = False  # Feature flag to enable MCP architecture
    MCP_LINKEDOMICS_SERVER_ENABLED: bool = False  # Optional external data MCP server
    MCP_GENE_UTILS_SERVER_ENABLED: bool = True   # Gene identifier resolution (Ensembl/UniProt → HGNC)
    MCP_LITERATURE_SERVER_ENABLED: bool = True   # PubMed literature search
    MCP_FILES_SERVER_ENABLED: bool = False  # Phase 3
    MCP_COMPUTE_SERVER_ENABLED: bool = False  # Phase 3

    # LangGraph Configuration (Phase 2: chained / parallel tool execution)
    # When True AND USE_MCP=True, process_query is handled by LangGraphOrchestrator.
    # Set to False to fall back to the legacy single-shot MCPOrchestrator planner.
    USE_LANGGRAPH: bool = True

    # Guest / Public Access
    # When True, /query and /stream accept unauthenticated requests (guest sessions are in-memory only)
    GUEST_MODE_ENABLED: bool = True
    # Set GUEST_RATE_LIMIT_ENABLED=false in .env to disable during NAR review period
    GUEST_RATE_LIMIT_ENABLED: bool = True
    GUEST_RATE_LIMIT_PER_HOUR: int = 2
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        env_ignore_empty=True
    )


settings = Settings()

# Debug: Log the final CORS_ORIGINS value
import logging
logger = logging.getLogger(__name__)
logger.info(f"Settings initialized - CORS_ORIGINS final value: {settings.CORS_ORIGINS}, type: {type(settings.CORS_ORIGINS)}")
