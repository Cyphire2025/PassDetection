"""Resolve client addresses only through explicitly trusted reverse proxies."""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from typing import Any, Mapping

from fastapi import Request

from app.core.config.settings import Settings, get_settings


@lru_cache(maxsize=16)
def _proxy_networks(cidrs: tuple[str, ...]) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(cidr, strict=False) for cidr in cidrs)


def _header_value(request: Request, name: str) -> str:
    """Read a header without requiring a complete ASGI request scope.

    Starlette's ``Request.headers`` property raises ``KeyError`` when a
    synthetic request omits the optional ``headers`` scope entry.  Audit and
    throttling code must fail safely to the direct peer in that case instead
    of turning an otherwise valid operation into a server error.
    """

    scope: Mapping[str, Any] | None = getattr(request, "scope", None)
    if scope is not None:
        expected = name.lower().encode("latin-1")
        for raw_name, raw_value in scope.get("headers", ()):
            if bytes(raw_name).lower() == expected:
                return bytes(raw_value).decode("latin-1").strip()

    try:
        headers = request.headers
    except (AttributeError, KeyError, TypeError):
        return ""
    return str(headers.get(name, "")).strip()


def trusted_client_ip(request: Request, *, settings: Settings | None = None) -> str | None:
    """Return the canonical client IP without trusting arbitrary forwarding headers.

    X-Real-IP is accepted only when the TCP peer belongs to a configured proxy
    network. This prevents direct clients from choosing another rate-limit or
    audit identity while allowing Nginx to forward the address established by
    its own Cloudflare allowlist.
    """

    direct_value = request.client.host.strip() if request.client and request.client.host else ""
    try:
        direct_ip = ipaddress.ip_address(direct_value)
    except ValueError:
        return None

    configured = settings or get_settings()
    networks = _proxy_networks(tuple(configured.trusted_proxy_networks))
    if any(direct_ip in network for network in networks):
        forwarded_value = _header_value(request, "x-real-ip")
        try:
            return ipaddress.ip_address(forwarded_value).compressed
        except ValueError:
            pass
    return direct_ip.compressed
