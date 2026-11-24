"""Rendered Compose services validation policies."""

from __future__ import annotations

from typing import Any

from compose_runtime_contract import (
    BACKEND_SERVICES,
    INTERNAL_SERVICES,
    NGINX_PUBLISHED_TARGETS,
    PINNED_CLAMAV_IMAGE,
    PINNED_NGINX_IMAGE,
    PINNED_STATSD_EXPORTER_IMAGE,
)
from compose_runtime_values import (
    _command_text,
    _healthcheck_text,
    _published_port_targets,
    _require,
    _volume_targets,
)
from storage_release import STORAGE_IMAGE


def validate_production_topology(
    production_services: dict[str, Any], production_backend: dict[str, Any]
) -> None:
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
        production_services["minio"].get("image") == STORAGE_IMAGE,
        "Current production storage must use the maintained immutable provider digest.",
    )
    storage = production_services["minio"]
    _require(
        storage.get("user") == "1000:1000" and storage.get("cap_drop") == ["ALL"],
        "Maintained storage must run without root or Linux capabilities.",
    )
    _require(
        storage.get("environment", {}) == {},
        "Provider administrator credentials belong in the protected identity file.",
    )
    _require(
        "-ip.bind=127.0.0.1" in _command_text(storage)
        and "-s3.ip.bind=0.0.0.0" in _command_text(storage),
        "Only authenticated S3 may bind the application network.",
    )
    _require(
        "minio_data" not in {value.get("source") for value in storage.get("volumes", [])},
        "SeaweedFS must never open the original MinIO data volume.",
    )
    _require(
        "maintenance" in production_services["storage-stage"].get("profiles", [])
        and "maintenance" in production_services["storage-copy"].get("profiles", []),
        "Copy/staging services must not run during ordinary application startup.",
    )
    clamav = production_services["clamav"]
    _require(
        clamav.get("image") == PINNED_CLAMAV_IMAGE,
        "Production ClamAV must use the reviewed immutable feature-line digest.",
    )
    _require(
        clamav.get("user") == "clamav" and clamav.get("entrypoint") == ["/init-unprivileged"],
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
    _require(
        any(
            mount.startswith("/var/log/clamav:")
            and {"uid=100", "gid=101", "mode=0750"}.issubset(set(mount.split(":", 1)[1].split(",")))
            for mount in clamav.get("tmpfs", [])
        ),
        "ClamAV's temporary log directory must be writable by its unprivileged user.",
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
