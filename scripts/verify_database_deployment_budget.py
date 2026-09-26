"""Calculate database pools from the actual rendered deployment, including surge.

Input Compose JSON can contain secrets. Output contains numeric capacity only.
The runtime settings validator remains a process configuration guard; this gate
is the deployment guard and must run after all replica/rollout overrides.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path

from verify_deployment_resource_budget import (
    _nonnegative_integer,
    _replicas,
    _worker_children,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "tooling/database-deployment-budget.json"
MAINTENANCE = {"database-admin", "database-migrate", "storage-copy"}


def calculate(config: dict, policy: dict) -> dict:
    if policy.get("schema_version") != 1 or not policy.get("owner"):
        raise ValueError("A reviewed database capacity policy is required")
    services = config["services"]
    reference = services["backend"]["environment"]
    keys = ("POSTGRES_SERVER_MAX_CONNECTIONS", "POSTGRES_RESERVED_CONNECTIONS", "POSTGRES_API_CONNECTION_BUDGET")
    maximum, reserve, api_budget = (_nonnegative_integer(reference[key]) for key in keys)
    if "db" in services:
        server_command = services["db"].get("command", [])
        if isinstance(server_command, str):
            server_command = shlex.split(server_command)
        if f"max_connections={maximum}" not in server_command:
            raise ValueError("Bundled PostgreSQL command does not match the declared connection ceiling")
    external = _nonnegative_integer(policy["external_connections"])
    maintenance = _nonnegative_integer(policy["maintenance_connections"])
    if maximum <= reserve or maintenance > reserve:
        raise ValueError("Server reserve must cover maintenance and leave application capacity")
    surge = policy["rollout_surge"]
    rows, seen = [], set()
    for name, service in services.items():
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
            raise ValueError("Invalid service identifier")
        env = service.get("environment", {})
        profile = env.get("POSTGRES_POOL_PROFILE")
        if name in MAINTENANCE:
            if "maintenance" not in service.get("profiles", []):
                raise ValueError("Maintenance database consumers must remain opt-in jobs")
            continue
        if profile is None:
            if env.get("POSTGRES_HOST") and name != "db":
                raise ValueError(f"{name}: database consumer requires an explicit pool profile")
            continue
        if profile not in {"api", "worker"} or name not in surge:
            raise ValueError(f"{name}: unreviewed database consumer or profile")
        seen.add(name)
        if any(env.get(key) != reference[key] for key in keys):
            raise ValueError(f"{name}: inconsistent database capacity declaration")
        replicas, overlap = _replicas(service), _nonnegative_integer(surge[name])
        if profile == "api":
            if service.get("command") is not None:
                raise ValueError("API command override requires a separate reviewed process-count contract")
            processes = _nonnegative_integer(env["WEB_CONCURRENCY"])
        else:
            command = service.get("command")
            tokens = shlex.split(command) if isinstance(command, str) else command
            if isinstance(tokens, list) and len(tokens) == 3 and tokens[:2] in (["sh", "-c"], ["/bin/sh", "-c"]):
                tokens = shlex.split(tokens[2])
            processes = _worker_children(tokens)
            if processes is None and name == "email-beat" and isinstance(tokens, list) and "beat" in tokens:
                processes = 1
            if processes is None:
                raise ValueError(f"{name}: cannot establish database process count")
        pool = _nonnegative_integer(env[f"POSTGRES_{profile.upper()}_POOL_SIZE"])
        overflow = _nonnegative_integer(env[f"POSTGRES_{profile.upper()}_MAX_OVERFLOW"])
        if not processes or not pool:
            raise ValueError(f"{name}: unbounded/zero pool or process count is unsupported")
        rows.append({"service": name, "profile": profile, "replicas": replicas,
                     "surge": overlap, "processes_per_replica": processes,
                     "pool_per_process": pool + overflow,
                     "steady_claim": replicas * processes * (pool + overflow),
                     "peak_claim": (replicas + overlap) * processes * (pool + overflow)})
    if seen != set(surge):
        raise ValueError("Capacity policy consumers differ from the rendered deployment")
    steady = sum(row["steady_claim"] for row in rows)
    peak = sum(row["peak_claim"] for row in rows)
    api_peak = sum(row["peak_claim"] for row in rows if row["profile"] == "api")
    errors = []
    if api_peak > api_budget:
        errors.append(f"API peak claim {api_peak} exceeds API budget {api_budget}")
    if peak + external + reserve > maximum:
        errors.append(f"Peak application {peak} + external {external} + reserve {reserve} exceeds server {maximum}")
    return {"schema_version": 1, "rows": rows, "steady_claim": steady, "peak_claim": peak,
            "external_connections": external, "reserved_connections": reserve,
            "maintenance_connections_within_reserve": maintenance,
            "server_max_connections": maximum, "headroom": maximum - reserve - external - peak,
            "errors": errors}


def capacity_markdown(report: dict) -> str:
    lines = ["<!-- Generated by scripts/verify_database_deployment_budget.py; do not hand-edit numbers. -->",
             "| Consumer | Replicas | Surge replicas | Processes / replica | Pool / process | Peak claim |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    lines.extend(f"| {r['service']} | {r['replicas']} | {r['surge']} | {r['processes_per_replica']} | {r['pool_per_process']} | {r['peak_claim']} |" for r in report["rows"])
    lines.append(f"\nSteady application claim **{report['steady_claim']}**; peak **{report['peak_claim']}**; external **{report['external_connections']}**; operational reserve **{report['reserved_connections']}** (includes **{report['maintenance_connections_within_reserve']}** simultaneous maintenance connections); PostgreSQL maximum **{report['server_max_connections']}**; remaining headroom **{report['headroom']}**.\n")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rendered_compose", type=Path)
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--check-markdown", type=Path)
    args = parser.parse_args()
    try:
        report = calculate(json.loads(args.rendered_compose.read_text(encoding="utf-8-sig")), json.loads(args.policy.read_text()))
        if args.markdown:
            args.markdown.write_text(capacity_markdown(report), encoding="utf-8")
        if args.check_markdown and args.check_markdown.read_text(encoding="utf-8") != capacity_markdown(report):
            report["errors"].append("Generated capacity documentation is stale")
        print(json.dumps(report, indent=2))
        return int(bool(report["errors"]))
    except (OSError, ValueError, KeyError, TypeError):
        parser.error("Invalid or incomplete database capacity input; no private configuration was printed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
