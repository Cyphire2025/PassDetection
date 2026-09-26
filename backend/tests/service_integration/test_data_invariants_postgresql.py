"""Actual PostgreSQL constraint failures, never metadata.create_all substitutes."""

import os

import pytest
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.data_invariants import CASES, assert_data_invariant

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]


@pytest.mark.parametrize("case", CASES)
async def test_migrated_tenant_and_ecr_constraints(case: str) -> None:
    database = os.environ["POSTGRES_DB"]
    if database != "test_db" and not database.startswith("passdetection_ci_"):
        pytest.fail("An isolated CI database must be explicitly selected")
    url = URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
                     password=os.environ["POSTGRES_PASSWORD"], database=database,
                     host=os.environ.get("POSTGRES_HOST", "localhost"),
                     port=int(os.environ.get("POSTGRES_PORT", "5432")))
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert await connection.scalar(text("SELECT current_database()")) == database
                assert await connection.scalar(text("SELECT convalidated FROM pg_constraint "
                    "WHERE conname = 'fk_passport_submissions_group_agency'")) is True
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    await assert_data_invariant(session, case)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
