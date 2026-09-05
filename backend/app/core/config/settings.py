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
from typing import Callable, Literal, Self, TypeVar, cast
from urllib.parse import quote, urlsplit
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
_S3_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_KMS_KEY_ARN_PATTERN = re.compile(
    r"^arn:(aws|aws-us-gov|aws-cn):kms:([a-z0-9-]+):([0-9]{12}):"
    r"key/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)

_SettingsValue = TypeVar("_SettingsValue", bound=BaseSettings)


def _validate_s3_bucket_name(value: str) -> None:
    if (
        _S3_BUCKET_PATTERN.fullmatch(value) is None
        or ".." in value
        or ".-" in value
        or "-." in value
    ):
        raise ValueError("My Photos AWS bucket names must use normalized S3 DNS syntax")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return
    raise ValueError("My Photos AWS bucket names cannot be formatted as IP addresses")


def _validate_kms_key_arn(value: str, *, region: str) -> str:
    match = _KMS_KEY_ARN_PATTERN.fullmatch(value)
    expected_partition = (
        "aws-cn" if region.startswith("cn-") else "aws-us-gov" if "-gov-" in region else "aws"
    )
    if match is None or match.group(1) != expected_partition or match.group(2) != region:
        raise ValueError(
            "My Photos KMS keys must be canonical key ARNs in the configured AWS region"
        )
    return match.group(3)


def _load_environment_settings(settings_type: type[_SettingsValue]) -> _SettingsValue:
    """Keep pydantic-settings environment construction visible to strict typing."""

    factory = cast(Callable[[], _SettingsValue], settings_type)
    return factory()


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
    api_statement_timeout_ms: int = Field(default=15_000, ge=1_000, le=60_000)
    worker_statement_timeout_ms: int = Field(default=300_000, ge=1_000, le=900_000)
    lock_timeout_ms: int = Field(default=5_000, ge=100, le=30_000)
    idle_in_transaction_session_timeout_ms: int = Field(
        default=30_000,
        ge=1_000,
        le=120_000,
    )
    server_max_connections: int = Field(default=100, ge=20, le=10_000)
    reserved_connections: int = Field(default=10, ge=5, le=1_000)
    api_connection_budget: int = Field(default=80, ge=5, le=10_000)

    @model_validator(mode="after")
    def validate_connection_reserve(self) -> Self:
        if self.reserved_connections >= self.server_max_connections:
            raise ValueError(
                "POSTGRES_RESERVED_CONNECTIONS must be lower than POSTGRES_SERVER_MAX_CONNECTIONS"
            )
        usable = self.server_max_connections - self.reserved_connections
        if self.api_connection_budget > usable:
            raise ValueError(
                "POSTGRES_API_CONNECTION_BUDGET cannot exceed the server capacity "
                "remaining after POSTGRES_RESERVED_CONNECTIONS"
            )
        if self.pool_profile == "api" and self.lock_timeout_ms > self.api_statement_timeout_ms:
            raise ValueError(
                "POSTGRES_LOCK_TIMEOUT_MS cannot exceed POSTGRES_API_STATEMENT_TIMEOUT_MS"
            )
        if (
            self.pool_profile == "worker"
            and self.lock_timeout_ms > self.worker_statement_timeout_ms
        ):
            raise ValueError(
                "POSTGRES_LOCK_TIMEOUT_MS cannot exceed POSTGRES_WORKER_STATEMENT_TIMEOUT_MS"
            )
        return self

    @property
    def pool_size(self) -> int:
        return self.api_pool_size if self.pool_profile == "api" else self.worker_pool_size

    @property
    def max_overflow(self) -> int:
        return self.api_max_overflow if self.pool_profile == "api" else self.worker_max_overflow

    @property
    def maximum_process_connections(self) -> int:
        return self.pool_size + self.max_overflow

    @property
    def statement_timeout_ms(self) -> int:
        return (
            self.api_statement_timeout_ms
            if self.pool_profile == "api"
            else self.worker_statement_timeout_ms
        )

    @computed_field  # type: ignore[prop-decorator]  # Pydantic computed property
    @property
    def async_url(self) -> str:
        """Async DSN used by SQLAlchemy + asyncpg at runtime."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"

    @computed_field  # type: ignore[prop-decorator]  # Pydantic computed property
    @property
    def sync_url(self) -> str:
        """Sync DSN used by Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"
        )


class RedisSettings(BaseSettings):
    """Redis connections partitioned by durability and eviction semantics.

    The legacy endpoint remains the development fallback. Production Compose
    enables ``domain_isolation_required`` and supplies four independent
    endpoints so broker pressure cannot weaken login throttles, realtime fanout,
    or evictable OCR caches.
    """

    model_config = SettingsConfigDict(env_prefix="REDIS_", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 6379
    username: str | None = None
    password: SecretStr = Field(default=SecretStr(""), repr=False)
    db: int = Field(default=0, ge=0, le=15)
    domain_isolation_required: bool = False

    broker_host: str | None = None
    broker_port: int | None = Field(default=None, ge=1, le=65_535)
    broker_username: str | None = None
    broker_password: SecretStr | None = Field(default=None, repr=False)
    broker_db: int | None = Field(default=None, ge=0, le=15)

    security_host: str | None = None
    security_port: int | None = Field(default=None, ge=1, le=65_535)
    security_username: str | None = None
    security_password: SecretStr | None = Field(default=None, repr=False)
    security_db: int | None = Field(default=None, ge=0, le=15)

    realtime_host: str | None = None
    realtime_port: int | None = Field(default=None, ge=1, le=65_535)
    realtime_username: str | None = None
    realtime_password: SecretStr | None = Field(default=None, repr=False)
    realtime_db: int | None = Field(default=None, ge=0, le=15)

    cache_host: str | None = None
    cache_port: int | None = Field(default=None, ge=1, le=65_535)
    cache_username: str | None = None
    cache_password: SecretStr | None = Field(default=None, repr=False)
    cache_db: int | None = Field(default=None, ge=0, le=15)

    @staticmethod
    def _normalized_host(value: str, *, field_name: str) -> str:
        normalized = value.strip()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError(f"{field_name} must be a non-empty host without whitespace")
        return normalized

    @field_validator(
        "host",
        "broker_host",
        "security_host",
        "realtime_host",
        "cache_host",
        mode="before",
    )
    @classmethod
    def validate_redis_host(cls, value: object, info: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Redis hosts must be strings")
        field_name = getattr(info, "field_name", "Redis host")
        return cls._normalized_host(value, field_name=str(field_name).upper())

    @staticmethod
    def _secret_value(value: SecretStr | None, fallback: SecretStr) -> str:
        selected = value if value is not None else fallback
        return selected.get_secret_value()

    @staticmethod
    def _connection_url(
        *,
        host: str,
        port: int,
        username: str | None,
        password: str,
        db: int,
    ) -> str:
        encoded_password = quote(password, safe="")
        if username:
            encoded_username = quote(username.strip(), safe="")
            credentials = encoded_username
            if password:
                credentials += f":{encoded_password}"
            authority = f"{credentials}@"
        elif password:
            authority = f":{encoded_password}@"
        else:
            authority = ""
        return f"redis://{authority}{host}:{port}/{db}"

    def _domain_endpoint(
        self,
        domain: Literal["broker", "security", "realtime", "cache"],
    ) -> tuple[str, int, str | None, str, int]:
        host = getattr(self, f"{domain}_host") or self.host
        port = getattr(self, f"{domain}_port") or self.port
        username = getattr(self, f"{domain}_username")
        if username is None:
            username = self.username
        password = self._secret_value(getattr(self, f"{domain}_password"), self.password)
        database = getattr(self, f"{domain}_db")
        if database is None:
            database = self.db
        return host, port, username, password, database

    def _domain_url(self, domain: Literal["broker", "security", "realtime", "cache"]) -> str:
        host, port, username, password, database = self._domain_endpoint(domain)
        return self._connection_url(
            host=host,
            port=port,
            username=username,
            password=password,
            db=database,
        )

    @model_validator(mode="after")
    def validate_domain_isolation(self) -> Self:
        if not self.domain_isolation_required:
            return self
        domains: tuple[Literal["broker", "security", "realtime", "cache"], ...] = (
            "broker",
            "security",
            "realtime",
            "cache",
        )
        missing_hosts = [domain for domain in domains if getattr(self, f"{domain}_host") is None]
        if missing_hosts:
            raise ValueError(
                "REDIS_DOMAIN_ISOLATION_REQUIRED needs explicit hosts for: "
                + ", ".join(missing_hosts)
            )
        endpoints: dict[tuple[str, int, int], str] = {}
        for domain in domains:
            host, port, _username, password, database = self._domain_endpoint(domain)
            if not password:
                raise ValueError(
                    f"REDIS_{domain.upper()}_PASSWORD is required when domain isolation is enabled"
                )
            endpoint = (host.casefold(), port, database)
            previous = endpoints.setdefault(endpoint, domain)
            if previous != domain:
                raise ValueError(
                    "Redis domain endpoints must be distinct; "
                    f"{previous} and {domain} resolve to the same host, port, and database"
                )
        return self

    @property
    def url(self) -> str:
        """Legacy compatibility endpoint; never serialized with model data."""

        return self._connection_url(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password.get_secret_value(),
            db=self.db,
        )

    @property
    def broker_url(self) -> str:
        return self._domain_url("broker")

    @property
    def security_url(self) -> str:
        return self._domain_url("security")

    @property
    def realtime_url(self) -> str:
        return self._domain_url("realtime")

    @property
    def cache_url(self) -> str:
        return self._domain_url("cache")


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
                "MOBILE_APP_ATTEST_ALLOWED_VALIDATION_CATEGORIES_JSON must contain 1-6 categories"
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
            raise ValueError("MOBILE_APP_ATTEST_ALLOWED_BUNDLE_VERSIONS_JSON must be JSON") from exc
        if not isinstance(parsed, list) or not 1 <= len(parsed) <= 64:
            raise ValueError(
                "MOBILE_APP_ATTEST_ALLOWED_BUNDLE_VERSIONS_JSON must contain 1-64 versions"
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
                raise ValueError(
                    "Play signing-certificate digests must be SHA-256 base64url values"
                )
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


class MyPhotosSettings(BaseSettings):
    """Fail-closed provider, matching, pagination, and job policy for My Photos."""

    model_config = SettingsConfigDict(env_prefix="MY_PHOTOS_", env_file=".env", extra="ignore")

    liveness_provider: Literal["disabled", "development", "aws_rekognition"] = "disabled"
    face_search_provider: Literal["disabled", "development", "aws_rekognition"] = "disabled"
    media_provider: Literal["disabled", "development", "s3"] = "disabled"
    development_fixtures_enabled: bool = False
    development_scenario: Literal[
        "success",
        "rejected",
        "expired",
        "cancelled",
        "throttled",
        "unavailable",
        "no_face",
        "multiple_faces",
        "no_matches",
        "partial_matches",
    ] = "success"
    consent_version: str = Field(default="my-photos-biometric-v1", min_length=3, max_length=64)
    liveness_session_ttl_seconds: int = Field(default=180, ge=30, le=300)
    liveness_provider_claim_seconds: int = Field(default=30, ge=10, le=120)
    liveness_provider_timeout_seconds: int = Field(default=20, ge=1, le=60)
    provider_audit_image_retention_enabled: bool = False
    # A production reference may be needed by later gallery revisions. The
    # value remains disabled by default and must align with the reviewed trip/
    # enrollment window plus the output bucket lifecycle.
    reference_frame_retention_seconds: int = Field(default=0, ge=0, le=31_536_000)
    liveness_confidence_threshold: float = Field(default=90.0, ge=0.0, le=100.0)
    maximum_liveness_attempts: int = Field(default=5, ge=1, le=20)
    liveness_cooldown_seconds: int = Field(default=900, ge=30, le=86_400)
    page_size: int = Field(default=48, ge=12, le=60)
    maximum_page_size: int = Field(default=60, ge=12, le=100)
    best_match_threshold: float = Field(default=92.0, ge=0.0, le=100.0)
    possible_match_threshold: float = Field(default=80.0, ge=0.0, le=100.0)
    match_config_version: str = Field(default="uncalibrated-v1", min_length=3, max_length=64)
    # The provider adapter may internally paginate, but the domain result must
    # not silently truncate a passenger's matches below a full V1 gallery.
    maximum_search_results: int = Field(default=5_000, ge=1, le=5_000)
    job_batch_size: int = Field(default=100, ge=10, le=500)
    index_max_failure_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    job_max_attempts: int = Field(default=5, ge=1, le=20)
    # Celery's My Photos hard envelope is 75 seconds; the durable lease must
    # outlive it so a killed task cannot race its redelivery finalizer.
    job_lease_seconds: int = Field(default=120, ge=90, le=900)
    face_search_provider_timeout_seconds: int = Field(default=20, ge=1, le=60)
    job_retry_base_seconds: int = Field(default=5, ge=1, le=60)
    job_retry_max_seconds: int = Field(default=300, ge=30, le=3_600)
    provider_retry_after_seconds: int = Field(default=30, ge=1, le=3_600)
    provider_deletion_batch_size: int = Field(default=25, ge=1, le=100)
    provider_deletion_concurrency: int = Field(default=4, ge=1, le=8)
    provider_deletion_max_attempts: int = Field(default=10, ge=1, le=20)
    provider_deletion_claim_seconds: int = Field(default=180, ge=30, le=300)
    recovery_batch_size: int = Field(default=100, ge=10, le=500)
    delivery_authorization_ttl_seconds: int = Field(default=300, ge=60, le=900)
    delivery_claim_seconds: int = Field(default=60, ge=15, le=300)
    delivery_authorization_concurrency: int = Field(default=4, ge=1, le=8)
    media_provider_timeout_seconds: int = Field(default=20, ge=1, le=60)
    maximum_delivery_batch: int = Field(default=50, ge=1, le=100)
    development_fixture_asset_count: int = Field(default=5_000, ge=5_000, le=5_000)
    development_fixture_match_count: int = Field(default=57, ge=57, le=57)

    # Production AWS values are deliberately unset. Selecting an AWS adapter
    # without every required scope/retention/credential-broker value fails
    # validation before any provider client is constructed.
    aws_region: str | None = Field(
        default=None,
        min_length=3,
        max_length=32,
        pattern=r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$",
    )
    aws_liveness_output_bucket: str | None = Field(default=None, min_length=3, max_length=63)
    aws_liveness_output_prefix: str = Field(
        default="my-photos/liveness",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9!_.*'()/-]*$",
    )
    aws_liveness_kms_key_id: str | None = Field(default=None, min_length=1, max_length=2_048)
    aws_liveness_audit_images_limit: int = Field(default=0, ge=0, le=4)
    native_temporary_credentials_mode: Literal["disabled", "cognito_identity_pool"] = "disabled"
    aws_cognito_identity_pool_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[a-z]{2}(?:-gov)?-[a-z]+-\d:[0-9a-f-]{36}$",
    )
    aws_media_bucket: str | None = Field(default=None, min_length=3, max_length=63)
    aws_media_kms_key_id: str | None = Field(default=None, min_length=1, max_length=2_048)
    aws_media_key_prefix: str = Field(
        default="my-photos/media",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9!_.*'()/-]*$",
    )
    aws_s3_endpoint_url: str | None = Field(default=None, min_length=8, max_length=512)
    aws_s3_addressing_style: Literal["auto", "virtual", "path"] = "auto"
    aws_expected_bucket_owner: str | None = Field(
        default=None,
        min_length=12,
        max_length=12,
        pattern=r"^[0-9]{12}$",
    )
    aws_collection_prefix: str = Field(
        default="pd-my-photos",
        min_length=1,
        max_length=48,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    # Scope derivation is deliberately separate from opaque-reference signing:
    # changing it requires an explicit collection/object migration. Reference
    # signing can rotate normally through the bounded previous-key ring.
    aws_scope_hmac_secret: SecretStr | None = Field(default=None, repr=False)
    aws_provider_hmac_key_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    aws_provider_hmac_secret: SecretStr | None = Field(default=None, repr=False)
    aws_provider_hmac_previous_keys: dict[str, SecretStr] = Field(
        default_factory=dict,
        repr=False,
    )
    aws_index_quality_filter: Literal["NONE", "LOW", "MEDIUM", "HIGH", "AUTO"] = "AUTO"
    aws_index_max_faces_per_asset: int = Field(default=100, ge=1, le=100)
    aws_index_concurrency: int = Field(default=4, ge=1, le=8)
    aws_search_quality_filter: Literal["NONE", "LOW", "MEDIUM", "HIGH", "AUTO"] = "AUTO"
    aws_connect_timeout_seconds: float = Field(default=3.0, ge=0.5, le=10.0)
    aws_read_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    aws_max_attempts: int = Field(default=3, ge=1, le=5)
    aws_max_pool_connections: int = Field(default=16, ge=4, le=64)

    @model_validator(mode="after")
    def validate_thresholds_and_pages(self) -> Self:
        if self.possible_match_threshold >= self.best_match_threshold:
            raise ValueError(
                "MY_PHOTOS_POSSIBLE_MATCH_THRESHOLD must be lower than "
                "MY_PHOTOS_BEST_MATCH_THRESHOLD"
            )
        if self.page_size > self.maximum_page_size:
            raise ValueError("MY_PHOTOS_PAGE_SIZE cannot exceed MY_PHOTOS_MAXIMUM_PAGE_SIZE")
        if self.job_retry_base_seconds > self.job_retry_max_seconds:
            raise ValueError(
                "MY_PHOTOS_JOB_RETRY_BASE_SECONDS cannot exceed MY_PHOTOS_JOB_RETRY_MAX_SECONDS"
            )
        if self.liveness_provider_timeout_seconds >= self.liveness_provider_claim_seconds:
            raise ValueError(
                "MY_PHOTOS_LIVENESS_PROVIDER_TIMEOUT_SECONDS must be shorter than "
                "MY_PHOTOS_LIVENESS_PROVIDER_CLAIM_SECONDS"
            )
        if self.face_search_provider_timeout_seconds >= self.job_lease_seconds:
            raise ValueError(
                "MY_PHOTOS_FACE_SEARCH_PROVIDER_TIMEOUT_SECONDS must be shorter than "
                "MY_PHOTOS_JOB_LEASE_SECONDS"
            )
        if self.media_provider_timeout_seconds >= self.delivery_claim_seconds:
            raise ValueError(
                "MY_PHOTOS_MEDIA_PROVIDER_TIMEOUT_SECONDS must be shorter than "
                "MY_PHOTOS_DELIVERY_CLAIM_SECONDS"
            )
        if self.face_search_provider_timeout_seconds > 60:
            raise ValueError("My Photos face-search timeout exceeds the worker envelope")
        if self.media_provider_timeout_seconds > 60:
            raise ValueError("My Photos media timeout exceeds the worker envelope")
        if self.liveness_provider_timeout_seconds >= self.provider_deletion_claim_seconds:
            raise ValueError(
                "MY_PHOTOS_LIVENESS_PROVIDER_TIMEOUT_SECONDS must be shorter than "
                "MY_PHOTOS_PROVIDER_DELETION_CLAIM_SECONDS"
            )
        return self

    @model_validator(mode="after")
    def validate_development_fixture_provider_shape(self) -> Self:
        if not self.development_fixtures_enabled:
            return self
        if {
            self.liveness_provider,
            self.face_search_provider,
            self.media_provider,
        } != {"development"}:
            raise ValueError(
                "MY_PHOTOS_DEVELOPMENT_FIXTURES_ENABLED requires every My Photos "
                "provider to be development"
            )
        return self

    @model_validator(mode="after")
    def validate_production_provider_shape(self) -> Self:
        aws_rekognition_selected = "aws_rekognition" in {
            self.liveness_provider,
            self.face_search_provider,
        }
        s3_selected = self.media_provider == "s3"
        if not (aws_rekognition_selected or s3_selected):
            return self

        if (
            self.liveness_provider,
            self.face_search_provider,
            self.media_provider,
        ) != ("aws_rekognition", "aws_rekognition", "s3"):
            raise ValueError(
                "Production My Photos activation requires the complete AWS Rekognition/S3 "
                "provider set"
            )

        if self.aws_region is None:
            raise ValueError("MY_PHOTOS_AWS_REGION is required for production providers")
        scope_secret = (
            self.aws_scope_hmac_secret.get_secret_value()
            if self.aws_scope_hmac_secret is not None
            else ""
        )
        if len(scope_secret) < 32:
            raise ValueError("MY_PHOTOS_AWS_SCOPE_HMAC_SECRET must contain at least 32 characters")
        if self.aws_provider_hmac_key_id is None:
            raise ValueError("MY_PHOTOS_AWS_PROVIDER_HMAC_KEY_ID is required")
        secret = (
            self.aws_provider_hmac_secret.get_secret_value()
            if self.aws_provider_hmac_secret is not None
            else ""
        )
        if len(secret) < 32:
            raise ValueError(
                "MY_PHOTOS_AWS_PROVIDER_HMAC_SECRET must contain at least 32 characters"
            )
        if len(self.aws_provider_hmac_previous_keys) > 3:
            raise ValueError("My Photos AWS reference verification key ring exceeds 3 keys")
        if self.aws_provider_hmac_key_id in self.aws_provider_hmac_previous_keys:
            raise ValueError(
                "Active My Photos AWS reference key cannot appear in the previous ring"
            )
        key_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
        previous_values: list[str] = []
        for key_id, previous_secret in self.aws_provider_hmac_previous_keys.items():
            value = previous_secret.get_secret_value()
            if key_pattern.fullmatch(key_id) is None or len(value) < 32:
                raise ValueError("My Photos AWS previous reference key ring is invalid")
            previous_values.append(value)
        if len({secret, *previous_values}) != 1 + len(previous_values):
            raise ValueError("My Photos AWS reference signing secrets must be distinct")
        for name, prefix in (
            ("MY_PHOTOS_AWS_LIVENESS_OUTPUT_PREFIX", self.aws_liveness_output_prefix),
            ("MY_PHOTOS_AWS_MEDIA_KEY_PREFIX", self.aws_media_key_prefix),
        ):
            if (
                prefix.endswith("/")
                or "//" in prefix
                or any(part in {".", ".."} for part in prefix.split("/"))
            ):
                raise ValueError(f"{name} must be a normalized object-key prefix")
        if self.aws_s3_endpoint_url is not None:
            endpoint = urlsplit(self.aws_s3_endpoint_url)
            try:
                endpoint.port
            except ValueError as exc:
                raise ValueError(
                    "MY_PHOTOS_AWS_S3_ENDPOINT_URL must be a reviewed HTTPS origin"
                ) from exc
            if (
                endpoint.scheme != "https"
                or endpoint.hostname is None
                or endpoint.username is not None
                or endpoint.password is not None
                or endpoint.query
                or endpoint.fragment
                or "//" in endpoint.path
                or any(part in {".", ".."} for part in endpoint.path.split("/"))
            ):
                raise ValueError("MY_PHOTOS_AWS_S3_ENDPOINT_URL must be a reviewed HTTPS origin")
        elif self.aws_expected_bucket_owner is None:
            raise ValueError(
                "MY_PHOTOS_AWS_EXPECTED_BUCKET_OWNER is required for the AWS S3 endpoint"
            )

        if self.aws_liveness_output_bucket is None:
            raise ValueError("MY_PHOTOS_AWS_LIVENESS_OUTPUT_BUCKET is required for Face Liveness")
        _validate_s3_bucket_name(self.aws_liveness_output_bucket)
        if self.aws_liveness_kms_key_id is None:
            raise ValueError("MY_PHOTOS_AWS_LIVENESS_KMS_KEY_ID is required")
        liveness_kms_account = _validate_kms_key_arn(
            self.aws_liveness_kms_key_id,
            region=self.aws_region,
        )
        if self.liveness_session_ttl_seconds > 180:
            raise ValueError(
                "MY_PHOTOS_LIVENESS_SESSION_TTL_SECONDS cannot exceed AWS's 180-second session"
            )
        if self.reference_frame_retention_seconds <= 0:
            raise ValueError(
                "MY_PHOTOS_REFERENCE_FRAME_RETENTION_SECONDS must be explicitly reviewed "
                "for AWS Face Liveness"
            )
        if self.provider_audit_image_retention_enabled != (
            self.aws_liveness_audit_images_limit > 0
        ):
            raise ValueError("AWS liveness audit-image retention flag and limit must agree")
        if self.native_temporary_credentials_mode != "cognito_identity_pool":
            raise ValueError(
                "MY_PHOTOS_NATIVE_TEMPORARY_CREDENTIALS_MODE must equal "
                "cognito_identity_pool for AWS Face Liveness"
            )
        if self.aws_cognito_identity_pool_id is None:
            raise ValueError("MY_PHOTOS_AWS_COGNITO_IDENTITY_POOL_ID is required for Cognito mode")

        if self.aws_media_bucket is None:
            raise ValueError("MY_PHOTOS_AWS_MEDIA_BUCKET is required for Rekognition and S3 media")
        _validate_s3_bucket_name(self.aws_media_bucket)
        if self.aws_media_kms_key_id is None:
            raise ValueError("MY_PHOTOS_AWS_MEDIA_KMS_KEY_ID is required")
        media_kms_account = _validate_kms_key_arn(
            self.aws_media_kms_key_id,
            region=self.aws_region,
        )
        if media_kms_account != liveness_kms_account or (
            self.aws_expected_bucket_owner is not None
            and media_kms_account != self.aws_expected_bucket_owner
        ):
            raise ValueError(
                "My Photos KMS key ARNs must use the reviewed AWS bucket-owner account"
            )
        if self.maximum_search_results > 4_096:
            raise ValueError(
                "MY_PHOTOS_MAXIMUM_SEARCH_RESULTS cannot exceed SearchFacesByImage's 4096 limit"
            )
        if self.match_config_version.startswith("uncalibrated"):
            raise ValueError(
                "A calibrated MY_PHOTOS_MATCH_CONFIG_VERSION is required for AWS matching"
            )
        return self

    def validate_runtime_environment(
        self,
        app_env: Literal["development", "staging", "production"],
    ) -> None:
        """Reject provider options that exist only for explicit local adapter tests."""

        development_selected = "development" in {
            self.liveness_provider,
            self.face_search_provider,
            self.media_provider,
        }
        if app_env != "development" and (development_selected or self.development_fixtures_enabled):
            raise ValueError(
                "Development My Photos providers and fixtures are forbidden outside "
                "development (APP_ENV=development only)"
            )
        aws_selected = (
            "aws_rekognition"
            in {
                self.liveness_provider,
                self.face_search_provider,
            }
            or self.media_provider == "s3"
        )
        if app_env != "development" and aws_selected and self.aws_s3_endpoint_url is not None:
            raise ValueError(
                "MY_PHOTOS_AWS_S3_ENDPOINT_URL is allowed only in APP_ENV=development; "
                "production AWS media must use the distinct AWS S3 object origin"
            )


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
    expected_database_schema_revision: str = Field(
        default="0090_upload_configuration",
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9_]+$",
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
    my_photos_worker_concurrency: int = Field(default=2, ge=1, le=8)

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

    @field_validator("email_oauth_frontend_return_url", "password_recovery_frontend_url")
    @classmethod
    def validate_frontend_return_url(cls, value: str) -> str:
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
                "Frontend return URLs must be absolute HTTP(S) URLs "
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
    # General HTTP/business metrics leave each API or Celery process through a
    # non-blocking StatsD boundary. Production Compose requires this exporter;
    # an external Prometheus-compatible collector owns aggregation and SLOs.
    metrics_exporter: Literal["disabled", "statsd"] = "disabled"
    metrics_export_required: bool = False
    metrics_statsd_host: str = Field(default="localhost", min_length=1, max_length=253)
    metrics_statsd_port: int = Field(default=9125, ge=1, le=65_535)
    metrics_namespace: str = Field(
        default="passdetection",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    )
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
    # All passport images, distribution PDFs, and public-upload documents are
    # untrusted until the original bytes have crossed the malware boundary.
    # This switch exists for deliberately document-free deployments; routes
    # fail closed when disabled rather than silently bypassing scanning.
    untrusted_document_ingestion_enabled: bool = True
    malware_scanner_enabled: bool = False
    malware_scanner_host: str = "localhost"
    malware_scanner_port: int = Field(default=3310, ge=1, le=65535)
    malware_scanner_timeout_seconds: float = Field(default=2.0, ge=0.2, le=10.0)
    malware_quarantine_enabled: bool = True
    malware_quarantine_prefix: str = Field(
        default="security-quarantine",
        min_length=3,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$",
    )
    malware_quarantine_retention_days: int = Field(default=14, ge=1, le=90)
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
    gemini_extraction_max_concurrency: int = Field(default=4, ge=1, le=64)
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
    def validate_identity_security_configuration(self) -> Self:
        """Reject ambiguous key rings and unsafe recovery-development controls."""

        rings = (
            (
                "IDENTITY_ACTION_HMAC",
                self.identity_action_hmac_key_id,
                self.identity_action_hmac_previous_keys,
            ),
            (
                "IDENTITY_MFA_ENCRYPTION",
                self.identity_mfa_encryption_key_id,
                self.identity_mfa_decryption_keys,
            ),
            (
                "IDENTITY_NOTIFICATION_ENCRYPTION",
                self.identity_notification_encryption_key_id,
                self.identity_notification_decryption_keys,
            ),
        )
        for label, active_key_id, previous_keys in rings:
            if active_key_id in previous_keys:
                raise ValueError(f"{label} active key ID must not also be a previous key")
            if len(previous_keys) > self.identity_previous_key_limit:
                raise ValueError(f"{label} previous key ring exceeds IDENTITY_PREVIOUS_KEY_LIMIT")

        if self.password_recovery_development_expose_token and not self.is_development:
            raise ValueError(
                "PASSWORD_RECOVERY_DEVELOPMENT_EXPOSE_TOKEN is allowed only in development"
            )
        if self.password_recovery_delivery_provider == "smtp":
            missing = []
            if not (self.password_recovery_smtp_host or "").strip():
                missing.append("PASSWORD_RECOVERY_SMTP_HOST")
            if not (self.password_recovery_smtp_sender or "").strip():
                missing.append("PASSWORD_RECOVERY_SMTP_SENDER")
            if missing:
                raise ValueError(
                    "PASSWORD_RECOVERY_DELIVERY_PROVIDER=smtp requires " + ", ".join(missing)
                )
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
            + self.my_photos_worker_concurrency
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
    def validate_metrics_export_configuration(self) -> Self:
        host = self.metrics_statsd_host.strip()
        if host != self.metrics_statsd_host or any(character.isspace() for character in host):
            raise ValueError(
                "METRICS_STATSD_HOST must not contain surrounding or embedded whitespace"
            )
        if self.metrics_export_required and self.metrics_exporter != "statsd":
            raise ValueError(
                "METRICS_EXPORTER=statsd is required when METRICS_EXPORT_REQUIRED=true"
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
    def validate_my_photos_provider_configuration(self) -> Self:
        """Never permit deterministic biometric/media simulation outside local development."""

        self.my_photos.validate_runtime_environment(self.app_env)
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
            raise ValueError("MOBILE_APP_ATTEST_TEAM_ID is required for production enforcement")
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

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def database(self) -> DatabaseSettings:
        return _load_environment_settings(DatabaseSettings)

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def redis(self) -> RedisSettings:
        return _load_environment_settings(RedisSettings)

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def jwt(self) -> JWTSettings:
        return _load_environment_settings(JWTSettings)

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def mobile(self) -> MobileSettings:
        return _load_environment_settings(MobileSettings)

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def my_photos(self) -> MyPhotosSettings:
        return _load_environment_settings(MyPhotosSettings)

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def s3(self) -> S3Settings:
        return _load_environment_settings(S3Settings)

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def mrz(self) -> MRZSettings:
        return _load_environment_settings(MRZSettings)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return _load_environment_settings(Settings)
