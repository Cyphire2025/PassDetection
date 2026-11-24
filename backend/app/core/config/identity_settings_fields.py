"""Versioned identity/storage keys, recovery and offline retention settings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings


class IdentitySettingsFields(BaseSettings):
    """Flat environment fields composed into the public Settings model."""

    # Dedicated, versioned encryption for durable document-cleanup tombstones.
    # When unset, version 1 derives from APP_SECRET_KEY for zero-downtime
    # adoption.  Set an explicit active key plus the previous version in the
    # decryption keyring before rotating either secret.
    storage_cleanup_encryption_key: SecretStr | None = Field(default=None, repr=False)
    storage_cleanup_encryption_key_version: int = Field(default=1, ge=1, le=1_000_000)
    storage_cleanup_decryption_keys: dict[int, SecretStr] = Field(
        default_factory=dict,
        repr=False,
    )

    # Workforce identity keys are deliberately independent from one another.
    # Unset active keys retain the pre-rotation APP_SECRET_KEY derivation for a
    # backward-compatible first rollout; operators can then introduce an
    # explicit current key and a bounded previous-key ring.
    identity_action_hmac_key_id: str = Field(
        default="legacy-v1",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    identity_action_hmac_key: SecretStr | None = Field(default=None, repr=False)
    identity_action_hmac_previous_keys: dict[str, SecretStr] = Field(
        default_factory=dict,
        repr=False,
    )
    identity_mfa_encryption_key_id: str = Field(
        default="legacy-v1",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    identity_mfa_encryption_key: SecretStr | None = Field(default=None, repr=False)
    identity_mfa_decryption_keys: dict[str, SecretStr] = Field(
        default_factory=dict,
        repr=False,
    )
    identity_notification_encryption_key_id: str = Field(
        default="legacy-v1",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    identity_notification_encryption_key: SecretStr | None = Field(default=None, repr=False)
    identity_notification_decryption_keys: dict[str, SecretStr] = Field(
        default_factory=dict,
        repr=False,
    )
    identity_previous_key_limit: int = Field(default=3, ge=0, le=8)
    password_recovery_token_ttl_minutes: int = Field(default=20, ge=5, le=60)
    password_recovery_delivery_provider: Literal["disabled", "development", "smtp"] = "development"
    password_recovery_development_expose_token: bool = False
    password_recovery_frontend_url: str = "http://localhost:3000/auth/recover"
    password_recovery_smtp_host: str | None = None
    password_recovery_smtp_port: int = Field(default=587, ge=1, le=65_535)
    password_recovery_smtp_username: str | None = None
    password_recovery_smtp_password: SecretStr | None = Field(default=None, repr=False)
    password_recovery_smtp_sender: str | None = None
    password_recovery_smtp_starttls: bool = True
    password_recovery_delivery_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    password_recovery_delivery_max_attempts: int = Field(default=5, ge=1, le=20)
    password_recovery_delivery_batch_size: int = Field(default=50, ge=1, le=200)
    password_recovery_account_limit_per_hour: int = Field(default=5, ge=1, le=20)
    password_recovery_tenant_limit_per_hour: int = Field(default=100, ge=10, le=2_000)
    password_recovery_ip_limit_per_hour: int = Field(default=20, ge=5, le=200)
    password_recovery_rate_limit_require_redis: bool = True
    identity_token_retention_days: int = Field(default=30, ge=1, le=365)
    identity_consumed_token_retention_days: int = Field(default=7, ge=1, le=90)
    identity_challenge_retention_days: int = Field(default=7, ge=1, le=90)
    identity_retention_batch_size: int = Field(default=500, ge=10, le=5_000)
    mfa_step_up_max_attempts: int = Field(default=5, ge=2, le=20)
    mfa_step_up_window_seconds: int = Field(default=300, ge=60, le=3_600)
    mfa_step_up_lock_seconds: int = Field(default=300, ge=30, le=3_600)
    attendance_runtime_retention_days: int = Field(default=90, ge=7, le=730)
    attendance_runtime_registration_days: int = Field(default=45, ge=1, le=180)
    attendance_discard_retention_days: int = Field(default=365, ge=30, le=3_650)
    attendance_discard_batch_size: int = Field(default=100, ge=1, le=200)
    browser_offline_authorization_ttl_minutes: int = Field(
        default=720,
        ge=15,
        le=10_080,
    )
    browser_offline_max_suspension_seconds: int = Field(
        default=43_200,
        ge=60,
        le=604_800,
    )
