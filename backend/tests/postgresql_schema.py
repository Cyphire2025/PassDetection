"""Build complete ORM fixtures without exposing migrated application tables."""

from __future__ import annotations

import os
import re
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.database.models import Base


async def seed_legacy_mcp_role_policy(
    connection: AsyncConnection, *, database: str, runtime: str, migrator: str,
    runtime_password: str, migration_password: str,
) -> None:
    """Build only this generated 0113 fixture's historical role/default policy."""
    assert os.getenv("RUN_SERVICE_INTEGRATION") == "1"
    assert re.fullmatch(r"passdetection_ci_mcp_roles_[0-9a-f]{12}", database)
    assert re.fullmatch(r"mcp_runtime_[0-9a-f]{12}", runtime)
    assert re.fullmatch(r"mcp_migrator_[0-9a-f]{12}", migrator)
    assert await connection.scalar(text("SELECT current_database()")) == database
    assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == "0113_document_follow_up"
    assert await connection.scalar(text("SELECT to_regclass('public.mcp_control')")) is None
    for role, password in ((runtime, runtime_password), (migrator, migration_password)):
        ddl = await connection.scalar(text(
            "SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOREPLICATION NOBYPASSRLS PASSWORD %L', CAST(:role AS text), CAST(:password AS text))"
        ), {"role": role, "password": password})
        await connection.execute(text(ddl))
    relations = (await connection.execute(text(
        "SELECT c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind IN ('r','S') ORDER BY CASE WHEN c.relkind='S' THEN 1 ELSE 0 END,c.relname"
    ))).all()
    for name, kind in relations:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name)
        relation = "SEQUENCE" if kind == "S" else "TABLE"
        await connection.execute(text(f'ALTER {relation} public."{name}" OWNER TO "{migrator}"'))
    enum_names = await connection.scalars(text(
        "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
        "WHERE n.nspname='public' AND t.typtype IN ('e','d')"
    ))
    for name in enum_names:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name)
        await connection.execute(text(f'ALTER TYPE public."{name}" OWNER TO "{migrator}"'))
    for statement in (
        f'ALTER DATABASE "{database}" OWNER TO "{migrator}"',
        f'ALTER SCHEMA public OWNER TO "{migrator}"',
        f'ALTER FUNCTION public.reject_audit_log_mutation() OWNER TO "{migrator}"',
        f'REVOKE CREATE ON DATABASE "{database}" FROM PUBLIC',
        'REVOKE CREATE ON SCHEMA public FROM PUBLIC',
        f'GRANT CONNECT ON DATABASE "{database}" TO "{runtime}"',
        f'GRANT USAGE ON SCHEMA public TO "{runtime}"',
        f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO "{runtime}"',
        f'GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO "{runtime}"',
        f'ALTER DEFAULT PRIVILEGES FOR ROLE "{migrator}" IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO "{runtime}"',
        f'ALTER DEFAULT PRIVILEGES FOR ROLE "{migrator}" IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO "{runtime}"',
        f'REVOKE ALL ON public.alembic_version FROM "{runtime}",PUBLIC',
        f'GRANT SELECT ON public.alembic_version TO "{runtime}"',
        f'REVOKE UPDATE,DELETE,TRUNCATE ON public.audit_logs FROM "{runtime}",PUBLIC',
    ):
        await connection.execute(text(statement))
    await connection.execute(text(f'SET LOCAL ROLE "{runtime}"'))
    await connection.execute(text(
        "INSERT INTO agencies(id,name,email,created_at,updated_at) "
        "VALUES (:id,'runtime CRUD verified',:email,now(),now())"
    ), {"id": uuid.uuid4(), "email": f"{uuid.uuid4()}@example.test"})
    await connection.execute(text(
        "INSERT INTO audit_logs(id,action,entity_type,created_at) VALUES (:id,'qualification','synthetic',now())"
    ), {"id": uuid.uuid4()})
    await connection.execute(text("RESET ROLE"))


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
