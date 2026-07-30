"""
Global Connects Dashboard - Application Settings
=============================================
Single source of truth for all configuration.
Uses pydantic-settings for:
  - Automatic environment variable loading
  - Type coercion and validation
  - No hardcoded secrets anywhere in the codebase
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_GEMINI_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection settings."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 5432
    db: str = "passdetection"
    user: str = "passdetection_user"
    password: str = Field(..., description="Must be set via POSTGRES_PASSWORD env var")

    @computed_field  # type: ignore[misc]
    @property
    def async_url(self) -> str:
        """Async DSN used by SQLAlchemy + asyncpg at runtime."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"

    @computed_field  # type: ignore[misc]
    @property
    def sync_url(self) -> str:
        """Sync DSN used by Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"
        )


class RedisSettings(BaseSettings):
    """Redis connection settings."""

    model_config = SettingsConfigDict(env_prefix="REDIS_", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 6379
    password: str = ""
    db: int = 0

    @computed_field  # type: ignore[misc]
    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class JWTSettings(BaseSettings):
    """JWT authentication settings."""

    model_config = SettingsConfigDict(env_prefix="JWT_", env_file=".env", extra="ignore")

    # The application uses one symmetric signing profile. Keeping this a
    # literal prevents an environment change from activating an unreviewed
    # JOSE/ECDSA implementation.
    algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    access_cookie_name: str = "access_token"
    refresh_cookie_name: str = "refresh_token"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    login_lockout_max_attempts: int = Field(default=5, ge=1, le=20)
    login_lockout_window_seconds: int = Field(default=900, ge=60, le=86_400)
    login_lockout_seconds: int = Field(default=900, ge=60, le=86_400)


class S3Settings(BaseSettings):
    """S3-compatible object storage settings."""

    model_config = SettingsConfigDict(env_prefix="S3_", env_file=".env", extra="ignore")

    endpoint_url: str | None = None
    public_endpoint_url: str | None = None
    access_key_id: str = Field(..., description="Must be set via S3_ACCESS_KEY_ID")
    secret_access_key: str = Field(..., description="Must be set via S3_SECRET_ACCESS_KEY")
    bucket_name: str = "passdetection-passports"
    region: str = "us-east-1"
    presigned_url_expiry_seconds: int = 3600
    connect_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    read_timeout_seconds: float = Field(default=10.0, ge=1.0, le=120.0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    max_pool_connections: int = Field(default=64, ge=10, le=512)


class MRZSettings(BaseSettings):
    """MRZ strip reader tuning."""

    model_config = SettingsConfigDict(env_prefix="MRZ_", env_file=".env", extra="ignore")

    timeout_seconds: float = Field(default=3.0, ge=0.5, le=30.0)


class Settings(BaseSettings):
    """
    Root application settings.

    All child settings objects are composed here so the entire
    application has a single, consistent configuration surface.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "staging", "production"] = "development"
    app_secret_key: str = Field(..., description="Must be set via APP_SECRET_KEY")
    app_debug: bool = False
    app_version: str = "1.0.0"
    app_name: str = "Global Connects Dashboard"

    api_v1_prefix: str = "/api/v1"
    backend_port: int = 8000

    allowed_origins: list[str] = ["http://localhost:3000"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return []

            if normalized.startswith("["):
                parsed = json.loads(normalized)
                if not isinstance(parsed, list):
                    raise ValueError(
                        "ALLOWED_ORIGINS must be a JSON array or comma-separated string"
                    )
                return [str(origin).strip() for origin in parsed if str(origin).strip()]

            return [origin.strip() for origin in normalized.split(",") if origin.strip()]

        return value

    @field_validator(
        "gemini_image_edit_model",
        "gemini_image_edit_fallback_model",
        mode="before",
    )
    @classmethod
    def validate_gemini_image_model(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Gemini image model names must be strings")
        normalized = value.strip()
        if normalized and not _GEMINI_MODEL_PATTERN.fullmatch(normalized):
            raise ValueError("Gemini image model names contain invalid characters")
        return normalized

    @field_validator("email_oauth_frontend_return_url")
    @classmethod
    def validate_email_oauth_frontend_return_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError(
                "EMAIL_OAUTH_FRONTEND_RETURN_URL must be an absolute HTTP(S) URL "
                "without embedded credentials or a fragment"
            )
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

    # Anonymous/non-dashboard API fallback. Authenticated dashboard traffic is
    # keyed by the verified JWT subject below so staff behind one office NAT do
    # not consume a shared bucket.
    rate_limit_per_minute: int = Field(default=60, ge=0, le=100_000)
    dashboard_rate_limit_per_minute: int = Field(
        default=5_000,
        ge=0,
        le=100_000,
    )
    # A short token bucket sits in front of the minute allowance so one noisy
    # account cannot monopolize the shared dashboard edge lane. The capacity
    # admits normal page-load bursts while the refill rate bounds sustained
    # pressure from one verified account.
    dashboard_rate_limit_per_second: int = Field(default=50, ge=0, le=10_000)
    dashboard_rate_limit_burst: int = Field(default=150, ge=0, le=100_000)
    # Protected image streams use an independent budget. A DOCS view can load
    # many authorized images without consuming the staff member's dashboard
    # action allowance, while still retaining a bounded abuse guard.
    dashboard_media_rate_limit_per_minute: int = Field(
        default=30_000,
        ge=0,
        le=100_000,
    )
    dashboard_media_rate_limit_per_second: int = Field(default=30, ge=0, le=10_000)
    dashboard_media_rate_limit_burst: int = Field(default=60, ge=0, le=100_000)
    # Per Gunicorn worker. The cache contains only metadata-stripped dashboard
    # thumbnails and never changes the original files or database rows.
    dashboard_thumbnail_max_dimension: int = Field(default=320, ge=128, le=1_024)
    dashboard_thumbnail_cache_max_bytes: int = Field(
        default=16 * 1024 * 1024,
        ge=1024 * 1024,
        le=512 * 1024 * 1024,
    )
    dashboard_rate_limit_require_redis: bool = True
    public_upload_bootstrap_session_rate_limit_per_minute: int = Field(
        default=30,
        ge=1,
        le=10_000,
    )
    public_upload_bootstrap_aggregate_rate_limit_per_minute: int = Field(
        default=600,
        ge=100,
        le=100_000,
    )
    public_upload_session_rate_limit_per_minute: int = Field(default=6, ge=1, le=1_000)
    public_upload_aggregate_rate_limit_per_minute: int = Field(
        default=180,
        ge=100,
        le=100_000,
    )
    public_upload_followup_session_rate_limit_per_minute: int = Field(
        default=120,
        ge=1,
        le=10_000,
    )
    public_upload_followup_aggregate_rate_limit_per_minute: int = Field(
        default=6_000,
        ge=100,
        le=100_000,
    )
    public_upload_rate_limit_require_redis: bool = True
    sentry_dsn: str | None = None
    processing_backend: Literal["background", "celery"] = "background"
    processing_job_max_attempts: int = Field(default=3, ge=1, le=10)
    processing_job_timeout_seconds: int = Field(default=45, ge=15, le=300)
    passport_local_extraction_timeout_seconds: float = Field(default=10.0, ge=1.0, le=10.0)
    processing_watchdog_delay_seconds: float = Field(default=8.0, ge=3.0, le=30.0)
    processing_worker_ping_timeout_seconds: float = Field(default=1.0, ge=0.2, le=5.0)
    processing_worker_readiness_cache_seconds: float = Field(
        default=15.0,
        ge=1.0,
        le=300.0,
    )
    roi_field_timeout_seconds: float = Field(default=8.0, ge=0.5, le=30.0)
    roi_max_concurrency: int = Field(default=4, ge=1, le=8)
    upload_max_file_size_bytes: int = Field(default=10 * 1024 * 1024, ge=1024 * 1024)
    upload_max_pixels: int = Field(default=24_000_000, ge=1_000_000)
    malware_scanner_enabled: bool = False
    malware_scanner_host: str = "localhost"
    malware_scanner_port: int = Field(default=3310, ge=1, le=65535)
    malware_scanner_timeout_seconds: float = Field(default=2.0, ge=0.2, le=10.0)
    ocr_cache_ttl_seconds: int = Field(default=3600, ge=0)
    google_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_verification_enabled: bool = True
    gemini_model: str = "gemini-3.5-flash"
    gemini_fallback_model: str = "gemini-3.1-flash-lite"
    gemini_image_edit_model: str = "gemini-3.1-flash-image"
    gemini_image_edit_fallback_model: str = "gemini-3-pro-image"
    gemini_image_edit_attempt_timeout_seconds: float = Field(
        default=120.0,
        ge=15.0,
        le=300.0,
    )
    gemini_image_edit_timeout_seconds: float = Field(
        default=300.0,
        ge=60.0,
        le=600.0,
    )
    gemini_image_edit_job_max_attempts: int = Field(default=2, ge=1, le=3)
    gemini_image_edit_max_concurrency: int = Field(default=1, ge=1, le=4)
    gemini_api_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_project_alias: str = Field(
        default="unconfigured",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    gemini_config_version: str = Field(
        default="v1",
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    gemini_timeout_seconds: float = Field(default=30.0, ge=1.0, le=60.0)
    gemini_max_retries: int = Field(default=1, ge=0, le=1)
    gemini_max_output_tokens: int = Field(default=512, ge=128, le=1024)
    gemini_extraction_max_concurrency: int = Field(default=32, ge=1, le=64)
    gemini_verification_max_concurrency: int = Field(default=1, ge=1, le=64)
    gemini_extraction_timeout_ms: int = Field(
        default=30_000,
        ge=1_000,
        le=300_000,
    )
    gemini_extraction_quiet_period_ms: int = Field(
        default=2_000,
        ge=0,
        le=300_000,
    )
    gemini_retry_max_attempts: int = Field(default=3, ge=1, le=10)
    gemini_priority_capacity_calibrated: bool = False

    # Email integrations ship dormant. Each higher-risk capability has a
    # separate switch so a connection cannot unexpectedly activate background
    # mailbox access, attachment processing, link retrieval, or auto-actions.
    email_integrations_enabled: bool = False
    email_sync_enabled: bool = False
    email_attachment_processing_enabled: bool = False
    email_link_retrieval_enabled: bool = False
    email_auto_actions_enabled: bool = False
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

    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_api_version: str = "v25.0"
    whatsapp_template_language: str = "en_US"
    whatsapp_welcome_template_name: str = ""
    whatsapp_passport_link_template_name: str = ""
    whatsapp_reminder_template_name: str = "reminder_v1"
    whatsapp_document_template_name: str = "documents_v1"
    whatsapp_qr_template_name: str = "qrcode_v1"
    whatsapp_webhook_verify_token: str | None = None
    whatsapp_app_secret: str | None = None

    @computed_field(repr=False)  # type: ignore[misc]
    @property
    def database(self) -> DatabaseSettings:
        return DatabaseSettings()

    @computed_field(repr=False)  # type: ignore[misc]
    @property
    def redis(self) -> RedisSettings:
        return RedisSettings()

    @computed_field(repr=False)  # type: ignore[misc]
    @property
    def jwt(self) -> JWTSettings:
        return JWTSettings()

    @computed_field(repr=False)  # type: ignore[misc]
    @property
    def s3(self) -> S3Settings:
        return S3Settings()

    @computed_field(repr=False)  # type: ignore[misc]
    @property
    def mrz(self) -> MRZSettings:
        return MRZSettings()

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return Settings()
