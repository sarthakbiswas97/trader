"""
Database connection and session management.

Uses SQLAlchemy with sync driver (psycopg2) for simplicity.
Neon Postgres connection via DATABASE_URL.
"""

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.core.logger import get_logger
from backend.db.models import Base

logger = get_logger(__name__)

# Create engine — use pool_pre_ping for Neon's serverless reconnects
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def create_tables():
    """Create all tables (idempotent — safe to call repeatedly)."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")


@contextmanager
def get_session() -> Session:
    """Get a database session with automatic commit/rollback."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session() -> Session:
    """Get a raw session (caller manages lifecycle)."""
    return SessionLocal()
