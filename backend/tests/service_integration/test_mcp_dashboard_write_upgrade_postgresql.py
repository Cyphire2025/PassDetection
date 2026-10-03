"""Real fenced additive helper, full historical data preservation and target drift rejection."""

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.release_source_fixtures import dashboard_write_source

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from release_mcp_dashboard_write_contract import source_contract  # noqa: E402

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


async def test_additive_helper_preserves_all_rows_refuses_held_writer_and_exact_schema_drift(
    tmp_path,
):
    host, port, parent = (
        os.environ["POSTGRES_HOST"],
        int(os.environ["POSTGRES_PORT"]),
        os.environ["POSTGRES_DB"],
    )
    if host not in {"127.0.0.1", "localhost"} or parent not in {"postgres", "test_db"}:
        pytest.fail("Explicit service-integration loopback cluster required")
    name = "passdetection_ci_mixed_" + uuid.uuid4().hex[:12]
    url = URL.create(
        "postgresql+asyncpg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=host,
        port=port,
        database=parent,
    )
    admin = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(url.set(database=name), poolclass=NullPool)
    environment = {
        **os.environ,
        "POSTGRES_DB": name,
        "MCP_ENABLED": "false",
        "MCP_READ_ONLY_MODE": "false",
        "MCP_ENABLED_CAPABILITIES": json.dumps(
            ["mcp:read", "mcp:change", "mcp:upload", "mcp:export", "mcp:communicate"]
        ),
        "MCP_EXPORT_FAMILIES": json.dumps(
            [
                "passport_excel",
                "passport_images",
                "tracking_excel",
                "rooming_excel",
                "document_assignments_excel",
            ]
        ),
        "MCP_EXPORT_SOURCE_ROW_LIMIT": "100",
        "MCP_EXPORT_SOURCE_BYTE_LIMIT": "1048576",
        "MCP_RELEASE_PROOF_SHA256": "d" * 64,
    }
    pinned = dashboard_write_source(ROOT, tmp_path / "pinned-source", executable=True)
    backend = pinned / "backend"
    contract = source_contract(pinned)

    async def command(arguments):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            *arguments,
            cwd=backend,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(process.communicate(), 150)
        return process.returncode, out.decode(errors="replace"), err.decode(errors="replace")

    async def helper():
        code, output, _ = await command(
            [
                "scripts/release_mcp_dashboard_write.py",
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
        code, _, error = await command(["-m", "alembic", "upgrade", "0125_mcp_connection_requests"])
        assert code == 0, error[-1500:]
        now, user, agency, grant, request = (
            datetime.now(UTC),
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
        )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users(id,email,hashed_password,full_name,role,is_active,created_at,updated_at) VALUES(:id,:email,'synthetic','Historical authority','super_admin',true,:now,:now)"
                ),
                {"id": user, "email": f"mixed-{user}@example.test", "now": now},
            )
            await connection.execute(
                text(
                    "INSERT INTO user_security_states(user_id,session_version,credential_state,mfa_secret_ciphertext,mfa_enabled_at) VALUES(:user,1,'active','synthetic',:now)"
                ),
                {"user": user, "now": now},
            )
            await connection.execute(
                text(
                    "INSERT INTO agencies(id,name,email,is_active,created_at,updated_at) VALUES(:id,'Historical agency',:email,true,:now,:now)"
                ),
                {"id": agency, "email": f"agency-{agency}@example.test", "now": now},
            )
            await connection.execute(
                text(
                    "UPDATE mcp_control SET enabled=true,allowed_read_sections='[\"all_groups\"]'::jsonb WHERE id=1"
                )
            )
            await connection.execute(
                text("""INSERT INTO mcp_grants(id,user_id,client_id,name,resource,capabilities,security_version,mfa_at,created_at,expires_at,enabled,device_platform)
                VALUES(:id,:user,'global-connects-desktop','Historical device','http://localhost:8000/mcp','["mcp:read","mcp:export"]'::jsonb,1,:now,:now,:expiry,false,'Windows')"""),
                {"id": grant, "user": user, "now": now, "expiry": now + timedelta(days=1)},
            )
            await connection.execute(
                text(
                    "INSERT INTO mcp_tokens(token_hash,grant_id,kind,created_at,expires_at) VALUES(:hash,:grant,'refresh',:now,:expiry)"
                ),
                {"hash": "a" * 64, "grant": grant, "now": now, "expiry": now + timedelta(days=1)},
            )
            await connection.execute(
                text(
                    "INSERT INTO mcp_authorization_codes(code_hash,grant_id,redirect_uri,code_challenge,expires_at) VALUES(:hash,:grant,'http://127.0.0.1:8765/callback',:challenge,:expiry)"
                ),
                {
                    "hash": "b" * 64,
                    "grant": grant,
                    "challenge": "c" * 43,
                    "expiry": now + timedelta(minutes=5),
                },
            )
            await connection.execute(
                text("""INSERT INTO mcp_connection_requests(id,credential_hash,source_hash,comparison_code,client_id,redirect_uri,resource,oauth_state,code_challenge,
                requested_capabilities,name,device_platform,status,created_at,expires_at) VALUES(:id,:credential,:source,'ABC-12345','global-connects-desktop','http://127.0.0.1:8765/callback',
                'http://localhost:8000/mcp','immutable-state-value',:challenge,'["mcp:read"]'::jsonb,'Historical request','Windows','pending',:now,:expiry)"""),
                {
                    "id": request,
                    "credential": "e" * 64,
                    "source": "f" * 64,
                    "challenge": "c" * 43,
                    "now": now,
                    "expiry": now + timedelta(minutes=10),
                },
            )
        async with engine.connect() as holder:
            await holder.execute(text("UPDATE mcp_control SET enabled=enabled WHERE id=1"))
            failed, receipt = await helper()
            assert failed == 2 and receipt["automatic_downgrade"] is False
            await holder.rollback()
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0125_mcp_connection_requests"
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns WHERE table_name='mcp_grants' AND column_name='write_enabled'"
                    )
                )
                == 0
            )
        code, receipt = await helper()
        assert code == 0 and receipt["status"] == "upgraded", receipt
        assert receipt["new_tables_empty"] is True and receipt["write_defaults_denied"] is True
        assert (
            set(
                (
                    "mcp_control",
                    "mcp_grants",
                    "mcp_tokens",
                    "mcp_authorization_codes",
                    "mcp_connection_requests",
                    "users",
                    "user_security_states",
                    "agencies",
                )
            )
            <= receipt["authority"].keys()
        )
        assert receipt["authority"]["mcp_connection_requests"]["count"] == 1
        code, retry = await helper()
        assert (
            code == 0
            and retry["status"] == "already_at_target"
            and retry["authority"] == receipt["authority"]
        )
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE mcp_native_transfers DROP CONSTRAINT ck_mcp_native_transfer_lane")
            )
            await connection.execute(
                text(
                    "ALTER TABLE mcp_native_transfers ADD CONSTRAINT ck_mcp_native_transfer_lane CHECK (true)"
                )
            )
        assert (await helper())[0] == 2
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE mcp_native_transfers DROP CONSTRAINT ck_mcp_native_transfer_lane")
            )
            await connection.execute(
                text(
                    "ALTER TABLE mcp_native_transfers ADD CONSTRAINT ck_mcp_native_transfer_lane "
                    + "CHECK ((kind='upload_workbook' AND purpose IN ('contact_broadcast','group_workbook')) OR (kind='upload_pdf' AND purpose='document_pdf') OR (kind='download' AND purpose='export'))"
                )
            )
            await connection.execute(
                text("ALTER TABLE mcp_grants ALTER COLUMN write_enabled SET DEFAULT true")
            )
        assert (await helper())[0] == 2
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE mcp_grants ALTER COLUMN write_enabled SET DEFAULT false")
            )
            await connection.execute(text("UPDATE mcp_control SET write_enabled=true WHERE id=1"))
        assert (await helper())[0] == 2
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE mcp_control SET write_enabled=false WHERE id=1"))
        result, receipt = await helper()
        assert result == 0, receipt
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"),
                {"name": name},
            )
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await admin.dispose()
