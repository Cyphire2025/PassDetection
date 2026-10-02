"""Real PostgreSQL request locks serialize decisions, finalization and quotas."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import URL, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp import connection_requests
from app.application.mcp.connection_requests import MCPConnectionRequestService
from app.application.mcp.credentials import MCPAuthError, pkce_challenge
from app.core.config.mcp import MCPSettings
from app.infrastructure.database.mcp_models import (
    MCPAuthorizationCodeModel,
    MCPConnectionRequestModel,
    MCPGrantModel,
)
from app.infrastructure.database.models import UserModel, UserSecurityStateModel

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


async def test_concurrent_decisions_finalization_and_creation_are_serialized(
    test_settings, monkeypatch
):
    host, source = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"localhost", "127.0.0.1", "postgres", "db"} or (
        source != "test_db" and not source.startswith("passdetection_ci_")
    ):
        pytest.fail("Request concurrency proof requires isolated local/CI PostgreSQL")
    name = "passdetection_ci_mcp_approval_" + uuid.uuid4().hex[:12]
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
    settings = test_settings.model_copy(
        update={"mcp": MCPSettings(_env_file=None, enabled=True, read_only_mode=True)}
    )
    now = datetime.now(UTC)
    user_id = uuid.uuid4()

    async def new_request(state):
        async with sessions() as session:
            row, secret = await MCPConnectionRequestService(session, settings).create(
                client_id="global-connects-desktop",
                redirect_uri="http://127.0.0.1:8765/callback",
                resource=settings.mcp.resource,
                state=state + "s" * 32,
                challenge=pkce_challenge("verifier-" + "x" * 43),
                scopes=["mcp:read"],
                platform="Other",
                source="local-concurrency",
                resume={},
            )
            await session.commit()
            return row.id, secret

    async def decide(identifier, approved):
        async with sessions() as session:
            try:
                row = await MCPConnectionRequestService(session, settings).decide(
                    identifier, approved=approved, user_id=user_id, security_version=1, mfa_at=now
                )
                await session.commit()
                return row.status
            except MCPAuthError as error:
                await session.rollback()
                return error.error

    async def finish(identifier, secret):
        async with sessions() as session:
            try:
                result = await MCPConnectionRequestService(session, settings).finalize(
                    identifier, secret
                )
                await session.commit()
                return "completed" if "redirect_url" in result else "invalid"
            except MCPAuthError as error:
                await session.rollback()
                return error.error

    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        backend = Path(__file__).resolve().parents[2]
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "0125_mcp_connection_requests",
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
                    email=f"approval-{uuid.uuid4()}@example.test",
                    hashed_password="synthetic",
                    full_name="Approval concurrency",
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
            await session.commit()
        identifier, secret = await new_request("decision-")
        # Hold the exact row to prove both independent sessions actually wait on
        # PostgreSQL, then release them into one accepted and one refused decision.
        async with sessions() as holder:
            await holder.scalar(
                select(MCPConnectionRequestModel)
                .where(MCPConnectionRequestModel.id == identifier)
                .with_for_update()
            )
            tasks = [asyncio.create_task(decide(identifier, value)) for value in (True, False)]
            await asyncio.sleep(0.2)
            assert not any(task.done() for task in tasks)
            await holder.commit()
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 10)
        assert outcomes.count("request_already_decided") == 1
        assert len(set(outcomes) & {"approved", "rejected"}) == 1
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 0
        identifier, secret = await new_request("finalize-")
        assert await decide(identifier, True) == "approved"
        async with sessions() as holder:
            await holder.scalar(
                select(MCPConnectionRequestModel)
                .where(MCPConnectionRequestModel.id == identifier)
                .with_for_update()
            )
            tasks = [
                asyncio.create_task(finish(identifier, secret)),
                asyncio.create_task(finish(identifier, secret)),
                asyncio.create_task(decide(identifier, False)),
            ]
            await asyncio.sleep(0.2)
            assert not any(task.done() for task in tasks)
            await holder.commit()
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 10)
        assert outcomes.count("completed") == 1
        assert outcomes.count("request_already_decided") == 1
        assert len(outcomes) == 3
        assert any(value in {"request_finalized", "request_decision_changed"} for value in outcomes)
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 1
            assert (
                await session.scalar(select(func.count()).select_from(MCPAuthorizationCodeModel))
                == 1
            )
        # Two independent creators share the persisted quota, rather than each
        # receiving one in-process allowance.
        monkeypatch.setattr(connection_requests, "SOURCE_CREATION_LIMIT", 3)

        async def bounded_create(state):
            try:
                await new_request(state)
                return "created"
            except MCPAuthError as error:
                return error.error

        assert sorted(
            await asyncio.wait_for(
                asyncio.gather(bounded_create("quota-a-"), bounded_create("quota-b-")), 10
            )
        ) == ["created", "slow_down"]
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
