"""
Authentication utilities for user management and JWT tokens
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from sqlalchemy import select
from core.config import settings
from models.database import User
import logging
import time
import uuid
import secrets

logger = logging.getLogger(__name__)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash (sync, CPU-bound — use verify_password_async in async context)."""
    try:
        if isinstance(plain_password, str):
            plain_password = plain_password.encode('utf-8')
        if isinstance(hashed_password, str):
            hashed_password = hashed_password.encode('utf-8')
        return bcrypt.checkpw(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Error verifying password: {e}")
        return False


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """Non-blocking bcrypt verify — runs in a thread pool to avoid stalling the event loop."""
    import asyncio
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt (sync, CPU-bound — use get_password_hash_async in async context)."""
    try:
        if isinstance(password, str):
            password_bytes = password.encode('utf-8')
        else:
            password_bytes = password

        if len(password_bytes) > 72:
            logger.warning("Password exceeds 72 bytes, truncating")
            password_bytes = password_bytes[:72]

        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    except Exception as e:
        logger.error(f"Error hashing password: {e}")
        raise


async def get_password_hash_async(password: str) -> str:
    """Non-blocking bcrypt hash — runs in a thread pool to avoid stalling the event loop."""
    import asyncio
    return await asyncio.to_thread(get_password_hash, password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT token"""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None


async def get_user_by_username(
    db, username: str
) -> Optional[User]:
    """Get user by username (works with both sync and async sessions)"""
    try:
        from core.config import settings as db_settings
        if db_settings.DATABASE_URL.startswith("sqlite"):
            # SQLite - sync session
            from sqlalchemy.orm import Session
            db_sync: Session = db
            return db_sync.query(User).filter(User.username == username).first()
        else:
            # PostgreSQL - async session
            result = await db.execute(select(User).filter(User.username == username))
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error getting user by username: {e}")
        return None


async def get_user_by_email(db, email: str) -> Optional[User]:
    """Get user by email (works with both sync and async sessions)"""
    try:
        from core.config import settings as db_settings
        if db_settings.DATABASE_URL.startswith("sqlite"):
            # SQLite - sync session
            from sqlalchemy.orm import Session
            db_sync: Session = db
            return db_sync.query(User).filter(User.email == email).first()
        else:
            # PostgreSQL - async session
            result = await db.execute(select(User).filter(User.email == email))
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error getting user by email: {e}")
        return None


async def get_user_by_id(db, user_id: str) -> Optional[User]:
    """Get user by ID (works with both sync and async sessions)"""
    try:
        from core.config import settings as db_settings
        if db_settings.DATABASE_URL.startswith("sqlite"):
            # SQLite - sync session
            from sqlalchemy.orm import Session
            db_sync: Session = db
            return db_sync.query(User).filter(User.id == user_id).first()
        else:
            # PostgreSQL - async session
            result = await db.execute(select(User).filter(User.id == user_id))
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error getting user by ID: {e}")
        return None


async def create_user(
    db, username: str, email: str, password: str
) -> User:
    """Create a new user (works with both sync and async sessions)"""
    from core.config import settings as db_settings
    hashed_password = await get_password_hash_async(password)
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        email=email,
        password_hash=hashed_password,
        is_active=True,
        created_at=time.time(),
    )
    
    try:
        if db_settings.DATABASE_URL.startswith("sqlite"):
            # SQLite - sync session
            from sqlalchemy.orm import Session
            db_sync: Session = db
            db_sync.add(user)
            db_sync.commit()
            db_sync.refresh(user)
        else:
            # PostgreSQL - async session
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return user
    except Exception as e:
        logger.error(f"Error in create_user: {e}", exc_info=True)
        if db_settings.DATABASE_URL.startswith("sqlite"):
            db.rollback()
        else:
            await db.rollback()
        raise


def generate_reset_token() -> str:
    """Generate a secure random token for password reset"""
    return secrets.token_urlsafe(32)


async def set_password_reset_token(
    db, user_id: str, token: str, expires_in_hours: int = 1
) -> None:
    """Set password reset token for a user"""
    from core.config import settings as db_settings
    expires_at = time.time() + (expires_in_hours * 3600)
    
    try:
        if db_settings.DATABASE_URL.startswith("sqlite"):
            # SQLite - sync session
            from sqlalchemy.orm import Session
            db_sync: Session = db
            user = db_sync.query(User).filter(User.id == user_id).first()
            if user:
                user.reset_token = token
                user.reset_token_expires = expires_at
                db_sync.commit()
        else:
            # PostgreSQL - async session
            result = await db.execute(select(User).filter(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.reset_token = token
                user.reset_token_expires = expires_at
                await db.commit()
    except Exception as e:
        logger.error(f"Error setting reset token: {e}")
        raise


async def get_user_by_reset_token(db, token: str) -> Optional[User]:
    """Get user by reset token if valid and not expired"""
    try:
        from core.config import settings as db_settings
        current_time = time.time()
        
        if db_settings.DATABASE_URL.startswith("sqlite"):
            # SQLite - sync session
            from sqlalchemy.orm import Session
            db_sync: Session = db
            user = db_sync.query(User).filter(
                User.reset_token == token,
                User.reset_token_expires > current_time
            ).first()
            return user
        else:
            # PostgreSQL - async session
            result = await db.execute(
                select(User).filter(
                    User.reset_token == token,
                    User.reset_token_expires > current_time
                )
            )
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error getting user by reset token: {e}")
        return None


async def update_user_password(
    db, user_id: str, new_password: str
) -> None:
    """Update user password and clear reset token"""
    from core.config import settings as db_settings
    hashed_password = await get_password_hash_async(new_password)
    
    try:
        if db_settings.DATABASE_URL.startswith("sqlite"):
            # SQLite - sync session
            from sqlalchemy.orm import Session
            db_sync: Session = db
            user = db_sync.query(User).filter(User.id == user_id).first()
            if user:
                user.password_hash = hashed_password
                user.reset_token = None
                user.reset_token_expires = None
                db_sync.commit()
        else:
            # PostgreSQL - async session
            result = await db.execute(select(User).filter(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.password_hash = hashed_password
                user.reset_token = None
                user.reset_token_expires = None
                await db.commit()
    except Exception as e:
        logger.error(f"Error updating password: {e}")
        raise
