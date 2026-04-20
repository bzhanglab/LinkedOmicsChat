"""
Database configuration and initialization
"""
from sqlalchemy import create_engine, text
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
    # PostgreSQL for production (async)
    # Convert postgresql:// to postgresql+asyncpg:// for async driver
    async_db_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(
        async_db_url,
        echo=settings.DEBUG,
        future=True
    )
    SessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )


def _run_sqlite_migrations(conn):
    """Add any missing columns to existing SQLite tables."""
    cursor = conn.cursor()
    changed = False

    cursor.execute("PRAGMA table_info(chat_sessions)")
    existing = {row[1] for row in cursor.fetchall()}
    if "shared_token" not in existing:
        # SQLite doesn't allow ADD COLUMN with UNIQUE — add column then create index
        cursor.execute("ALTER TABLE chat_sessions ADD COLUMN shared_token VARCHAR")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_chat_sessions_shared_token ON chat_sessions (shared_token)")
        logger.info("Migration: added shared_token column to chat_sessions")
        changed = True

    cursor.execute("PRAGMA table_info(users)")
    existing = {row[1] for row in cursor.fetchall()}
    if "email_verified" not in existing:
        cursor.execute("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 1")
        logger.info("Migration: added email_verified column to users")
        changed = True
    if "email_verification_token" not in existing:
        cursor.execute("ALTER TABLE users ADD COLUMN email_verification_token VARCHAR")
        logger.info("Migration: added email_verification_token column to users")
        changed = True
    if "email_verification_expires" not in existing:
        cursor.execute("ALTER TABLE users ADD COLUMN email_verification_expires FLOAT")
        logger.info("Migration: added email_verification_expires column to users")
        changed = True
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_users_email_verification_token ON users (email_verification_token)")

    if changed:
        conn.commit()


async def _run_postgres_migrations(conn):
    """Add any missing columns to existing PostgreSQL tables."""
    changed = False

    result = await conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'chat_sessions'"
        )
    )
    chat_session_columns = {row[0] for row in result.fetchall()}
    if "shared_token" not in chat_session_columns:
        await conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN shared_token VARCHAR"))
        logger.info("Migration: added shared_token column to chat_sessions")
        changed = True
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_chat_sessions_shared_token "
            "ON chat_sessions (shared_token)"
        )
    )

    result = await conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'users'"
        )
    )
    user_columns = {row[0] for row in result.fetchall()}
    if "email_verified" not in user_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT TRUE"))
        logger.info("Migration: added email_verified column to users")
        changed = True
    if "email_verification_token" not in user_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN email_verification_token VARCHAR"))
        logger.info("Migration: added email_verification_token column to users")
        changed = True
    if "email_verification_expires" not in user_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN email_verification_expires DOUBLE PRECISION"))
        logger.info("Migration: added email_verification_expires column to users")
        changed = True
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_users_email_verification_token "
            "ON users (email_verification_token)"
        )
    )

    if changed:
        logger.info("PostgreSQL schema migrations applied successfully")


async def init_db():
    """Initialize database tables"""
    try:
        # Import models first to register them
        import_models()

        if settings.DATABASE_URL.startswith("sqlite"):
            Base.metadata.create_all(bind=engine)
            with engine.connect() as conn:
                _run_sqlite_migrations(conn.connection)
        else:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await _run_postgres_migrations(conn)
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
