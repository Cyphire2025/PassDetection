from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.exceptions.exceptions import AuthenticationError, DependencyUnavailableError
from app.infrastructure.security import login_attempt_limiter as limiter_module


def _settings(*, require_redis: bool, max_attempts: int = 2) -> SimpleNamespace:
    return SimpleNamespace(
        app_secret_key="test-app-secret-key",
        login_lockout_require_redis=require_redis,
        redis=SimpleNamespace(security_url="redis://security.invalid:6379/0"),
        jwt=SimpleNamespace(
            login_lockout_max_attempts=max_attempts,
            login_lockout_window_seconds=900,
            login_lockout_seconds=900,
        ),
    )


class _UnavailableRedis:
    def __init__(self) -> None:
        self.closed = False

    async def exists(self, _key: str) -> bool:
        raise ConnectionError("redis unavailable")

    async def aclose(self) -> None:
        self.closed = True


class _AtomicCounterRedis:
    def __init__(self, *, fail_eval: bool = False) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.locks: dict[str, tuple[int, str]] = {}
        self.eval_calls: list[tuple[str, str]] = []
        self.fail_eval = fail_eval
        self.closed = False

    async def eval(
        self,
        script: str,
        numkeys: int,
        key: str,
        ttl_seconds: str,
    ) -> int:
        if self.fail_eval:
            raise ConnectionError("redis unavailable")
        assert numkeys == 1
        assert "redis.call('INCR', key)" in script
        assert "redis.call('TTL', key)" in script
        assert "redis.call('EXPIRE', key, ttl_seconds)" in script
        self.eval_calls.append((key, ttl_seconds))
        ttl = int(ttl_seconds)
        self.counts[key] = self.counts.get(key, 0) + 1
        if key not in self.ttls:
            self.ttls[key] = ttl
        return self.counts[key]

    async def setex(self, key: str, ttl_seconds: int, value: str) -> None:
        self.locks[key] = (ttl_seconds, value)

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_redis_first_increment_sets_ttl_in_same_eval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _AtomicCounterRedis()
    monkeypatch.setattr(limiter_module, "get_settings", lambda: _settings(require_redis=True))
    monkeypatch.setattr(limiter_module.Redis, "from_url", lambda *_args, **_kwargs: redis)
    limiter = limiter_module.LoginAttemptLimiter()

    await limiter.record_failure(email="person@example.com", ip_address="203.0.113.7")

    count_key = f"{limiter._key('person@example.com', '203.0.113.7')}:count"
    assert redis.eval_calls == [(count_key, "900")]
    assert redis.ttls == {count_key: 900}


@pytest.mark.asyncio
async def test_redis_increment_preserves_existing_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _AtomicCounterRedis()
    monkeypatch.setattr(limiter_module, "get_settings", lambda: _settings(require_redis=True))
    monkeypatch.setattr(limiter_module.Redis, "from_url", lambda *_args, **_kwargs: redis)
    limiter = limiter_module.LoginAttemptLimiter()
    count_key = f"{limiter._key('person@example.com', '203.0.113.7')}:count"
    redis.counts[count_key] = 1
    redis.ttls[count_key] = 321

    await limiter.record_failure(email="person@example.com", ip_address="203.0.113.7")

    assert redis.counts[count_key] == 2
    assert redis.ttls[count_key] == 321


def test_required_redis_configuration_failure_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(limiter_module, "get_settings", lambda: _settings(require_redis=True))
    monkeypatch.setattr(
        limiter_module.Redis,
        "from_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad redis url")),
    )

    with pytest.raises(
        DependencyUnavailableError, match="Authentication is temporarily unavailable"
    ):
        limiter_module.LoginAttemptLimiter()


@pytest.mark.asyncio
async def test_required_redis_runtime_failure_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _UnavailableRedis()
    monkeypatch.setattr(limiter_module, "get_settings", lambda: _settings(require_redis=True))
    monkeypatch.setattr(
        limiter_module.Redis,
        "from_url",
        lambda *_args, **_kwargs: redis,
    )
    limiter = limiter_module.LoginAttemptLimiter()

    with pytest.raises(
        DependencyUnavailableError, match="Authentication is temporarily unavailable"
    ):
        await limiter.check_allowed(email="person@example.com", ip_address="203.0.113.7")
    assert redis.closed is True


@pytest.mark.asyncio
async def test_required_redis_eval_failure_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _AtomicCounterRedis(fail_eval=True)
    monkeypatch.setattr(limiter_module, "get_settings", lambda: _settings(require_redis=True))
    monkeypatch.setattr(limiter_module.Redis, "from_url", lambda *_args, **_kwargs: redis)
    limiter = limiter_module.LoginAttemptLimiter()

    with pytest.raises(
        DependencyUnavailableError, match="Authentication is temporarily unavailable"
    ):
        await limiter.record_failure(email="person@example.com", ip_address="203.0.113.7")
    assert redis.closed is True


@pytest.mark.asyncio
async def test_explicit_close_releases_the_request_scoped_redis_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _AtomicCounterRedis()
    monkeypatch.setattr(limiter_module, "get_settings", lambda: _settings(require_redis=True))
    monkeypatch.setattr(limiter_module.Redis, "from_url", lambda *_args, **_kwargs: redis)
    limiter = limiter_module.LoginAttemptLimiter()

    await limiter.aclose()
    await limiter.aclose()

    assert redis.closed is True
    assert limiter._redis is None


@pytest.mark.asyncio
async def test_optional_redis_eval_failure_uses_bounded_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _AtomicCounterRedis(fail_eval=True)
    monkeypatch.setattr(limiter_module, "get_settings", lambda: _settings(require_redis=False))
    monkeypatch.setattr(limiter_module.Redis, "from_url", lambda *_args, **_kwargs: redis)
    limiter_module.LoginAttemptLimiter._local_counts.clear()
    limiter_module.LoginAttemptLimiter._local_locks.clear()
    limiter = limiter_module.LoginAttemptLimiter()

    await limiter.record_failure(email="person@example.com", ip_address="203.0.113.7")
    await limiter.record_failure(email="person@example.com", ip_address="203.0.113.7")

    with pytest.raises(AuthenticationError, match="Too many failed login attempts"):
        await limiter.check_allowed(email="person@example.com", ip_address="203.0.113.7")


@pytest.mark.asyncio
async def test_explicit_local_fallback_remains_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limiter_module, "get_settings", lambda: _settings(require_redis=False))
    monkeypatch.setattr(
        limiter_module.Redis,
        "from_url",
        lambda *_args, **_kwargs: _UnavailableRedis(),
    )
    limiter_module.LoginAttemptLimiter._local_counts.clear()
    limiter_module.LoginAttemptLimiter._local_locks.clear()
    limiter = limiter_module.LoginAttemptLimiter()

    await limiter.record_failure(email="person@example.com", ip_address="203.0.113.7")
    await limiter.record_failure(email="person@example.com", ip_address="203.0.113.7")

    with pytest.raises(AuthenticationError, match="Too many failed login attempts"):
        await limiter.check_allowed(email="person@example.com", ip_address="203.0.113.7")


def test_lockout_key_is_stable_normalized_and_contains_no_pii(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(limiter_module, "get_settings", lambda: _settings(require_redis=False))
    monkeypatch.setattr(
        limiter_module.Redis,
        "from_url",
        lambda *_args, **_kwargs: _UnavailableRedis(),
    )
    limiter = limiter_module.LoginAttemptLimiter()

    first = limiter._key(" Person@Example.com ", "203.0.113.7")
    second = limiter._key("person@example.com", "203.0.113.7")

    assert first == second
    assert first.startswith("login-attempt:v2:")
    assert len(first.removeprefix("login-attempt:v2:")) == 64
    assert "person@example.com" not in first
    assert "203.0.113.7" not in first


def test_lockout_key_separates_account_and_client_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(limiter_module, "get_settings", lambda: _settings(require_redis=False))
    monkeypatch.setattr(
        limiter_module.Redis,
        "from_url",
        lambda *_args, **_kwargs: _UnavailableRedis(),
    )
    limiter = limiter_module.LoginAttemptLimiter()

    base = limiter._key("person@example.com", "203.0.113.7")

    assert limiter._key("other@example.com", "203.0.113.7") != base
    assert limiter._key("person@example.com", "203.0.113.8") != base
    assert limiter._key("person@example.com", None) != base
