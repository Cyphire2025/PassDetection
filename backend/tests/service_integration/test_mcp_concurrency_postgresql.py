"""Real PostgreSQL connection races; never point this lane at business data."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import URL, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError, pkce_challenge
from app.core.config.mcp import MCPSettings
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel, MCPTokenModel
from app.infrastructure.database.models import UserModel, UserSecurityStateModel

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]
CLIENT = "global-connects-desktop"
REDIRECT = "http://127.0.0.1:8765/callback"
RESOURCE = "http://localhost:8000/mcp"
VERIFIER = "isolated-postgresql-verifier-" + "p" * 43


@pytest.fixture
async def mcp_sessions(test_settings):
    database = os.environ["POSTGRES_DB"]
    host = os.environ.get("POSTGRES_HOST", "localhost")
    if host not in {"localhost", "127.0.0.1", "postgres", "db"} or (
        database != "test_db" and not database.startswith("passdetection_ci_")
    ):
        pytest.fail("MCP concurrency tests require the isolated local/CI PostgreSQL database")
    engine = create_async_engine(
        URL.create(
            "postgresql+asyncpg",
            username=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            host=host,
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            database=database,
        ),
        poolclass=NullPool,
    )
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT to_regclass('mcp_grants')")) is not None
    settings = test_settings.model_copy(update={"mcp": MCPSettings(enabled=True)})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory, settings
    finally:
        await engine.dispose()


async def seed_code(fixture):
    sessions, settings = fixture
    async with sessions() as session:
        now = datetime.now(UTC)
        user = UserModel(
            id=uuid.uuid4(),
            email=f"mcp-{uuid.uuid4()}@example.test",
            full_name="MCP race fixture",
            hashed_password="not-a-credential",
            role="super_admin",
            is_active=True,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserSecurityStateModel(
                user_id=user.id,
                session_version=1,
                credential_state="active",
                mfa_secret_ciphertext="synthetic",
                mfa_enabled_at=now,
            )
        )
        control = await session.get(MCPControlModel, 1)
        assert control is not None, "Run the complete migration chain before service tests"
        control.enabled = True
        await session.flush()
        code = await MCPAuthorizationService(session, settings).authorize(
            user_id=user.id,
            security_version=1,
            mfa_at=now,
            client_id=CLIENT,
            redirect_uri=REDIRECT,
            resource=RESOURCE,
            challenge=pkce_challenge(VERIFIER),
            scopes=["mcp:read"],
            name="Race fixture",
        )
        grant_id = await session.scalar(
            select(MCPGrantModel.id).where(MCPGrantModel.user_id == user.id)
        )
        await session.commit()
        return code, grant_id


async def exchange(fixture, code):
    sessions, settings = fixture
    async with sessions() as session:
        try:
            result = await MCPAuthorizationService(session, settings).exchange_code(
                code=code,
                verifier=VERIFIER,
                client_id=CLIENT,
                redirect_uri=REDIRECT,
                resource=RESOURCE,
            )
        except MCPAuthError as error:
            await session.commit()
            return error
        await session.commit()
        return result


async def refresh(fixture, token):
    sessions, settings = fixture
    async with sessions() as session:
        try:
            result = await MCPAuthorizationService(session, settings).refresh(
                token=token,
                client_id=CLIENT,
                resource=RESOURCE,
            )
        except MCPAuthError as error:
            await session.commit()
            return error
        await session.commit()
        return result


async def test_one_authorization_code_issues_exactly_one_pair_under_contention(mcp_sessions):
    sessions, _ = mcp_sessions
    code, grant_id = await seed_code(mcp_sessions)
    results = await asyncio.gather(*(exchange(mcp_sessions, code) for _ in range(8)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, MCPAuthError) for result in results) == 7
    async with sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(MCPTokenModel)
            .where(MCPTokenModel.grant_id == grant_id)
        )
        assert count == 2


async def test_refresh_race_cannot_issue_two_successors_and_replay_revocation_persists(
    mcp_sessions,
):
    sessions, settings = mcp_sessions
    code, grant_id = await seed_code(mcp_sessions)
    initial = await exchange(mcp_sessions, code)
    results = await asyncio.gather(
        *(refresh(mcp_sessions, initial["refresh_token"]) for _ in range(8))
    )
    winners = [result for result in results if isinstance(result, dict)]
    assert len(winners) == 1
    async with sessions() as session:
        grant = await session.get(MCPGrantModel, grant_id)
        assert grant.revoked_at is not None and grant.revocation_reason == "refresh_reuse"
        count = await session.scalar(
            select(func.count())
            .select_from(MCPTokenModel)
            .where(MCPTokenModel.grant_id == grant_id)
        )
        assert count == 4
        for token in (initial["access_token"], winners[0]["access_token"]):
            with pytest.raises(MCPAuthError):
                await MCPAuthorizationService(session, settings).verify_access(token)


async def test_revoke_winning_grant_lock_fences_waiting_refresh(mcp_sessions):
    sessions, settings = mcp_sessions
    code, grant_id = await seed_code(mcp_sessions)
    initial = await exchange(mcp_sessions, code)
    attempted = asyncio.Event()

    class ObservedService(MCPAuthorizationService):
        async def require_grant(self, grant_id, *, lock=False):
            if lock:
                attempted.set()
            return await super().require_grant(grant_id, lock=lock)

    async with sessions() as revoker, sessions() as contender:
        grant = await revoker.scalar(
            select(MCPGrantModel).where(MCPGrantModel.id == grant_id).with_for_update()
        )
        pending = asyncio.create_task(
            ObservedService(contender, settings).refresh(
                token=initial["refresh_token"],
                client_id=CLIENT,
                resource=RESOURCE,
            )
        )
        await asyncio.wait_for(attempted.wait(), 5)
        assert not pending.done()
        grant.revoked_at, grant.revocation_reason = datetime.now(UTC), "administrator_revoked"
        await revoker.commit()
        with pytest.raises(MCPAuthError):
            await asyncio.wait_for(pending, 5)
        await contender.commit()
    async with sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(MCPTokenModel)
            .where(MCPTokenModel.grant_id == grant_id)
        )
        assert count == 2
