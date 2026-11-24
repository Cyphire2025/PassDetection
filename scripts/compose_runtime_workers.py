"""Rendered Compose workers validation policies."""

from __future__ import annotations

import shlex
from typing import Any

from compose_runtime_contract import (
    BACKEND_SERVICES,
    WORKER_QUEUE_CONTRACTS,
)
from compose_runtime_values import (
    _command_text,
    _healthcheck_text,
    _require,
)


def _worker_queues(service: dict[str, Any]) -> set[str]:
    """Read the declared queue option without executing the Compose command."""
    command = service.get("command")
    try:
        parts = (
            [str(part) for part in command]
            if isinstance(command, list)
            else shlex.split(str(command or ""))
        )
        # Existing Compose workers use one fixed shell wrapper around exec celery.
        if (
            len(parts) == 3
            and parts[0] in {"sh", "/bin/sh", "bash", "/bin/bash"}
            and parts[1] == "-c"
        ):
            parts = shlex.split(parts[2])
    except ValueError as exc:
        raise AssertionError("Worker command must contain valid shell quoting.") from exc
    options = []
    for index, part in enumerate(parts):
        if part in {"-Q", "--queues"}:
            _require(index + 1 < len(parts), "Worker queue option must have a value.")
            options.append(parts[index + 1])
        elif part.startswith(("-Q=", "--queues=")):
            options.append(part.split("=", 1)[1])
    _require(len(options) == 1, "Worker must declare exactly one explicit queue option.")
    return set(options[0].split(","))


def validate_backend_consistency(
    production_services: dict[str, Any], production_backend: dict[str, Any]
) -> None:
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
            str(environment.get("UNTRUSTED_DOCUMENT_INGESTION_ENABLED", "")).lower() == "true"
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


def validate_workers(production_services: dict[str, Any]) -> None:
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
        _require(
            _worker_queues(service) == set(expected_parts[1:]),
            f"{service_name} must consume exactly its reviewed queue set.",
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
