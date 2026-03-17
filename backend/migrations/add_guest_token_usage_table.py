"""
Database migration: Add guest_token_usage table

Tracks per-query LLM token consumption for unauthenticated (guest) users,
keyed by IP address instead of user ID.

Run:
    python migrations/add_guest_token_usage_table.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text, inspect
from core.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def table_exists(engine, name: str) -> bool:
    return inspect(engine).has_table(name)


def apply_migration():
    logger.info("Starting migration: add guest_token_usage table")
    engine = create_engine(settings.DATABASE_URL)

    try:
        with engine.connect() as conn:
            if not table_exists(engine, "guest_token_usage"):
                logger.info("Creating guest_token_usage table...")
                conn.execute(text("""
                    CREATE TABLE guest_token_usage (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        ip_address    TEXT NOT NULL,
                        input_tokens  INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        model         TEXT,
                        timestamp     REAL NOT NULL
                    )
                """))
                conn.execute(text("CREATE INDEX idx_guest_token_ip ON guest_token_usage (ip_address)"))
                conn.execute(text("CREATE INDEX idx_guest_token_ts ON guest_token_usage (timestamp)"))
                conn.commit()
                logger.info("✓ guest_token_usage table created")
            else:
                logger.info("guest_token_usage table already exists — skipping")

    except Exception as e:
        logger.error(f"✗ Migration failed: {e}")
        raise
    finally:
        engine.dispose()

    logger.info("Migration complete.")


if __name__ == "__main__":
    apply_migration()
