"""
Pydantic schemas for API request/response validation
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class AgentType(str, Enum):
    """Types of agents in the system"""
    DATA_CURATION = "data_curation"
    STATISTICAL_ANALYSIS = "statistical_analysis"
    VISUALIZATION = "visualization"
    LITERATURE_MINING = "literature_mining"
    INTERPRETATION = "interpretation"
    ORCHESTRATOR = "orchestrator"


class MessageRole(str, Enum):
    """Message roles in conversation"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    AGENT = "agent"


class ChatMessage(BaseModel):
    """Chat message schema"""
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    agent_type: Optional[AgentType] = None
    metadata: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    """Request schema for chat endpoint"""
    message: str
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class TurnTruncateRequest(BaseModel):
    """Request schema for truncating a session from a given turn/message row."""
    message_id: int


class ChatResponse(BaseModel):
    """Response schema for chat endpoint"""
    message: str
    summary: Optional[str] = None
    session_id: str
    turn_id: Optional[int] = None
    agent_responses: List[Dict[str, Any]] = []
    visualizations: List[Dict[str, Any]] = []
    analyses: List[Dict[str, Any]] = []  # Analysis results (correlations, etc.)
    suggestions: List[str] = []
    clarification_options: List[str] = []
    tool_sources: Dict[str, str] = {}
    tools_used: List[str] = []
    no_collapse: Optional[bool] = None
    is_general_knowledge: Optional[bool] = None
    execution_trace: List[Dict[str, Any]] = []
    confidence: Optional[str] = None  # "high" | "partial" | "low" | "general_knowledge"
    metadata: Optional[Dict[str, Any]] = None


class DatasetInfo(BaseModel):
    """Dataset information schema"""
    id: str
    name: str
    description: str
    cancer_type: Optional[str] = None
    sample_count: int
    feature_count: int
    data_types: List[str]
    publication: Optional[str] = None
    source: str


class AnalysisRequest(BaseModel):
    """Request schema for analysis"""
    analysis_type: str
    dataset_ids: List[str]
    parameters: Dict[str, Any]
    target_genes: Optional[List[str]] = None


class AnalysisResult(BaseModel):
    """Result schema for analysis"""
    id: str
    analysis_type: str
    status: str
    results: Dict[str, Any]
    visualizations: List[Dict[str, Any]]
    statistics: Dict[str, Any]
    created_at: datetime
    completed_at: Optional[datetime] = None


class WorkflowStep(BaseModel):
    """Workflow step schema"""
    step_id: str
    agent_type: AgentType
    action: str
    parameters: Dict[str, Any]
    dependencies: List[str] = []
    status: str = "pending"


class Workflow(BaseModel):
    """Workflow schema"""
    id: str
    name: str
    description: str
    steps: List[WorkflowStep]
    created_at: datetime
    status: str


class AgentStatus(BaseModel):
    """Agent status schema"""
    agent_type: AgentType
    status: str
    current_task: Optional[str] = None
    queue_length: int = 0


class SystemStatus(BaseModel):
    """System status schema"""
    status: str
    agents: List[AgentStatus]
    active_sessions: int
    uptime: float


# Authentication schemas
class UserRegister(BaseModel):
    """User registration schema"""
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., pattern=r'^[^@]+@[^@]+\.[^@]+$')
    password: str = Field(..., min_length=8)


class UserLogin(BaseModel):
    """User login schema"""
    username: str
    password: str


class Token(BaseModel):
    """Token response schema"""
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """User response schema"""
    id: str
    username: str
    email: str
    is_active: bool
    created_at: float


class ForgotPasswordRequest(BaseModel):
    """Forgot password request schema"""
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., pattern=r'^[^@]+@[^@]+\.[^@]+$')


class ResetPasswordRequest(BaseModel):
    """Reset password request schema"""
    token: str
    new_password: str = Field(..., min_length=8)


class FeedbackRequest(BaseModel):
    """Request schema for submitting response feedback"""
    turn_id: Optional[int] = None
    session_id: Optional[str] = None
    rating: int  # 1 = thumbs up, -1 = thumbs down
    reason: Optional[str] = None  # "wrong_data" | "not_relevant" | "hallucination"


class PublicRuntimeConfig(BaseModel):
    """Safe server runtime configuration exposed to the frontend."""
    llm_provider: str
    llm_model: str
    temperature: float
    max_tokens: int
    architecture: str
    orchestration: str
