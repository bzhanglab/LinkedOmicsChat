"""
FastAPI dependencies for authentication
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from core.database import get_db
from core.config import settings
from core.auth import decode_access_token, get_user_by_id
from models.database import User
import logging

logger = logging.getLogger(__name__)

security = HTTPBearer()


def is_admin_user(user: Optional[User]) -> bool:
    """Return True when the user is allowed to access internal admin routes."""
    if user is None or not user.email:
        return False
    return user.email.strip().lower() in set(settings.ADMIN_EMAILS)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency to get the current authenticated user from JWT token
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    
    # For both SQLite and PostgreSQL, use get_user_by_id
    # The function handles the database type internally
    if settings.DATABASE_URL.startswith("sqlite"):
        # SQLite - sync session, but get_user_by_id expects async signature
        # So we need to handle it differently
        from sqlalchemy.orm import Session
        db_sync: Session = db
        user = db_sync.query(User).filter(User.id == user_id).first()
    else:
        # PostgreSQL - async session
        user = await get_user_by_id(db, user_id)
    
    if user is None:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive"
        )
    
    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Optional dependency to get current user (returns None if not authenticated)
    Useful for endpoints that work with or without authentication
    """
    if credentials is None:
        return None
    
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require an authenticated admin user."""
    if not is_admin_user(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
