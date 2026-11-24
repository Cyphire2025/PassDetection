"""Inspect the isolated capacity profile and run its fixed synthetic fixture command."""

from __future__ import annotations

import json
import subprocess

from mcp_capacity_profile import require_minimum_profile
from run_qualification_stack import COMPOSE, ROOT
from workload_capacity_contract import API_MEMORY_BYTES, FIXTURES, ORIGIN


def fixture(action: str, run_id: str) -> dict:
    result = subprocess.run(
        [*FIXTURES, action, run_id],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=150,
        check=True,
    )
    # The seed includes short-lived synthetic access tokens. They stay in
    # memory and must not be included in retained reports or console output.
    return json.loads(result.stdout.strip().splitlines()[-1])


def inspect_backend() -> dict:
    inspection = json.loads(
        subprocess.check_output(
            [*COMPOSE, "ps", "--format", "json"], cwd=ROOT, text=True
        ).splitlines()[0]
    )
    if inspection.get("Project") not in {None, "passdetection-qualification"}:
        raise RuntimeError("Unexpected Compose project")
    backend_id = subprocess.check_output(
        [*COMPOSE, "ps", "-q", "backend"], cwd=ROOT, text=True
    ).strip()
    backend = json.loads(subprocess.check_output(["docker", "inspect", backend_id], text=True))[0]
    if (
        backend["Config"].get("Labels", {}).get("com.docker.compose.project")
        != "passdetection-qualification"
    ):
        raise RuntimeError(
            "Backend container does not belong to the isolated qualification project"
        )
    env = dict(item.split("=", 1) for item in backend["Config"]["Env"] if "=" in item)
    require_minimum_profile(
        enabled=env.get("MCP_ENABLED", "").lower() == "true",
        capabilities=json.loads(env.get("MCP_ENABLED_CAPABILITIES", "[]")),
        families=json.loads(env.get("MCP_EXPORT_FAMILIES", "[]")),
        rows=int(env.get("MCP_EXPORT_SOURCE_ROW_LIMIT", "0")),
        byte_limit=int(env.get("MCP_EXPORT_SOURCE_BYTE_LIMIT", "0")),
    )
    if (
        env.get("POSTGRES_DB") != "passdetection_ci_browser"
        or env.get("WEB_CONCURRENCY") != "4"
        or env.get("POSTGRES_API_POOL_SIZE") != "3"
        or env.get("POSTGRES_API_MAX_OVERFLOW") != "3"
        or env.get("MALWARE_SCANNER_TIMEOUT_SECONDS") != "10.0"
        or env.get("MCP_ENABLED", "").lower() != "true"
        or env.get("MCP_PUBLIC_ORIGIN") != ORIGIN
        or env.get("MCP_FRONTEND_ORIGIN") != ORIGIN
        or set(json.loads(env.get("MCP_ENABLED_CAPABILITIES", "[]"))) != {"mcp:read", "mcp:export"}
        or backend["HostConfig"]["Memory"] != API_MEMORY_BYTES
        or backend["HostConfig"]["MemorySwap"] != API_MEMORY_BYTES
        or backend["HostConfig"]["NanoCpus"] != 4 * 10**9
    ):
        raise RuntimeError(
            "Capacity lane requires its reviewed 4-worker/24-connection/2560MiB overlay"
        )
    return backend


# Preserve the original QA import and pickle identities through its facade.
for _export in (
    fixture,
    inspect_backend,
):
    _export.__module__ = "qualify_workload_capacity"
del _export
