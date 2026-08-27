from __future__ import annotations

from typing import Literal

import pytest
from pydantic import ValidationError

from app.core.config.settings import DatabaseSettings, MobileSettings, RedisSettings, Settings

_STRONG_APP_SECRET = "9Wv!mR3#kP7@xN2$zQ8&bL5^tY4*cH6+"


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "app_secret_key": _STRONG_APP_SECRET,
        "web_concurrency": 4,
        "worker_concurrency": 2,
        "email_worker_concurrency": 2,
        "email_ai_worker_concurrency": 2,
        "my_photos_worker_concurrency": 2,
        "gemini_extraction_max_concurrency": 32,
        "gemini_verification_max_concurrency": 1,
        "gemini_image_edit_max_concurrency": 1,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_default_database_profiles_are_bounded_for_four_api_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "unit-test-password")
    monkeypatch.setenv("POSTGRES_API_POOL_SIZE", "8")
    monkeypatch.setenv("POSTGRES_API_MAX_OVERFLOW", "2")
    monkeypatch.setenv("POSTGRES_WORKER_POOL_SIZE", "1")
    monkeypatch.setenv("POSTGRES_WORKER_MAX_OVERFLOW", "0")
    monkeypatch.setenv("POSTGRES_SERVER_MAX_CONNECTIONS", "100")
    monkeypatch.setenv("POSTGRES_RESERVED_CONNECTIONS", "10")
    monkeypatch.setenv("POSTGRES_API_CONNECTION_BUDGET", "80")
    monkeypatch.setenv("MOBILE_ENABLED", "false")

    settings = _production_settings()
    database = settings.database

    assert settings.web_concurrency * (database.api_pool_size + database.api_max_overflow) == 40
    assert database.server_max_connections - database.reserved_connections == 90
    assert (
        DatabaseSettings(
            password="test",
            pool_profile="worker",
            _env_file=None,
        ).maximum_process_connections
        == 1
    )


def test_api_process_pool_budget_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "unit-test-password")
    monkeypatch.setenv("POSTGRES_API_POOL_SIZE", "20")
    monkeypatch.setenv("POSTGRES_API_MAX_OVERFLOW", "10")
    monkeypatch.setenv("POSTGRES_API_CONNECTION_BUDGET", "80")
    monkeypatch.setenv("MOBILE_ENABLED", "false")

    with pytest.raises(ValidationError, match="POSTGRES_API_CONNECTION_BUDGET"):
        _production_settings()


def test_database_deadlines_are_profile_specific_and_bounded() -> None:
    api = DatabaseSettings(
        password="test",
        pool_profile="api",
        api_statement_timeout_ms=12_000,
        worker_statement_timeout_ms=240_000,
        lock_timeout_ms=4_000,
        idle_in_transaction_session_timeout_ms=20_000,
        _env_file=None,
    )
    worker = DatabaseSettings(
        password="test",
        pool_profile="worker",
        api_statement_timeout_ms=12_000,
        worker_statement_timeout_ms=240_000,
        lock_timeout_ms=4_000,
        idle_in_transaction_session_timeout_ms=20_000,
        _env_file=None,
    )

    assert api.statement_timeout_ms == 12_000
    assert worker.statement_timeout_ms == 240_000
    assert api.lock_timeout_ms == worker.lock_timeout_ms == 4_000
    assert api.idle_in_transaction_session_timeout_ms == 20_000


@pytest.mark.parametrize("pool_profile", ["api", "worker"])
def test_database_lock_timeout_cannot_outlive_statement_timeout(
    pool_profile: Literal["api", "worker"],
) -> None:
    with pytest.raises(ValidationError, match="LOCK_TIMEOUT_MS"):
        DatabaseSettings(
            password="test",
            pool_profile=pool_profile,
            api_statement_timeout_ms=4_000,
            worker_statement_timeout_ms=4_000,
            lock_timeout_ms=5_000,
            _env_file=None,
        )


def test_redis_domains_fall_back_to_one_escaped_development_endpoint() -> None:
    redis = RedisSettings(
        host="localhost",
        port=6379,
        password="test:p@ss/word",
        db=3,
        _env_file=None,
    )

    assert redis.url == "redis://:test%3Ap%40ss%2Fword@localhost:6379/3"
    assert redis.broker_url == redis.url
    assert redis.security_url == redis.url
    assert redis.realtime_url == redis.url
    assert redis.cache_url == redis.url
    assert "test:p@ss/word" not in repr(redis)


def test_redis_domain_isolation_requires_explicit_distinct_protected_endpoints() -> None:
    values: dict[str, object] = {
        "domain_isolation_required": True,
        "broker_host": "redis-broker",
        "broker_password": "broker-secret",
        "security_host": "redis-security",
        "security_password": "security-secret",
        "realtime_host": "redis-realtime",
        "realtime_password": "realtime-secret",
        "cache_host": "redis-cache",
        "cache_password": "cache-secret",
        "_env_file": None,
    }
    redis = RedisSettings(**values)  # type: ignore[arg-type]

    assert redis.broker_url == "redis://:broker-secret@redis-broker:6379/0"
    assert redis.security_url == "redis://:security-secret@redis-security:6379/0"
    assert redis.realtime_url == "redis://:realtime-secret@redis-realtime:6379/0"
    assert redis.cache_url == "redis://:cache-secret@redis-cache:6379/0"

    duplicate = dict(values)
    duplicate["cache_host"] = "redis-realtime"
    with pytest.raises(ValidationError, match="endpoints must be distinct"):
        RedisSettings(**duplicate)  # type: ignore[arg-type]

    missing_password = dict(values)
    missing_password["security_password"] = ""
    with pytest.raises(ValidationError, match="REDIS_SECURITY_PASSWORD"):
        RedisSettings(**missing_password)  # type: ignore[arg-type]


def test_aggregate_background_pool_budget_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "unit-test-password")
    monkeypatch.setenv("POSTGRES_API_POOL_SIZE", "8")
    monkeypatch.setenv("POSTGRES_API_MAX_OVERFLOW", "2")
    monkeypatch.setenv("POSTGRES_WORKER_POOL_SIZE", "1")
    monkeypatch.setenv("POSTGRES_WORKER_MAX_OVERFLOW", "0")
    monkeypatch.setenv("POSTGRES_SERVER_MAX_CONNECTIONS", "100")
    monkeypatch.setenv("POSTGRES_RESERVED_CONNECTIONS", "10")
    monkeypatch.setenv("MOBILE_ENABLED", "false")

    with pytest.raises(ValidationError, match="exceeding the usable deployment budget"):
        _production_settings(gemini_extraction_max_concurrency=64)


def test_required_metrics_exporter_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "unit-test-password")
    monkeypatch.setenv("MOBILE_ENABLED", "false")

    with pytest.raises(ValidationError, match="METRICS_EXPORTER=statsd"):
        _production_settings(
            metrics_export_required=True,
            metrics_exporter="disabled",
        )

    settings = _production_settings(
        metrics_export_required=True,
        metrics_exporter="statsd",
        metrics_statsd_host="metrics-exporter",
    )
    assert settings.metrics_statsd_port == 9125


def test_realtime_global_limits_and_lease_window_are_validated() -> None:
    # A deployment-wide ceiling may legitimately exceed one process-local
    # safety rail when sockets are spread over multiple replicas.
    settings = MobileSettings(
        realtime_max_connections=100,
        realtime_global_max_connections=10_000,
        _env_file=None,
    )
    assert settings.realtime_global_max_connections == 10_000
    with pytest.raises(ValidationError, match="three renewal intervals"):
        MobileSettings(
            realtime_lease_ttl_seconds=30,
            realtime_lease_renew_interval_seconds=20,
            _env_file=None,
        )
