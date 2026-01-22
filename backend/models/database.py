"""
SQLAlchemy database models
"""
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship
from core.database import Base
import uuid


class User(Base):
    """User model for authentication"""
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(Float, nullable=False)
    
    # Password reset fields
    reset_token = Column(String, nullable=True, index=True)
    reset_token_expires = Column(Float, nullable=True)
    
    # Relationship to sessions
    sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")


class ChatSession(Base):
    """Chat session model"""
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=True)
    created_at = Column(Float, nullable=False)
    last_updated = Column(Float, nullable=False)
    context = Column(JSON, nullable=True)

    # Relationships
    user = relationship("User", back_populates="sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    """Chat message model"""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    query = Column(Text, nullable=False)
    response = Column(JSON, nullable=False)
    timestamp = Column(Float, nullable=False)

    # Relationship to session
    session = relationship("ChatSession", back_populates="messages")


class WorkflowExecution(Base):
    """Workflow execution record - stores each run of a workflow"""
    __tablename__ = "workflow_executions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id = Column(String, nullable=False, index=True)  # Reference to workflow definition
    workflow_name = Column(String, nullable=False)
    status = Column(String, nullable=False)  # running, completed, failed, partially_completed
    parameters = Column(JSON, nullable=True)  # User-provided parameters
    step_results = Column(JSON, nullable=True)  # Results from each step
    summary = Column(Text, nullable=True)  # Execution summary
    started_at = Column(Float, nullable=False)
    completed_at = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
