"""Strict dashboard-only permission decisions, never bearer authority."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.mcp_read_sections import validate_read_sections
from app.domain.mcp_section_permissions import (
    WRITE_TOOL_SECTIONS,
    validate_write_sections,
    validate_write_tools,
)


class MCPDevicePermissionValues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    read_enabled: bool = Field(default=True, strict=True)
    write_enabled: bool = Field(default=False, strict=True)
    allowed_read_sections: list[str] | None = Field(default=None, max_length=64)
    allowed_write_sections: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("allowed_read_sections")
    @classmethod
    def read_sections(cls, values: list[str] | None) -> list[str] | None:
        return validate_read_sections(values) if values is not None else None

    @field_validator("allowed_write_sections")
    @classmethod
    def write_sections(cls, values: list[str]) -> list[str]:
        return validate_write_sections(values)


class MCPConnectionPermissionsUpdate(MCPDevicePermissionValues):
    expected_revision: int = Field(ge=1, strict=True)


class MCPPermissionsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    read_enabled: bool = Field(strict=True)
    write_enabled: bool = Field(strict=True)
    allowed_read_sections: list[str] = Field(max_length=64)
    allowed_write_sections: list[str] = Field(max_length=64)
    allowed_write_tools: list[str] | None = Field(default=None, max_length=256)

    @field_validator("allowed_read_sections")
    @classmethod
    def read_sections(cls, values: list[str]) -> list[str]:
        return validate_read_sections(values)

    @field_validator("allowed_write_sections")
    @classmethod
    def write_sections(cls, values: list[str]) -> list[str]:
        return validate_write_sections(values)

    @field_validator("allowed_write_tools")
    @classmethod
    def write_tools(cls, values: list[str] | None) -> list[str] | None:
        return validate_write_tools(values) if values is not None else None

    @model_validator(mode="after")
    def tools_within_sections(self):
        if self.allowed_write_tools is None:
            self.allowed_write_tools = sorted(name for name, required in WRITE_TOOL_SECTIONS.items()
                                              if not required - set(self.allowed_write_sections))
        if any(WRITE_TOOL_SECTIONS[name] - set(self.allowed_write_sections) for name in self.allowed_write_tools):
            raise ValueError("Every allowed tool requires all its write sections")
        return self
