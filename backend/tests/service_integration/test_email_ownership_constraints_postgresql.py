"""Same negative inserts against actual Alembic-migrated PostgreSQL constraints."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.email_ownership_constraints import CASES, assert_email_parent_constraint

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"),
]


@pytest.mark.parametrize("case", CASES)
async def test_email_parent_scope_is_enforced_by_migrated_postgresql(case: str) -> None:
    database = os.environ["POSTGRES_DB"]
    # test_db is the fixed GitHub Actions service DB; local qualification uses
    # explicitly prefixed synthetic databases. Never use a production database.
    if database != "test_db" and not database.startswith("passdetection_ci_"):
        pytest.fail("An isolated CI PostgreSQL database must be explicitly selected")
    url = URL.create(
        "postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")), database=database,
    )
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert await connection.scalar(text("SELECT current_database()")) == database
                assert await connection.scalar(text("SELECT count(*) FROM alembic_version")) == 1
                # Do not create ORM tables here: the deployed migration must
                # contain and enforce the same composite boundary as SQLite.
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    await assert_email_parent_constraint(session, case)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
