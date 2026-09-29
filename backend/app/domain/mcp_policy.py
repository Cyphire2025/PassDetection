"""MCP authority and effect policy, independent of the transport and model output."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MCPCapability(StrEnum):
    READ = "mcp:read"
    EXPORT = "mcp:export"
    UPLOAD = "mcp:upload"
    CHANGE = "mcp:change"
    COMMUNICATE = "mcp:communicate"
    DIAGNOSE = "mcp:diagnose"


CAPABILITIES = frozenset(item.value for item in MCPCapability)
FORBIDDEN_EFFECTS = frozenset(
    {
        "delete",
        "remove_member",
        "archive",
        "purge",
        "replace_without_history",
        "erase_source_file",
        "server_control",
        "grant_mcp_authority",
        "fabricate_physical_event",
    }
)


@dataclass(frozen=True, slots=True)
class MCPToolPolicy:
    name: str
    capability: MCPCapability
    effects: frozenset[str]

    def validate(self) -> None:
        if self.effects & FORBIDDEN_EFFECTS:
            raise ValueError(f"Forbidden MCP effects for {self.name}")


def validate_capabilities(values: list[str]) -> list[str]:
    if not values or set(values) - CAPABILITIES:
        raise ValueError("Select at least one supported MCP capability")
    return sorted(set(values))
