"""Approved clients and bounded, fail-closed OpenAI client metadata validation.

Direct native connections use only OpenAI's two stable CIMD documents. The
dashboard constants describe their expected callbacks; the fetched document is
still authoritative whenever an authorization code is created or exchanged.
"""

from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlsplit

import httpx

from app.application.mcp.credentials import MCPAuthError
from app.core.config.mcp import MCPSettings

DIRECT_CLIENT_NAMES = {
    "https://chatgpt.com/oauth/client.json": "ChatGPT",
    "https://chatgpt.com/oauth/codex/client.json": "Codex",
}
DIRECT_CLIENT_REDIRECTS = {
    "https://chatgpt.com/oauth/client.json": [
        "https://chatgpt.com/connector_platform_oauth_redirect",
    ],
    "https://chatgpt.com/oauth/codex/client.json": ["http://127.0.0.1/callback"],
}
_MAX_METADATA_BYTES = 16 * 1024
_METADATA_TIMEOUT_SECONDS = 5.0
_METADATA_CACHE_SECONDS = 300.0
_metadata_cache: dict[str, tuple[float, tuple[str, ...]]] = {}


def validate_client(settings: MCPSettings, client_id: str, redirect_uri: str | None = None) -> None:
    """Check grant identity locally; direct callbacks require the async helper."""
    if client_id in DIRECT_CLIENT_NAMES:
        if redirect_uri is not None:
            raise MCPAuthError("invalid_client")
        return
    redirects = settings.approved_clients.get(client_id)
    if not redirects or (redirect_uri is not None and redirect_uri not in redirects):
        raise MCPAuthError("invalid_client")


def _safe_redirect(value: object) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or any(ord(character) <= 32 for character in value)
        or any(character in value for character in "\\?#")
    ):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in {"https", "http"}
            and bool(parsed.netloc)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and (parsed.port is None or 1 <= parsed.port <= 65535)
        )
    except ValueError:
        return False


def _expected_redirect(client_id: str, redirect_uri: str) -> bool:
    if not _safe_redirect(redirect_uri):
        return False
    if DIRECT_CLIENT_NAMES[client_id] == "ChatGPT":
        return redirect_uri in DIRECT_CLIENT_REDIRECTS[client_id]
    parsed = urlsplit(redirect_uri)
    authority, separator, port = parsed.netloc.partition(":")
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and authority == "127.0.0.1"
        and (not separator or (port.isascii() and port.isdecimal()))
        and parsed.path == "/callback"
    )


def _document_redirects(client_id: str, document: object) -> tuple[str, ...]:
    if not isinstance(document, dict) or document.get("client_id", client_id) != client_id:
        raise MCPAuthError("invalid_client")
    methods = (
        document["token_endpoint_auth_methods_supported"]
        if "token_endpoint_auth_methods_supported" in document
        else [document.get("token_endpoint_auth_method")]
    )
    if (
        not isinstance(methods, list)
        or not methods
        or any(not isinstance(method, str) for method in methods)
        or "none" not in methods
    ):
        raise MCPAuthError("invalid_client")
    redirects = document.get("redirect_uris")
    if (
        not isinstance(redirects, list)
        or not 1 <= len(redirects) <= 20
        or any(not _safe_redirect(value) for value in redirects)
    ):
        raise MCPAuthError("invalid_client")
    # Other well-formed published callbacks, such as localhost, do not broaden
    # this deployment's explicit literal-loopback/ChatGPT callback policy.
    approved = tuple(
        value
        for value in redirects
        if isinstance(value, str) and _expected_redirect(client_id, value)
    )
    if not approved:
        raise MCPAuthError("invalid_client")
    return approved


async def _fetch_metadata(client_id: str) -> object:
    """Fetch only trusted metadata; this boundary is replaceable by test transports."""
    if client_id not in DIRECT_CLIENT_NAMES:
        raise MCPAuthError("invalid_client")
    try:
        async with asyncio.timeout(_METADATA_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                follow_redirects=False,
                trust_env=False,
                timeout=_METADATA_TIMEOUT_SECONDS,
            ) as client:
                async with client.stream(
                    "GET", client_id, headers={"Accept": "application/json"}
                ) as response:
                    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
                    if response.status_code >= 500 or response.status_code == 429:
                        raise MCPAuthError("temporarily_unavailable", 503)
                    if response.status_code != 200 or media_type != "application/json":
                        raise MCPAuthError("invalid_client")
                    payload = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=_MAX_METADATA_BYTES + 1):
                        payload.extend(chunk)
                        if len(payload) > _MAX_METADATA_BYTES:
                            raise MCPAuthError("invalid_client")
                    document: object = json.loads(payload)
                    return document
    except (httpx.HTTPError, TimeoutError) as exc:
        raise MCPAuthError("temporarily_unavailable", 503) from exc
    except ValueError as exc:
        raise MCPAuthError("invalid_client") from exc


async def _direct_redirects(client_id: str) -> tuple[str, ...]:
    if client_id not in DIRECT_CLIENT_NAMES:
        raise MCPAuthError("invalid_client")
    cached = _metadata_cache.get(client_id)
    if cached is not None and cached[0] > time.monotonic():
        return cached[1]
    # An expired entry must never become a fallback when its refresh fails.
    _metadata_cache.pop(client_id, None)
    redirects = _document_redirects(client_id, await _fetch_metadata(client_id))
    _metadata_cache[client_id] = (time.monotonic() + _METADATA_CACHE_SECONDS, redirects)
    return redirects


async def validate_authorization_client(
    settings: MCPSettings, client_id: str, redirect_uri: str
) -> None:
    """Require the current trusted CIMD policy for direct authorization callbacks."""
    if client_id not in DIRECT_CLIENT_NAMES:
        validate_client(settings, client_id, redirect_uri)
        return
    if not _expected_redirect(client_id, redirect_uri):
        raise MCPAuthError("invalid_client")
    redirects = await _direct_redirects(client_id)
    if DIRECT_CLIENT_NAMES[client_id] == "ChatGPT":
        matches = redirect_uri in redirects
    else:
        # RFC 8252 allows native clients to select the listening loopback port.
        target = urlsplit(redirect_uri)
        matches = any(
            (target.scheme, target.hostname, target.path)
            == (published.scheme, published.hostname, published.path)
            for published in (urlsplit(value) for value in redirects)
        )
    if not matches:
        raise MCPAuthError("invalid_client")


async def get_direct_client_metadata() -> dict[str, list[str]]:
    """Return validated available direct policies, without stale/failed documents."""
    client_ids = tuple(DIRECT_CLIENT_NAMES)
    results = await asyncio.gather(
        *(_direct_redirects(client_id) for client_id in client_ids), return_exceptions=True
    )
    return {
        client_id: list(result)
        for client_id, result in zip(client_ids, results, strict=True)
        if isinstance(result, tuple)
    }


def validate_resource(settings: MCPSettings, resource: str) -> None:
    if resource != settings.resource:
        raise MCPAuthError("invalid_target")
