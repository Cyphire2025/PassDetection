"""Readiness checks for the opt-in email integration runtime."""

from __future__ import annotations

import socket
from collections.abc import Callable

from redis import Redis

from app.application.interfaces.email_provider import EmailProviderError
from app.core.config.settings import Settings
from app.infrastructure.ai_priority.worker_readiness import (
    CachedCeleryQueueProbe,
    celery_queue_readiness,
)
from app.infrastructure.email.gmail_provider import GmailEmailProvider
from app.infrastructure.email.oauth import generate_oauth_state, generate_pkce_pair
from app.infrastructure.email.outlook_provider import OutlookEmailProvider
from app.infrastructure.email.token_encryption import EmailTokenCipher, TokenEncryptionError

EMAIL_INTEGRATION_QUEUE = "email_integrations"
EMAIL_SCHEDULER_HEARTBEAT_KEY = "passdetection:email:scheduler-heartbeat:v1"

HeartbeatProbe = Callable[[Settings], bool]
ScannerProbe = Callable[[Settings], bool]


def email_runtime_readiness(
    settings: Settings,
    *,
    queue_probe: CachedCeleryQueueProbe | None = None,
    heartbeat_probe: HeartbeatProbe | None = None,
    scanner_probe: ScannerProbe | None = None,
) -> tuple[dict[str, str], bool]:
    """Return provider, worker, scheduler, and scanner readiness."""

    if not settings.email_integrations_enabled:
        return (
            {
                "email_provider_configuration": "not_required_feature_disabled",
                "email_worker": "not_required_feature_disabled",
                "email_scheduler": "not_required_feature_disabled",
                "email_malware_scanner": "not_required_feature_disabled",
            },
            True,
        )

    provider_ready = _provider_configuration_ready(settings)
    checks = {
        "email_provider_configuration": (
            "configured" if provider_ready else "invalid_or_incomplete"
        )
    }
    overall_ready = provider_ready

    if settings.email_sync_enabled:
        worker_status, worker_ready = celery_queue_readiness(
            EMAIL_INTEGRATION_QUEUE,
            settings,
            probe=queue_probe,
        )
        scheduler_ready = (heartbeat_probe or _scheduler_heartbeat_exists)(settings)
        checks["email_worker"] = worker_status
        checks["email_scheduler"] = "heartbeat_recent" if scheduler_ready else "heartbeat_missing"
        overall_ready = overall_ready and worker_ready and scheduler_ready
    else:
        checks["email_worker"] = "not_required_sync_disabled"
        checks["email_scheduler"] = "not_required_sync_disabled"

    if settings.email_attachment_processing_enabled:
        if settings.malware_scanner_enabled:
            scanner_ready = (scanner_probe or _clamav_ping)(settings)
            scanner_status = "available" if scanner_ready else "unreachable"
            overall_ready = overall_ready and scanner_ready
        else:
            scanner_status = "disabled_optional"
        checks["email_malware_scanner"] = scanner_status
    else:
        checks["email_malware_scanner"] = "not_required_processing_disabled"

    return checks, overall_ready


def _provider_configuration_ready(settings: Settings) -> bool:
    if not settings.email_token_encryption_key:
        return False
    try:
        EmailTokenCipher.from_settings(settings)
        pkce = generate_pkce_pair()
        configured_providers = []
        if (
            settings.gmail_oauth_client_id
            and settings.gmail_oauth_client_secret
            and settings.gmail_oauth_client_secret.get_secret_value().strip()
            and settings.gmail_oauth_redirect_uri
        ):
            configured_providers.append(GmailEmailProvider(settings=settings))
        if (
            settings.outlook_oauth_client_id
            and settings.outlook_oauth_client_secret
            and settings.outlook_oauth_client_secret.get_secret_value().strip()
            and settings.outlook_oauth_redirect_uri
        ):
            configured_providers.append(OutlookEmailProvider(settings=settings))
        if not configured_providers:
            return False
        state = generate_oauth_state()
        for provider in configured_providers:
            provider.build_authorization_url(
                state=state,
                code_challenge=pkce.challenge,
            )
    except (EmailProviderError, TokenEncryptionError, TypeError, ValueError):
        return False
    return True


def _scheduler_heartbeat_exists(settings: Settings) -> bool:
    timeout = settings.processing_worker_ping_timeout_seconds
    client = Redis.from_url(
        settings.redis.url,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
        decode_responses=True,
    )
    try:
        return bool(client.get(EMAIL_SCHEDULER_HEARTBEAT_KEY))
    except Exception:
        return False
    finally:
        client.close()  # type: ignore[no-untyped-call]


def _clamav_ping(settings: Settings) -> bool:
    try:
        with socket.create_connection(
            (settings.malware_scanner_host, settings.malware_scanner_port),
            timeout=settings.malware_scanner_timeout_seconds,
        ) as connection:
            connection.settimeout(settings.malware_scanner_timeout_seconds)
            connection.sendall(b"zPING\0")
            return connection.recv(32).rstrip(b"\0\r\n") == b"PONG"
    except OSError:
        return False
