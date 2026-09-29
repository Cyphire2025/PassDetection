"""Read cgroup-v2 event deltas for the fixed local qualification project.

No container is changed. Each host /proc cgroup must name its inspected Docker
ID; remote daemons and Docker Desktop VM PID lookalikes cannot supply evidence.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT = "passdetection-qualification"
MAX_CONTAINERS = 32
REQUIRED = frozenset({"backend", "frontend", "nginx", "worker", "ecr-worker", "scheduler",
                      "postgres", "redis", "object-storage", "clamav"})
COUNTERS = frozenset({"oom", "oom_kill", "oom_group_kill"})
FORMAT = ('{"id":{{json .Id}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
          '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
          '"root":{{json (index .Config.Labels "com.docker.compose.project.working_dir")}},'
          '"oneoff":{{json (index .Config.Labels "com.docker.compose.oneoff")}},'
          '"state":{{json .State}},"restarts":{{json .RestartCount}}}')


def command(*arguments: str) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=10, check=True)
    if len(result.stdout) > 16384:
        raise ValueError("Container observation exceeded its fixed output budget")
    return result.stdout.strip()


def bounded_read(path: Path) -> str:
    with path.open("rb") as stream:
        value = stream.read(4097)
    if len(value) > 4096:
        raise ValueError("Kernel observation exceeded its fixed input budget")
    return value.decode("ascii")


def parse_events(raw: str) -> dict[str, int]:
    result = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[a-z_]+", parts[0]) or not parts[1].isdigit():
            raise ValueError("Invalid cgroup event evidence")
        name, value = parts
        if name in result:
            raise ValueError("Duplicate cgroup event evidence")
        result[name] = int(value)
    if not {"oom", "oom_kill"} <= result.keys():
        raise ValueError("Missing cgroup OOM evidence")
    return result


def cgroup_for(identifier: str, pid: int, proc: Path, root: Path) -> Path:
    if type(pid) is not int or pid <= 0 or not re.fullmatch(r"[0-9a-f]{64}", identifier):
        raise ValueError("Invalid local container identity")
    lines = bounded_read(proc / str(pid) / "cgroup").splitlines()
    if len(lines) != 1 or not lines[0].startswith("0::/"):
        raise ValueError("Native unified cgroup-v2 evidence required")
    relative = lines[0][4:]
    pieces = Path(relative).parts
    if not pieces or ".." in pieces or pieces[-1] not in {identifier, f"docker-{identifier}.scope"}:
        raise ValueError("Host process cgroup does not match the inspected container")
    base, path = root.resolve(strict=True), (root / relative).resolve(strict=True)
    if not path.is_relative_to(base) or path == base:
        raise ValueError("Container cgroup escaped the kernel hierarchy")
    return path


def capture(workspace: Path, *, run=command, proc: Path = Path("/proc"),
            cgroups: Path = Path("/sys/fs/cgroup")) -> dict:
    if not sys.platform.startswith("linux") or os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise ValueError("Native local Linux Docker evidence required")
    if run("docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}") != "unix:///var/run/docker.sock":
        raise ValueError("The fixed local Docker daemon is required")
    identifiers = run("docker", "ps", "-q", "--no-trunc", "--filter",
                      f"label=com.docker.compose.project={PROJECT}", "--filter",
                      "label=com.docker.compose.oneoff=False").split()
    if not identifiers or len(identifiers) > MAX_CONTAINERS or len(set(identifiers)) != len(identifiers):
        raise ValueError("Unexpected qualification container inventory")
    containers = {}
    for identifier in identifiers:
        if not re.fullmatch(r"[0-9a-f]{64}", identifier):
            raise ValueError("Invalid Docker container identifier")
        item = json.loads(run("docker", "inspect", "--format", FORMAT, identifier))
        service, state = item["service"], item["state"]
        if (item["id"] != identifier or item["project"] != PROJECT or item["oneoff"] != "False"
                or Path(item["root"]).resolve() != workspace.resolve()
                or not isinstance(service, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", service)
                or service in containers or state.get("Running") is not True):
            raise ValueError("Qualification container binding changed")
        directory = cgroup_for(identifier, state["Pid"], proc, cgroups)
        events = parse_events(bounded_read(directory / "memory.events"))
        containers[service] = {"id": identifier, "started_at": state["StartedAt"],
            "restarts": item["restarts"], "oom_killed": state["OOMKilled"], "events": events}
    if not REQUIRED <= containers.keys():
        raise ValueError("Incomplete workload container inventory")
    return {"at": datetime.now(UTC).isoformat(), "containers": containers}


def gates(before: dict | None, after: dict | None) -> list[str]:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return ["containers:missing_oom_evidence"]
    original, current = before.get("containers", {}), after.get("containers", {})
    if not REQUIRED <= original.keys() or original.keys() != current.keys():
        return ["containers:inventory_changed_or_incomplete"]
    failures = []
    for service in sorted(original):
        first, last = original[service], current[service]
        if any(first.get(key) != last.get(key) for key in ("id", "started_at", "restarts")):
            failures.append(f"containers:{service}:restarted_or_replaced")
        left, right = first.get("events", {}), last.get("events", {})
        if not {"oom", "oom_kill"} <= left.keys() or (left.keys() & COUNTERS) != (right.keys() & COUNTERS):
            failures.append(f"containers:{service}:missing_oom_evidence")
            continue
        for event in sorted(left.keys() & COUNTERS):
            initial, final = left[event], right[event]
            if type(initial) is not int or type(final) is not int or initial < 0 or final < initial:
                failures.append(f"containers:{service}:invalid_oom_evidence")
            elif final > initial:
                failures.append(f"containers:{service}:{event}_during_workload")
        if first.get("oom_killed") is not True and last.get("oom_killed") is True:
            failures.append(f"containers:{service}:new_oom_killed_flag")
    return sorted(set(failures))
