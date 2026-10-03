"""Real row-lock concurrency and additive permission defaults on disposable PostgreSQL."""

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import URL, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.core.config.mcp import MCPSettings
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.models import AuditLogModel, UserModel, UserSecurityStateModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.main import create_application
from tests.dashboard_session_fixtures import issue_dashboard_access

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]


async def test_concurrent_global_device_saves_and_inflight_control_barrier(test_settings):
    host, source, port = os.environ["POSTGRES_HOST"], os.environ["POSTGRES_DB"], int(os.environ["POSTGRES_PORT"])
    if host not in {"localhost", "127.0.0.1"} or (source != "test_db" and not source.startswith("passdetection_ci_") and not (source == "postgres" and port == 55436)):
        pytest.fail("Only explicitly isolated local PostgreSQL is supported")
    name = "passdetection_ci_permissions_" + uuid.uuid4().hex[:12]
    url = URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"], host=host, port=port, database=source)
    admin = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(url.set(database=name), poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = test_settings.model_copy(update={"mcp": MCPSettings(_env_file=None, enabled=True)})
    now, identifier, grant_id = datetime.now(UTC), uuid.uuid4(), uuid.uuid4()
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        backend = Path(__file__).resolve().parents[2]
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", "alembic", "upgrade", "0125_mcp_connection_requests", cwd=backend,
            env={**os.environ, "POSTGRES_DB": name}, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        output, _ = await asyncio.wait_for(process.communicate(), 90)
        assert process.returncode == 0, output.decode(errors="replace")[-3000:]
        async with sessions() as session:
            session.add(UserModel(id=identifier, email=f"permission-{identifier}@example.test", hashed_password="synthetic", full_name="Permission concurrency", role="super_admin", is_active=True))
            await session.flush()
            session.add(UserSecurityStateModel(user_id=identifier, session_version=1, credential_state="active", mfa_secret_ciphertext="synthetic", mfa_enabled_at=now))
            await session.execute(text("UPDATE mcp_control SET enabled=true,allowed_read_sections='[\"all_groups\"]'::jsonb WHERE id=1"))
            await session.execute(text("""INSERT INTO mcp_grants
                (id,user_id,client_id,name,resource,capabilities,security_version,mfa_at,created_at,expires_at,enabled)
                VALUES (:id,:user,'global-connects-desktop','Concurrency fixture',:resource,'["mcp:read","mcp:change"]'::jsonb,1,:now,:now,:expires,true)"""),
                {"id": grant_id, "user": identifier, "resource": settings.mcp.resource, "now": now, "expires": now + timedelta(days=1)})
            await session.execute(text("""INSERT INTO mcp_authorization_codes
                (code_hash,grant_id,redirect_uri,code_challenge,expires_at) VALUES (:hash,:grant,'http://127.0.0.1:8765/callback',:challenge,:expiry)"""),
                {"hash": "a" * 64, "grant": grant_id, "challenge": "b" * 43, "expiry": now + timedelta(minutes=5)})
            await session.execute(text("""INSERT INTO mcp_tokens
                (token_hash,grant_id,kind,created_at,expires_at) VALUES (:hash,:grant,'access',:now,:expiry)"""),
                {"hash": "c" * 64, "grant": grant_id, "now": now, "expiry": now + timedelta(minutes=15)})
            await session.commit()

        async def authority_projection():
            columns = "'{read_enabled,write_enabled,allowed_write_sections,allowed_write_tools,allowed_read_sections,permission_revision}'::text[]"
            # Control's preexisting allowed_read_sections must be retained too.
            control_columns = "'{read_enabled,write_enabled,allowed_write_sections,allowed_write_tools}'::text[]"
            async with sessions() as snapshot:
                return {table: (await snapshot.execute(text(
                    f"SELECT coalesce(jsonb_agg(to_jsonb(t) - {control_columns if table == 'mcp_control' else columns} ORDER BY to_jsonb(t)::text),'[]'::jsonb) FROM {table} t"))).scalar_one()
                    for table in ("mcp_control", "mcp_grants", "mcp_tokens", "mcp_authorization_codes")}

        before = await authority_projection()
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", "alembic", "upgrade", "0126_mcp_section_permissions", cwd=backend,
            env={**os.environ, "POSTGRES_DB": name}, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        output, _ = await asyncio.wait_for(process.communicate(), 90)
        assert process.returncode == 0, output.decode(errors="replace")[-3000:]
        assert await authority_projection() == before
        async with sessions() as session:
            control = await session.get(MCPControlModel, 1)
            assert control.read_enabled is True and control.write_enabled is False and control.allowed_write_sections == []
            grant = await session.get(MCPGrantModel, grant_id)
            assert grant.read_enabled is True and grant.write_enabled is False and grant.allowed_read_sections is None
            tokens = await MCPAuthorizationService(session, settings).issue_pair(grant, now)
            dashboard, _ = await issue_dashboard_access(session, identifier, "super_admin", session_version=1, authentication_methods=("pwd", "totp"), mfa_authenticated_at=now)
            await session.commit()
        app = create_application(settings, initialize_rate_limit_redis=False)

        async def request_session():
            async with sessions() as session:
                try:
                    yield session
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db_session] = request_session
        app.state.mcp_session_factory = sessions
        app.state.mcp_management_audit_session_factory = sessions
        headers = {"Authorization": f"Bearer {dashboard}"}
        body = {"expected_revision": 1, "read_enabled": True, "write_enabled": True,
                "allowed_read_sections": ["all_groups"], "allowed_write_sections": ["all_groups"]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8000") as client:
            async with sessions() as holder:
                await holder.scalar(select(MCPControlModel).where(MCPControlModel.id == 1).with_for_update())
                requests = [asyncio.create_task(client.put("/api/v1/admin/mcp/permissions", headers=headers, json=body)) for _ in range(4)]
                await asyncio.sleep(0.2)
                assert not any(request.done() for request in requests)
                await holder.commit()
            results = await asyncio.wait_for(asyncio.gather(*requests), 15)
            assert sorted(response.status_code for response in results) == [200, 409, 409, 409]
            device_body = {"expected_revision": 1, "read_enabled": True, "write_enabled": True,
                           "allowed_read_sections": None, "allowed_write_sections": ["all_groups"]}
            async with sessions() as holder:
                await holder.scalar(select(MCPGrantModel).where(MCPGrantModel.id == grant_id).with_for_update())
                requests = [asyncio.create_task(client.put(f"/api/v1/admin/mcp/connections/{grant_id}/permissions", headers=headers, json=device_body)) for _ in range(4)]
                await asyncio.sleep(0.2)
                assert not any(request.done() for request in requests)
                await holder.commit()
            results = await asyncio.wait_for(asyncio.gather(*requests), 15)
            assert sorted(response.status_code for response in results) == [200, 409, 409, 409]
            # A real authorized transaction retains its shared control lock until
            # commit; a global pause waits, then all later reads are denied.
            async with sessions() as holder:
                await MCPAuthorizationService(holder, settings).verify_access(tokens["access_token"], "mcp:read")
                waiting = asyncio.create_task(client.put("/api/v1/admin/mcp/permissions", headers=headers,
                    json={**body, "expected_revision": 2, "read_enabled": False}))
                await asyncio.sleep(0.2)
                assert not waiting.done()
                await holder.commit()
            assert (await asyncio.wait_for(waiting, 15)).status_code == 200
        async with sessions() as session:
            with pytest.raises(MCPAuthError, match="read_access_denied"):
                await MCPAuthorizationService(session, settings).verify_access(tokens["access_token"], "mcp:read")
            grant = await session.get(MCPGrantModel, grant_id)
            assert grant.capabilities == ["mcp:read", "mcp:change"] and grant.permission_revision == 2 and grant.write_enabled is True
            assert await session.scalar(select(func.count()).select_from(AuditLogModel).where(AuditLogModel.action == "mcp.permissions_changed")) == 2
            assert await session.scalar(select(func.count()).select_from(AuditLogModel).where(AuditLogModel.action == "mcp.connection_permissions_changed")) == 1
            assert (await AuditLogRepository(session).verify_chain(None)).valid
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"), {"name": name})
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await admin.dispose()
