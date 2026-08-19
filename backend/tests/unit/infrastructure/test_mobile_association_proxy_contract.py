from __future__ import annotations

from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def _exact_location(config: str, path: str) -> str:
    marker = f"location = {path} {{"
    start = config.index(marker)
    depth = 0
    for index in range(start, len(config)):
        if config[index] == "{":
            depth += 1
        elif config[index] == "}":
            depth -= 1
            if depth == 0:
                return config[start : index + 1]
    raise AssertionError(f"Unclosed Nginx location: {path}")


def test_verified_link_files_are_direct_bounded_backend_proxies() -> None:
    site = (_REPOSITORY_ROOT / "nginx/conf.d/default.conf").read_text(encoding="utf-8")
    contracts = {
        "/.well-known/apple-app-site-association": (
            "proxy_pass http://backend/api/v1/mobile/associations/apple;"
        ),
        "/.well-known/assetlinks.json": (
            "proxy_pass http://backend/api/v1/mobile/associations/android;"
        ),
    }
    for path, expected_proxy in contracts.items():
        location = _exact_location(site, path)
        for directive in (
            "limit_except GET { deny all; }",
            "client_max_body_size 1K;",
            expected_proxy,
            'proxy_set_header Connection "";',
            "proxy_hide_header Set-Cookie;",
            "proxy_request_buffering off;",
            "proxy_read_timeout 10s;",
            "proxy_connect_timeout 5s;",
            "proxy_send_timeout 10s;",
        ):
            assert directive in location
        assert "return 30" not in location
