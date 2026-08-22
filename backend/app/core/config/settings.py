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

import ipaddress
import json
import re
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.security.mobile_offline_lease import (
    validate_mobile_offline_lease_signing_configuration,
)

_GEMINI_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WHATSAPP_API_VERSION_PATTERN = re.compile(r"^v[1-9][0-9]*\.0$")
_WHATSAPP_TEMPLATE_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,512}$")
_WHATSAPP_LANGUAGE_PATTERN = re.compile(r"^[a-z]{2,3}(?:_[A-Z]{2})?$")


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection settings."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 5432
    db: str = "passdetection"
    user: str = "passdetection_user"
    password: str = Field(..., description="Must be set via POSTGRES_PASSWORD env var")
    # One process owns one SQLAlchemy pool. API and background-worker profiles
    # are intentionally separate so Celery prefork concurrency cannot multiply
    # an API-sized pool across every child process.
    pool_profile: Literal["api", "worker"] = "api"
    api_pool_size: int = Field(default=8, ge=1, le=64)
    api_max_overflow: int = Field(default=2, ge=0, le=64)
    worker_pool_size: int = Field(default=1, ge=1, le=8)
    worker_max_overflow: int = Field(default=0, ge=0, le=8)
    pool_timeout_seconds: float = Field(default=5.0, ge=0.5, le=60.0)
    pool_recycle_seconds: int = Field(default=1_800, ge=60, le=86_400)
    server_max_connections: int = Field(default=100, ge=20, le=10_000)
    reserved_connections: int = Field(default=10, ge=5, le=1_000)
    api_connection_budget: int = Field(default=80, ge=5, le=10_000)

    @model_validator(mode="after")
    def validate_connection_reserve(self) -> Self:
        if self.reserved_connections >= self.server_max_connections:
            raise ValueError(
                "POSTGRES_RESERVED_CONNECTIONS must be lower than "
                "POSTGRES_SERVER_MAX_CONNECTIONS"
            )
        usable = self.server_max_connections - self.reserved_connections
        if self.api_connection_budget > usable:
            raise ValueError(
                "POSTGRES_API_CONNECTION_BUDGET cannot exceed the server capacity "
                "remaining after POSTGRES_RESERVED_CONNECTIONS"
            )
        return self

    @property
    def pool_size(self) -> int:
        return self.api_pool_size if self.pool_profile == "api" else self.worker_pool_size

    @property
    def max_overflow(self) -> int:
        return (
            self.api_max_overflow
            if self.pool_profile == "api"
            else self.worker_max_overflow
        )

    @property
    def maximum_process_connections(self) -> int:
        return self.pool_size + self.max_overflow

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


class MobileSettings(BaseSettings):
    """GC mobile authentication, OTP, and synchronization settings."""

    model_config = SettingsConfigDict(env_prefix="MOBILE_", env_file=".env", extra="ignore")

    enabled: bool = False
    jwt_secret_key: SecretStr | None = None
    jwt_issuer: str = Field(default="passdetection", min_length=3, max_length=120)
    jwt_audience: str = Field(default="gc-mobile", min_length=3, max_length=120)
    access_token_expire_minutes: int = Field(default=15, ge=5, le=60)
    refresh_token_expire_days: int = Field(default=30, ge=1, le=90)
    # Ed25519 is intentionally independent from the symmetric online access
    # token profile. Public verification keys are embedded in reviewed mobile
    # builds; the active PKCS8 private key remains backend-only.
    offline_lease_active_kid: str | None = Field(default=None, max_length=64)
    offline_lease_private_key_b64: SecretStr | None = None
    offline_lease_public_keys_json: str | None = Field(default=None, max_length=8_192)
    offline_lease_issuer: str = Field(
        default="passdetection-mobile-offline",
        min_length=3,
        max_length=120,
    )
    offline_lease_audience: str = Field(
        default="gc-mobile-offline",
        min_length=3,
        max_length=120,
    )
    offline_lease_ttl_minutes: int = Field(default=720, ge=5, le=1_440)
    otp_provider: Literal["disabled", "development", "whatsapp"] = "disabled"
    otp_development_code: SecretStr | None = None
    otp_ttl_seconds: int = Field(default=300, ge=60, le=900)
    otp_delivery_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=15, le=600)
    otp_max_attempts: int = Field(default=5, ge=1, le=10)
    otp_phone_limit_per_hour: int = Field(default=10, ge=1, le=100)
    otp_ip_limit_per_hour: int = Field(default=30, ge=1, le=1_000)
    otp_require_redis: bool = True
    sync_page_size: int = Field(default=200, ge=25, le=500)
    # Shared dashboard/API/mobile capacity contracts. These are deliberately
    # configurable, but one deployed environment must expose and enforce the
    # same values instead of allowing clients to discover a hard ceiling late.
    sync_max_incremental_changes: int = Field(default=10_000, ge=500, le=100_000)
    max_group_passengers: int = Field(default=10_000, ge=100, le=100_000)
    max_attendance_sessions_per_group: int = Field(
        default=10_000,
        ge=100,
        le=100_000,
    )
    # Redis pub/sub carries only lossy invalidation hints. The append-only
    # database cursor remains authoritative, so deployments may explicitly
    # choose a visible cursor-only degradation mode while repairing Redis.
    realtime_enabled: bool = False
    realtime_require_redis: bool = True
    realtime_heartbeat_seconds: int = Field(default=20, ge=5, le=60)
    realtime_idle_timeout_seconds: int = Field(default=65, ge=15, le=180)
    realtime_authorization_refresh_seconds: int = Field(default=60, ge=15, le=300)
    # These two values are process-local safety rails. Deployment-wide
    # admission is enforced by the Redis leases below.
    realtime_max_connections: int = Field(default=5_000, ge=100, le=50_000)
    # Keep handshake database work near the per-process SQL pool width. A much
    # larger value only moves a reconnect storm into the pool wait queue and
    # can starve ordinary dashboard/mobile requests.
    realtime_max_authenticating_connections: int = Field(default=32, ge=10, le=5_000)
    realtime_global_max_connections: int = Field(default=1_000, ge=100, le=50_000)
    realtime_global_max_authenticating_connections: int = Field(
        default=32,
        ge=10,
        le=5_000,
    )
    realtime_lease_ttl_seconds: int = Field(default=90, ge=30, le=300)
    realtime_lease_renew_interval_seconds: int = Field(default=20, ge=5, le=60)
    realtime_max_connections_per_session: int = Field(default=3, ge=1, le=10)
    realtime_max_trips_per_connection: int = Field(default=500, ge=1, le=5_000)
    realtime_max_pending_trips_per_connection: int = Field(default=64, ge=4, le=1_000)
    realtime_publish_queue_size: int = Field(default=20_000, ge=100, le=200_000)
    realtime_send_timeout_seconds: float = Field(default=5.0, ge=1.0, le=15.0)
    # App attestation is deliberately opt-in. ``monitor`` records fixed result
    # codes while preserving workflows; ``enforce`` denies only the explicitly
    # protected high-risk action when a server-verified proof is unavailable.
    app_integrity_mode: Literal["disabled", "monitor", "enforce"] = "disabled"
    app_integrity_challenge_ttl_seconds: int = Field(default=120, ge=30, le=300)
    app_integrity_require_redis: bool = True
    app_integrity_proof_max_bytes: int = Field(default=32_768, ge=4_096, le=65_536)
    play_integrity_package_name: str = Field(
        default="com.globalconnects.groupcompanion",
        min_length=3,
        max_length=255,
    )
    play_integrity_allowed_certificate_digests_json: str | None = Field(
        default=None,
        max_length=4_096,
    )
    play_integrity_require_licensed: bool = True
    play_integrity_required_device_verdict: Literal[
        "MEETS_BASIC_INTEGRITY",
        "MEETS_DEVICE_INTEGRITY",
        "MEETS_STRONG_INTEGRITY",
    ] = "MEETS_DEVICE_INTEGRITY"
    play_integrity_timeout_seconds: float = Field(default=8.0, ge=2.0, le=20.0)
    app_attest_team_id: str | None = Field(default=None, max_length=20)
    app_attest_bundle_id: str = Field(
        default="com.globalconnects.groupcompanion",
        min_length=3,
        max_length=255,
    )
    app_attest_environment: Literal["development", "production"] = "development"
    # Exact iOS 27+ App Attest extension allowlists. Keep them unset until an
    # environment has identified its real distribution lane and CFBundleVersion.
    app_attest_allowed_validation_categories_json: str | None = Field(
        default=None,
        max_length=64,
    )
    app_attest_allowed_bundle_versions_json: str | None = Field(
        default=None,
        max_length=2_048,
    )
    # Explicit production acknowledgement: the strict extension contract is
    # available only on iOS 27+, while this app still supports older iOS.
    app_attest_ios27_extension_rollout_confirmed: bool = False
    admin_page_size: int = Field(default=50, ge=10, le=100)
    common_document_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        ge=1024,
        le=100 * 1024 * 1024,
    )
    personal_document_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        ge=1024,
        le=25 * 1024 * 1024,
    )
    document_grant_ttl_seconds: int = Field(default=60, ge=30, le=300)
    push_provider: Literal["disabled", "expo"] = "disabled"
    push_access_token: SecretStr | None = None
    push_batch_size: int = Field(default=100, ge=1, le=100)
    push_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    push_dispatch_interval_seconds: int = Field(default=5, ge=1, le=300)
    push_max_send_attempts: int = Field(default=5, ge=1, le=10)
    push_retry_base_seconds: int = Field(default=5, ge=1, le=300)
    push_receipt_batch_size: int = Field(default=1_000, ge=1, le=1_000)
    push_receipt_initial_delay_seconds: int = Field(default=900, ge=60, le=3_600)
    push_receipt_poll_interval_seconds: int = Field(default=60, ge=15, le=900)
    push_receipt_max_attempts: int = Field(default=8, ge=1, le=24)
    push_receipt_max_age_hours: int = Field(default=23, ge=1, le=24)
    push_countdown_scan_interval_seconds: int = Field(default=900, ge=60, le=3_600)
    push_countdown_timezone: str = "Asia/Kolkata"
    push_countdown_send_hour: int = Field(default=9, ge=0, le=23)

    @field_validator(
        "jwt_secret_key",
        "offline_lease_private_key_b64",
        "otp_development_code",
        "push_access_token",
        mode="before",
    )
    @classmethod
    def normalize_optional_mobile_secrets(cls, value: object) -> object | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "offline_lease_active_kid",
        "offline_lease_public_keys_json",
        "play_integrity_allowed_certificate_digests_json",
        "app_attest_team_id",
        "app_attest_allowed_validation_categories_json",
        "app_attest_allowed_bundle_versions_json",
        mode="before",
    )
    @classmethod
    def normalize_optional_offline_lease_values(cls, value: object) -> object | None:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("offline_lease_issuer", "offline_lease_audience")
    @classmethod
    def validate_offline_lease_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,119}", normalized):
            raise ValueError(
                "Mobile offline lease issuer and audience must use a bounded ASCII identifier"
            )
        return normalized

    @field_validator("play_integrity_package_name", "app_attest_bundle_id")
    @classmethod
    def validate_mobile_app_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9_-]+)+", normalized):
            raise ValueError("Mobile app-integrity identifiers must be bounded package IDs")
        return normalized

    @field_validator("app_attest_team_id")
    @classmethod
    def validate_app_attest_team_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{10}", normalized):
            raise ValueError("MOBILE_APP_ATTEST_TEAM_ID must be a 10-character Apple team ID")
        return normalized

    @field_validator("app_attest_allowed_validation_categories_json")
    @classmethod
    def validate_app_attest_validation_categories(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "MOBILE_APP_ATTEST_ALLOWED_VALIDATION_CATEGORIES_JSON must be JSON"
            ) from exc
        if not isinstance(parsed, list) or not 1 <= len(parsed) <= 6:
            raise ValueError(
                "MOBILE_APP_ATTEST_ALLOWED_VALIDATION_CATEGORIES_JSON must contain "
                "1-6 categories"
            )
        categories: set[int] = set()
        for category in parsed:
            if (
                isinstance(category, bool)
                or not isinstance(category, int)
                or category not in {1, 2, 3, 4, 5, 6}
            ):
                raise ValueError(
                    "App Attest validation categories must be explicit Apple categories 1-6"
                )
            categories.add(category)
        return json.dumps(sorted(categories), separators=(",", ":"))

    @field_validator("app_attest_allowed_bundle_versions_json")
    @classmethod
    def validate_app_attest_bundle_versions(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "MOBILE_APP_ATTEST_ALLOWED_BUNDLE_VERSIONS_JSON must be JSON"
            ) from exc
        if not isinstance(parsed, list) or not 1 <= len(parsed) <= 64:
            raise ValueError(
                "MOBILE_APP_ATTEST_ALLOWED_BUNDLE_VERSIONS_JSON must contain "
                "1-64 versions"
            )
        versions: set[str] = set()
        for version in parsed:
            if not isinstance(version, str) or not re.fullmatch(
                r"[0-9]{1,8}(?:\.[0-9]{1,8}){0,2}",
                version,
            ):
                raise ValueError(
                    "App Attest bundle versions must be exact bounded CFBundleVersion values"
                )
            versions.add(version)
        return json.dumps(sorted(versions), separators=(",", ":"))

    @field_validator("play_integrity_allowed_certificate_digests_json")
    @classmethod
    def validate_play_certificate_digests(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON must be JSON"
            ) from exc
        if not isinstance(parsed, list) or not 1 <= len(parsed) <= 8:
            raise ValueError(
                "MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON must contain 1-8 digests"
            )
        for digest in parsed:
            if not isinstance(digest, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}=?", digest):
                raise ValueError("Play signing-certificate digests must be SHA-256 base64url values")
        return json.dumps(sorted(set(parsed)), separators=(",", ":"))

    @model_validator(mode="after")
    def validate_development_otp(self) -> Self:
        if self.otp_provider == "development" and self.otp_development_code is None:
            raise ValueError(
                "MOBILE_OTP_DEVELOPMENT_CODE is required for the development OTP provider"
            )
        return self

    @model_validator(mode="after")
    def validate_push_receipt_window(self) -> Self:
        if self.push_receipt_initial_delay_seconds >= self.push_receipt_max_age_hours * 3_600:
            raise ValueError(
                "MOBILE_PUSH_RECEIPT_INITIAL_DELAY_SECONDS must be shorter than "
                "MOBILE_PUSH_RECEIPT_MAX_AGE_HOURS"
            )
        return self

    @model_validator(mode="after")
    def validate_realtime_heartbeat_window(self) -> Self:
        if self.realtime_idle_timeout_seconds <= self.realtime_heartbeat_seconds * 2:
            raise ValueError(
                "MOBILE_REALTIME_IDLE_TIMEOUT_SECONDS must exceed two heartbeat intervals"
            )
        return self

    @model_validator(mode="after")
    def validate_realtime_capacity_leases(self) -> Self:
        if self.realtime_lease_ttl_seconds < self.realtime_lease_renew_interval_seconds * 3:
            raise ValueError(
                "MOBILE_REALTIME_LEASE_TTL_SECONDS must cover at least three renewal intervals"
            )
        return self

    @field_validator("push_countdown_timezone")
    @classmethod
    def validate_push_countdown_timezone(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError(
                "MOBILE_PUSH_COUNTDOWN_TIMEZONE must be a valid IANA timezone"
            ) from exc
        return normalized


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
    # Baked into release images from the source commit. Keeping this separate
    # from the marketing/API version makes mixed client/server deployments
    # immediately diagnosable without exposing configuration or secrets.
    app_revision: str = Field(
        default="unknown",
        min_length=7,
        max_length=64,
        pattern=r"^(?:unknown|[0-9a-f]{7,64})$",
    )
    app_name: str = "Global Connects Dashboard"

    api_v1_prefix: str = "/api/v1"
    backend_port: int = 8000
    # These counts are consumed by runtime commands and by the PostgreSQL
    # deployment-budget validator. Raising concurrency therefore cannot
    # silently multiply the number of process-local connection pools.
    web_concurrency: int = Field(default=4, ge=1, le=32)
    worker_concurrency: int = Field(default=2, ge=1, le=128)
    email_worker_concurrency: int = Field(default=2, ge=1, le=128)
    email_ai_worker_concurrency: int = Field(default=2, ge=1, le=128)

    allowed_origins: list[str] = ["http://localhost:3000"]
    # Only these direct peers may supply X-Real-IP. The production backend is
    # private to the Compose network and receives requests from Nginx on the
    # 172.16/12 bridge range. Loopback supports local reverse-proxy testing.
    trusted_proxy_networks: list[str] = ["127.0.0.0/8", "::1/128", "172.16.0.0/12"]

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

    @field_validator("trusted_proxy_networks")
    @classmethod
    def validate_trusted_proxy_networks(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            network = ipaddress.ip_network(str(item).strip(), strict=False)
            normalized.append(network.with_prefixlen)
        if not normalized:
            raise ValueError("TRUSTED_PROXY_NETWORKS must contain at least one CIDR")
        return normalized

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

    @field_validator("gemini_model")
    @classmethod
    def validate_gemini_model(cls, value: str) -> str:
        normalized = value.strip()
        if not _GEMINI_MODEL_PATTERN.fullmatch(normalized):
            raise ValueError("GEMINI_MODEL contains invalid characters")
        return normalized

    @field_validator("email_ai_default_timezone")
    @classmethod
    def validate_email_ai_default_timezone(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("EMAIL_AI_DEFAULT_TIMEZONE must be a valid IANA timezone") from exc
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
    # Credential lockouts must remain global across every API worker in
    # production.  Development and isolated tests can opt into the bounded
    # in-process fallback explicitly, but a Redis outage must never silently
    # weaken the production authentication boundary.
    login_lockout_require_redis: bool = True
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

    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_api_version: str = "v25.0"
    whatsapp_template_language: str = "en_US"
    whatsapp_welcome_template_name: str = ""
    whatsapp_passport_link_template_name: str = ""
    whatsapp_reminder_template_name: str = "reminder_v1"
    whatsapp_document_template_name: str = "documents_v1"
    whatsapp_qr_template_name: str = "qrcode_v1"
    whatsapp_otp_template_name: str = ""
    whatsapp_otp_template_language: str = "en_US"
    whatsapp_delivery_concurrency: int = Field(default=4, ge=1, le=16)
    whatsapp_webhook_verify_token: str | None = None
    whatsapp_app_secret: str | None = None

    @field_validator("whatsapp_api_version")
    @classmethod
    def validate_whatsapp_api_version(cls, value: str) -> str:
        normalized = value.strip()
        if not _WHATSAPP_API_VERSION_PATTERN.fullmatch(normalized):
            raise ValueError("WHATSAPP_API_VERSION must use the form v25.0")
        return normalized

    @field_validator("whatsapp_phone_number_id")
    @classmethod
    def validate_whatsapp_phone_number_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized and not normalized.isascii():
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID must contain ASCII digits")
        if normalized and not normalized.isdigit():
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID must contain ASCII digits")
        return normalized or None

    @field_validator("whatsapp_otp_template_name")
    @classmethod
    def validate_whatsapp_otp_template_name(cls, value: str) -> str:
        normalized = value.strip()
        if normalized and not _WHATSAPP_TEMPLATE_NAME_PATTERN.fullmatch(normalized):
            raise ValueError(
                "WHATSAPP_OTP_TEMPLATE_NAME must contain only lowercase letters, "
                "numbers, and underscores"
            )
        return normalized

    @field_validator("whatsapp_otp_template_language")
    @classmethod
    def validate_whatsapp_otp_template_language(cls, value: str) -> str:
        normalized = value.strip()
        if not _WHATSAPP_LANGUAGE_PATTERN.fullmatch(normalized):
            raise ValueError(
                "WHATSAPP_OTP_TEMPLATE_LANGUAGE must be an approved Meta language code"
            )
        return normalized

    @model_validator(mode="after")
    def validate_mobile_otp_configuration(self) -> Self:
        mobile = self.mobile
        if self.is_production and mobile.otp_provider == "development":
            raise ValueError("MOBILE_OTP_PROVIDER=development is forbidden when APP_ENV=production")
        if mobile.otp_provider != "whatsapp":
            return self

        missing: list[str] = []
        if not (self.whatsapp_access_token or "").strip():
            missing.append("WHATSAPP_ACCESS_TOKEN")
        if not (self.whatsapp_phone_number_id or "").strip():
            missing.append("WHATSAPP_PHONE_NUMBER_ID")
        if not self.whatsapp_otp_template_name:
            missing.append("WHATSAPP_OTP_TEMPLATE_NAME")
        if missing:
            raise ValueError("MOBILE_OTP_PROVIDER=whatsapp requires " + ", ".join(missing))
        return self

    @model_validator(mode="after")
    def validate_database_connection_budget(self) -> Self:
        """Fail staging/production before process pools can exceed PostgreSQL."""

        if self.app_env == "development":
            return self
        database = self.database
        api_per_process = database.api_pool_size + database.api_max_overflow
        api_claim = self.web_concurrency * api_per_process
        if api_claim > database.api_connection_budget:
            raise ValueError(
                "WEB_CONCURRENCY multiplied by the API PostgreSQL pool exceeds "
                "POSTGRES_API_CONNECTION_BUDGET"
            )
        background_processes = (
            self.worker_concurrency
            + self.email_worker_concurrency
            + self.email_ai_worker_concurrency
            + self.gemini_extraction_max_concurrency
            + self.gemini_verification_max_concurrency
            + self.gemini_image_edit_max_concurrency
            + 1  # Celery Beat scheduler process.
        )
        worker_per_process = database.worker_pool_size + database.worker_max_overflow
        total_claim = api_claim + (background_processes * worker_per_process)
        usable = database.server_max_connections - database.reserved_connections
        if total_claim > usable:
            raise ValueError(
                "Configured API and background process pools can claim "
                f"{total_claim} PostgreSQL connections, exceeding the usable "
                f"deployment budget of {usable}"
            )
        return self

    @model_validator(mode="after")
    def validate_dashboard_signing_secret(self) -> Self:
        """Reject weak shared signing keys outside local development."""

        if self.app_env == "development":
            return self

        secret = self.app_secret_key.strip()
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
        return self

    @model_validator(mode="after")
    def validate_mobile_production_signing_secret(self) -> Self:
        """Fail startup before a weak production mobile signing key can be used."""

        mobile = self.mobile
        if not (self.is_production and mobile.enabled):
            return self
        configured = mobile.jwt_secret_key
        secret = configured.get_secret_value() if configured is not None else ""
        if len(secret.encode("utf-8")) < 32:
            raise ValueError(
                "MOBILE_JWT_SECRET_KEY must contain at least 32 bytes when the mobile API "
                "is enabled in production"
            )
        return self

    @model_validator(mode="after")
    def validate_mobile_offline_lease_signing_keys(self) -> Self:
        """Fail closed outside development when mobile offline auth cannot be verified."""

        mobile = self.mobile
        if self.app_env == "development" or not mobile.enabled:
            return self
        private_key_b64 = (
            mobile.offline_lease_private_key_b64.get_secret_value().strip()
            if mobile.offline_lease_private_key_b64 is not None
            else None
        )
        validate_mobile_offline_lease_signing_configuration(
            active_kid=mobile.offline_lease_active_kid,
            private_key_b64=private_key_b64,
            public_keys_json=mobile.offline_lease_public_keys_json,
        )
        return self

    @model_validator(mode="after")
    def validate_mobile_verified_link_configuration(self) -> Self:
        """Keep the production Android association document available and exact."""

        mobile = self.mobile
        if not (self.is_production and mobile.enabled):
            return self
        if mobile.play_integrity_package_name != "com.globalconnects.groupcompanion":
            raise ValueError(
                "MOBILE_PLAY_INTEGRITY_PACKAGE_NAME must equal the production Android "
                "package com.globalconnects.groupcompanion"
            )
        if mobile.play_integrity_allowed_certificate_digests_json is None:
            raise ValueError(
                "MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON is required "
                "for production Android verified links"
            )
        return self

    @model_validator(mode="after")
    def validate_mobile_app_integrity_configuration(self) -> Self:
        """Reject an enforcement rollout that lacks cross-worker/provider bindings."""

        mobile = self.mobile
        if mobile.app_integrity_mode == "disabled" or not mobile.enabled:
            return self
        if mobile.app_integrity_mode == "enforce" and not mobile.app_integrity_require_redis:
            raise ValueError(
                "MOBILE_APP_INTEGRITY_REQUIRE_REDIS must be true when integrity is enforced"
            )
        if not self.is_production or mobile.app_integrity_mode != "enforce":
            return self
        if mobile.play_integrity_allowed_certificate_digests_json is None:
            raise ValueError(
                "MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON is required "
                "for production enforcement"
            )
        if mobile.app_attest_team_id is None:
            raise ValueError(
                "MOBILE_APP_ATTEST_TEAM_ID is required for production enforcement"
            )
        if mobile.app_attest_environment != "production":
            raise ValueError(
                "MOBILE_APP_ATTEST_ENVIRONMENT must be production for production enforcement"
            )
        if not mobile.app_attest_ios27_extension_rollout_confirmed:
            raise ValueError(
                "MOBILE_APP_ATTEST_IOS27_EXTENSION_ROLLOUT_CONFIRMED must be true "
                "only after the iOS 27 minimum-version or adoption gate is complete"
            )
        if mobile.app_attest_allowed_validation_categories_json is None:
            raise ValueError(
                "MOBILE_APP_ATTEST_ALLOWED_VALIDATION_CATEGORIES_JSON is required "
                "for production enforcement"
            )
        allowed_categories: object = json.loads(
            mobile.app_attest_allowed_validation_categories_json
        )
        if not isinstance(allowed_categories, list) or not set(allowed_categories).issubset(
            {2, 4, 5}
        ):
            raise ValueError(
                "Production iOS App Attest categories must be TestFlight, App Store, "
                "or approved enterprise/ad-hoc distribution (2, 4, or 5)"
            )
        if mobile.app_attest_allowed_bundle_versions_json is None:
            raise ValueError(
                "MOBILE_APP_ATTEST_ALLOWED_BUNDLE_VERSIONS_JSON is required "
                "for production enforcement"
            )
        return self

    @model_validator(mode="after")
    def validate_email_ai_lease_duration(self) -> Self:
        minimum_lease = (2 * self.email_ai_analysis_timeout_seconds) + 30
        if self.email_ai_lease_seconds < minimum_lease:
            raise ValueError(
                "EMAIL_AI_LEASE_SECONDS must cover two bounded analysis "
                "attempts plus a 30-second safety margin"
            )
        return self

    @property
    def email_ai_runtime_ready(self) -> bool:
        """Whether workers may send mailbox content to the configured AI."""

        api_key = (
            self.google_api_key.get_secret_value().strip()
            if self.google_api_key is not None
            else ""
        )
        return bool(
            self.email_integrations_enabled
            and self.email_sync_enabled
            and self.email_ai_enabled
            and api_key
        )

    @property
    def email_ai_notifications_ready(self) -> bool:
        return bool(self.email_ai_runtime_ready and self.email_ai_notifications_enabled)

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
    def mobile(self) -> MobileSettings:
        return MobileSettings()

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
