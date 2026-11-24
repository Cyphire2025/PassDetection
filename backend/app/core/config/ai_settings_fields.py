"""AI extraction and image-editing provider budgets."""

from __future__ import annotations

import re

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings

_GEMINI_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class AISettingsFields(BaseSettings):
    """Flat environment fields composed into the public Settings model."""

    google_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_verification_enabled: bool = True
    gemini_model: str = "gemini-3.5-flash"
    ecr_gemini_model: str = "gemini-3.5-flash"
    ecr_gemini_timeout_seconds: float = Field(default=45.0, ge=5, le=120)
    ecr_gemini_max_attempts: int = Field(default=3, ge=1, le=5)
    ecr_image_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    ecr_image_max_pixels: int = Field(default=40_000_000, ge=1_000_000, le=40_000_000)
    ecr_image_max_dimension: int = Field(default=2000, ge=1200, le=3000)
    ecr_max_concurrency: int = Field(default=8, ge=1, le=32)
    ecr_requests_per_minute: int = Field(default=120, ge=1, le=600)
    ecr_retention_days: int = Field(default=7, ge=1, le=30)
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

    # Extraction applies a 4096-token floor for reasoning plus complete JSON;
    # this shared override may raise that bounded budget when needed.
    gemini_max_output_tokens: int = Field(default=512, ge=128, le=8192)
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
