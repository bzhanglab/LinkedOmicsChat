"""
SQLAlchemy database models
"""
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from core.database import Base
import uuid


class ChatSession(Base):
    """Chat session model"""
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=True)
    created_at = Column(Float, nullable=False)
    last_updated = Column(Float, nullable=False)
    context = Column(JSON, nullable=True)

    # Relationship to messages
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
