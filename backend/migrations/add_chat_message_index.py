"""
Database migration: Add composite index for chat_messages

This migration adds a composite index on (session_id, timestamp) to the
chat_messages table to optimize pagination queries when loading chat history.

Run this script to apply the migration to your existing database:
    python migrations/add_chat_message_index.py
"""
import sys
import os
from pathlib import Path

# Add parent directory to path to import from backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text, inspect
from core.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_index_exists(engine, table_name: str, index_name: str) -> bool:
    """Check if an index already exists"""
    inspector = inspect(engine)
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def apply_migration():
    """Apply the migration to add composite index"""
    logger.info("Starting migration: Add composite index to chat_messages")
    logger.info(f"Database URL: {settings.DATABASE_URL}")
    
    # Create engine
    engine = create_engine(settings.DATABASE_URL)
    
    try:
        # Check if index already exists
        if check_index_exists(engine, 'chat_messages', 'idx_session_timestamp'):
            logger.info("Index 'idx_session_timestamp' already exists. Skipping migration.")
            return
        
        # Create the index
        logger.info("Creating composite index on (session_id, timestamp)...")
        with engine.connect() as conn:
            # SQLite and PostgreSQL both support this syntax
            conn.execute(text(
                "CREATE INDEX idx_session_timestamp ON chat_messages (session_id, timestamp)"
            ))
            conn.commit()
        
        logger.info("✓ Migration completed successfully!")
        logger.info("Index 'idx_session_timestamp' created on chat_messages table")
        
        # Verify the index was created
        if check_index_exists(engine, 'chat_messages', 'idx_session_timestamp'):
            logger.info("✓ Index verified successfully")
        else:
            logger.warning("⚠ Index creation may have failed - please verify manually")
            
    except Exception as e:
        logger.error(f"✗ Migration failed: {e}")
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    apply_migration()
