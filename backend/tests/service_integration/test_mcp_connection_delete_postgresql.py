"""Actual HTTP deletions serialize with each other and refresh on PostgreSQL."""

from __future__ import annotations

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
from app.infrastructure.database.mcp_models import MCPGrantModel, MCPTokenModel
from app.infrastructure.database.models import AuditLogModel, UserModel, UserSecurityStateModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.main import create_application
from tests.dashboard_session_fixtures import issue_dashboard_access

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1",
        reason="isolated PostgreSQL required",
    ),
]


async def test_actual_http_duplicate_delete_and_refresh_are_serialized(test_settings):
    host, source = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"localhost", "127.0.0.1", "postgres", "db"} or (
        source != "test_db" and not source.startswith("passdetection_ci_")
    ):
        pytest.fail("Deletion concurrency requires isolated local/CI PostgreSQL")
    name = "passdetection_ci_mcp_delete_" + uuid.uuid4().hex[:12]
    url = URL.create(
        "postgresql+asyncpg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=host,
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=source,
    )
    admin = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(url.set(database=name), poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = test_settings.model_copy(update={"mcp": MCPSettings(_env_file=None, enabled=True)})
    user_id, grant_id, other_id, now = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), datetime.now(UTC)
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        backend = Path(__file__).resolve().parents[2]
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
            cwd=backend,
            env={**os.environ, "POSTGRES_DB": name},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(process.communicate(), 90)
        assert process.returncode == 0, output.decode(errors="replace")[-4000:]
        async with sessions() as session:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"delete-{uuid.uuid4()}@example.test",
                    hashed_password="synthetic",
                    full_name="Delete concurrency",
                    role="super_admin",
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                UserSecurityStateModel(
                    user_id=user_id,
                    session_version=1,
                    credential_state="active",
                    mfa_secret_ciphertext="synthetic",
                    mfa_enabled_at=now,
                )
            )
            await session.execute(text("UPDATE mcp_control SET enabled=true WHERE id=1"))
            grants = [
                MCPGrantModel(
                    id=identifier,
                    user_id=user_id,
                    client_id="global-connects-desktop",
                    name=label,
                    resource=settings.mcp.resource,
                    capabilities=["mcp:read"],
                    security_version=1,
                    mfa_at=now,
                    created_at=now,
                    expires_at=now + timedelta(days=1),
                    enabled=True,
                )
                for identifier, label in (
                    (grant_id, "Concurrent deletion"),
                    (other_id, "Unchanged device"),
                )
            ]
            session.add_all(grants)
            await session.flush()
            tokens = await MCPAuthorizationService(session, settings).issue_pair(grants[0], now)
            dashboard, _ = await issue_dashboard_access(
                session,
                user_id,
                "super_admin",
                session_version=1,
                authentication_methods=("pwd", "totp"),
                mfa_authenticated_at=now,
            )
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
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost:8000"
        ) as client:

            async def delete():
                return await client.delete(
                    f"/api/v1/admin/mcp/connections/{grant_id}",
                    headers={"Authorization": f"Bearer {dashboard}"},
                )

            async def refresh():
                return await client.post(
                    "/oauth/mcp/token",
                    data={
                        "grant_type": "refresh_token",
                        "client_id": "global-connects-desktop",
                        "resource": settings.mcp.resource,
                        "refresh_token": tokens["refresh_token"],
                    },
                )

            async with sessions() as holder:
                await holder.scalar(
                    select(MCPGrantModel).where(MCPGrantModel.id == grant_id).with_for_update()
                )
                tasks = [asyncio.create_task(delete()) for _ in range(6)] + [
                    asyncio.create_task(refresh())
                ]
                await asyncio.sleep(0.2)
                assert not any(task.done() for task in tasks)
                await holder.commit()
            outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 15)
            assert all(
                response.status_code == 200 and response.json() == {"deleted": True}
                for response in outcomes[:6]
            )
            assert outcomes[-1].status_code in {200, 400}
            if outcomes[-1].status_code == 400:
                assert outcomes[-1].json()["error"] == "invalid_grant"
            repeated = await delete()
            assert repeated.status_code == 200 and repeated.json() == {"deleted": True}
            listing = await client.get(
                "/api/v1/admin/mcp/connections", headers={"Authorization": f"Bearer {dashboard}"}
            )
            assert listing.status_code == 200 and [
                row["id"] for row in listing.json()["items"]
            ] == [str(other_id)]
        async with sessions() as session:
            grant, other = (
                await session.get(MCPGrantModel, grant_id),
                await session.get(MCPGrantModel, other_id),
            )
            assert (
                grant.revoked_at is not None and grant.revocation_reason == "administrator_removed"
            )
            assert (
                other.revoked_at is None
                and other.revocation_reason is None
                and other.enabled is True
            )
            assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 2
            audits = list(
                (
                    await session.scalars(
                        select(AuditLogModel).where(
                            AuditLogModel.action == "mcp.connection_removed"
                        )
                    )
                ).all()
            )
            assert (
                len(audits) == 1
                and audits[0].entity_id == str(grant_id)
                and audits[0].user_id == user_id
            )
            assert (await AuditLogRepository(session).verify_chain(None)).valid
            assert await session.scalar(select(func.count()).select_from(MCPTokenModel)) == (
                4 if outcomes[-1].status_code == 200 else 2
            )
            bearers = [tokens["access_token"]]
            if outcomes[-1].status_code == 200:
                bearers.append(outcomes[-1].json()["access_token"])
            for bearer in bearers:
                with pytest.raises(MCPAuthError):
                    await MCPAuthorizationService(session, settings).verify_access(bearer)
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"
                ),
                {"name": name},
            )
            await connection.execute(text(f'DROP DATABASE "{name}"'))
        await admin.dispose()
