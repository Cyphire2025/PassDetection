"""Rendered Compose clients validation policies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from compose_runtime_contract import (
    DEVELOPMENT_PUBLISHED_TARGETS,
    FRONTEND_ALLOWED_BUILD_KEYS,
    FRONTEND_ALLOWED_ENVIRONMENT_KEYS,
    FRONTEND_FORBIDDEN_ENVIRONMENT_KEYS,
)
from compose_runtime_values import (
    _command_text,
    _healthcheck_text,
    _published_port_targets,
    _require,
    _volume_targets,
)


def validate_frontend(production_services: dict[str, Any]) -> None:
    production_frontend_environment = production_services["frontend"].get(
        "environment",
        {},
    )
    _require(
        not production_services["frontend"].get("env_file"),
        "Production frontend must not load the server environment file.",
    )
    _require(
        set(production_frontend_environment).issubset(FRONTEND_ALLOWED_ENVIRONMENT_KEYS),
        "Production frontend may receive only explicitly public runtime variables.",
    )
    _require(
        not (set(production_frontend_environment) & FRONTEND_FORBIDDEN_ENVIRONMENT_KEYS),
        "Production frontend must not receive backend credentials or secrets.",
    )
    production_frontend_build_args = (
        production_services["frontend"].get("build", {}).get("args", {})
    )
    _require(
        set(production_frontend_build_args).issubset(FRONTEND_ALLOWED_BUILD_KEYS),
        "Production frontend build may receive only explicitly public variables.",
    )
    _require(
        production_frontend_build_args.get("NEXT_PUBLIC_API_BASE_URL") == "",
        "Production frontend build must use same-origin API requests.",
    )
    _require(
        production_frontend_build_args.get("NEXT_PUBLIC_DEV_APP_URL") == "",
        "Production frontend build must not bake in a development origin.",
    )


def validate_runtime_source_files(
    backend_dockerfile_path: Path,
    gunicorn_configuration_path: Path,
    frontend_dockerignore_path: Path,
    backend_dockerignore_path: Path,
) -> None:
    dockerfile = backend_dockerfile_path.read_text(encoding="utf-8")
    _require(
        '"gunicorn", "--config", "gunicorn.conf.py", "app.main:app"' in dockerfile,
        "Backend runtime image must load the validated Gunicorn configuration.",
    )
    gunicorn_config = gunicorn_configuration_path.read_text(encoding="utf-8")
    _require(
        'worker_class = "app.infrastructure.bounded_uvicorn_worker.BoundedUvicornWorker"'
        in gunicorn_config,
        ("Backend runtime image must use the bounded Uvicorn worker under Gunicorn."),
    )
    _require(
        "workers = _settings.web_concurrency" in gunicorn_config,
        "Gunicorn workers must come from validated WEB_CONCURRENCY settings.",
    )
    frontend_dockerignore = frontend_dockerignore_path.read_text(encoding="utf-8")
    _require(
        ".env*" in frontend_dockerignore.splitlines(),
        "Frontend build context must exclude every .env variant.",
    )
    backend_dockerignore = backend_dockerignore_path.read_text(encoding="utf-8")
    _require(
        {".env", ".env.*"}.issubset(backend_dockerignore.splitlines()),
        "Backend build context must exclude every .env variant.",
    )


def validate_development(development_services: dict[str, Any]) -> None:
    development_backend = development_services["backend"]
    _require(
        "--reload" in _command_text(development_backend),
        "Development backend must retain hot reload.",
    )
    _require(
        "/app" in _volume_targets(development_backend),
        "Development backend must retain its source bind mount.",
    )
    _require(
        "/api/v1/health/live" in _healthcheck_text(development_backend),
        "Development backend must retain the lightweight liveness probe.",
    )
    development_frontend = development_services["frontend"]
    _require(
        "npm run dev" in _command_text(development_frontend),
        "Development frontend must retain its development server.",
    )
    _require(
        "/app" in _volume_targets(development_frontend),
        "Development frontend must retain its source bind mount.",
    )
    for service_name, expected_targets in DEVELOPMENT_PUBLISHED_TARGETS.items():
        _require(
            _published_port_targets(development_services[service_name]) == expected_targets,
            (
                f"Development {service_name} must retain host publications for "
                f"container ports {sorted(expected_targets)}."
            ),
        )
