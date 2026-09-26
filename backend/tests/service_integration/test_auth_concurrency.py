"""Real migrated PostgreSQL and atomic Redis authentication boundaries."""

from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import URL, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain.exceptions.exceptions import AuthenticationError, ConflictError
from app.infrastructure.database.models import DashboardSessionModel
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.infrastructure.security import login_attempt_limiter as limiter_module
from tests.unit.infrastructure.test_dashboard_session_families import create_session

pytestmark = [pytest.mark.service_integration,
              pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated services required")]


@pytest.fixture
async def sessions():
    database = os.environ["POSTGRES_DB"]
    if database != "test_db" and not database.startswith("passdetection_ci_"):
        pytest.fail("Only an explicitly isolated CI database may be used")
    url = URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
                     password=os.environ["POSTGRES_PASSWORD"], host=os.environ.get("POSTGRES_HOST", "localhost"),
                     port=int(os.environ.get("POSTGRES_PORT", "5432")), database=database)
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT to_regclass('dashboard_sessions')")) is not None
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("contender", ["refresh", "logout"])
async def test_refresh_and_logout_races_serialize_on_real_family_row(sessions, contender):
    async with sessions() as seed:
        user, original, _, family_id = await create_session(seed)
        await seed.commit()
    observed = asyncio.Event()
    class ContenderRepository(RefreshTokenRepository):
        async def _lock_account(self, user_id):
            observed.set()  # First token read completed before the winning commit.
            return await super()._lock_account(user_id)
    async with sessions() as first, sessions() as second:
        winner = RefreshTokenRepository(first)
        old = await winner.claim_for_rotation(original)
        assert old is not None
        other = ContenderRepository(second)
        task = asyncio.create_task(other.claim_for_rotation(original) if contender == "refresh" else other.revoke(original))
        await asyncio.wait_for(observed.wait(), 5)
        assert not task.done()
        successor = str(uuid.uuid4())
        await winner.save(successor, user.id, old.expires_at, session_id=family_id)
        await first.commit()
        if contender == "refresh":
            with pytest.raises(ConflictError) as error:
                await asyncio.wait_for(task, 5)
            assert error.value.code == "REFRESH_IN_PROGRESS"
        else:
            await asyncio.wait_for(task, 5)
        await second.commit()
    async with sessions() as check:
        family = await check.get(DashboardSessionModel, family_id)
        if contender == "logout":
            assert family.revoked_at is not None
            assert await RefreshTokenRepository(check).get_valid_token(successor) is None
        else:
            assert family.revoked_at is None
            assert await RefreshTokenRepository(check).get_valid_token(successor) is not None
            # A later replay is not covered by the concurrency exception.
            with pytest.raises(AuthenticationError) as error:
                await RefreshTokenRepository(check).claim_for_rotation(original)
            assert error.value.code == "REFRESH_TOKEN_REUSED"
            await check.commit()
            assert (await check.scalar(select(DashboardSessionModel).where(DashboardSessionModel.id == family_id))).revoked_at is not None
            assert await RefreshTokenRepository(check).get_valid_token(successor) is None


@pytest.fixture
def redis_settings(monkeypatch):
    host = os.getenv("REDIS_HOST", "localhost")
    assert host in {"localhost", "127.0.0.1", "redis"}, "Only an isolated local/CI Redis is allowed"
    settings = SimpleNamespace(
        app_secret_key=f"synthetic-auth-budget-{uuid.uuid4()}", login_lockout_require_redis=True,
        redis=SimpleNamespace(security_url=f"redis://{host}:{int(os.getenv('REDIS_PORT', '6379'))}/14"),
        jwt=SimpleNamespace(login_lockout_max_attempts=5, login_lockout_window_seconds=900, login_lockout_seconds=900),
    )
    monkeypatch.setattr(limiter_module, "get_settings", lambda: settings)
    return settings


async def test_rotating_ips_cannot_bypass_atomic_account_admission(redis_settings):
    limiters = [limiter_module.LoginAttemptLimiter() for _ in range(40)]
    try:
        results = await asyncio.gather(*(
            limiter.check_allowed(email=" Staff@Example.test ", ip_address=f"192.0.2.{i+1}")
            for i, limiter in enumerate(limiters)
        ), return_exceptions=True)
        assert sum(result is None for result in results) == limiter_module._ACCOUNT_ATTEMPTS
        assert all(result is None or isinstance(result, AuthenticationError) for result in results)
        await limiters[0].record_success(email="staff@example.test", ip_address="192.0.2.1")
        with pytest.raises(AuthenticationError):
            await limiters[-1].check_allowed(email="staff@example.test", ip_address="198.51.100.9")
        # No permanent account change: independent identities still work.
        await limiters[-1].check_allowed(email="another@example.test", ip_address="198.51.100.9")
    finally:
        await asyncio.gather(*(limiter.aclose() for limiter in limiters))


async def test_shared_ip_and_wider_budget_limit_account_spraying(redis_settings, monkeypatch):
    monkeypatch.setattr(limiter_module, "_IP_ATTEMPTS", 3)
    monkeypatch.setattr(limiter_module, "_GLOBAL_ATTEMPTS", 5)
    limiter = limiter_module.LoginAttemptLimiter()
    try:
        for index in range(3):
            await limiter.check_allowed(email=f"user{index}@example.test", ip_address="192.0.2.1")
        with pytest.raises(AuthenticationError):
            await limiter.check_allowed(email="other@example.test", ip_address="192.0.2.1")
        for index in range(2):
            await limiter.check_allowed(email=f"spray{index}@example.test", ip_address=f"198.51.100.{index}")
        with pytest.raises(AuthenticationError):
            await limiter.check_allowed(email="new@example.test", ip_address="203.0.113.4")
    finally:
        await limiter.aclose()


async def test_denied_requests_do_not_extend_account_window(redis_settings, monkeypatch):
    monkeypatch.setattr(limiter_module, "_ADMISSION_WINDOW_SECONDS", 1)
    monkeypatch.setattr(limiter_module, "_ACCOUNT_ATTEMPTS", 1)
    limiter = limiter_module.LoginAttemptLimiter()
    try:
        await limiter.check_allowed(email="short-window@example.test", ip_address="192.0.2.1")
        await asyncio.sleep(0.6)
        with pytest.raises(AuthenticationError):
            await limiter.check_allowed(email="short-window@example.test", ip_address="192.0.2.2")
        await asyncio.sleep(0.5)
        await limiter.check_allowed(email="short-window@example.test", ip_address="192.0.2.3")
    finally:
        await limiter.aclose()


async def test_stale_budget_without_ttl_gets_bounded_expiry(redis_settings):
    limiter = limiter_module.LoginAttemptLimiter()
    try:
        key = limiter._admission_keys("stale@example.test", "192.0.2.1")[0]
        await limiter._redis.set(key, limiter_module._ACCOUNT_ATTEMPTS)
        assert await limiter._redis.ttl(key) == -1
        with pytest.raises(AuthenticationError):
            await limiter.check_allowed(email="stale@example.test", ip_address="192.0.2.2")
        assert 0 < await limiter._redis.ttl(key) <= limiter_module._ADMISSION_WINDOW_SECONDS
    finally:
        await limiter.aclose()
