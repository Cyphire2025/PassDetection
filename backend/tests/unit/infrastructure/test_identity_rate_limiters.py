from __future__ import annotations

import uuid

import pytest

from app.core.config.settings import Settings
from app.infrastructure.security import (
    identity_recovery_rate_limiter as recovery_limiter_module,
)
from app.infrastructure.security import mfa_step_up_rate_limiter as mfa_limiter_module
from app.infrastructure.security.identity_recovery_rate_limiter import (
    IdentityRecoveryRateLimited,
    IdentityRecoveryRateLimiter,
    IdentityRecoveryRateLimiterUnavailable,
)
from app.infrastructure.security.mfa_step_up_rate_limiter import (
    MFAStepUpLocked,
    MFAStepUpRateLimiter,
)


class _UnavailableRedis:
    def __init__(self) -> None:
        self.closed = False

    async def eval(self, *_args: object, **_kwargs: object) -> object:
        raise ConnectionError("isolated test Redis outage")

    async def exists(self, *_args: object, **_kwargs: object) -> int:
        raise ConnectionError("isolated test Redis outage")

    async def delete(self, *_args: object, **_kwargs: object) -> int:
        raise ConnectionError("isolated test Redis outage")

    async def aclose(self) -> None:
        self.closed = True


def _install_unavailable_redis(
    monkeypatch: pytest.MonkeyPatch,
    *,
    module: object,
) -> None:
    redis_type = getattr(module, "Redis")
    monkeypatch.setattr(redis_type, "from_url", lambda *_args, **_kwargs: _UnavailableRedis())


@pytest.mark.asyncio
async def test_recovery_ip_budget_cannot_be_bypassed_by_rotating_risk_context(
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={
            "password_recovery_ip_limit_per_hour": 5,
            "password_recovery_rate_limit_require_redis": False,
        }
    )
    IdentityRecoveryRateLimiter._local_counts.clear()
    monkeypatch.setattr(recovery_limiter_module, "get_settings", lambda: settings)
    _install_unavailable_redis(monkeypatch, module=recovery_limiter_module)
    limiter = IdentityRecoveryRateLimiter()

    for attempt in range(5):
        await limiter.consume_network(
            ip_address="203.0.113.8",
            risk_context=f"rotating-agent-{attempt}",
        )

    with pytest.raises(IdentityRecoveryRateLimited):
        await limiter.consume_network(
            ip_address="203.0.113.8",
            risk_context="another-agent",
        )


@pytest.mark.asyncio
async def test_recovery_risk_budget_cannot_be_bypassed_by_rotating_ip(
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={
            "password_recovery_ip_limit_per_hour": 5,
            "password_recovery_rate_limit_require_redis": False,
        }
    )
    IdentityRecoveryRateLimiter._local_counts.clear()
    monkeypatch.setattr(recovery_limiter_module, "get_settings", lambda: settings)
    _install_unavailable_redis(monkeypatch, module=recovery_limiter_module)
    limiter = IdentityRecoveryRateLimiter()

    for attempt in range(5):
        await limiter.consume_network(
            ip_address=f"203.0.113.{attempt + 1}",
            risk_context="stable-risk-context",
        )

    with pytest.raises(IdentityRecoveryRateLimited):
        await limiter.consume_network(
            ip_address="198.51.100.20",
            risk_context="stable-risk-context",
        )


@pytest.mark.asyncio
async def test_recovery_production_redis_outage_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={
            "app_env": "production",
            "password_recovery_rate_limit_require_redis": True,
        }
    )
    monkeypatch.setattr(recovery_limiter_module, "get_settings", lambda: settings)
    _install_unavailable_redis(monkeypatch, module=recovery_limiter_module)

    with pytest.raises(IdentityRecoveryRateLimiterUnavailable):
        await IdentityRecoveryRateLimiter().consume_network(
            ip_address="203.0.113.8",
            risk_context="risk",
        )


@pytest.mark.asyncio
async def test_recovery_account_and_tenant_budgets_are_independent(
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={
            "password_recovery_account_limit_per_hour": 2,
            "password_recovery_tenant_limit_per_hour": 10,
            "password_recovery_rate_limit_require_redis": False,
        }
    )
    IdentityRecoveryRateLimiter._local_counts.clear()
    monkeypatch.setattr(recovery_limiter_module, "get_settings", lambda: settings)
    _install_unavailable_redis(monkeypatch, module=recovery_limiter_module)
    limiter = IdentityRecoveryRateLimiter()
    agency_id = uuid.uuid4()
    first_user = uuid.uuid4()

    await limiter.consume_account(user_id=first_user, agency_id=agency_id)
    await limiter.consume_account(user_id=first_user, agency_id=agency_id)
    with pytest.raises(IdentityRecoveryRateLimited):
        await limiter.consume_account(user_id=first_user, agency_id=agency_id)

    IdentityRecoveryRateLimiter._local_counts.clear()
    for _ in range(10):
        await limiter.consume_account(user_id=uuid.uuid4(), agency_id=agency_id)
    with pytest.raises(IdentityRecoveryRateLimited):
        await limiter.consume_account(user_id=uuid.uuid4(), agency_id=agency_id)


@pytest.mark.asyncio
async def test_mfa_step_up_has_account_wide_temporary_backoff_across_ips(
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    current_time = [1_000.0]
    settings = test_settings.model_copy(
        update={
            "mfa_step_up_max_attempts": 2,
            "mfa_step_up_window_seconds": 60,
            "mfa_step_up_lock_seconds": 30,
        }
    )
    MFAStepUpRateLimiter._local_failures.clear()
    MFAStepUpRateLimiter._local_locks.clear()
    monkeypatch.setattr(mfa_limiter_module, "get_settings", lambda: settings)
    monkeypatch.setattr(mfa_limiter_module.time, "time", lambda: current_time[0])
    _install_unavailable_redis(monkeypatch, module=mfa_limiter_module)
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    limiter = MFAStepUpRateLimiter()

    await limiter.record_failure(user_id=user_id, ip_address="203.0.113.1")
    with pytest.raises(MFAStepUpLocked):
        await limiter.record_failure(user_id=user_id, ip_address="198.51.100.2")
    with pytest.raises(MFAStepUpLocked):
        await limiter.ensure_available(user_id=user_id, ip_address="192.0.2.3")

    # One attacker can cause only a bounded temporary denial for one account;
    # another principal is isolated and the lock expires automatically.
    await limiter.ensure_available(user_id=other_user_id, ip_address="192.0.2.3")
    current_time[0] += 61
    await limiter.ensure_available(user_id=user_id, ip_address="192.0.2.3")


@pytest.mark.asyncio
async def test_successful_mfa_step_up_clears_account_and_context_failures(
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"mfa_step_up_max_attempts": 2})
    MFAStepUpRateLimiter._local_failures.clear()
    MFAStepUpRateLimiter._local_locks.clear()
    monkeypatch.setattr(mfa_limiter_module, "get_settings", lambda: settings)
    _install_unavailable_redis(monkeypatch, module=mfa_limiter_module)
    user_id = uuid.uuid4()
    limiter = MFAStepUpRateLimiter()

    await limiter.record_failure(user_id=user_id, ip_address="203.0.113.1")
    await limiter.clear(user_id=user_id, ip_address="203.0.113.1")
    await limiter.record_failure(user_id=user_id, ip_address="198.51.100.2")
    await limiter.ensure_available(user_id=user_id, ip_address="192.0.2.3")
