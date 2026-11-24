"""Cross-setting startup admission checks; called in the public model order."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from app.core.config.settings import Settings

_SettingsT = TypeVar("_SettingsT", bound="Settings")


def validate_identity_security_configuration(settings: _SettingsT) -> _SettingsT:
    """Reject ambiguous key rings and unsafe recovery-development controls."""

    rings = (
        (
            "IDENTITY_ACTION_HMAC",
            settings.identity_action_hmac_key_id,
            settings.identity_action_hmac_previous_keys,
        ),
        (
            "IDENTITY_MFA_ENCRYPTION",
            settings.identity_mfa_encryption_key_id,
            settings.identity_mfa_decryption_keys,
        ),
        (
            "IDENTITY_NOTIFICATION_ENCRYPTION",
            settings.identity_notification_encryption_key_id,
            settings.identity_notification_decryption_keys,
        ),
    )
    for label, active_key_id, previous_keys in rings:
        if active_key_id in previous_keys:
            raise ValueError(f"{label} active key ID must not also be a previous key")
        if len(previous_keys) > settings.identity_previous_key_limit:
            raise ValueError(f"{label} previous key ring exceeds IDENTITY_PREVIOUS_KEY_LIMIT")

    if settings.password_recovery_development_expose_token and not settings.is_development:
        raise ValueError(
            "PASSWORD_RECOVERY_DEVELOPMENT_EXPOSE_TOKEN is allowed only in development"
        )
    if settings.password_recovery_delivery_provider == "smtp":
        missing = []
        if not (settings.password_recovery_smtp_host or "").strip():
            missing.append("PASSWORD_RECOVERY_SMTP_HOST")
        if not (settings.password_recovery_smtp_sender or "").strip():
            missing.append("PASSWORD_RECOVERY_SMTP_SENDER")
        if missing:
            raise ValueError(
                "PASSWORD_RECOVERY_DELIVERY_PROVIDER=smtp requires " + ", ".join(missing)
            )
    return settings


def validate_dashboard_signing_secret(settings: _SettingsT) -> _SettingsT:
    """Reject weak shared signing keys outside local development."""

    if settings.app_env == "development":
        return settings

    secret = settings.app_secret_key.strip()
    if len(secret.encode("utf-8")) < 32:
        raise ValueError(
            "APP_SECRET_KEY must contain at least 32 bytes in staging and production"
        )

    normalized = re.sub(r"[^a-z0-9]+", "_", secret.casefold()).strip("_")
    if normalized.startswith("change_me") or normalized in {
        "password",
        "secret",
        "unit_test_secret",
    }:
        raise ValueError("APP_SECRET_KEY must not use a placeholder in staging or production")
    return settings
