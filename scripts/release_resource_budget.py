"""Account for normal and fenced release phases without weakening memory caps.

Planning uses the candidate Compose ceilings. Execution admission additionally
counts EVERY running Docker container, including unrelated projects, using its
actual inspected cap. A maintenance profile is not evidence that it is stopped.
"""
from __future__ import annotations

import copy
from typing import Any

from verify_deployment_resource_budget import _memory_bytes, validate_budget

HOST_RESERVE_BYTES = 2 * 1024**3
MAINTENANCE_SERVICES = frozenset({"database-admin", "database-migrate", "storage-stage", "storage-copy"})
PERSISTENT_REPLACEMENTS = frozenset({"db", "clamav"})


def plan_release_phases(config: dict[str, Any], *, host_memory_bytes: int,
                        writers: set[str]) -> dict[str, Any]:
    if isinstance(host_memory_bytes, bool) or not isinstance(host_memory_bytes, int) or host_memory_bytes <= HOST_RESERVE_BYTES:
        raise ValueError("Docker host memory must exceed the fixed 2 GiB host reserve")
    services = config.get("services")
    if not isinstance(services, dict) or not writers or not writers <= services.keys():
        raise ValueError("Release phase planning requires every application writer")
    if not MAINTENANCE_SERVICES <= services.keys():
        raise ValueError("Release phase planning requires all four reviewed maintenance services")
    for name, service in services.items():
        profiles = service.get("profiles", [])
        if name in MAINTENANCE_SERVICES:
            if profiles != ["maintenance"] or service.get("restart", "no") != "no":
                raise ValueError(f"{name}: maintenance service must be opt-in and non-restarting")
        elif profiles:
            raise ValueError(f"{name}: unreviewed profile requires explicit resource planning")
    normal = {name: service for name, service in services.items() if name not in MAINTENANCE_SERVICES}
    phases = {"steady": normal}
    fenced = {name: service for name, service in normal.items() if name not in writers}
    for helper in ("database-admin", "database-migrate"):
        phases[helper] = {**fenced, helper: services[helper]}
    phases["storage-copy"] = {**fenced, **{name: services[name] for name in ("storage-stage", "storage-copy")}}
    rows = {}
    errors = []
    for name, selected in phases.items():
        failures, total = validate_budget({"services": selected}, host_memory_bytes / 1024**3, 2)
        rows[name] = {"container_bytes": round(total * 1024**3), "services": sorted(selected),
                      "requires_stopped_writers": sorted(writers) if name != "steady" else [], "errors": failures}
        errors.extend(f"{name}: {failure}" for failure in failures)
    return {"host_memory_bytes": host_memory_bytes, "host_reserve_bytes": HOST_RESERVE_BYTES,
            "phases": rows, "errors": errors,
            "execution_requirement": "Every maintenance admission must independently inspect all live containers and prove writers stopped"}


def admit_live_phase(config: dict[str, Any], *, host_memory_bytes: int,
                     project: str, running_containers: list[dict[str, Any]],
                     starting_services: set[str], required_stopped: set[str]) -> dict[str, int]:
    """Admit one reviewed phase using actual concurrent caps, including foreigners.

    Database/ClamAV replacements are admitted only after the original process
    has stopped. Redis is deliberately absent: its volatile data requires an
    in-place resize, never admission of a replacement container.
    """
    services = config.get("services", {})
    if not project or not starting_services or not starting_services <= services.keys():
        raise ValueError("Phase admission requires an exact project and known starting services")
    replacing_persistent = bool(starting_services & PERSISTENT_REPLACEMENTS)
    if replacing_persistent:
        if len(starting_services) != 1:
            raise ValueError("Persistent replacements must execute serially without helpers")
    elif not starting_services <= MAINTENANCE_SERVICES:
        raise ValueError("This admission path only starts reviewed maintenance helpers or persistent replacements")
    if {"database-admin", "database-migrate"} <= starting_services:
        raise ValueError("Database administrative and migration helpers must execute serially")
    if starting_services & {"database-admin", "database-migrate"} and len(starting_services) != 1:
        raise ValueError("A database helper cannot overlap another maintenance helper")
    live_total = 0
    seen_ids = set()
    for container in running_containers:
        if not container.get("State", {}).get("Running"):
            continue
        identity = container.get("Id")
        if not isinstance(identity, str) or not identity or identity in seen_ids:
            raise ValueError("Live container inventory must have unique inspected identities")
        seen_ids.add(identity)
        labels = container.get("Config", {}).get("Labels") or {}
        service = labels.get("com.docker.compose.service")
        if labels.get("com.docker.compose.project") == project:
            if service in required_stopped:
                raise ValueError(f"{service}: application writer is still running")
            if replacing_persistent and service in starting_services:
                raise ValueError(f"{service}: original persistent process is still running")
            if service in MAINTENANCE_SERVICES and not (service == "storage-stage" and starting_services == {"storage-copy"}):
                raise ValueError(f"{service}: another maintenance helper is still running")
        # A zero/unset Docker cap is unbounded, never zero consumption.
        live_total += _memory_bytes(container.get("HostConfig", {}).get("Memory"))
    selected = copy.deepcopy({name: services[name] for name in starting_services})
    failures, starting_gib = validate_budget({"services": selected}, host_memory_bytes / 1024**3, 2)
    if failures:
        raise ValueError("Starting service resource declaration is invalid: " + "; ".join(failures))
    starting_bytes = round(starting_gib * 1024**3)
    if live_total + starting_bytes + HOST_RESERVE_BYTES > host_memory_bytes:
        raise ValueError("Actual running containers plus the requested helper and fixed host reserve exceed physical memory")
    return {"live_container_bytes": live_total, "starting_container_bytes": starting_bytes,
            "host_reserve_bytes": HOST_RESERVE_BYTES, "host_memory_bytes": host_memory_bytes}
