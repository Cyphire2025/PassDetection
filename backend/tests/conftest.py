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

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Deterministic Ed25519 fixture material used only by the isolated test process.
# Production and staging must inject independent keys through their secret manager.
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("POSTGRES_PASSWORD", "test-database-password")
os.environ.setdefault("S3_ACCESS_KEY_ID", "test-storage-access-key")
os.environ.setdefault("S3_SECRET_ACCESS_KEY", "test-storage-secret-key")
os.environ.setdefault("MOBILE_OFFLINE_LEASE_ACTIVE_KID", "unit-test-2026-01")
os.environ.setdefault(
    "MOBILE_OFFLINE_LEASE_PRIVATE_KEY_B64",
    "MC4CAQAwBQYDK2VwBCIEIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8g",
)
os.environ.setdefault(
    "MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON",
    '{"unit-test-2026-01":"ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ"}',
)

from app.core.config.settings import Settings  # noqa: E402
from app.infrastructure.database.models import Base  # noqa: E402
from app.infrastructure.database.session import get_db_session  # noqa: E402
from app.main import create_application  # noqa: E402
from tests.sqlite_trip_timezone import register_sqlite_trip_timezone  # noqa: E402

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Override settings for the test environment."""
    return Settings(
        app_env="development",
        app_secret_key="test-secret-key-not-for-production",
        app_debug=True,
        login_lockout_require_redis=False,
        dashboard_rate_limit_require_redis=False,
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
        await register_sqlite_trip_timezone(session)
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
    app = create_application(
        settings=test_settings,
        initialize_rate_limit_redis=False,
    )

    async def override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client
