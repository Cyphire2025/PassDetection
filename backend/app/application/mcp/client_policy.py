"""Exact approved-client and resource binding shared by authorization and exchange."""

from app.application.mcp.credentials import MCPAuthError
from app.core.config.mcp import MCPSettings


def validate_client(settings: MCPSettings, client_id: str, redirect_uri: str | None = None) -> None:
    redirects = settings.approved_clients.get(client_id)
    if not redirects or (redirect_uri is not None and redirect_uri not in redirects):
        raise MCPAuthError("invalid_client")


def validate_resource(settings: MCPSettings, resource: str) -> None:
    if resource != settings.resource:
        raise MCPAuthError("invalid_target")
