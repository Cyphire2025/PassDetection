"""Real in-image helper proof on generated databases and a non-superuser owner."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import runpy
import shutil
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]
BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
SOURCE = "0123_mcp_read_sections"
TARGET = "0124_mcp_device_access"


@pytest.mark.parametrize("control_enabled", [True, False])
async def test_exact_helper_upgrade_rejection_lock_retry_and_target_retry(control_enabled, tmp_path):
    host = os.environ.get("POSTGRES_HOST", "localhost")
    source = os.environ["POSTGRES_DB"]
    if host not in {"localhost", "127.0.0.1", "postgres", "db"} or (
        source != "test_db" and not source.startswith("passdetection_ci_")
    ):
        pytest.fail("Helper proof requires isolated local/CI PostgreSQL")
    suffix = uuid.uuid4().hex[:12]
    name = "passdetection_ci_devices_helper_" + suffix
    owner = "passdetection_ci_devices_owner_" + suffix
    reader = "passdetection_ci_devices_reader_" + suffix
    password = "synthetic-local-helper"
    base_url = URL.create(
        "postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=host,
        port=int(os.environ.get("POSTGRES_PORT", "5432")), database=source,
    )
    admin = create_async_engine(base_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(base_url.set(database=name), poolclass=NullPool)
    environment = {
        **os.environ, "POSTGRES_DB": name, "POSTGRES_USER": owner,
        "POSTGRES_PASSWORD": password, "MCP_READ_ONLY_MODE": "true", "MCP_ENABLED": "false",
        "MCP_ENABLED_CAPABILITIES": '["mcp:read"]', "MCP_RELEASE_PROOF_SHA256": "a" * 64,
    }
    # Retain qualification of the frozen 0124 helper against its own original
    # migration head instead of widening it to the repository's newer release.
    historical = tmp_path / "historical-backend"
    (historical / "scripts").mkdir(parents=True)
    shutil.copyfile(BACKEND / "scripts/apply_mcp_direct_devices_upgrade.py",
                    historical / "scripts/apply_mcp_direct_devices_upgrade.py")
    shutil.copyfile(BACKEND / "alembic.ini", historical / "alembic.ini")
    shutil.copytree(BACKEND / "alembic", historical / "alembic", ignore=lambda _path, names: [
        name for name in names if name[:4].isdigit() and int(name[:4]) > 124
    ])
    environment["PYTHONPATH"] = str(BACKEND)
    definition = runpy.run_path(str(ROOT / "scripts/release_mcp_direct_devices_contract.py"))
    contract = {**copy.deepcopy(definition["POLICY"]), "migrations": [{
        "revision": TARGET, "parent": SOURCE, "path": definition["PATH"],
        "sha256": hashlib.sha256((ROOT / definition["PATH"]).read_bytes()).hexdigest(),
    }]}

    async def process(arguments, *, env=None, cwd=BACKEND):
        child = await asyncio.create_subprocess_exec(
            sys.executable, *arguments, cwd=cwd, env=environment if env is None else env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(child.communicate(), 90)
        return child.returncode, output.decode("utf-8", errors="replace")

    async def helper(value=None, *, env=None):
        return await process([
            "scripts/apply_mcp_direct_devices_upgrade.py", "--contract-json",
            json.dumps(contract if value is None else value),
        ], env=env, cwd=historical)

    async def schema():
        async with engine.connect() as connection:
            return await connection.scalar(text("SELECT version_num FROM alembic_version"))

    async def snapshot():
        result = {}
        async with engine.connect() as connection:
            for table in ("agencies", "users", "mcp_control", "mcp_grants", "mcp_tokens",
                          "mcp_authorization_codes"):
                rows = (await connection.execute(text(
                    f"SELECT row_to_json(record) FROM (SELECT * FROM {table}) record"
                ))).scalars().all()
                if table == "mcp_grants":
                    for row in rows:
                        row.pop("enabled", None)
                        row.pop("device_platform", None)
                result[table] = sorted(json.dumps(row, sort_keys=True) for row in rows)
        return result

    async with admin.connect() as connection:
        for role in (owner, reader):
            await connection.execute(text(
                f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                f"NOREPLICATION PASSWORD '{password}'"
            ))
        await connection.execute(text(f'CREATE DATABASE "{name}" OWNER "{owner}"'))
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'ALTER SCHEMA public OWNER TO "{owner}"'))
        code, output = await process(["-m", "alembic", "upgrade", SOURCE])
        assert code == 0, output[-4000:]
        now, user, grant = datetime.now(UTC), uuid.uuid4(), uuid.uuid4()
        async with engine.begin() as connection:
            await connection.execute(text("""
                INSERT INTO users (id,email,hashed_password,full_name,role,is_active,created_at,updated_at)
                VALUES (:id,'synthetic-helper@example.test','synthetic','Retained account',
                    'super_admin',true,:now,:now)
            """), {"id": user, "now": now})
            await connection.execute(text("""
                INSERT INTO agencies (id,name,email,created_at,updated_at)
                VALUES (:id,'Retained helper agency','synthetic-agency@example.test',:now,:now)
            """), {"id": uuid.uuid4(), "now": now})
            await connection.execute(text("""
                UPDATE mcp_control SET enabled=:enabled,
                    allowed_read_sections='["dashboard","all_groups"]'::jsonb,
                    read_access_revision=7 WHERE id=1
            """), {"enabled": control_enabled})
            await connection.execute(text("""
                INSERT INTO mcp_grants (id,user_id,client_id,name,resource,capabilities,
                    security_version,mfa_at,created_at,expires_at)
                VALUES (:id,:user,'global-connects-desktop','Retained connection',
                    'https://tech.gctravels.com/mcp','["mcp:read"]'::jsonb,
                    1,:now,:now,:expiry)
            """), {"id": grant, "user": user, "now": now, "expiry": now + timedelta(days=7)})
            for index, kind in enumerate(("access", "refresh"), 1):
                await connection.execute(text("""
                    INSERT INTO mcp_tokens (token_hash,grant_id,kind,created_at,expires_at)
                    VALUES (:hash,:grant,:kind,:now,:expiry)
                """), {"hash": str(index) * 64, "grant": grant, "kind": kind,
                       "now": now, "expiry": now + timedelta(minutes=15)})
            await connection.execute(text("""
                INSERT INTO mcp_authorization_codes
                    (code_hash,grant_id,redirect_uri,code_challenge,expires_at)
                VALUES (:hash,:grant,'http://127.0.0.1:8765/callback',:challenge,:expiry)
            """), {"hash": "3" * 64, "grant": grant, "challenge": "x" * 43,
                   "expiry": now + timedelta(minutes=5)})
            await connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{reader}"'))
            await connection.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA public TO "{reader}"'))
        before = await snapshot()
        bad_hash = copy.deepcopy(contract)
        bad_hash["migrations"][0]["sha256"] = "0" * 64
        for label, value, env in (
            ("hash", bad_hash, environment),
            ("proof", contract, {key: value for key, value in environment.items()
                                 if key != "MCP_RELEASE_PROOF_SHA256"}),
            ("writes", contract, {**environment, "MCP_READ_ONLY_MODE": "false"}),
            ("runtime_identity", contract, {**environment, "POSTGRES_USER": reader}),
        ):
            code, output = await helper(value, env=env)
            assert code == 2, (label, output[-4000:])
            assert '"automatic_downgrade":false' in output
            assert await schema() == SOURCE and await snapshot() == before
        # A held source grant writer forces the reviewed five-second DDL lock timeout.
        async with engine.begin() as connection:
            await connection.execute(text("LOCK TABLE mcp_grants IN ROW EXCLUSIVE MODE"))
            code, output = await helper()
            assert code == 2 and "direct_devices_upgrade_failed" in output
            assert await schema() == SOURCE
        assert await snapshot() == before
        code, output = await helper()
        assert code == 0, output[-4000:]
        upgraded = json.loads(output.strip().splitlines()[-1])
        assert upgraded["status"] == "upgraded" and upgraded["authority_preserved"] is True
        assert upgraded["automatic_downgrade"] is False
        assert upgraded["authority"]["mcp_control"]["count"] == 1
        assert upgraded["authority"]["mcp_grants"]["count"] == 1
        assert await schema() == TARGET and await snapshot() == before
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT enabled FROM mcp_grants")) is True
            assert await connection.scalar(text("SELECT device_platform FROM mcp_grants")) is None
            await connection.execute(text(
                "UPDATE mcp_grants SET enabled=false,device_platform='macOS'"
            ))
        # Retry at target preserves decisions made after the original migration.
        code, output = await helper()
        assert code == 0, output[-4000:]
        retry = json.loads(output.strip().splitlines()[-1])
        assert retry["status"] == "already_at_target" and retry["authority_preserved"] is True
        async with engine.connect() as connection:
            assert (await connection.execute(text(
                "SELECT enabled,device_platform FROM mcp_grants"
            ))).one() == (False, "macOS")
            assert await connection.scalar(text("SELECT enabled FROM mcp_control")) is control_enabled
        assert await snapshot() == before
        # A validated same-name CHECK(TRUE) must not masquerade as the target schema.
        async with engine.begin() as connection:
            await connection.execute(text(
                "ALTER TABLE mcp_grants DROP CONSTRAINT ck_mcp_grant_device_platform"
            ))
            await connection.execute(text(
                "ALTER TABLE mcp_grants ADD CONSTRAINT ck_mcp_grant_device_platform CHECK (TRUE)"
            ))
        code, output = await helper()
        assert code == 2 and "direct_devices_upgrade_failed" in output
        assert await schema() == TARGET and await snapshot() == before
        async with engine.connect() as connection:
            assert (await connection.execute(text(
                "SELECT enabled,device_platform FROM mcp_grants"
            ))).one() == (False, "macOS")
        async with engine.begin() as connection:
            await connection.execute(text(
                "ALTER TABLE mcp_grants DROP CONSTRAINT ck_mcp_grant_device_platform"
            ))
            await connection.execute(text("""
                ALTER TABLE mcp_grants ADD CONSTRAINT ck_mcp_grant_device_platform
                CHECK (device_platform IS NULL OR device_platform IN ('Windows','macOS','Other'))
            """))
        code, output = await helper()
        assert code == 0, output[-4000:]
        assert json.loads(output.strip().splitlines()[-1])["status"] == "already_at_target"
        # A stamped foreign schema must fail without returning to 0123 or changing rows.
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE alembic_version SET version_num='0122_mcp_gc_push'"))
        code, output = await helper()
        assert code == 2
        assert await schema() == "0122_mcp_gc_push" and await snapshot() == before
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
            for role in (reader, owner):
                await connection.execute(text(f'DROP ROLE "{role}"'))
        await admin.dispose()
