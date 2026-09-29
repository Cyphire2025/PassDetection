"""Bound local cgroup evidence for the retained direct-release lane."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from mcp_direct_build import BuildError, command
from qa.capacity_container_events import (
    COUNTERS,
    bounded_read,
    cgroup_for,
    parse_events,
)


def capture(
    containers: dict, *, inspect, proc=Path("/proc"), cgroups=Path("/sys/fs/cgroup")
) -> dict:
    try:
        if (
            sys.platform != "linux"
            or os.environ.get("DOCKER_HOST")
            or os.environ.get("DOCKER_CONTEXT")
            or command(
                "docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
            )
            != "unix:///var/run/docker.sock"
            or not 1 <= len(containers) <= 32
        ):
            raise ValueError("binding")
        result = {}
        for service, expected in containers.items():
            current = inspect(expected)
            state = current["State"]
            if current["Id"] != expected["Id"] or state.get("Running") is not True:
                raise ValueError("identity")
            directory = cgroup_for(current["Id"], state["Pid"], proc, cgroups)
            result[service] = {
                "id": current["Id"],
                "started_at": state["StartedAt"],
                "restarts": current["RestartCount"],
                "oom_killed": state["OOMKilled"],
                "events": parse_events(bounded_read(directory / "memory.events")),
            }
        return {"at": datetime.now(UTC).isoformat(), "containers": result}
    except BuildError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise BuildError("bound_cgroup_evidence_unavailable") from None


def compare(before: dict, after: dict) -> None:
    try:
        initial, current = before["containers"], after["containers"]
        if not initial or initial.keys() != current.keys():
            raise ValueError("inventory")
        for service, last in current.items():
            first = initial[service]
            if any(first[key] != last[key] for key in ("id", "started_at", "restarts")):
                raise ValueError("identity")
            left, right = first["events"], last["events"]
            if not {"oom", "oom_kill"} <= left.keys() or (left.keys() & COUNTERS) != (
                right.keys() & COUNTERS
            ):
                raise ValueError("counters")
            if any(
                type(left[key]) is not int
                or type(right[key]) is not int
                or left[key] < 0
                or right[key] != left[key]
                for key in left.keys() & COUNTERS
            ):
                raise ValueError("delta")
            if first["oom_killed"] is not True and last["oom_killed"] is True:
                raise ValueError("oom")
    except (ValueError, KeyError, TypeError):
        raise BuildError("new_oom_or_container_identity_change") from None


def require_zero(snapshot: dict) -> None:
    try:
        for row in snapshot["containers"].values():
            if (
                row["oom_killed"]
                or row["restarts"] != 0
                or any(
                    row["events"][key] != 0 for key in row["events"].keys() & COUNTERS
                )
            ):
                raise ValueError("new_container_oom")
    except (ValueError, KeyError, TypeError):
        raise BuildError("new_container_oom_or_restart") from None
