"""Mailbox, OAuth, analysis and retention settings."""

from __future__ import annotations

from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings


class EmailSettingsFields(BaseSettings):
    """Flat environment fields composed into the public Settings model."""

    # Email integrations ship dormant. Each higher-risk capability has a
    # separate switch so a connection cannot unexpectedly activate background
    # mailbox access, attachment processing, link retrieval, or auto-actions.
    email_integrations_enabled: bool = False
    email_sync_enabled: bool = False
    email_attachment_processing_enabled: bool = False
    email_link_retrieval_enabled: bool = False
    email_auto_actions_enabled: bool = False
    email_ai_enabled: bool = False
    email_ai_notifications_enabled: bool = False
    email_ai_analysis_timeout_seconds: float = Field(default=30.0, ge=1.0, le=60.0)
    email_ai_max_input_chars: int = Field(default=16_000, ge=1_000, le=50_000)
    email_ai_max_output_tokens: int = Field(default=2_048, ge=256, le=8_192)
    email_ai_max_candidates: int = Field(default=24, ge=1, le=24)
    email_ai_lease_seconds: int = Field(default=180, ge=30, le=3_600)
    email_ai_max_attempts: int = Field(default=3, ge=1, le=10)
    email_ai_max_manual_retries: int = Field(default=3, ge=0, le=10)
    email_ai_max_inflight: int = Field(default=4, ge=1, le=20)
    email_ai_auto_confidence_threshold: float = Field(default=0.9, ge=0.0, le=1.0)
    email_ai_deadline_confidence_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
    )
    email_ai_deadline_notification_window_days: int = Field(
        default=14,
        ge=1,
        le=30,
    )
    email_ai_default_timezone: str = "UTC"
    email_token_encryption_key: SecretStr | None = Field(default=None, repr=False)
    email_token_encryption_key_version: int = Field(default=1, ge=1, le=1_000_000)
    email_token_decryption_keys: dict[int, SecretStr] = Field(
        default_factory=dict,
        repr=False,
    )
    email_oauth_frontend_return_url: str = "http://localhost:3000/email-integrations"
    gmail_oauth_client_id: str | None = None
    gmail_oauth_client_secret: SecretStr | None = Field(default=None, repr=False)
    gmail_oauth_redirect_uri: str | None = None
    outlook_oauth_client_id: str | None = None
    outlook_oauth_client_secret: SecretStr | None = Field(default=None, repr=False)
    outlook_oauth_redirect_uri: str | None = None
    outlook_oauth_tenant: str = Field(
        default="common",
        min_length=4,
        max_length=64,
        pattern=(
            r"^(?:common|organizations|consumers|"
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
        ),
    )
    email_oauth_state_ttl_seconds: int = Field(default=600, ge=120, le=1_800)
    email_sync_interval_seconds: int = Field(default=15, ge=15, le=86_400)
    email_sync_lease_seconds: int = Field(default=300, ge=30, le=3_600)
    email_sync_full_lookback_days: int = Field(default=7, ge=1, le=90)
    email_sync_max_messages: int = Field(default=500, ge=1, le=5_000)
    email_attachment_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        ge=1024 * 1024,
        le=100 * 1024 * 1024,
    )
    email_pdf_max_pages: int = Field(default=100, ge=1, le=500)
    email_max_artifacts_per_message: int = Field(default=100, ge=1, le=500)
    email_content_retention_days: int = Field(default=30, ge=1, le=3_650)
    email_storage_orphan_grace_hours: int = Field(default=24, ge=1, le=168)

    @field_validator("email_ai_default_timezone")
    @classmethod
    def validate_email_ai_default_timezone(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("EMAIL_AI_DEFAULT_TIMEZONE must be a valid IANA timezone") from exc
        return normalized

    @field_validator(
        "gmail_oauth_redirect_uri",
        "outlook_oauth_redirect_uri",
        mode="before",
    )
    @classmethod
    def validate_email_provider_oauth_redirect_uri(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Email provider OAuth redirect URI must be a string")
        normalized = value.strip()
        if not normalized:
            return None
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError(
                "Email provider OAuth redirect URI must be an absolute HTTP(S) URL "
                "without credentials or a fragment"
            )
        return normalized
