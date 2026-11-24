"""Read-only host and existing application observations; no rollout or cleanup.

Run on the existing Linux VPS with its authorized local Docker context. Output
contains bounded operational metadata, never full environment/config/log data.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from release_reliability import ReliabilityRelease
from release_traveller_whatsapp import ReleaseError

PROJECT = "com.docker.compose.project"
SERVICE = "com.docker.compose.service"
DIRECTORY = "com.docker.compose.project.working_dir"
ID = re.compile(r"[a-f0-9]{64}")
REVISION = re.compile(r"[a-f0-9]{40}")
SCHEMA = re.compile(r"[0-9]{4}_[a-z0-9_]+")
NUMERIC_SETTINGS = (
    "WEB_CONCURRENCY", "POSTGRES_API_POOL_SIZE", "POSTGRES_API_MAX_OVERFLOW",
    "POSTGRES_WORKER_POOL_SIZE", "POSTGRES_WORKER_MAX_OVERFLOW",
    "POSTGRES_SERVER_MAX_CONNECTIONS", "POSTGRES_RESERVED_CONNECTIONS",
)
CAPABILITIES = {"mcp:read", "mcp:export", "mcp:upload", "mcp:change", "mcp:communicate", "mcp:diagnose"}
DATABASE_SQL = """SELECT json_build_object(
  'schema', (SELECT version_num FROM public.alembic_version),
  'max_connections', current_setting('max_connections')::int,
  'total_connections', (SELECT count(*) FROM pg_stat_activity),
  'database_connections', (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()),
  'has_mcp_control', to_regclass('public.mcp_control') IS NOT NULL)
"""
PSQL = ('export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -X -A -t -v ON_ERROR_STOP=1 '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"')


class BaselineError(RuntimeError):
    pass


def run(*arguments: str) -> str:
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise BaselineError("A required read-only probe could not finish") from None
    if result.returncode or len(result.stdout) > 8 * 1024 * 1024:
        # Commands can fail with environment values in stderr. Never expose them.
        raise BaselineError("A required read-only probe failed or exceeded its output bound")
    return result.stdout.strip()


def runtime_configuration(container: dict) -> dict:
    values = dict(value.split("=", 1) for value in container.get("Config", {}).get("Env", []) if "=" in value)
    output = {name: int(values[name]) if values.get(name, "").isascii()
              and values.get(name, "").isdigit() else None for name in NUMERIC_SETTINGS}
    revision, schema = values.get("APP_REVISION", ""), values.get("EXPECTED_DATABASE_SCHEMA_REVISION", "")
    output["revision"] = revision if REVISION.fullmatch(revision) else None
    output["configured_schema"] = schema if SCHEMA.fullmatch(schema) else None
    enabled = values.get("MCP_ENABLED", "").lower()
    output["mcp_deployment_enabled"] = True if enabled in {"true", "1"} else False if enabled in {"false", "0"} else None
    try:
        scopes = json.loads(values.get("MCP_ENABLED_CAPABILITIES", "null"))
    except (ValueError, TypeError):
        scopes = None
    output["mcp_enabled_capabilities"] = sorted(set(scopes)) if isinstance(scopes, list) and all(isinstance(value, str) and value in CAPABILITIES for value in scopes) else None
    return output


def memory_snapshot(source: str) -> dict:
    fields = dict(re.findall(r"^(MemTotal|MemAvailable|SwapTotal|SwapFree):\s+(\d+) kB$", source, re.MULTILINE))
    if set(fields) != {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
        raise BaselineError("Host memory observation is incomplete")
    return {name + "_bytes": int(value) * 1024 for name, value in fields.items()}


def collect(root: Path, *, runner=run, memory: str | None = None) -> dict:
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise BaselineError("Use the authorized default local Docker context")
    endpoint = runner("docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
    if not endpoint.startswith("unix:///"):
        raise BaselineError("The baseline requires the existing host's local Docker socket")
    identifiers = runner("docker", "ps", "-aq", "--no-trunc").split()
    if not identifiers or len(identifiers) > 512 or any(not ID.fullmatch(value) for value in identifiers):
        raise BaselineError("Container inventory is unavailable or exceeds the 512-container bound")
    containers = []
    for start in range(0, len(identifiers), 20):
        batch = json.loads(runner("docker", "inspect", *identifiers[start:start + 20]))
        if not isinstance(batch, list) or {item.get("Id") for item in batch} != set(identifiers[start:start + 20]):
            raise BaselineError("Container inspection did not match the requested identities")
        containers.extend(batch)
    bound = [item for item in containers if item.get("Config", {}).get("Labels", {}).get(DIRECTORY) == str(root)]
    backends = [item for item in bound if item["Config"]["Labels"].get(SERVICE) == "backend"
                and item.get("State", {}).get("Running")
                and item["Config"]["Labels"].get("com.docker.compose.oneoff") == "False"]
    if len(backends) != 1:
        raise BaselineError("Exactly one running application backend must match the explicit deployment root")
    project = backends[0]["Config"]["Labels"].get(PROJECT)
    if not isinstance(project, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", project):
        raise BaselineError("The existing Compose project identity is invalid")
    selected = [item for item in bound if item["Config"]["Labels"].get(PROJECT) == project]
    databases = [item for item in selected if item["Config"]["Labels"].get(SERVICE) == "db" and item.get("State", {}).get("Running")]
    if len(databases) != 1:
        raise BaselineError("Exactly one existing project database must be running")
    ReliabilityRelease._verify_live_database_target(backends[0], databases[0])
    database = json.loads(runner("docker", "exec", databases[0]["Id"], "sh", "-c", PSQL, "mcp-readonly-baseline", DATABASE_SQL))
    if (not isinstance(database, dict) or set(database) != {"schema", "max_connections", "total_connections", "database_connections", "has_mcp_control"}
            or not isinstance(database["schema"], str) or not SCHEMA.fullmatch(database["schema"])
            or any(type(database[key]) is not int or database[key] < 0 for key in ("max_connections", "total_connections", "database_connections"))
            or type(database["has_mcp_control"]) is not bool):
        raise BaselineError("Database baseline returned an invalid bounded observation")
    database["mcp_emergency_enabled"] = None
    if database["has_mcp_control"]:
        value = runner("docker", "exec", databases[0]["Id"], "sh", "-c", PSQL, "mcp-readonly-baseline", "SELECT enabled FROM public.mcp_control WHERE id=1")
        if value not in {"t", "f"}:
            raise BaselineError("MCP control state is unavailable")
        database["mcp_emergency_enabled"] = value == "t"
    running = [item for item in selected if item.get("State", {}).get("Running")]
    host_running = [item for item in containers if item.get("State", {}).get("Running")]
    host_limits = [item.get("HostConfig", {}).get("Memory") for item in host_running]
    if any(type(value) is not int or value < 0 for value in host_limits):
        raise BaselineError("Host container memory limits are unavailable")
    statistics = runner("docker", "stats", "--no-stream", "--no-trunc", "--format", "{{json .}}", *[item["Id"] for item in running])
    stats = {}
    for line in statistics.splitlines():
        entry = json.loads(line)
        identifier = entry.get("ID", entry.get("Container"))
        if identifier not in {item["Id"] for item in running} or identifier in stats:
            raise BaselineError("Container usage observation has unknown or repeated identities")
        allowed = {key: entry.get(key) for key in ("CPUPerc", "MemUsage", "MemPerc", "PIDs")}
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9 .%/A-Za-z-]{1,80}", value) for value in allowed.values()):
            raise BaselineError("Container usage contains unexpected values")
        stats[identifier] = allowed
    if set(stats) != {item["Id"] for item in running}:
        raise BaselineError("Container usage observation is incomplete")
    rows = []
    for item in selected:
        labels, state, limits = item["Config"]["Labels"], item["State"], item["HostConfig"]
        rows.append({"id": item["Id"], "service": labels.get(SERVICE), "image_id": item.get("Image"),
                     "running": state.get("Running"), "oom_killed": state.get("OOMKilled"),
                     "memory_limit_bytes": limits.get("Memory"), "swap_limit_bytes": limits.get("MemorySwap"),
                     "nano_cpus": limits.get("NanoCpus"), "usage": stats.get(item["Id"]),
                     "configuration": runtime_configuration(item) if labels.get(SERVICE) == "backend" else None})
    return {"schema_version": 1, "observed_at": datetime.now(timezone.utc).isoformat(),
            "scope": "read-only existing-host snapshot", "deployment_root": str(root), "compose_project": project,
            "host_memory": memory_snapshot(memory if memory is not None else Path("/proc/meminfo").read_text()),
            "host_container_count": len(containers), "unrelated_container_count": len(containers) - len(selected),
            "host_running_container_count": len(host_running),
            "unrelated_running_container_count": len(host_running) - len(running),
            "host_running_memory_limit_bytes": sum(host_limits),
            "host_running_unbounded_memory_count": host_limits.count(0),
            "database": database, "containers": rows,
            "limitations": ["One snapshot is not a workload or MCP-overhead measurement.",
                            "This does not qualify runtime grants, storage, backup, migration or recovery.",
                            "No containers, queues, credentials, application records or deployment settings were changed."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Exact existing Compose working directory")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output", type=Path, help="New local JSON evidence file; never overwritten")
    destination.add_argument("--stdout", action="store_true", help="Return bounded evidence over an existing authenticated transport without writing a remote file")
    args = parser.parse_args()
    if sys.platform != "linux" or args.root.is_symlink() or not args.root.is_absolute() or not args.root.is_dir():
        raise BaselineError("Run on the existing Linux VPS with its explicit regular deployment directory")
    report = collect(args.root.resolve())
    if args.stdout:
        print(json.dumps(report, indent=2))
        return
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("Read-only baseline saved. No deployment or cleanup was performed.")


if __name__ == "__main__":
    try:
        main()
    except (BaselineError, ReleaseError, OSError, ValueError, TypeError, KeyError):
        print("Baseline could not be verified; no partial evidence was reported.", file=sys.stderr)
        raise SystemExit(1) from None
