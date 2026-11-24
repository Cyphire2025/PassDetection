"""Retained direct release environment, proxy and clean-stop contracts."""

from __future__ import annotations

from typing import Any

from mcp_direct_build import BuildError
from mcp_direct_state import APPLICATION

TARGET = "0122_mcp_gc_push"


ORIGIN = "https://tech.gctravels.com"


WRITERS = APPLICATION | {"nginx"}


def environment(container: dict[str, Any]) -> dict[str, str]:
    return dict(value.split("=", 1) for value in container["Config"]["Env"] if "=" in value)


def runtime_environment(original: dict[str, Any], revision: str) -> dict[str, str]:
    result = environment(original)
    if original["Config"]["Labels"]["com.docker.compose.service"] == "frontend":
        result["NEXT_PUBLIC_APP_REVISION"] = revision
    else:
        result.update(
            APP_REVISION=revision,
            EXPECTED_DATABASE_SCHEMA_REVISION=TARGET,
            PYTHONPATH="/opt/mcp-deps:/app",
            MCP_ENABLED="true",
            MCP_ENABLED_CAPABILITIES='["mcp:read","mcp:export"]',
            MCP_EXPORT_FAMILIES='["passport_excel"]',
            MCP_EXPORT_SOURCE_ROW_LIMIT="100",
            MCP_EXPORT_SOURCE_BYTE_LIMIT="1048576",
            MCP_PUBLIC_ORIGIN=ORIGIN,
            MCP_FRONTEND_ORIGIN=ORIGIN,
            MCP_APPROVED_CLIENTS='{"global-connects-desktop":["http://127.0.0.1:8765/callback"]}',
        )
    return result


def render_proxy(config: str, backend_alias: str, frontend_alias: str) -> str:
    for source, target in (
        ("server backend:8000;", f"server {backend_alias}:8000;"),
        ("server frontend:3000;", f"server {frontend_alias}:3000;"),
    ):
        if config.count(source) != 1:
            raise BuildError("proxy_upstream_binding_changed")
        config = config.replace(source, target)
    return config


def clean_stop(container: dict[str, Any], original: dict[str, Any] | None = None) -> None:
    state = container["State"]
    # The observed original proxy retains an old OOMKilled flag. Preserve that
    # evidence; only a newly set flag is a stop failure. New clones stay strict.
    prior_oom = original is not None and original["State"].get("OOMKilled") is True
    # The retained Node standalone server exits with 128 + SIGTERM after the
    # proxy has drained. This is expected for that stateless frontend only.
    frontend_term = (
        container.get("Config", {}).get("Labels", {}).get("com.docker.compose.service")
        == "frontend"
        and container["Config"].get("Cmd") == ["node", "server.js"]
        and state.get("ExitCode") == 143
    )
    if (
        state["Running"]
        or (state.get("ExitCode") != 0 and not frontend_term)
        or (state.get("OOMKilled") and not prior_oom)
        or (
            original is not None
            and container.get("RestartCount", 0) != original.get("RestartCount", 0)
        )
    ):
        raise BuildError("application_not_cleanly_drained")


for _name in ("environment", "runtime_environment", "render_proxy", "clean_stop"):
    globals()[_name].__module__ = "mcp_direct_activate"
del _name
