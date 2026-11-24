"""Rendered Compose capacity validation policies."""

from __future__ import annotations

from typing import Any

from compose_runtime_contract import (
    BACKEND_SERVICES,
    EXPECTED_DATABASE_SCHEMA_REVISION,
    REDIS_SERVICES,
)
from compose_runtime_values import (
    _command_text,
    _require,
)


def validate_production_capacity(
    production_services: dict[str, Any], production_backend: dict[str, Any]
) -> None:
    backend_environment = production_backend.get("environment", {})
    database_environment = production_services["db"].get("environment", {})
    for service in BACKEND_SERVICES:
        environment = production_services[service].get("environment", {})
        _require(
            environment.get("POSTGRES_USER") != database_environment.get("POSTGRES_USER"),
            f"{service}: runtime and bootstrap database identities must differ.",
        )
        _require(
            not environment.get("POSTGRES_MIGRATION_PASSWORD")
            and not environment.get("POSTGRES_RUNTIME_PASSWORD"),
            f"{service}: extra database credential variables must be cleared.",
        )
    _require(
        backend_environment.get("EXPECTED_DATABASE_SCHEMA_REVISION")
        == EXPECTED_DATABASE_SCHEMA_REVISION,
        "Production readiness must gate on the reviewed Alembic merge head.",
    )
    _require(
        backend_environment.get("METRICS_EXPORTER") == "statsd"
        and str(backend_environment.get("METRICS_EXPORT_REQUIRED", "")).lower() == "true"
        and backend_environment.get("METRICS_STATSD_HOST") == "metrics-exporter"
        and int(backend_environment.get("METRICS_STATSD_PORT", 0)) == 9125,
        "Production API and workers must export metrics through the private StatsD service.",
    )
    _require(
        str(backend_environment.get("REDIS_DOMAIN_ISOLATION_REQUIRED", "")).lower() == "true",
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
            dependencies.get("metrics-exporter", {}).get("condition") == "service_started",
            f"Production {service_name} must start after the metrics exporter.",
        )
    security_command = _command_text(production_services["redis"])
    for service_name in (
        *BACKEND_SERVICES,
        "db",
        *REDIS_SERVICES,
        "minio",
        "frontend",
        "nginx",
    ):
        _require(
            int(production_services[service_name].get("mem_limit", 0)) > 0
            and float(production_services[service_name].get("cpus", 0)) > 0,
            f"Production {service_name} must declare memory and CPU ceilings.",
        )
    for service_name in REDIS_SERVICES:
        _require(
            "--maxmemory " in _command_text(production_services[service_name]),
            f"{service_name} must bound data memory below the container ceiling.",
        )
    for name in BACKEND_SERVICES:
        _require(
            all(
                production_services[name].get("environment", {}).get(key) == ""
                for key in (
                    "MINIO_ROOT_USER",
                    "MINIO_ROOT_PASSWORD",
                    "OBJECT_STORAGE_ADMIN_ACCESS_KEY",
                    "OBJECT_STORAGE_ADMIN_SECRET_KEY",
                )
            ),
            "Long-running application services must not inherit storage administrator credentials.",
        )
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
    _require(
        "--concurrency=1" in _command_text(production_services["ecr-worker"]),
        "ECR must keep one batch process; its eight image lanes share that process budget.",
    )
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
        + 1  # Scheduler process.
        + 1  # ECR has one prefork process; its image lanes share that pool.
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
