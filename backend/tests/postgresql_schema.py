"""Build complete ORM fixtures without exposing migrated application tables."""

from __future__ import annotations

import os
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.database.models import Base


async def create_isolated_postgresql_tables(connection: AsyncConnection, schema: str) -> None:
    database = await connection.scalar(text("SELECT current_database()"))
    assert os.getenv("RUN_SERVICE_INTEGRATION") == "1"
    assert database in {os.environ.get("POSTGRES_DB"), os.environ.get("FCM_TEST_POSTGRES_DB")}
    assert database == "test_db" or database.startswith("passdetection_ci_")
    assert re.fullmatch(r"(?:receipt_test_|fcm_dispatch_test_|manual_review_)[0-9a-f]{32}", schema)
    assert await connection.scalar(text("SELECT current_schema()")) == schema
    assert not await connection.scalar(text(
        "SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=:schema)"), {"schema": schema})
    previous_path = await connection.scalar(text("SHOW search_path"))
    await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public"))
    assert await connection.scalar(text(
        "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace "
        "WHERE e.extname='pg_trgm'")) == "public"
    try:
        # The extension's GIN operator class is public. Include it only while
        # creating the new schema's tables; ordinary fixture queries retain
        # UUID-only search_path and cannot fall through to application tables.
        await connection.execute(text("SELECT set_config('search_path', :path, true)"),
                                 {"path": f'"{schema}", public'})
        async with connection.begin_nested():
            # Default checkfirst would see existing public tables and silently
            # omit fixture tables. The explicit empty-schema guard above makes
            # unconditional creation safe and proves every table is isolated.
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, checkfirst=False))
    finally:
        # The savepoint rolls back a failed DDL statement before this reset.
        await connection.execute(text("SELECT set_config('search_path', :path, true)"),
                                 {"path": previous_path})
    tables = set(await connection.scalars(text(
        "SELECT tablename FROM pg_tables WHERE schemaname=:schema"), {"schema": schema}))
    assert tables == set(Base.metadata.tables)
    assert await connection.scalar(text("SHOW search_path")) == previous_path
