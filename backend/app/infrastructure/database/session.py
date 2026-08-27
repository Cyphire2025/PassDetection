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
from typing import Protocol, cast

from sqlalchemy import event
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config.settings import DatabaseSettings, get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.observability.metrics import metrics

logger = get_logger(__name__)

_settings = get_settings()
_database_settings = _settings.database


def _postgres_server_settings(database: DatabaseSettings) -> dict[str, str]:
    """Deadlines applied by asyncpg whenever a physical connection is opened."""

    return {
        "statement_timeout": str(database.statement_timeout_ms),
        "lock_timeout": str(database.lock_timeout_ms),
        "idle_in_transaction_session_timeout": str(
            database.idle_in_transaction_session_timeout_ms
        ),
    }

# ── Engine ────────────────────────────────────────────────────────────────────

engine = create_async_engine(
    _database_settings.async_url,
    echo=_settings.app_debug,
    pool_size=_database_settings.pool_size,
    max_overflow=_database_settings.max_overflow,
    pool_timeout=_database_settings.pool_timeout_seconds,
    pool_pre_ping=True,
    pool_recycle=_database_settings.pool_recycle_seconds,
    connect_args={"server_settings": _postgres_server_settings(_database_settings)},
)


class _QueuePoolMetrics(Protocol):
    """The queue-pool counters exposed by SQLAlchemy's concrete pool."""

    def checkedout(self) -> int: ...

    def checkedin(self) -> int: ...

    def overflow(self) -> int: ...


def _queue_pool_metrics() -> _QueuePoolMetrics:
    return cast(_QueuePoolMetrics, engine.sync_engine.pool)


def _record_pool_state() -> None:
    pool = _queue_pool_metrics()
    metrics.set_gauge("database.pool.checked_out", float(pool.checkedout()))
    metrics.set_gauge("database.pool.checked_in", float(pool.checkedin()))
    metrics.set_gauge("database.pool.overflow", float(pool.overflow()))


@event.listens_for(engine.sync_engine, "checkout")
def _on_pool_checkout(*_: object) -> None:
    metrics.increment("database.pool.checkouts")
    _record_pool_state()


@event.listens_for(engine.sync_engine, "checkin")
def _on_pool_checkin(*_: object) -> None:
    metrics.increment("database.pool.checkins")
    _record_pool_state()


@event.listens_for(engine.sync_engine, "invalidate")
def _on_pool_invalidate(*_: object) -> None:
    metrics.increment("database.pool.invalidations")


def _database_pool_snapshot() -> dict[str, str | int | float]:
    pool = _queue_pool_metrics()
    return {
        "profile": _database_settings.pool_profile,
        "configured_pool_size": _database_settings.pool_size,
        "configured_max_overflow": _database_settings.max_overflow,
        "configured_pool_timeout_seconds": _database_settings.pool_timeout_seconds,
        "checked_out": pool.checkedout(),
        "checked_in": pool.checkedin(),
        "overflow": pool.overflow(),
    }


metrics.register_snapshot_provider("database_pool", _database_pool_snapshot)

# ── Session Factory ───────────────────────────────────────────────────────────

AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Entities remain accessible after commit
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
        except SQLAlchemyTimeoutError:
            metrics.increment("database.pool.checkout_timeouts")
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
