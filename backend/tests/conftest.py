"""
conftest.py — Shared Test Fixtures
====================================
Pytest fixtures available to all test files without explicit import.

Design:
  - Tests use an in-memory SQLite database (not PostgreSQL) for speed.
  - Each test gets a fresh database session — tests are fully isolated.
  - The application factory is called with a test-specific settings override.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config.settings import Settings
from app.infrastructure.database.models import Base
from app.infrastructure.database.session import get_db_session
from app.main import create_application

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Override settings for the test environment."""
    return Settings(
        app_env="development",
        app_secret_key="test-secret-key-not-for-production",
        app_debug=True,
        public_upload_rate_limit_require_redis=False,
        _env_file=None,  # Do not load .env in tests
    )


@pytest.fixture
async def db_session() -> AsyncSession:
    """
    Create a fresh in-memory SQLite database for each test.

    All tables are created before the test and dropped after.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession, test_settings: Settings) -> AsyncClient:
    """
    Create an HTTPX async test client for the FastAPI application.

    The database dependency is overridden to use the test session.
    """
    app = create_application(settings=test_settings)

    async def override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client
