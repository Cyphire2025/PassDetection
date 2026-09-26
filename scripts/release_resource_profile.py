"""Bind the opt-in KVM4 configuration to its measured workload envelope."""
from __future__ import annotations

import re
import shlex
import stat
import sys
from pathlib import Path
from typing import Any

from image_runtime_policy import (
    BACKEND_PROCESSES,
    WORKER_COMMANDS,
    reviewed_process_command,
)
from verify_deployment_resource_budget import _memory_bytes

PROVIDERS = ("MY_PHOTOS_LIVENESS_PROVIDER", "MY_PHOTOS_FACE_SEARCH_PROVIDER", "MY_PHOTOS_MEDIA_PROVIDER")
UNCHANGED_SWAP_SERVICES = frozenset({"nginx", "metrics-exporter"})
EXPECTED_ENV = {
    "WEB_CONCURRENCY": "4", "WORKER_CONCURRENCY": "1", "EMAIL_WORKER_CONCURRENCY": "1",
    "EMAIL_AI_WORKER_CONCURRENCY": "1", "MY_PHOTOS_WORKER_CONCURRENCY": "1",
    "GEMINI_EXTRACTION_MAX_CONCURRENCY": "1", "GEMINI_VERIFICATION_MAX_CONCURRENCY": "1",
    "GEMINI_IMAGE_EDIT_MAX_CONCURRENCY": "1", "POSTGRES_API_POOL_SIZE": "3",
    "POSTGRES_API_MAX_OVERFLOW": "3", "POSTGRES_WORKER_POOL_SIZE": "1",
    "POSTGRES_WORKER_MAX_OVERFLOW": "0", "POSTGRES_API_CONNECTION_BUDGET": "24",
    "POSTGRES_SERVER_MAX_CONNECTIONS": "100", "POSTGRES_RESERVED_CONNECTIONS": "10",
}


def validate_profile(config: dict[str, Any], metadata: dict[str, Any], *, activation: bool,
                     my_photos_jobs: int, live_backend_environment: dict[str, str]) -> None:
    if (metadata.get("schema_version") != 1 or metadata.get("profile") != "kvm4"
            or metadata.get("host_reserve_mib") != 2048 or metadata.get("api_processes") != 4
            or metadata.get("worker_children_each") != 1):
        raise ValueError("KVM4 profile metadata changed outside the reviewed contract")
    if activation and metadata.get("qualification_status") != "qualified":
        raise ValueError("KVM4 activation requires completed actual-image and lifecycle qualification")
    limits = {**metadata["memory_limits_mib"], **metadata["maintenance_limits_mib"]}
    services = config["services"]
    if set(services) != set(limits):
        raise ValueError("KVM4 service inventory differs from the qualified profile")
    for name, memory_mib in limits.items():
        service = services[name]
        if _memory_bytes(service.get("mem_limit")) != memory_mib * 1024**2:
            raise ValueError(f"{name}: memory ceiling differs from the qualified profile")
        if name in UNCHANGED_SWAP_SERVICES:
            if service.get("memswap_limit") is not None:
                raise ValueError(f"{name}: unchanged service must retain its existing swap setting on the verified swap-free host")
        elif _memory_bytes(service.get("memswap_limit")) != memory_mib * 1024**2:
            raise ValueError(f"{name}: swap must remain disabled at the qualified memory ceiling")
        if service.get("scale", 1) != 1 or service.get("deploy", {}).get("replicas", 1) != 1:
            raise ValueError(f"{name}: KVM4 profile supports one container per service")
    if sum(metadata["memory_limits_mib"].values()) != metadata["steady_container_ceiling_mib"]:
        raise ValueError("KVM4 metadata total is inconsistent")
    if float(services["backend"].get("cpus", 0)) != 4:
        raise ValueError("KVM4 API requires the qualified four-CPU ceiling")
    for name in BACKEND_PROCESSES:
        environment = services[name].get("environment", {})
        if any(str(environment.get(key, "")) != value for key, value in EXPECTED_ENV.items()):
            raise ValueError(f"{name}: API/worker/pool concurrency differs from qualification")
        for key in PROVIDERS:
            if str(environment.get(key, "disabled")).lower() != "disabled":
                raise ValueError("Enabled My Photos providers require a separately qualified resource profile")
        # These are existing application defaults exercised at their accepted
        # maxima, not a reduced user limit. A larger operator override needs a
        # new memory qualification, never silent acceptance under smaller caps.
        for key, maximum in {"UPLOAD_MAX_FILE_SIZE_BYTES": 10 * 1024**2,
                             "UPLOAD_MAX_PIXELS": 24_000_000,
                             "ECR_IMAGE_MAX_PIXELS": 40_000_000,
                             "ECR_IMAGE_MAX_DIMENSION": 2000,
                             "ECR_MAX_CONCURRENCY": 8,
                             "EMAIL_ATTACHMENT_MAX_BYTES": 25 * 1024**2,
                             "EMAIL_PDF_MAX_PAGES": 100}.items():
            value = str(environment.get(key, maximum))
            if not re.fullmatch(r"[0-9]+", value) or int(value) > maximum:
                raise ValueError(f"{name}: {key} exceeds the measured input envelope")
    for name in WORKER_COMMANDS:
        if services[name].get("command") != reviewed_process_command(name, concurrency=1):
            raise ValueError(f"{name}: must retain its reviewed queues with exactly one child")
    if services["db"].get("command") != ["postgres", "-c", "max_connections=100"]:
        raise ValueError("PostgreSQL settings differ from the qualified connection/query memory envelope")
    for name, maximum_mib in {"redis": 128, "redis-broker": 512, "redis-realtime": 128, "redis-cache": 256}.items():
        command = services[name].get("command")
        tokens = shlex.split(command) if isinstance(command, str) else command
        if not isinstance(tokens, list) or not tokens or tokens[0] != "redis-server" or tokens.count("--maxmemory") != 1:
            raise ValueError(f"{name}: must declare one reviewed Redis maxmemory bound")
        position = tokens.index("--maxmemory")
        if position + 1 >= len(tokens) or _memory_bytes(tokens[position + 1]) > maximum_mib * 1024**2:
            raise ValueError(f"{name}: maxmemory exceeds the qualified Redis envelope")
        policy = "allkeys-lru" if name == "redis-cache" else "noeviction"
        if tokens.count("--maxmemory-policy") != 1 or tokens[tokens.index("--maxmemory-policy") + 1:] == []:
            raise ValueError(f"{name}: Redis eviction policy is missing")
        if tokens[tokens.index("--maxmemory-policy") + 1] != policy:
            raise ValueError(f"{name}: Redis eviction policy differs from the qualified data boundary")
    if any(live_backend_environment.get(key, "disabled").lower() != "disabled" for key in PROVIDERS):
        raise ValueError("KVM4 cannot lower memory beneath an already enabled My Photos workload")
    if isinstance(my_photos_jobs, bool) or not isinstance(my_photos_jobs, int) or my_photos_jobs != 0:
        raise ValueError("KVM4 My Photos qualification requires an empty existing job table")


def validate_local_swap_free_host(docker_endpoint: str) -> None:
    """The two unchanged service swap allowances are safe only without host swap."""
    if sys.platform != "linux" or not docker_endpoint.startswith("unix://"):
        raise ValueError("KVM4 activation requires a verified local Linux Docker socket")
    socket = Path(docker_endpoint.removeprefix("unix://"))
    if not socket.is_absolute() or not stat.S_ISSOCK(socket.stat().st_mode):
        raise ValueError("KVM4 Docker endpoint is not a local Unix socket")
    memory = Path("/proc/meminfo").read_text()
    swap = re.findall(r"^SwapTotal:\s+(\d+)\s+kB\s*$", memory, re.MULTILINE)
    if swap != ["0"]:
        raise ValueError("KVM4 unchanged infrastructure exception requires zero configured host swap")
