"""OAuth return and connection-action policy helpers for email integrations."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException, status

from app.core.config.settings import Settings
from app.infrastructure.database.email_models import EmailConnectionModel


def _provider_configured(settings: Settings, provider: str = "gmail") -> bool:
    if provider == "gmail":
        credentials_ready = bool(
            getattr(settings, "gmail_oauth_client_id", None)
            and _secret_is_set(getattr(settings, "gmail_oauth_client_secret", None))
            and getattr(settings, "gmail_oauth_redirect_uri", None)
        )
    elif provider == "outlook":
        credentials_ready = bool(
            getattr(settings, "outlook_oauth_client_id", None)
            and _secret_is_set(getattr(settings, "outlook_oauth_client_secret", None))
            and getattr(settings, "outlook_oauth_redirect_uri", None)
        )
    else:
        return False
    return credentials_ready and _secret_is_set(settings.email_token_encryption_key)


def _provider_scopes(provider: str) -> list[str]:
    if provider == "outlook":
        return [
            "openid",
            "profile",
            "offline_access",
            "https://graph.microsoft.com/User.Read",
            "https://graph.microsoft.com/Mail.Read",
        ]
    return ["https://www.googleapis.com/auth/gmail.readonly"]


def _secret_is_set(value: object) -> bool:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        secret = getter()
        return isinstance(secret, str) and bool(secret.strip())
    return isinstance(value, str) and bool(value.strip())


def _require_feature(settings: Settings) -> None:
    if not settings.email_integrations_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email integrations are not enabled for this deployment.",
        )


def _oauth_return_url(settings: Settings, outcome: str, provider: str = "gmail") -> str:
    allowed = {"connected", "reconnected", "cancelled", "denied", "failed"}
    safe_outcome = outcome if outcome in allowed else "failed"
    parsed = urlsplit(settings.email_oauth_frontend_return_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in {"code", "state", "error", "email_oauth", "email_provider"}
    ]
    query.append(("email_oauth", safe_outcome))
    query.append(("email_provider", provider if provider in {"gmail", "outlook"} else "gmail"))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _allowed_connection_actions(
    connection: EmailConnectionModel,
    settings: Settings,
) -> list[str]:
    reconnect_available = settings.email_integrations_enabled and _provider_configured(
        settings,
        connection.provider,
    )
    sync_available = settings.email_integrations_enabled and settings.email_sync_enabled
    if connection.status == "paused":
        actions = ["resume"] if sync_available else []
        if reconnect_available:
            actions.append("reconnect")
        actions.extend(["disconnect", "remove"])
        return actions
    if connection.status in {"expired", "disconnected"}:
        actions = ["reconnect"] if reconnect_available else []
        actions.extend(["disconnect", "remove"])
        return actions
    if connection.status == "disconnecting":
        return ["disconnect", "remove"]
    actions = ["sync"] if sync_available else []
    actions.append("pause")
    if reconnect_available:
        actions.append("reconnect")
    actions.extend(["disconnect", "remove"])
    return actions


def _email_removal_confirmation_matches(
    *,
    confirmation_email: str,
    connection_email: str,
) -> bool:
    """Require the operator to type the exact selected mailbox address."""

    return confirmation_email.strip().casefold() == connection_email.strip().casefold()
