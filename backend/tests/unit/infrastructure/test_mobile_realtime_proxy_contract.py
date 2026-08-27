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


def test_mobile_realtime_proxy_preserves_upgrade_auth_and_bounded_timeouts() -> None:
    site = (_REPOSITORY_ROOT / "nginx/conf.d/default.conf").read_text(encoding="utf-8")
    location = _exact_location(site, "/api/v1/mobile/realtime")
    required_directives = (
        "proxy_http_version 1.1;",
        "proxy_set_header Upgrade $http_upgrade;",
        "proxy_set_header Connection $connection_upgrade;",
        "proxy_set_header Authorization $http_authorization;",
        "proxy_buffering off;",
        "proxy_request_buffering off;",
        "proxy_read_timeout 90s;",
        "proxy_send_timeout 30s;",
        "client_max_body_size 1K;",
    )
    for directive in required_directives:
        assert directive in location


def test_dashboard_realtime_proxy_preserves_same_origin_cookie_upgrade() -> None:
    site = (_REPOSITORY_ROOT / "nginx/conf.d/default.conf").read_text(encoding="utf-8")
    location = _exact_location(site, "/api/v1/dashboard/realtime")
    required_directives = (
        "proxy_http_version 1.1;",
        "proxy_set_header Upgrade $http_upgrade;",
        "proxy_set_header Connection $connection_upgrade;",
        "proxy_set_header Origin $http_origin;",
        "proxy_set_header Cookie $http_cookie;",
        "proxy_buffering off;",
        "proxy_request_buffering off;",
        "proxy_read_timeout 90s;",
        "proxy_send_timeout 30s;",
        "client_max_body_size 1K;",
    )
    for directive in required_directives:
        assert directive in location


def test_proxy_and_compose_retain_10k_file_descriptor_headroom() -> None:
    nginx = (_REPOSITORY_ROOT / "nginx/nginx.conf").read_text(encoding="utf-8")
    compose = (_REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "worker_rlimit_nofile 65536;" in nginx
    assert "worker_connections 32768;" in nginx
    assert compose.count("soft: 65536") >= 2
    assert compose.count("hard: 65536") >= 2


def test_asgi_transport_bounds_frames_before_application_validation() -> None:
    compose = (_REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (_REPOSITORY_ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    gunicorn_config = (_REPOSITORY_ROOT / "backend/gunicorn.conf.py").read_text(
        encoding="utf-8"
    )
    worker = (_REPOSITORY_ROOT / "backend/app/infrastructure/bounded_uvicorn_worker.py").read_text(
        encoding="utf-8"
    )
    assert "--ws-max-size 1024" in compose
    assert "--ws-max-queue 4" in compose
    assert "--ws-per-message-deflate false" in compose
    assert '"--config", "gunicorn.conf.py"' in dockerfile
    assert "app.infrastructure.bounded_uvicorn_worker.BoundedUvicornWorker" in gunicorn_config
    assert '"ws_max_size": 1_024' in worker
    assert '"ws_max_queue": 4' in worker
    assert '"ws_per_message_deflate": False' in worker
