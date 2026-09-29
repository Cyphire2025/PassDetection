"""Rehearse new MCP tables under existing migration-role default privileges.

Every run owns a fresh, retained synthetic database and two unique roles on the
explicit local/CI cluster. No production endpoint or existing database is edited.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.infrastructure.database.role_policy import RUNTIME_ROLE_QUERY, require_runtime_role

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]
BACKEND = Path(__file__).resolve().parents[2]
HEAD = json.loads((BACKEND / "app/core/config/release_manifest.json").read_text())["schema_revision"]


async def test_existing_default_privileges_cover_mcp_upgrade_and_protected_rows():
    host, source = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"localhost", "127.0.0.1", "postgres", "db"} or (
        source != "test_db" and not source.startswith("passdetection_ci_")
    ):
        pytest.fail("Role migration proof requires an isolated local/CI PostgreSQL cluster")
    suffix = uuid.uuid4().hex[:12]
    name = "passdetection_ci_mcp_roles_" + suffix
    runtime, migrator = "mcp_runtime_" + suffix, "mcp_migrator_" + suffix
    environment = {
        **os.environ, "POSTGRES_DB": name,
        "POSTGRES_RUNTIME_USER": runtime, "POSTGRES_MIGRATION_USER": migrator,
        "POSTGRES_RUNTIME_PASSWORD": "synthetic-runtime-" + suffix,
        "POSTGRES_MIGRATION_PASSWORD": "synthetic-migration-" + suffix,
        "APP_SECRET_KEY": "isolated-role-migration-test-not-production",
    }
    url = URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=host,
        port=int(os.environ.get("POSTGRES_PORT", "5432")), database=source)
    admin = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    runtime_engine = create_async_engine(url.set(database=name, username=runtime,
        password=environment["POSTGRES_RUNTIME_PASSWORD"]), poolclass=NullPool)

    async def command(*arguments: str, migration_identity: bool = False) -> None:
        child_env = dict(environment)
        if migration_identity:
            child_env.update(POSTGRES_USER=migrator,
                             POSTGRES_PASSWORD=environment["POSTGRES_MIGRATION_PASSWORD"])
        process = await asyncio.create_subprocess_exec(
            sys.executable, *arguments, cwd=BACKEND, env=child_env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        output, _ = await asyncio.wait_for(process.communicate(), 120)
        assert process.returncode == 0, output.decode("utf-8", errors="replace")[-4000:]

    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
        await command("-m", "alembic", "upgrade", "head")
        # The existing role qualifier requires the current full model inventory.
        # Provision it first; then return this otherwise empty MCP schema to the
        # exact source revision while retaining the configured roles/defaults.
        await command("scripts/qualify_database_roles.py")
        await command("-m", "alembic", "downgrade", "0113_document_follow_up",
                      migration_identity=True)
        async with runtime_engine.connect() as connection:
            before = (await connection.execute(text(
                "SELECT row_to_json(a) FROM (SELECT * FROM agencies ORDER BY id) a"
            ))).scalars().all()
            assert len(before) == 1 and before[0]["name"] == "runtime CRUD verified"
            assert await connection.scalar(text("SELECT to_regclass('public.mcp_control')")) is None
            require_runtime_role((await connection.execute(text(RUNTIME_ROLE_QUERY))).one())

        # Crucially, do not reprovision or issue any GRANT after this upgrade.
        await command("-m", "alembic", "upgrade", "head", migration_identity=True)
        async with runtime_engine.begin() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            assert (await connection.execute(text(
                "SELECT row_to_json(a) FROM (SELECT * FROM agencies ORDER BY id) a"
            ))).scalars().all() == before
            require_runtime_role((await connection.execute(text(RUNTIME_ROLE_QUERY))).one())
            tables = (await connection.execute(text("""
                SELECT c.relname, pg_get_userbyid(c.relowner),
                  has_table_privilege(current_user,c.oid,'SELECT'),
                  has_table_privilege(current_user,c.oid,'INSERT'),
                  has_table_privilege(current_user,c.oid,'UPDATE'),
                  has_table_privilege(current_user,c.oid,'DELETE'),
                  has_table_privilege(current_user,c.oid,'TRUNCATE')
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind='r'
                  AND (c.relname LIKE 'mcp_%' OR c.relname='whatsapp_send_intents')
                ORDER BY c.relname
            """))).all()
            assert len(tables) >= 16
            assert {row[0] for row in tables} >= {"mcp_gc_push_plans", "mcp_gc_push_origins",
                "mcp_artifacts", "mcp_whatsapp_outbox", "whatsapp_send_intents"}
            for table, owner, can_read, can_insert, can_update, can_delete, can_truncate in tables:
                assert owner == migrator, table
                assert all((can_read, can_insert, can_update, can_delete)), table
                assert not can_truncate, table
                await connection.execute(text(f'SELECT 1 FROM "{table}" LIMIT 1'))
            assert await connection.scalar(text("SELECT enabled FROM mcp_control WHERE id=1")) is False
            await connection.execute(text("UPDATE mcp_control SET updated_at=updated_at WHERE id=1"))
            await connection.execute(text("""
                INSERT INTO audit_logs(id,action,entity_type,created_at)
                VALUES (:id,'mcp.role_migration_qualification','synthetic',now())
            """), {"id": uuid.uuid4()})
            assert await connection.scalar(text("SELECT count(*) FROM audit_logs")) == 2
    finally:
        await runtime_engine.dispose()
        await admin.dispose()
        # Retain this run's synthetic rows, database and unique roles for review.
