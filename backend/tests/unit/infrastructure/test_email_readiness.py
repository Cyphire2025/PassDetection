from __future__ import annotations

from unittest.mock import Mock

from cryptography.fernet import Fernet

from app.core.config.settings import Settings
from app.infrastructure.ai_priority.worker_readiness import (
    CachedCeleryQueueProbe,
    CeleryQueueSnapshot,
)
from app.infrastructure.email.readiness import (
    EMAIL_INTEGRATION_QUEUE,
    email_runtime_readiness,
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_secret_key": "unit-test-secret",
        "app_env": "production",
        "processing_backend": "celery",
        "email_integrations_enabled": True,
        "email_sync_enabled": True,
        "gmail_oauth_client_id": "client-id",
        "gmail_oauth_client_secret": "client-secret",
        "gmail_oauth_redirect_uri": "https://api.example.test/oauth/callback",
        "email_token_encryption_key": Fernet.generate_key().decode("ascii"),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _queue_probe(*queues: str) -> CachedCeleryQueueProbe:
    return CachedCeleryQueueProbe(
        query=lambda _timeout: CeleryQueueSnapshot(
            available_queues=frozenset(queues),
            control_reachable=True,
        )
    )


def test_disabled_email_feature_skips_runtime_dependencies() -> None:
    heartbeat = Mock(side_effect=AssertionError("heartbeat must not be queried"))
    scanner = Mock(side_effect=AssertionError("scanner must not be queried"))

    checks, ready = email_runtime_readiness(
        _settings(email_integrations_enabled=False),
        heartbeat_probe=heartbeat,
        scanner_probe=scanner,
    )

    assert ready is True
    assert checks["email_worker"] == "not_required_feature_disabled"
    heartbeat.assert_not_called()
    scanner.assert_not_called()


def test_enabled_sync_requires_worker_and_recent_scheduler_heartbeat() -> None:
    checks, ready = email_runtime_readiness(
        _settings(),
        queue_probe=_queue_probe(EMAIL_INTEGRATION_QUEUE),
        heartbeat_probe=lambda _settings: True,
    )

    assert ready is True
    assert checks["email_provider_configuration"] == "configured"
    assert checks["email_worker"] == "available"
    assert checks["email_scheduler"] == "heartbeat_recent"

    checks, ready = email_runtime_readiness(
        _settings(),
        queue_probe=_queue_probe(),
        heartbeat_probe=lambda _settings: True,
    )

    assert ready is False
    assert checks["email_worker"] == "queue_not_consumed"


def test_attachment_processing_allows_optional_scanner_to_be_disabled() -> None:
    checks, ready = email_runtime_readiness(
        _settings(email_attachment_processing_enabled=True),
        queue_probe=_queue_probe(EMAIL_INTEGRATION_QUEUE),
        heartbeat_probe=lambda _settings: True,
    )

    assert ready is True
    assert checks["email_malware_scanner"] == "disabled_optional"


def test_enabled_attachment_scanner_must_be_reachable() -> None:
    checks, ready = email_runtime_readiness(
        _settings(
            email_attachment_processing_enabled=True,
            malware_scanner_enabled=True,
        ),
        queue_probe=_queue_probe(EMAIL_INTEGRATION_QUEUE),
        heartbeat_probe=lambda _settings: True,
        scanner_probe=lambda _settings: True,
    )

    assert ready is True
    assert checks["email_malware_scanner"] == "available"

    checks, ready = email_runtime_readiness(
        _settings(
            email_attachment_processing_enabled=True,
            malware_scanner_enabled=True,
        ),
        queue_probe=_queue_probe(EMAIL_INTEGRATION_QUEUE),
        heartbeat_probe=lambda _settings: True,
        scanner_probe=lambda _settings: False,
    )

    assert ready is False
    assert checks["email_malware_scanner"] == "unreachable"
