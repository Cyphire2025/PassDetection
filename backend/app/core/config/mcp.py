"""Explicit MCP deployment policy. Connections start disabled in the database."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.mcp_policy import CAPABILITIES

EXPORT_FAMILIES = frozenset({
    "passport_excel", "passport_images", "tracking_excel", "rooming_excel",
    "document_assignments_excel",
})


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", env_file=".env", extra="ignore")

    enabled: bool = False
    read_only_mode: bool = False
    enabled_capabilities: list[str] = Field(default_factory=lambda: sorted(CAPABILITIES))
    export_families: list[str] = Field(default_factory=lambda: sorted(EXPORT_FAMILIES))
    export_source_row_limit: int = Field(default=1500, ge=1, le=1500)
    export_source_byte_limit: int = Field(default=16 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024)
    public_origin: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:3000"
    approved_clients: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "global-connects-desktop": ["http://127.0.0.1:8765/callback"],
        }
    )
    requests_per_minute: int = Field(default=120, ge=1, le=1000)
    diagnostic_log_root: Path | None = None

    @field_validator("diagnostic_log_root")
    @classmethod
    def validate_diagnostic_log_root(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("MCP diagnostic log root must be an absolute operator path")
        return value

    @field_validator("enabled_capabilities")
    @classmethod
    def validate_enabled_capabilities(cls, value: list[str]) -> list[str]:
        if set(value) - CAPABILITIES:
            raise ValueError("Only defined MCP capabilities may be enabled")
        return sorted(set(value))

    @field_validator("export_families")
    @classmethod
    def validate_export_families(cls, value: list[str]) -> list[str]:
        if set(value) - EXPORT_FAMILIES:
            raise ValueError("Only reviewed MCP export families may be enabled")
        return sorted(set(value))

    @model_validator(mode="after")
    def validate_origins(self) -> MCPSettings:
        for origin in (self.public_origin, self.frontend_origin):
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"})
            ):
                raise ValueError("MCP origins require HTTPS (HTTP loopback only) and no path")
        self.public_origin = self.public_origin.rstrip("/")
        self.frontend_origin = self.frontend_origin.rstrip("/")
        for client_id, redirects in self.approved_clients.items():
            if not client_id or len(client_id) > 200 or not redirects:
                raise ValueError("MCP clients require an ID and exact approved redirects")
            for redirect in redirects:
                parsed = urlsplit(redirect)
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.netloc
                    or parsed.username
                    or parsed.password
                    or parsed.fragment
                    or parsed.query
                    or (parsed.scheme == "http" and parsed.hostname != "127.0.0.1")
                ):
                    raise ValueError("MCP redirects require HTTPS or a literal IPv4 loopback")
        return self

    @property
    def resource(self) -> str:
        return f"{self.public_origin}/mcp"

    @property
    def effective_capabilities(self) -> list[str]:
        """Deployment authority is a ceiling; dashboard controls cannot widen it."""
        if self.read_only_mode:
            return ["mcp:read"] if "mcp:read" in self.enabled_capabilities else []
        return self.enabled_capabilities
