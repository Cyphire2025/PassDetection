from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config.settings import DatabaseSettings, MobileSettings, Settings

_STRONG_APP_SECRET = "9Wv!mR3#kP7@xN2$zQ8&bL5^tY4*cH6+"


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "app_secret_key": _STRONG_APP_SECRET,
        "web_concurrency": 4,
        "worker_concurrency": 2,
        "email_worker_concurrency": 2,
        "email_ai_worker_concurrency": 2,
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
