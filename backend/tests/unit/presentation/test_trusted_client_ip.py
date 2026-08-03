from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request

from app.presentation.security.client_ip import trusted_client_ip


def _request(*, peer: str, real_ip: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if real_ip is not None:
        headers.append((b"x-real-ip", real_ip.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (peer, 12345),
        }
    )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        trusted_proxy_networks=["127.0.0.0/8", "::1/128", "172.16.0.0/12"]
    )


def test_accepts_real_ip_from_configured_proxy() -> None:
    request = _request(peer="172.20.0.4", real_ip="203.0.113.9")
    assert trusted_client_ip(request, settings=_settings()) == "203.0.113.9"


def test_rejects_spoofed_real_ip_from_untrusted_peer() -> None:
    request = _request(peer="198.51.100.20", real_ip="203.0.113.9")
    assert trusted_client_ip(request, settings=_settings()) == "198.51.100.20"


def test_invalid_forwarded_value_falls_back_to_proxy_peer() -> None:
    request = _request(peer="172.20.0.4", real_ip="not-an-ip")
    assert trusted_client_ip(request, settings=_settings()) == "172.20.0.4"


def test_missing_headers_scope_falls_back_to_direct_peer() -> None:
    request = Request({"type": "http", "client": ("127.0.0.1", 12345)})
    assert trusted_client_ip(request, settings=_settings()) == "127.0.0.1"
