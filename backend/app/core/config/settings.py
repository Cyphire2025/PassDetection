"""
PassDetection Platform - Application Settings
=============================================
Single source of truth for all configuration.
Uses pydantic-settings for:
  - Automatic environment variable loading
  - Type coercion and validation
  - No hardcoded secrets anywhere in the codebase
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
        )

    @computed_field  # type: ignore[misc]
    @property
    def sync_url(self) -> str:
        """Sync DSN used by Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
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

    algorithm: str = "HS256"
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
    app_name: str = "PassDetection MRZ Platform"

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
                    raise ValueError("ALLOWED_ORIGINS must be a JSON array or comma-separated string")
                return [str(origin).strip() for origin in parsed if str(origin).strip()]

            return [origin.strip() for origin in normalized.split(",") if origin.strip()]

        return value

    rate_limit_per_minute: int = 60
    sentry_dsn: str | None = None
    processing_backend: Literal["background", "celery"] = "background"
    processing_job_max_attempts: int = Field(default=3, ge=1, le=10)
    processing_job_timeout_seconds: int = Field(default=60, ge=15, le=300)
    roi_field_timeout_seconds: float = Field(default=8.0, ge=0.5, le=30.0)
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
    gemini_api_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_timeout_seconds: float = Field(default=30.0, ge=1.0, le=60.0)
    gemini_max_output_tokens: int = Field(default=512, ge=128, le=1024)
    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_api_version: str = "v25.0"
    whatsapp_template_language: str = "en_US"
    whatsapp_welcome_template_name: str = "global_connect_welcome_v1"
    whatsapp_passport_link_template_name: str = "global_connect_passport_link_v1"
    whatsapp_webhook_verify_token: str | None = None
    whatsapp_app_secret: str | None = None

    @computed_field  # type: ignore[misc]
    @property
    def database(self) -> DatabaseSettings:
        return DatabaseSettings()

    @computed_field  # type: ignore[misc]
    @property
    def redis(self) -> RedisSettings:
        return RedisSettings()

    @computed_field  # type: ignore[misc]
    @property
    def jwt(self) -> JWTSettings:
        return JWTSettings()

    @computed_field  # type: ignore[misc]
    @property
    def s3(self) -> S3Settings:
        return S3Settings()

    @computed_field  # type: ignore[misc]
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
