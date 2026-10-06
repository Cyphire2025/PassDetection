"""Isolated 0128→0129 proof with live authority and inherited runtime privileges."""

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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from release_travel_tracker_contract import source_contract  # noqa: E402

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


async def test_tracker_helper_preserves_authority_and_refuses_schema_or_grant_drift():
    host, parent = os.environ["POSTGRES_HOST"], os.environ["POSTGRES_DB"]
    if host not in {"localhost", "127.0.0.1"} or parent not in {
        "postgres", "test_db", "passdetection_ci_services",
    }:
        pytest.fail("Explicit service-integration loopback cluster required")
    name = "passdetection_ci_tracker_" + uuid.uuid4().hex[:12]
    url = URL.create(
        "postgresql+asyncpg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=host,
        port=int(os.environ["POSTGRES_PORT"]),
        database=parent,
    )
    admin = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(url.set(database=name), poolclass=NullPool)
    environment = {**os.environ, "POSTGRES_DB": name, "MCP_RELEASE_PROOF_SHA256": "d" * 64}
    contract = source_contract(ROOT)

    async def command(arguments):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            *arguments,
            cwd=ROOT / "backend",
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(process.communicate(), 150)
        return process.returncode, out.decode(errors="replace"), err.decode(errors="replace")

    async def helper():
        code, output, _ = await command(
            [
                "scripts/release_travel_tracker_upgrade.py",
                "--contract-json",
                json.dumps(contract, sort_keys=True, separators=(",", ":")),
            ]
        )
        return code, json.loads(output.strip().splitlines()[-1])

    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        async with engine.begin() as connection:
            owner = connection.dialect.identifier_preparer.quote_identifier(
                os.environ["POSTGRES_USER"]
            )
            await connection.execute(text(f"ALTER SCHEMA public OWNER TO {owner}"))
            # These synthetic defaults affect only this disposable database.
            await connection.execute(
                text(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO PUBLIC"
                )
            )
        code, _, error = await command(["-m", "alembic", "upgrade", "0128_mcp_document_delivery"])
        assert code == 0, error[-1500:]
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE mcp_control SET enabled=true,read_enabled=false,write_enabled=true,allowed_read_sections='[\"all_groups\"]'::jsonb,allowed_write_sections='[\"docs\"]'::jsonb,allowed_write_tools='[\"travel_tracker.mark\"]'::jsonb,read_access_revision=7 WHERE id=1"
                )
            )
        async with engine.connect() as holder:
            await holder.execute(
                text("LOCK TABLE public.passport_submissions IN ACCESS EXCLUSIVE MODE")
            )
            code, failed = await helper()
            assert code == 2 and failed["automatic_downgrade"] is False
            await holder.rollback()
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0128_mcp_document_delivery"
            )
            assert (
                await connection.scalar(text("SELECT to_regclass('public.travel_tracker')")) is None
            )
        code, receipt = await helper()
        assert code == 0, receipt
        assert receipt["status"] == "upgraded" and receipt["authority_preserved"] is True
        assert receipt["runtime_grants_verified"] is True and receipt["new_tables_empty"] is True
        code, retry = await helper()
        assert code == 0 and retry["status"] == "already_at_target"
        assert retry["authority"] == receipt["authority"]
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT write_enabled AND NOT read_enabled AND read_access_revision=7 FROM mcp_control WHERE id=1"
                    )
                )
                is True
            )
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE travel_tracker ALTER COLUMN visa_applied SET DEFAULT true")
            )
        assert (await helper())[0] == 2
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE travel_tracker ALTER COLUMN visa_applied SET DEFAULT false")
            )
            await connection.execute(text("REVOKE DELETE ON public.travel_tracker FROM PUBLIC"))
        assert (await helper())[0] == 2
        async with engine.begin() as connection:
            await connection.execute(text("GRANT DELETE ON public.travel_tracker TO PUBLIC"))
        assert (await helper())[0] == 0
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"),
                {"name": name},
            )
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await admin.dispose()
