"""Dashboard-only connection controls. They are never registered as MCP tools."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.mcp_policy import validate_capabilities


class MCPConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1, max_length=200)
    redirect_uri: str = Field(min_length=1, max_length=1024)
    resource: str = Field(min_length=1, max_length=512)
    state: str = Field(min_length=16, max_length=512)
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    code_challenge_method: str = Field(default="S256", pattern=r"^S256$")
    response_type: str = Field(default="code", pattern=r"^code$")
    scopes: list[str] = Field(min_length=1, max_length=6)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("scopes")
    @classmethod
    def valid_scopes(cls, values: list[str]) -> list[str]:
        return validate_capabilities(values)


class MCPControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class MCPConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    capabilities: list[str] = Field(min_length=1, max_length=6)

    @field_validator("capabilities")
    @classmethod
    def valid_scopes(cls, values: list[str]) -> list[str]:
        return validate_capabilities(values)
