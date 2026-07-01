"""
Database Session Factory
========================
Manages the async SQLAlchemy engine and session lifecycle.

Design:
  - Single engine per process (created at startup).
  - Sessions are created per-request via FastAPI's dependency injection.
  - Async sessions ensure no blocking I/O on database calls.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

_settings = get_settings()

# ── Engine ────────────────────────────────────────────────────────────────────

engine = create_async_engine(
    _settings.database.async_url,
    echo=_settings.app_debug,        # Log SQL queries in debug mode
    pool_size=20,                    # Base pool size
    max_overflow=10,                 # Allow 10 extra connections under load
    pool_pre_ping=True,              # Verify connections before use
    pool_recycle=3600,               # Recycle connections every hour
)

# ── Session Factory ───────────────────────────────────────────────────────────

AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,     # Entities remain accessible after commit
    autocommit=False,
    autoflush=False,
)


# ── FastAPI Dependency ────────────────────────────────────────────────────────

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a database session for each request.

    Usage in route handlers:

        @router.get("/example")
        async def handler(db: AsyncSession = Depends(get_db_session)):
            ...

    The session is committed on success and rolled back on exception.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
