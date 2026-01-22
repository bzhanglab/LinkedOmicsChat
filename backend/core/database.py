"""
Database configuration and initialization
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker
from core.config import settings
import logging

logger = logging.getLogger(__name__)

# Create base class for declarative models
Base = declarative_base()

# Import models to ensure they're registered with Base
def import_models():
    """Import all models to ensure they're registered"""
    try:
        from models import database  # noqa: F401
        logger.info("Database models imported successfully")
    except ImportError as e:
        logger.warning(f"Could not import database models: {e}")

# Create engine
if settings.DATABASE_URL.startswith("sqlite"):
    # SQLite for development
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=settings.DEBUG
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
else:
    # PostgreSQL for production
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        future=True
    )
    SessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )


async def init_db():
    """Initialize database tables"""
    try:
        # Import models first to register them
        import_models()
        
        if settings.DATABASE_URL.startswith("sqlite"):
            Base.metadata.create_all(bind=engine)
        else:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise


async def get_db():
    """Dependency for getting database session"""
    if settings.DATABASE_URL.startswith("sqlite"):
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    else:
        async with SessionLocal() as session:
            yield session
