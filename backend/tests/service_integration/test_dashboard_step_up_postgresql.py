"""Step-up/rotation/revocation races in retained isolated PostgreSQL schemas."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import URL, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.dtos.auth_dtos import RefreshTokenInputDTO
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.application.use_cases.auth.logout_all_use_case import LogoutAllUseCase
from app.application.use_cases.auth.refresh_token_use_case import RefreshTokenUseCase
from app.domain.exceptions.exceptions import AuthenticationError
from app.infrastructure.database.models import (
    DashboardSessionModel,
    RefreshTokenModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.dashboard_step_up_repository import lock_step_up_session
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.infrastructure.repositories.user_repository import UserRepository
from tests.postgresql_schema import create_isolated_postgresql_tables

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]


@pytest.fixture
async def step_sessions():
    database = os.environ["POSTGRES_DB"]
    host = os.environ.get("POSTGRES_HOST", "localhost")
    assert host in {"127.0.0.1", "localhost", "postgres", "db"}
    assert database == "test_db" or database.startswith("passdetection_ci_")
    url = URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
                     password=os.environ["POSTGRES_PASSWORD"], host=host,
                     port=int(os.environ.get("POSTGRES_PORT", "5432")), database=database)
    schema = f"manual_review_{uuid.uuid4().hex}"
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await engine.dispose()
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"server_settings": {
        "search_path": schema, "lock_timeout": "5000", "statement_timeout": "15000",
    }})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await create_isolated_postgresql_tables(connection, schema)
        async with sessions() as session:
            now = datetime.now(UTC)
            user = UserModel(email=f"step-{uuid.uuid4()}@example.test", full_name="Synthetic step-up",
                             hashed_password="not-a-credential", role="super_admin", is_active=True)
            session.add(user)
            await session.flush()
            session.add(UserSecurityStateModel(user_id=user.id, session_version=1, credential_state="active"))
            credential = await RefreshTokenRepository(session).save(
                token="old-opaque-token", user_id=user.id, expires_at=now + timedelta(days=1),
                authentication_methods=("pwd", "totp"), mfa_authenticated_at=now - timedelta(hours=1),
            )
            await session.commit()
            fixture = (sessions, user.id, credential.session_id, credential.expires_at, now)
        yield fixture
    finally:
        await engine.dispose()
        print(f"DASHBOARD_STEP_UP_SCHEMA_RETAINED={schema}")


async def _lock(session, fixture):
    return await lock_step_up_session(
        session, user_id=fixture[1], session_id=fixture[2], session_version=1,
        deadline=fixture[3].replace(microsecond=0), now=fixture[4],
    )


async def _refresh(session, token="old-opaque-token"):
    return await RefreshTokenUseCase(UserRepository(session), RefreshTokenRepository(session),
                                    IdentitySecurityRepository(session)).execute(
        RefreshTokenInputDTO(refresh_token=token))


async def _wait_for_account_lock(holder, contender_pid):
    holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
    for _ in range(200):
        blockers = await holder.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": contender_pid})
        if holder_pid in blockers:
            return
        await asyncio.sleep(0.01)
    pytest.fail("Contender did not wait on the account lock")


async def _start_contender(sessions, operation):
    started = asyncio.Future()

    async def run():
        async with sessions() as session:
            started.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            result = await operation(session)
            await session.commit()
            return result

    task = asyncio.create_task(run())
    return task, await started


async def test_step_up_winner_is_inherited_by_waiting_rotation(step_sessions):
    f = step_sessions
    async with f[0]() as first:
        locked = await _lock(first, f)
        locked.record_assurance(method="totp", now=f[4])
        task, pid = await _start_contender(f[0], _refresh)
        await _wait_for_account_lock(first, pid)
        await first.commit()
        rotated = await asyncio.wait_for(task, 5)
    async with f[0]() as session:
        row = await RefreshTokenRepository(session).get_valid_token(rotated.refresh_token)
        assert row.mfa_authenticated_at == f[4]
        assert row.expires_at == f[3]
        assert row.session_id == f[2] and row.session_version == 1


async def test_rotation_winner_successor_receives_waiting_step_up(step_sessions):
    f = step_sessions

    async def step(session):
        locked = await _lock(session, f)
        locked.record_assurance(method="recovery_code", now=f[4])

    async with f[0]() as first:
        rotated = await _refresh(first)
        task, pid = await _start_contender(f[0], step)
        await _wait_for_account_lock(first, pid)
        await first.commit()
        await asyncio.wait_for(task, 5)
    async with f[0]() as session:
        row = await RefreshTokenRepository(session).get_valid_token(rotated.refresh_token)
        assert row.mfa_authenticated_at == f[4]
        assert row.authentication_methods == "pwd,recovery_code"
        assert row.expires_at == f[3]
        consumed = await session.scalar(select(RefreshTokenModel).where(RefreshTokenModel.is_revoked.is_(True)))
        assert consumed.mfa_authenticated_at == f[4] - timedelta(hours=1)


@pytest.mark.parametrize("revocation", ["logout", "logout_all"])
async def test_revocation_winner_blocks_waiting_step_up(step_sessions, revocation):
    f = step_sessions
    async with f[0]() as first:
        tokens = RefreshTokenRepository(first)
        if revocation == "logout":
            await tokens.revoke_session(f[2], user_id=f[1])
        else:
            await LogoutAllUseCase(tokens, IdentitySecurityRepository(first)).execute(f[1])
        task, pid = await _start_contender(f[0], lambda session: _lock(session, f))
        await _wait_for_account_lock(first, pid)
        await first.commit()
        with pytest.raises(AuthenticationError, match="Session is no longer valid"):
            await asyncio.wait_for(task, 5)
    async with f[0]() as session:
        family = await session.get(DashboardSessionModel, f[2])
        assert family.revoked_at is not None
        row = await session.scalar(select(RefreshTokenModel))
        assert row.is_revoked and row.mfa_authenticated_at == f[4] - timedelta(hours=1)


async def test_revocation_waiting_for_step_up_still_revokes_updated_credential(step_sessions):
    f = step_sessions
    async with f[0]() as first:
        locked = await _lock(first, f)
        locked.record_assurance(method="totp", now=f[4])
        task, pid = await _start_contender(f[0], lambda session: RefreshTokenRepository(session).revoke_session(f[2], user_id=f[1]))
        await _wait_for_account_lock(first, pid)
        await first.commit()
        await asyncio.wait_for(task, 5)
    async with f[0]() as session:
        row = await session.scalar(select(RefreshTokenModel))
        assert row.is_revoked and row.mfa_authenticated_at == f[4]
        assert row.expires_at == f[3]
        with pytest.raises(AuthenticationError):
            await _refresh(session)


async def _issue_challenge(session, user_id):
    return await IdentitySecurityRepository(session).issue_auth_challenge(
        user_id=user_id, purpose="mfa_login", pending_secret_ciphertext=None,
        request_ip_hash=None, user_agent_hash=None,
    )


@pytest.mark.parametrize("winner", ["verification", "step_up"])
async def test_mfa_verification_and_step_up_use_account_first_order(step_sessions, winner):
    f = step_sessions
    async with f[0]() as seed:
        _, raw = await _issue_challenge(seed, f[1])
        await seed.commit()

    async def verify_and_issue(session):
        repository = IdentitySecurityRepository(session)
        challenge = await repository.get_pending_auth_challenge(raw_token=raw)
        assert challenge is not None
        state = await repository.get_state(f[1], lock=True)
        user = await UserRepository(session).get_by_id(f[1])
        challenge.status = "consumed"
        # Production verification has validated its factor before this shared
        # account update/session issuance; HTTP tests cover factor consumption.
        return await LoginUseCase(UserRepository(session), RefreshTokenRepository(session)).issue_session(
            user, session_version=state.session_version,
            authentication_methods=("pwd", "totp"), mfa_authenticated_at=f[4],
        )

    async def step(session):
        locked = await _lock(session, f)
        locked.record_assurance(method="totp", now=f[4])

    async with f[0]() as first:
        if winner == "verification":
            repository = IdentitySecurityRepository(first)
            assert await repository.get_pending_auth_challenge(raw_token=raw)
            await repository.get_state(f[1], lock=True)
            task, pid = await _start_contender(f[0], step)
            await _wait_for_account_lock(first, pid)
            await verify_and_issue(first)
        else:
            await step(first)
            task, pid = await _start_contender(f[0], verify_and_issue)
            await _wait_for_account_lock(first, pid)
        await first.commit()
        await asyncio.wait_for(task, 5)
    async with f[0]() as session:
        original = await RefreshTokenRepository(session).get_valid_token("old-opaque-token")
        assert original.mfa_authenticated_at == f[4]
        assert original.expires_at == f[3]


async def test_challenge_replacement_fences_waiting_verification(step_sessions):
    f = step_sessions
    async with f[0]() as seed:
        _, raw = await _issue_challenge(seed, f[1])
        await seed.commit()
    async with f[0]() as first:
        await _issue_challenge(first, f[1])
        task, pid = await _start_contender(f[0], lambda session:
            IdentitySecurityRepository(session).get_pending_auth_challenge(raw_token=raw))
        await _wait_for_account_lock(first, pid)
        await first.commit()
        assert await asyncio.wait_for(task, 5) is None


async def test_challenge_expiring_during_account_wait_is_rejected(step_sessions):
    f = step_sessions
    async with f[0]() as seed:
        challenge, raw = await _issue_challenge(seed, f[1])
        challenge.expires_at = datetime.now(UTC) + timedelta(seconds=1)
        expiry = challenge.expires_at
        await seed.commit()
    async with f[0]() as first:
        await first.scalar(select(UserModel.id).where(UserModel.id == f[1]).with_for_update())
        task, pid = await _start_contender(f[0], lambda session:
            IdentitySecurityRepository(session).get_pending_auth_challenge(raw_token=raw))
        await _wait_for_account_lock(first, pid)
        await asyncio.sleep(max(0, (expiry - datetime.now(UTC)).total_seconds()) + 0.02)
        await first.commit()
        assert await asyncio.wait_for(task, 5) is None
