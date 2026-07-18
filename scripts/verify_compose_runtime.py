"""Verify that development and production Compose runtimes stay separated.

This check renders Compose configuration only; it does not require a running
Docker daemon or start any container.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "docker-compose.yml"
DEV_COMPOSE = ROOT / "docker-compose.dev.yml"
PROD_COMPOSE = ROOT / "docker-compose.prod.yml"
BACKEND_DOCKERFILE = ROOT / "backend" / "Dockerfile"
BACKEND_DOCKERIGNORE = ROOT / "backend" / ".dockerignore"
FRONTEND_DOCKERIGNORE = ROOT / "frontend" / ".dockerignore"
BACKEND_SERVICES = (
    "backend",
    "worker",
    "extraction-worker",
    "verification-worker",
)
INTERNAL_SERVICES = ("db", "redis", "minio", "backend")
DEVELOPMENT_PUBLISHED_TARGETS = {
    "db": {5432},
    "redis": {6379},
    "minio": {9000, 9001},
    "backend": {8000},
}
NGINX_PUBLISHED_TARGETS = {80, 443}
PINNED_NGINX_IMAGE = "nginx:1.30.4-alpine"
PINNED_MINIO_IMAGE = (
    "minio/minio:RELEASE.2025-09-07T16-13-09Z"
    "@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"
)
FRONTEND_ALLOWED_ENVIRONMENT_KEYS = {
    "NEXT_PUBLIC_API_BASE_URL",
    "NEXT_PUBLIC_APP_URL",
    "NEXT_PUBLIC_DEV_APP_URL",
}
FRONTEND_FORBIDDEN_ENVIRONMENT_KEYS = {
    "APP_SECRET_KEY",
    "GOOGLE_API_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_WEBHOOK_VERIFY_TOKEN",
}
WORKER_QUEUE_CONTRACTS = {
    "worker": ("general@", "passport_ocr", "whatsapp"),
    "extraction-worker": (
        "extraction@",
        "interactive-passport-extraction",
    ),
    "verification-worker": (
        "verification@",
        "post-submission-ai-verification",
    ),
}


def _render_compose(*files: Path) -> dict[str, Any]:
    command = ["docker", "compose"]
    for file in files:
        command.extend(("-f", str(file)))
    command.extend(("config", "--format", "json", "--no-env-resolution"))
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Docker Compose CLI is required for this check.") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "Compose configuration failed."
        raise RuntimeError(detail)
    return json.loads(completed.stdout)


def _command_text(service: dict[str, Any]) -> str:
    command = service.get("command")
    if command is None:
        return ""
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return str(command)


def _volume_targets(service: dict[str, Any]) -> set[str]:
    return {
        str(volume.get("target"))
        for volume in service.get("volumes", [])
        if isinstance(volume, dict) and volume.get("target")
    }


def _healthcheck_text(service: dict[str, Any]) -> str:
    test = service.get("healthcheck", {}).get("test", [])
    if isinstance(test, list):
        return " ".join(str(part) for part in test)
    return str(test)


def _published_port_targets(service: dict[str, Any]) -> set[int]:
    targets: set[int] = set()
    for port in service.get("ports", []):
        if not isinstance(port, dict) or port.get("published") is None:
            continue
        target = port.get("target")
        if isinstance(target, int):
            targets.add(target)
        elif isinstance(target, str) and target.isdigit():
            targets.add(int(target))
    return targets


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    production = _render_compose(BASE_COMPOSE, PROD_COMPOSE)
    development = _render_compose(BASE_COMPOSE, DEV_COMPOSE)

    production_services = production["services"]
    development_services = development["services"]

    production_backend = production_services["backend"]
    _require(
        production_backend.get("command") is None,
        "Production backend must inherit the runtime image CMD.",
    )
    _require(
        "--reload" not in _command_text(production_backend),
        "Production backend must not enable Uvicorn reload.",
    )
    for service_name in BACKEND_SERVICES:
        _require(
            "/app" not in _volume_targets(production_services[service_name]),
            f"Production {service_name} must not bind-mount application source.",
        )
    for service_name in INTERNAL_SERVICES:
        _require(
            not production_services[service_name].get("ports"),
            f"Production {service_name} must not publish host ports.",
        )
    _require(
        _published_port_targets(production_services["nginx"])
        == NGINX_PUBLISHED_TARGETS,
        "Production Nginx must remain the only public entry point on ports 80 and 443.",
    )
    _require(
        production_services["nginx"].get("image") == PINNED_NGINX_IMAGE,
        "Production Nginx must use the reviewed stable image pin.",
    )
    _require(
        production_services["minio"].get("image") == PINNED_MINIO_IMAGE,
        "Production MinIO must use the reviewed immutable release digest.",
    )
    _require(
        "/api/v1/health/ready" in _healthcheck_text(production_backend),
        "Production backend must use the dependency readiness probe.",
    )
    for service_name in BACKEND_SERVICES:
        environment = production_services[service_name].get("environment", {})
        _require(
            environment.get("APP_ENV") == "production",
            f"Production {service_name} must force APP_ENV=production.",
        )
        _require(
            str(environment.get("APP_DEBUG", "")).lower() == "false",
            f"Production {service_name} must force APP_DEBUG=false.",
        )
    _require(
        production_backend.get("environment", {}).get("PROCESSING_BACKEND")
        == "celery",
        "Production backend must dispatch durable work through Celery.",
    )
    _require(
        str(
            production_backend.get("environment", {}).get(
                "PUBLIC_UPLOAD_RATE_LIMIT_REQUIRE_REDIS",
                "",
            )
        ).lower()
        == "true",
        "Production public-upload rate limits must fail closed through Redis.",
    )
    production_frontend_environment = production_services["frontend"].get(
        "environment",
        {},
    )
    _require(
        not production_services["frontend"].get("env_file"),
        "Production frontend must not load the server environment file.",
    )
    _require(
        set(production_frontend_environment).issubset(
            FRONTEND_ALLOWED_ENVIRONMENT_KEYS
        ),
        "Production frontend may receive only explicitly public runtime variables.",
    )
    _require(
        not (
            set(production_frontend_environment)
            & FRONTEND_FORBIDDEN_ENVIRONMENT_KEYS
        ),
        "Production frontend must not receive backend credentials or secrets.",
    )
    production_frontend_build_args = (
        production_services["frontend"].get("build", {}).get("args", {})
    )
    _require(
        set(production_frontend_build_args).issubset(
            FRONTEND_ALLOWED_ENVIRONMENT_KEYS
        ),
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
    for service_name, expected_parts in WORKER_QUEUE_CONTRACTS.items():
        service = production_services[service_name]
        command = _command_text(service)
        healthcheck = _healthcheck_text(service)
        _require(
            "--hostname=" in command and expected_parts[0] in command,
            f"{service_name} must have a stable queue-specific Celery node name.",
        )
        _require(
            "worker_healthcheck" in healthcheck,
            f"{service_name} must use the queue-specific healthcheck helper.",
        )
        for queue_name in expected_parts[1:]:
            _require(
                queue_name in command,
                f"{service_name} must consume its assigned queue ({queue_name}).",
            )
        for expected_part in expected_parts:
            _require(
                expected_part in healthcheck,
                (
                    f"{service_name} healthcheck must target its own node and "
                    f"queue contract ({expected_part})."
                ),
            )

    dockerfile = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    _require(
        '"gunicorn", "app.main:app"' in dockerfile,
        "Backend runtime image must define the Gunicorn application CMD.",
    )
    _require(
        '"--worker-class", "uvicorn.workers.UvicornWorker"' in dockerfile,
        "Backend runtime image must use Uvicorn workers under Gunicorn.",
    )
    frontend_dockerignore = FRONTEND_DOCKERIGNORE.read_text(encoding="utf-8")
    _require(
        ".env*" in frontend_dockerignore.splitlines(),
        "Frontend build context must exclude every .env variant.",
    )
    backend_dockerignore = BACKEND_DOCKERIGNORE.read_text(encoding="utf-8")
    _require(
        {".env", ".env.*"}.issubset(backend_dockerignore.splitlines()),
        "Backend build context must exclude every .env variant.",
    )

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
            _published_port_targets(development_services[service_name])
            == expected_targets,
            (
                f"Development {service_name} must retain host publications for "
                f"container ports {sorted(expected_targets)}."
            ),
        )

    print(
        "Compose runtime contracts verified: production uses the immutable "
        "Gunicorn image with internal services private behind Nginx; "
        "development retains hot reload and local service ports."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Compose runtime verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
