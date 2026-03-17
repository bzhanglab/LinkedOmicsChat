"""
Database migration: Add token_usage table

Tracks per-query LLM token consumption for registered users.
Also drops the unused workflow_executions table if present.

Run:
    python migrations/add_token_usage_table.py
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
    logger.info("Starting migration: add token_usage table")
    engine = create_engine(settings.DATABASE_URL)

    try:
        with engine.connect() as conn:
            # Create token_usage table
            if not table_exists(engine, "token_usage"):
                logger.info("Creating token_usage table...")
                conn.execute(text("""
                    CREATE TABLE token_usage (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        session_id  TEXT,
                        input_tokens  INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        model       TEXT,
                        timestamp   REAL NOT NULL
                    )
                """))
                conn.execute(text("CREATE INDEX idx_token_usage_user ON token_usage (user_id)"))
                conn.execute(text("CREATE INDEX idx_token_usage_session ON token_usage (session_id)"))
                conn.commit()
                logger.info("✓ token_usage table created")
            else:
                logger.info("token_usage table already exists — skipping")

            # Drop dead workflow_executions table if still present
            if table_exists(engine, "workflow_executions"):
                logger.info("Dropping unused workflow_executions table...")
                conn.execute(text("DROP TABLE workflow_executions"))
                conn.commit()
                logger.info("✓ workflow_executions table dropped")

    except Exception as e:
        logger.error(f"✗ Migration failed: {e}")
        raise
    finally:
        engine.dispose()

    logger.info("Migration complete.")


if __name__ == "__main__":
    apply_migration()
