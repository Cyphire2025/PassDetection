"""Qualify 0123→0124 retention and paused refresh using a disposable local DB.

This lane refuses remote hosts and business database names, creates only a
generated test database, and never alters its administrative source database.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import URL, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError, new_credential, pkce_challenge
from app.core.config.mcp import MCPSettings
from app.infrastructure.database.mcp_models import MCPGrantModel, MCPTokenModel
from app.infrastructure.database.models import AgencyModel, UserModel, UserSecurityStateModel

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]
SOURCE = "0123_mcp_read_sections"
TARGET = "0124_mcp_device_access"
CLIENT = "global-connects-desktop"


@pytest.mark.parametrize("control_enabled", [True, False])
async def test_device_upgrade_preserves_authority_and_serializes_pause_before_refresh(
    test_settings, control_enabled
):
    host = os.environ.get("POSTGRES_HOST", "localhost")
    source = os.environ["POSTGRES_DB"]
    if host not in {"localhost", "127.0.0.1", "postgres", "db"} or (
        source != "test_db" and not source.startswith("passdetection_ci_")
    ):
        pytest.fail("Device migration proof requires isolated local/CI PostgreSQL")
    name = "passdetection_ci_mcp_devices_" + uuid.uuid4().hex[:12]
    base_url = URL.create(
        "postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=host,
        port=int(os.environ.get("POSTGRES_PORT", "5432")), database=source,
    )
    admin = create_async_engine(base_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(base_url.set(database=name), poolclass=NullPool)
    environment = {**os.environ, "POSTGRES_DB": name}
    backend = Path(__file__).resolve().parents[2]
    settings = test_settings.model_copy(update={
        "mcp": MCPSettings(_env_file=None, enabled=True, read_only_mode=True),
    })
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def migrate(*arguments):
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "alembic", *arguments, cwd=backend, env=environment,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(process.communicate(), 90)
        return process.returncode, output.decode("utf-8", errors="replace")

    async def snapshot():
        result = {}
        async with engine.connect() as connection:
            for table in ("agencies", "users", "user_security_states", "mcp_control",
                          "mcp_grants", "mcp_tokens", "mcp_authorization_codes"):
                rows = (await connection.execute(text(
                    f"SELECT row_to_json(row) FROM (SELECT * FROM {table}) row"
                ))).scalars().all()
                if table == "mcp_grants":
                    for row in rows:
                        row.pop("enabled", None)
                        row.pop("device_platform", None)
                result[table] = sorted(json.dumps(row, sort_keys=True) for row in rows)
        return result

    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        code, output = await migrate("upgrade", SOURCE)
        assert code == 0, output[-4000:]
        now = datetime.now(UTC)
        grants = [uuid.uuid4(), uuid.uuid4()]
        access = [new_credential("access"), new_credential("access")]
        refresh = [new_credential("refresh"), new_credential("refresh")]
        async with sessions() as session:
            user = UserModel(
                id=uuid.uuid4(), email=f"devices-{uuid.uuid4()}@example.test",
                full_name="Retained device account", hashed_password="synthetic",
                role="super_admin", is_active=True,
            )
            session.add_all([user, AgencyModel(
                id=uuid.uuid4(), name="Retained agency", email=f"agency-{uuid.uuid4()}@example.test"
            )])
            await session.flush()
            session.add(UserSecurityStateModel(
                user_id=user.id, session_version=1, credential_state="active",
                mfa_secret_ciphertext="synthetic", mfa_enabled_at=now,
            ))
            await session.flush()
            await session.execute(text("""
                UPDATE mcp_control SET enabled=:enabled,
                    allowed_read_sections='["dashboard","all_groups"]'::jsonb,
                    read_access_revision=9 WHERE id=1
            """), {"enabled": control_enabled})
            authorization = MCPAuthorizationService(session, settings)
            for index, grant_id in enumerate(grants):
                # Use the previous schema's SQL projection rather than latest ORM columns.
                await session.execute(text("""
                    INSERT INTO mcp_grants (id,user_id,client_id,name,resource,capabilities,
                        security_version,mfa_at,created_at,expires_at)
                    VALUES (:id,:user,:client,:name,:resource,'["mcp:read"]'::jsonb,
                        1,:now,:now,:expires)
                """), {"id": grant_id, "user": user.id, "client": CLIENT,
                       "name": f"Retained connection {index}", "resource": settings.mcp.resource,
                       "now": now, "expires": now + timedelta(days=7)})
                for raw, kind, expiry in ((access[index], "access", now + timedelta(minutes=15)),
                                           (refresh[index], "refresh", now + timedelta(days=7))):
                    await session.execute(text("""
                        INSERT INTO mcp_tokens (token_hash,grant_id,kind,created_at,expires_at)
                        VALUES (:hash,:grant,:kind,:now,:expiry)
                    """), {"hash": authorization.digest(raw), "grant": grant_id,
                           "kind": kind, "now": now, "expiry": expiry})
                await session.execute(text("""
                    INSERT INTO mcp_authorization_codes
                        (code_hash,grant_id,redirect_uri,code_challenge,expires_at)
                    VALUES (:hash,:grant,:redirect,:challenge,:expiry)
                """), {"hash": authorization.digest(new_credential("code")), "grant": grant_id,
                       "redirect": "http://127.0.0.1:8765/callback",
                       "challenge": pkce_challenge("retained-verifier-" + "x" * 43),
                       "expiry": now + timedelta(minutes=5)})
            await session.commit()
        before = await snapshot()
        code, output = await migrate("upgrade", TARGET)
        assert code == 0, output[-4000:]
        assert await snapshot() == before
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == TARGET
            assert (await connection.execute(text(
                "SELECT enabled,device_platform FROM mcp_grants ORDER BY name"
            ))).all() == [(True, None), (True, None)]
            assert await connection.scalar(text("SELECT enabled FROM mcp_control")) is control_enabled
        # DB constraints reject invalid labels and NULL switches atomically.
        for change in ("device_platform='unknown'", "enabled=NULL"):
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(text(f"UPDATE mcp_grants SET {change}"))
        assert await snapshot() == before
        # Exercise the granted credentials only inside this disposable test DB.
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE mcp_control SET enabled=true WHERE id=1"))
        reached_lock = asyncio.Event()

        class ObservedAuthorization(MCPAuthorizationService):
            async def require_grant(self, grant_id, *, lock=False):
                if lock:
                    reached_lock.set()
                return await super().require_grant(grant_id, lock=lock)

        async def waiting_refresh():
            async with sessions() as session:
                try:
                    await ObservedAuthorization(session, settings).refresh(
                        token=refresh[0], client_id=CLIENT, resource=settings.mcp.resource,
                    )
                except MCPAuthError as error:
                    await session.commit()
                    return error.error, error.status_code
                raise AssertionError("Paused connection refreshed credentials")

        async with sessions() as session:
            grant = await session.scalar(select(MCPGrantModel).where(
                MCPGrantModel.id == grants[0]
            ).with_for_update())
            grant.enabled = False
            await session.flush()
            waiting = asyncio.create_task(waiting_refresh())
            await asyncio.wait_for(reached_lock.wait(), 5)
            await asyncio.sleep(0.1)
            assert not waiting.done(), "Refresh must wait for the connection decision"
            await session.commit()
        assert await asyncio.wait_for(waiting, 5) == ("access_denied", 403)
        async with sessions() as session:
            authorization = MCPAuthorizationService(session, settings)
            paused = await session.get(MCPTokenModel, authorization.digest(refresh[0]))
            assert paused.consumed_at is None
            assert (await authorization.verify_access(access[1])).grant_id == grants[1]
            grant = await session.get(MCPGrantModel, grants[0])
            grant.enabled, grant.device_platform = True, "Windows"
            await session.commit()
        async with sessions() as session:
            pair = await MCPAuthorizationService(session, settings).refresh(
                token=refresh[0], client_id=CLIENT, resource=settings.mcp.resource,
            )
            assert pair["refresh_token"] != refresh[0]
            assert (await session.get(MCPGrantModel, grants[0])).revoked_at is None
            await session.commit()
        code, output = await migrate("downgrade", SOURCE)
        assert code != 0 and "Retain connection access decisions" in output
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == TARGET
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            # Delete only the generated database owned by this exact test run.
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
