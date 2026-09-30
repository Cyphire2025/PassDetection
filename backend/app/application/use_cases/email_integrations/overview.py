"""Canonical email readiness and summary semantics, without transport or I/O."""

from datetime import UTC, datetime
from typing import Literal, TypedDict

from app.core.config.settings import Settings

ACTIVE_CONNECTION_STATUSES = frozenset({"active", "failing", "paused"})
ACTIVE_REVIEW_STATUSES = frozenset({"open", "deferred"})


class EmailProviderReadiness(TypedDict):
    provider: Literal["gmail", "outlook"]
    label: str
    configured: bool


class EmailReadiness(TypedDict):
    enabled: bool
    sync_enabled: bool
    attachment_processing_enabled: bool
    auto_actions_enabled: bool
    ai_enabled: bool
    ai_notifications_enabled: bool
    providers: list[EmailProviderReadiness]


def secret_is_set(value: object) -> bool:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        secret = getter()
        return isinstance(secret, str) and bool(secret.strip())
    return isinstance(value, str) and bool(value.strip())


def provider_configured(settings: Settings, provider: str = "gmail") -> bool:
    if provider not in {"gmail", "outlook"}:
        return False
    credentials_ready = bool(
        getattr(settings, f"{provider}_oauth_client_id", None)
        and secret_is_set(getattr(settings, f"{provider}_oauth_client_secret", None))
        and getattr(settings, f"{provider}_oauth_redirect_uri", None)
    )
    return credentials_ready and secret_is_set(settings.email_token_encryption_key)


def email_readiness(settings: Settings) -> EmailReadiness:
    """Configuration presence only; never validates credentials against a provider."""
    return {"enabled": settings.email_integrations_enabled,
        "sync_enabled": settings.email_sync_enabled,
        "attachment_processing_enabled": settings.email_attachment_processing_enabled,
        "auto_actions_enabled": settings.email_auto_actions_enabled,
        "ai_enabled": settings.email_ai_runtime_ready,
        "ai_notifications_enabled": settings.email_ai_notifications_ready,
        "providers": [
            {"provider": "gmail", "label": "Gmail", "configured": provider_configured(settings, "gmail")},
            {"provider": "outlook", "label": "Microsoft Outlook", "configured": provider_configured(settings, "outlook")},
        ]}


def email_summary_day_start() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
