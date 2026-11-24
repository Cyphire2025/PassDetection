"""Private S3-compatible object storage connections."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class S3Settings(BaseSettings):
    """S3-compatible object storage settings."""

    model_config = SettingsConfigDict(env_prefix="S3_", env_file=".env", extra="ignore")

    endpoint_url: str | None = None
    public_endpoint_url: str | None = None
    access_key_id: str = Field(..., repr=False, description="Must be set via S3_ACCESS_KEY_ID")
    secret_access_key: str = Field(..., repr=False, description="Must be set via S3_SECRET_ACCESS_KEY")
    bucket_name: str = "passdetection-passports"
    region: str = "us-east-1"
    presigned_url_expiry_seconds: int = 3600
    connect_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    read_timeout_seconds: float = Field(default=10.0, ge=1.0, le=120.0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    max_pool_connections: int = Field(default=64, ge=10, le=512)
