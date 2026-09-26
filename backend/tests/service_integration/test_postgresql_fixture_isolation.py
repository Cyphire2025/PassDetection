"""Prove fixture setup cannot reuse application tables or leak its search path."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.infrastructure.database.models import Base
from tests.postgresql_schema import create_isolated_postgresql_tables
from tests.service_integration.test_whatsapp_receipts_postgresql import pg_url

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]


async def test_fixture_setup_rejects_application_and_nonempty_schemas():
    engine = create_async_engine(pg_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            async with connection.begin() as transaction:
                with pytest.raises(AssertionError):
                    await create_isolated_postgresql_tables(connection, "public")
                schema = "receipt_test_" + uuid.uuid4().hex
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text("SELECT set_config('search_path', :schema, true)"), {"schema": schema})
                await connection.execute(text("CREATE TABLE existing_fixture (id integer)"))
                with pytest.raises(AssertionError):
                    await create_isolated_postgresql_tables(connection, schema)
                assert await connection.scalar(text("SELECT current_schema()")) == schema
                await transaction.rollback()
    finally:
        await engine.dispose()


async def test_failed_fixture_ddl_restores_path_and_rolls_back_partial_tables(monkeypatch):
    def fail_after_create(connection, *, checkfirst):
        assert checkfirst is False
        connection.execute(text("CREATE TABLE partial_fixture (id integer)"))
        connection.execute(text("SELECT nonexistent_fixture_column FROM partial_fixture"))

    monkeypatch.setattr(Base.metadata, "create_all", fail_after_create)
    engine = create_async_engine(pg_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            async with connection.begin() as transaction:
                schema = "receipt_test_" + uuid.uuid4().hex
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text("SELECT set_config('search_path', :schema, true)"), {"schema": schema})
                with pytest.raises(DBAPIError):
                    await create_isolated_postgresql_tables(connection, schema)
                assert await connection.scalar(text("SHOW search_path")) == schema
                assert await connection.scalar(text("SELECT to_regclass('partial_fixture')")) is None
                assert await connection.scalar(text("SELECT current_schema()")) == schema
                await transaction.rollback()
    finally:
        await engine.dispose()
