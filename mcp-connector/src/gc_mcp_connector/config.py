"""An explicitly configured application origin is the complete network authority."""

from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlsplit

CLIENT_ID = "global-connects-desktop"
REDIRECT_URI = "http://127.0.0.1:8765/callback"
SCOPES = frozenset(
    {"mcp:read", "mcp:export", "mcp:upload", "mcp:change", "mcp:communicate", "mcp:diagnose"}
)


class ConnectorError(Exception):
    """Only deliberately safe, actionable messages belong in this exception."""


@dataclass(frozen=True)
class Config:
    origin: str

    def __post_init__(self) -> None:
        if any(ord(char) <= 32 or ord(char) >= 127 for char in self.origin):
            raise ConnectorError("Use an ASCII HTTPS application origin without whitespace.")
        try:
            parsed = urlsplit(self.origin)
            port = parsed.port
        except ValueError:
            raise ConnectorError("Invalid application origin.") from None
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or port == 0
            or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"})
        ):
            raise ConnectorError(
                "Use HTTPS; unencrypted HTTP is permitted only for loopback tests."
            )
        object.__setattr__(self, "origin", self.origin.rstrip("/"))

    @property
    def resource(self) -> str:
        return f"{self.origin}/mcp"

    @property
    def credential_key(self) -> str:
        digest = sha256(f"{CLIENT_ID}\0{self.resource}".encode()).hexdigest()
        return f"GlobalConnects:MCP:v1:{digest}"
