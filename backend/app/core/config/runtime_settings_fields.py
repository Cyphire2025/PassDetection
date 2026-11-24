"""Application identity, process counts and trusted dashboard origins."""

from __future__ import annotations

import ipaddress
import json
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from app.core.config.mcp import MCPSettings
from app.core.config.release_contract import SCHEMA_REVISION


class RuntimeSettingsFields(BaseSettings):
    """Flat environment fields composed into the public Settings model."""

    app_env: Literal["development", "staging", "production"] = "development"
    app_secret_key: str = Field(..., repr=False, description="Must be set via APP_SECRET_KEY")
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
        default=SCHEMA_REVISION,
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9_]+$",
    )
    app_name: str = "Global Connects Dashboard"
    api_v1_prefix: str = "/api/v1"
    mcp: MCPSettings = Field(default_factory=MCPSettings)
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
