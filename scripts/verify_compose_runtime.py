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
GUNICORN_CONFIG = ROOT / "backend" / "gunicorn.conf.py"
BACKEND_DOCKERIGNORE = ROOT / "backend" / ".dockerignore"
FRONTEND_DOCKERIGNORE = ROOT / "frontend" / ".dockerignore"
BACKEND_SERVICES = (
    "backend",
    "worker",
    "my-photos-worker",
    "email-worker",
    "email-ai-worker",
    "email-beat",
    "extraction-worker",
    "verification-worker",
    "visa-ai-worker",
)
REDIS_SERVICES = ("redis", "redis-broker", "redis-realtime", "redis-cache")
INTERNAL_SERVICES = (
    "db",
    *REDIS_SERVICES,
    "clamav",
    "minio",
    "metrics-exporter",
    "backend",
)
DEVELOPMENT_PUBLISHED_TARGETS = {
    "db": {5432},
    "redis": {6379},
    "redis-broker": {6379},
    "redis-realtime": {6379},
    "redis-cache": {6379},
    "minio": {9000, 9001},
    "metrics-exporter": {9102},
    "backend": {8000},
}
NGINX_PUBLISHED_TARGETS = {80, 443}
PINNED_NGINX_IMAGE = "nginx:1.30.4-alpine"
PINNED_MINIO_IMAGE = (
    "minio/minio:RELEASE.2025-09-07T16-13-09Z"
    "@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"
)
PINNED_CLAMAV_IMAGE = (
    "clamav/clamav:1.5_base"
    "@sha256:2a682381f314a3ac6ec13eea55b69bd2594887598e5358d938e711a30df850f2"
)
PINNED_STATSD_EXPORTER_IMAGE = (
    "prom/statsd-exporter:v0.29.0"
    "@sha256:632f705804922d50c1c95ba8ff9c8c0cc18d4bbb0cc265dc4f9ae708271c95b3"
)
EXPECTED_DATABASE_SCHEMA_REVISION = "0088_merge_my_photos_hardening"
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
    "REDIS_BROKER_PASSWORD",
    "REDIS_SECURITY_PASSWORD",
    "REDIS_REALTIME_PASSWORD",
    "REDIS_CACHE_PASSWORD",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_WEBHOOK_VERIFY_TOKEN",
}
WORKER_QUEUE_CONTRACTS = {
    "worker": ("general@", "passport_ocr", "whatsapp"),
    "my-photos-worker": (
        "my-photos@",
        "my_photos_control",
        "my_photos_index",
        "my_photos_media",
        "my_photos_search",
    ),
    "extraction-worker": (
        "extraction@",
        "interactive-passport-extraction",
    ),
    "verification-worker": (
        "verification@",
        "post-submission-ai-verification",
    ),
    "visa-ai-worker": (
        "visa-ai@",
        "visa-ai-image-edit",
    ),
    "email-worker": (
        "email@",
        "email_integrations",
    ),
    "email-ai-worker": (
        "email-ai@",
        "email_ai",
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
        _published_port_targets(production_services["nginx"]) == NGINX_PUBLISHED_TARGETS,
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
    clamav = production_services["clamav"]
    _require(
        clamav.get("image") == PINNED_CLAMAV_IMAGE,
        "Production ClamAV must use the reviewed immutable feature-line digest.",
    )
    _require(
        clamav.get("user") == "clamav"
        and clamav.get("entrypoint") == ["/init-unprivileged"],
        "ClamAV must run through its unprivileged initialization path.",
    )
    _require(
        clamav.get("cap_drop") == ["ALL"]
        and "no-new-privileges:true" in clamav.get("security_opt", []),
        "ClamAV must drop Linux capabilities and forbid privilege escalation.",
    )
    _require(
        "/var/lib/clamav" in _volume_targets(clamav),
        "ClamAV signatures must persist across container replacement.",
    )
    clamav_healthcheck = _healthcheck_text(clamav)
    _require(
        "PING" in clamav_healthcheck and "127.0.0.1 3310" in clamav_healthcheck,
        "ClamAV health must probe the IPv4 clamd socket, not only its process.",
    )
    _require(
        int(clamav.get("mem_limit", 0)) >= 4 * 1024**3
        and float(clamav.get("cpus", 0)) >= 2
        and int(clamav.get("pids_limit", 0)) == 256,
        "ClamAV must keep the reviewed memory, CPU, and process resource envelope.",
    )
    statsd_exporter = production_services["metrics-exporter"]
    _require(
        statsd_exporter.get("image") == PINNED_STATSD_EXPORTER_IMAGE,
        "StatsD exporter must use the reviewed immutable release digest.",
    )
    _require(
        statsd_exporter.get("read_only") is True
        and statsd_exporter.get("cap_drop") == ["ALL"]
        and "no-new-privileges:true" in statsd_exporter.get("security_opt", []),
        "StatsD exporter must be read-only and unable to gain Linux privileges.",
    )
    _require(
        int(statsd_exporter.get("mem_limit", 0)) <= 128 * 1024**2
        and float(statsd_exporter.get("cpus", 0)) <= 0.25
        and int(statsd_exporter.get("pids_limit", 0)) == 64,
        "StatsD exporter must retain its bounded resource envelope.",
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
            str(environment.get("UNTRUSTED_DOCUMENT_INGESTION_ENABLED", "")).lower()
            == "true"
            and str(environment.get("MALWARE_SCANNER_ENABLED", "")).lower() == "true"
            and environment.get("MALWARE_SCANNER_HOST") == "clamav"
            and int(environment.get("MALWARE_SCANNER_PORT", 0)) == 3310,
            (
                f"Production {service_name} must fail closed through the shared "
                "ClamAV document-ingestion boundary."
            ),
        )
        expected_pool_profile = "api" if service_name == "backend" else "worker"
        _require(
            environment.get("POSTGRES_POOL_PROFILE") == expected_pool_profile,
            f"Production {service_name} must use the {expected_pool_profile} database pool.",
        )
        for capacity_key in (
            "WEB_CONCURRENCY",
            "WORKER_CONCURRENCY",
            "EMAIL_WORKER_CONCURRENCY",
            "EMAIL_AI_WORKER_CONCURRENCY",
            "MY_PHOTOS_WORKER_CONCURRENCY",
            "GEMINI_EXTRACTION_MAX_CONCURRENCY",
            "GEMINI_VERIFICATION_MAX_CONCURRENCY",
            "GEMINI_IMAGE_EDIT_MAX_CONCURRENCY",
            "POSTGRES_API_POOL_SIZE",
            "POSTGRES_API_MAX_OVERFLOW",
            "POSTGRES_WORKER_POOL_SIZE",
            "POSTGRES_WORKER_MAX_OVERFLOW",
            "POSTGRES_POOL_TIMEOUT_SECONDS",
            "POSTGRES_POOL_RECYCLE_SECONDS",
            "POSTGRES_API_STATEMENT_TIMEOUT_MS",
            "POSTGRES_WORKER_STATEMENT_TIMEOUT_MS",
            "POSTGRES_LOCK_TIMEOUT_MS",
            "POSTGRES_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS",
            "POSTGRES_SERVER_MAX_CONNECTIONS",
            "POSTGRES_RESERVED_CONNECTIONS",
            "POSTGRES_API_CONNECTION_BUDGET",
            "EXPECTED_DATABASE_SCHEMA_REVISION",
            "METRICS_EXPORTER",
            "METRICS_EXPORT_REQUIRED",
            "METRICS_STATSD_HOST",
            "METRICS_STATSD_PORT",
            "METRICS_NAMESPACE",
        ):
            _require(
                environment.get(capacity_key)
                == production_backend.get("environment", {}).get(capacity_key),
                f"Production {service_name} must share {capacity_key} with the API.",
            )
        for redis_key in (
            "REDIS_DOMAIN_ISOLATION_REQUIRED",
            "REDIS_BROKER_HOST",
            "REDIS_BROKER_PORT",
            "REDIS_BROKER_PASSWORD",
            "REDIS_BROKER_DB",
            "REDIS_SECURITY_HOST",
            "REDIS_SECURITY_PORT",
            "REDIS_SECURITY_PASSWORD",
            "REDIS_SECURITY_DB",
            "REDIS_REALTIME_HOST",
            "REDIS_REALTIME_PORT",
            "REDIS_REALTIME_PASSWORD",
            "REDIS_REALTIME_DB",
            "REDIS_CACHE_HOST",
            "REDIS_CACHE_PORT",
            "REDIS_CACHE_PASSWORD",
            "REDIS_CACHE_DB",
        ):
            _require(
                environment.get(redis_key)
                == production_backend.get("environment", {}).get(redis_key),
                f"Production {service_name} must share {redis_key} with the API.",
            )
    backend_environment = production_backend.get("environment", {})
    _require(
        backend_environment.get("EXPECTED_DATABASE_SCHEMA_REVISION")
        == EXPECTED_DATABASE_SCHEMA_REVISION,
        "Production readiness must gate on the reviewed Alembic merge head.",
    )
    _require(
        backend_environment.get("METRICS_EXPORTER") == "statsd"
        and str(backend_environment.get("METRICS_EXPORT_REQUIRED", "")).lower()
        == "true"
        and backend_environment.get("METRICS_STATSD_HOST") == "metrics-exporter"
        and int(backend_environment.get("METRICS_STATSD_PORT", 0)) == 9125,
        "Production API and workers must export metrics through the private StatsD service.",
    )
    _require(
        str(backend_environment.get("REDIS_DOMAIN_ISOLATION_REQUIRED", "")).lower()
        == "true",
        "Production must require Redis domain isolation.",
    )
    redis_endpoints = {
        (
            str(backend_environment[f"REDIS_{domain}_HOST"]),
            int(backend_environment[f"REDIS_{domain}_PORT"]),
            int(backend_environment[f"REDIS_{domain}_DB"]),
        )
        for domain in ("BROKER", "SECURITY", "REALTIME", "CACHE")
    }
    _require(
        len(redis_endpoints) == 4,
        "Broker, security, realtime, and cache Redis domains must be distinct.",
    )
    for service_name in BACKEND_SERVICES:
        dependencies = production_services[service_name].get("depends_on", {})
        _require(
            set(REDIS_SERVICES).issubset(dependencies),
            f"Production {service_name} must wait for every isolated Redis domain.",
        )
        _require(
            dependencies.get("clamav", {}).get("condition") == "service_healthy",
            f"Production {service_name} must wait for a healthy malware scanner.",
        )
        _require(
            dependencies.get("metrics-exporter", {}).get("condition")
            == "service_started",
            f"Production {service_name} must start after the metrics exporter.",
        )
    security_command = _command_text(production_services["redis"])
    broker_command = _command_text(production_services["redis-broker"])
    realtime_command = _command_text(production_services["redis-realtime"])
    cache_command = _command_text(production_services["redis-cache"])
    for service_name, command in (
        ("redis", security_command),
        ("redis-broker", broker_command),
    ):
        _require(
            "--appendonly yes" in command
            and "--appendfsync everysec" in command
            and "--maxmemory-policy noeviction" in command,
            f"{service_name} must be persistent and non-evicting.",
        )
    _require(
        "--appendonly no" in realtime_command
        and "--maxmemory-policy noeviction" in realtime_command,
        "Realtime Redis must be reconstructable but non-evicting.",
    )
    _require(
        "--appendonly no" in cache_command
        and "--maxmemory-policy allkeys-lru" in cache_command
        and "--maxmemory" in cache_command,
        "Cache Redis must be explicitly memory-bounded and evictable.",
    )
    declared_server_connections = production_backend.get("environment", {}).get(
        "POSTGRES_SERVER_MAX_CONNECTIONS"
    )
    _require(
        f"max_connections={declared_server_connections}"
        in _command_text(production_services["db"]),
        "Bundled PostgreSQL must apply the declared server connection ceiling.",
    )
    capacity_environment = production_backend.get("environment", {})
    api_claim = int(capacity_environment["WEB_CONCURRENCY"]) * (
        int(capacity_environment["POSTGRES_API_POOL_SIZE"])
        + int(capacity_environment["POSTGRES_API_MAX_OVERFLOW"])
    )
    _require(
        api_claim <= int(capacity_environment["POSTGRES_API_CONNECTION_BUDGET"]),
        "Rendered API worker pools exceed POSTGRES_API_CONNECTION_BUDGET.",
    )
    background_processes = (
        int(capacity_environment["WORKER_CONCURRENCY"])
        + int(capacity_environment["EMAIL_WORKER_CONCURRENCY"])
        + int(capacity_environment["EMAIL_AI_WORKER_CONCURRENCY"])
        + int(capacity_environment["MY_PHOTOS_WORKER_CONCURRENCY"])
        + int(capacity_environment["GEMINI_EXTRACTION_MAX_CONCURRENCY"])
        + int(capacity_environment["GEMINI_VERIFICATION_MAX_CONCURRENCY"])
        + int(capacity_environment["GEMINI_IMAGE_EDIT_MAX_CONCURRENCY"])
        + 1
    )
    total_claim = api_claim + background_processes * (
        int(capacity_environment["POSTGRES_WORKER_POOL_SIZE"])
        + int(capacity_environment["POSTGRES_WORKER_MAX_OVERFLOW"])
    )
    usable_connections = int(declared_server_connections) - int(
        capacity_environment["POSTGRES_RESERVED_CONNECTIONS"]
    )
    _require(
        total_claim <= usable_connections,
        "Rendered API and worker pools exceed the usable PostgreSQL connection budget.",
    )
    _require(
        production_backend.get("environment", {}).get("PROCESSING_BACKEND") == "celery",
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
    _require(
        str(
            production_backend.get("environment", {}).get(
                "MOBILE_REALTIME_ENABLED",
                "",
            )
        ).lower()
        == "true",
        "Production must enable the mobile realtime invalidation service.",
    )
    _require(
        str(
            production_backend.get("environment", {}).get(
                "MOBILE_REALTIME_REQUIRE_REDIS",
                "",
            )
        ).lower()
        == "true",
        "Production mobile realtime must fail readiness closed through Redis.",
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
        set(production_frontend_build_args).issubset(FRONTEND_ALLOWED_ENVIRONMENT_KEYS),
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

    email_beat = production_services["email-beat"]
    _require(
        " beat " in f" {_command_text(email_beat)} ",
        "email-beat must run the Celery Beat scheduler.",
    )
    _require(
        "app.infrastructure.email.beat_healthcheck" in _healthcheck_text(email_beat),
        "email-beat must verify its durable scheduler heartbeat.",
    )

    dockerfile = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    _require(
        '"gunicorn", "--config", "gunicorn.conf.py", "app.main:app"' in dockerfile,
        "Backend runtime image must load the validated Gunicorn configuration.",
    )
    gunicorn_config = GUNICORN_CONFIG.read_text(encoding="utf-8")
    _require(
        'worker_class = "app.infrastructure.bounded_uvicorn_worker.BoundedUvicornWorker"'
        in gunicorn_config,
        ("Backend runtime image must use the bounded Uvicorn worker under Gunicorn."),
    )
    _require(
        "workers = _settings.web_concurrency" in gunicorn_config,
        "Gunicorn workers must come from validated WEB_CONCURRENCY settings.",
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
            _published_port_targets(development_services[service_name]) == expected_targets,
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
