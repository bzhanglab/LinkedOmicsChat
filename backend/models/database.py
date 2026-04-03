"""
SQLAlchemy database models
"""
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, JSON, Boolean, Index
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
    shared_token = Column(String, nullable=True, unique=True, index=True)

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
    
    # Composite index for efficient pagination queries
    __table_args__ = (
        Index('idx_session_timestamp', 'session_id', 'timestamp'),
    )


class TokenUsage(Base):
    """Per-query token usage record for registered users"""
    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String, nullable=True, index=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    model = Column(String, nullable=True)
    timestamp = Column(Float, nullable=False)


class GuestTokenUsage(Base):
    """Per-query token usage record for guest (unauthenticated) users, keyed by IP"""
    __tablename__ = "guest_token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip_address = Column(String, nullable=False, index=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    model = Column(String, nullable=True)
    timestamp = Column(Float, nullable=False)


class MessageFeedback(Base):
    """Thumbs-up / thumbs-down feedback on individual assistant messages"""
    __tablename__ = "message_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # turn_id corresponds to ChatMessage.id; nullable for guest sessions
    turn_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(String, nullable=True, index=True)
    user_id = Column(String, nullable=True, index=True)
    rating = Column(Integer, nullable=False)  # 1 = thumbs up, -1 = thumbs down
    reason = Column(String, nullable=True)    # optional: "wrong_data" | "not_relevant" | "hallucination"
    timestamp = Column(Float, nullable=False)
