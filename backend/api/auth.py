"""
Authentication API endpoints
Handles user registration, login, and token management
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import timedelta
import logging

from models.schemas import (
    UserRegister,
    UserLogin,
    Token,
    UserResponse,
    RegistrationResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    PublicRuntimeConfig,
    EmailVerificationRequest,
    EmailVerificationResponse,
    ResendVerificationRequest,
)
from core.database import get_db
from core.auth import (
    verify_password_async,
    create_access_token,
    get_user_by_username,
    get_user_by_email,
    create_user,
    generate_reset_token,
    generate_email_verification_token,
    set_password_reset_token,
    get_user_by_reset_token,
    update_user_password,
    set_email_verification_token,
    get_user_by_email_verification_token,
    mark_user_email_verified,
)
from core.config import settings
from core.dependencies import get_current_user, is_admin_user
from core.database import SessionLocal
from core.email import email_delivery_configured, send_verification_email
from models.database import User, TokenUsage
import time

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()


def _infer_llm_provider(model_name: str) -> str:
    """Infer the active provider from server settings."""
    if settings.USE_OLLAMA:
        return "Ollama"
    if "gemini" in model_name.lower() or settings.GOOGLE_API_KEY:
        return "Google Gemini"
    if "claude" in model_name.lower() or settings.ANTHROPIC_API_KEY:
        return "Anthropic"
    return "OpenAI"


def _email_verification_required() -> bool:
    return settings.EMAIL_VERIFICATION_ENABLED


@router.post("/register", response_model=RegistrationResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    db = Depends(get_db)
):
    """
    Register a new user
    
    Args:
        user_data: User registration data (username, email, password)
        
    Returns:
        Created user information
    """
    # Check if username already exists
    existing_user = await get_user_by_username(db, user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    # Check if email already exists
    existing_email = await get_user_by_email(db, user_data.email)
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    verification_required = _email_verification_required()
    if verification_required and not email_delivery_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email verification is enabled but SMTP email delivery is not configured"
        )

    verification_token = None
    verification_expires = None
    if verification_required:
        verification_token = generate_email_verification_token()
        verification_expires = time.time() + (settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS * 3600)

    # Create new user
    try:
        user = await create_user(
            db,
            username=user_data.username,
            email=user_data.email,
            password=user_data.password,
            email_verified=not verification_required,
            email_verification_token=verification_token,
            email_verification_expires=verification_expires,
        )
        logger.info(f"New user registered: {user.username}")

        if verification_required and verification_token:
            message = (
                "Your account was created. Check your inbox for a verification link "
                "before signing in."
            )
            try:
                send_verification_email(user.username, user.email, verification_token)
            except Exception as e:
                logger.error("Failed to send verification email to %s: %s", user.email, e, exc_info=True)
                message = (
                    "Your account was created, but we could not send the verification "
                    "email right now. Please request a new verification email before signing in."
                )

            return RegistrationResponse(
                message=message,
                email=user.email,
                requires_email_verification=True,
                auto_login=False,
            )

        return RegistrationResponse(
            message="Account created successfully.",
            email=user.email,
            requires_email_verification=False,
            auto_login=True,
        )
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        )


@router.post("/login", response_model=Token)
async def login(
    user_data: UserLogin,
    db = Depends(get_db)
):
    """
    Login and get access token
    
    Args:
        user_data: Login credentials (username, password)
        
    Returns:
        JWT access token
    """
    logger.info(f"Attempting login for user: '{user_data.username}'")
    # Get user by username
    user = await get_user_by_username(db, user_data.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password (runs bcrypt in thread pool — avoids blocking the event loop)
    if not await verify_password_async(user_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    if _email_verification_required() and not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before signing in"
        )
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.id}, expires_delta=access_token_expires
    )
    
    logger.info(f"User logged in: {user.username}")
    
    return Token(access_token=access_token, token_type="bearer")
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.id}, expires_delta=access_token_expires
    )
    
    logger.info(f"User logged in: {user.username}")
    
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    Get current authenticated user information
    
    Returns:
        Current user information
    """
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        is_active=current_user.is_active,
        is_admin=is_admin_user(current_user),
        email_verified=current_user.email_verified,
        created_at=current_user.created_at
    )


@router.post("/verify-email", response_model=EmailVerificationResponse)
async def verify_email(
    request: EmailVerificationRequest,
    db: AsyncSession = Depends(get_db)
):
    """Verify an account using the emailed verification token."""
    user = await get_user_by_email_verification_token(db, request.token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token"
        )

    await mark_user_email_verified(db, user.id)
    logger.info("Email verified for user: %s", user.username)

    return EmailVerificationResponse(
        message="Email verified successfully. You can now sign in.",
        email=user.email,
    )


@router.post("/resend-verification", response_model=EmailVerificationResponse)
async def resend_verification_email(
    request: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db)
):
    """Resend the verification email for an existing unverified account."""
    if not _email_verification_required():
        return EmailVerificationResponse(
            message="Email verification is not enabled for this deployment."
        )

    if not email_delivery_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMTP email delivery is not configured"
        )

    user = await get_user_by_email(db, request.email)
    generic_message = (
        "If this email belongs to an unverified account, a new verification link has been sent."
    )

    if not user or user.email_verified:
        return EmailVerificationResponse(message=generic_message)

    token = generate_email_verification_token()
    await set_email_verification_token(
        db,
        user.id,
        token,
        expires_in_hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS,
    )

    try:
        send_verification_email(user.username, user.email, token)
    except Exception as e:
        logger.error("Failed to resend verification email to %s: %s", user.email, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send verification email right now"
        )

    return EmailVerificationResponse(
        message=generic_message,
        email=user.email,
    )


@router.get("/public-config", response_model=PublicRuntimeConfig)
async def get_public_runtime_config():
    """Expose safe runtime configuration needed by the frontend settings UI."""
    model_name = settings.OLLAMA_MODEL if settings.USE_OLLAMA else settings.DEFAULT_LLM_MODEL
    return PublicRuntimeConfig(
        llm_provider=_infer_llm_provider(model_name),
        llm_model=model_name,
        temperature=settings.DEFAULT_TEMPERATURE,
        max_tokens=settings.MAX_TOKENS,
        architecture="MCP-based agents",
        orchestration="LangGraph" if settings.USE_LANGGRAPH else "Legacy orchestrator",
        email_verification_enabled=settings.EMAIL_VERIFICATION_ENABLED,
    )


@router.get("/me/usage")
async def get_usage(current_user: User = Depends(get_current_user)):
    """Token usage summary for the authenticated user."""
    db = SessionLocal()
    try:
        rows = db.query(TokenUsage).filter(TokenUsage.user_id == current_user.id).all()

        total_input = sum(r.input_tokens for r in rows)
        total_output = sum(r.output_tokens for r in rows)
        total_queries = len(rows)

        # Per-day breakdown (last 30 days)
        now = time.time()
        cutoff = now - 30 * 86400
        from collections import defaultdict
        import datetime
        daily: dict = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0, "queries": 0})
        for r in rows:
            if r.timestamp >= cutoff:
                day = datetime.datetime.utcfromtimestamp(r.timestamp).strftime("%Y-%m-%d")
                daily[day]["input_tokens"] += r.input_tokens
                daily[day]["output_tokens"] += r.output_tokens
                daily[day]["queries"] += 1

        return {
            "user_id": current_user.id,
            "username": current_user.username,
            "total_queries": total_queries,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "last_30_days": [
                {"date": d, **v} for d, v in sorted(daily.items())
            ],
        }
    finally:
        db.close()


@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Request password reset - generates a reset token
    
    SECURITY WARNING: This is Option 1 (no email). Anyone who knows the email
    can reset the password. Only use for development/internal systems.
    
    Args:
        request: Email address
        
    Returns:
        Reset token (for Option 1 - no email service)
    """
    # Find user by BOTH username AND email (security: requires both pieces of info)
    try:
        user_by_email = await get_user_by_email(db, request.email)
        user_by_username = await get_user_by_username(db, request.username)
        
        logger.info(f"Password reset request - email: {request.email}, username: {request.username}")
        logger.info(f"User by email found: {user_by_email is not None}")
        logger.info(f"User by username found: {user_by_username is not None}")
        
        if user_by_email:
            logger.info(f"  Email user: username={user_by_email.username}, id={user_by_email.id}")
        if user_by_username:
            logger.info(f"  Username user: email={user_by_username.email}, id={user_by_username.id}")
        
        # Verify both username and email match the same user
        if not user_by_email:
            logger.warning(f"No user found with email: {request.email}")
        if not user_by_username:
            logger.warning(f"No user found with username: {request.username}")
        if user_by_email and user_by_username:
            logger.info(f"Comparing IDs: {user_by_email.id} == {user_by_username.id}? {user_by_email.id == user_by_username.id}")
            if user_by_email.id != user_by_username.id:
                logger.warning(f"Username and email belong to different users")
        
        if not user_by_email or not user_by_username or user_by_email.id != user_by_username.id:
            # Don't reveal which part is wrong (security best practice)
            # Return generic message to prevent enumeration
            logger.warning(f"Password reset failed: user_by_email={user_by_email is not None}, user_by_username={user_by_username is not None}, ids_match={user_by_email and user_by_username and user_by_email.id == user_by_username.id}")
            return {
                "message": "If the username and email match an existing account, a reset token would be generated",
                "reset_token": None,
                "expires_in": "1 hour",
                "warning": "This is a development-only feature. In production, use email-based reset."
            }
        
        user = user_by_email  # Use either one, they're the same
    except Exception as e:
        logger.error(f"Error in forgot_password: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing password reset request"
        )
    
    # Generate reset token
    reset_token = generate_reset_token()
    
    # Save token to database (expires in 1 hour)
    await set_password_reset_token(db, user.id, reset_token, expires_in_hours=1)
    
    logger.warning(f"Password reset token generated for user: {user.username} - SECURITY: No email verification!")
    
    # For Option 1: Return token directly (no email)
    # In production with email, you would send email and return success message
    return {
        "message": "Password reset token generated",
        "reset_token": reset_token,
        "expires_in": "1 hour",
        "warning": "⚠️ SECURITY WARNING: This token allows password reset. Keep it secure!",
        "note": "This is a development-only feature. In production, use email-based reset."
    }


@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Reset password using reset token
    
    Args:
        request: Reset token and new password
        
    Returns:
        Success message
    """
    # Find user by valid reset token
    user = await get_user_by_reset_token(db, request.token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    # Update password and clear reset token
    await update_user_password(db, user.id, request.new_password)
    
    logger.info(f"Password reset successful for user: {user.username}")
    
    return {
        "message": "Password reset successfully. You can now login with your new password."
    }
