"""Explicitly authorized retained direct-release preparation and bounded builds.

Run with Python -B from the exact source archive. This path is separate from the
hosted-CI signed-artifact updater and never weakens that updater's requirements.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid

sys.dont_write_bytecode = True

from mcp_direct_build import BuildError, RetainedBuild, admit_builder, command
from mcp_direct_memory import capture as capture_memory
from mcp_direct_memory import compare as compare_memory
from mcp_direct_memory import require_zero
from mcp_direct_state import ROOT, WORKERS, DirectState, fingerprint, private_json
from release_traveller_whatsapp import release_lock

IDLE_PROBE = """
import json,sys
from celery import Celery
from app.core.config.settings import get_settings
nodes=json.loads(sys.argv[1])
client=Celery('direct_release_probe',broker=get_settings().redis.broker_url)
inspector=client.control.inspect(destination=nodes,timeout=8)
result={}
for method in ('active','reserved','scheduled'):
 rows=getattr(inspector,method)()
 assert isinstance(rows,dict) and set(rows)==set(nodes)
 assert all(isinstance(value,list) for value in rows.values())
 result[method]={node:len(rows[node]) for node in nodes}
print('MCP_DIRECT_IDLE='+json.dumps(result))
"""


def inspect(identifier: str) -> dict:
    rows = json.loads(command("docker", "inspect", identifier))
    if len(rows) != 1 or rows[0]["Id"] != identifier:
        raise BuildError("container_identity_changed")
    return rows[0]


def bound_original(original: dict) -> dict:
    current = inspect(original["Id"])
    if current["Image"] != original["Image"] or any(
        fingerprint(current[key]) != fingerprint(original[key])
        for key in ("Config", "HostConfig", "Mounts")
    ):
        raise BuildError("original_container_configuration_changed")
    return current


def require_idle(containers: dict) -> dict:
    nodes = [
        f"{prefix}@{containers[name]['Config']['Hostname']}"
        for name, prefix in WORKERS.items()
    ]
    backend = bound_original(containers["backend"])
    if not backend["State"]["Running"]:
        raise BuildError("idle_probe_requires_bound_backend")
    output = command(
        "docker",
        "exec",
        backend["Id"],
        "python",
        "-c",
        IDLE_PROBE,
        json.dumps(nodes),
        timeout=40,
    )
    records = [
        line[len("MCP_DIRECT_IDLE=") :]
        for line in output.splitlines()
        if line.startswith("MCP_DIRECT_IDLE=")
    ]
    if len(records) != 1:
        raise BuildError("worker_idle_evidence_unavailable")
    result = json.loads(records[0])
    if set(result) != {"active", "reserved", "scheduled"} or any(
        set(rows) != set(nodes)
        or any(type(count) is not int or count != 0 for count in rows.values())
        for rows in result.values()
    ):
        raise BuildError("workers_busy_wait_before_build")
    return result


def resume_original_workers(state: DirectState, baseline: dict) -> None:
    originals = baseline["containers"]
    database = bound_original(originals["db"])
    schema = command(
        "docker",
        "exec",
        database["Id"],
        "sh",
        "-c",
        (
            'export PGPASSWORD="$POSTGRES_PASSWORD"; '
            'exec psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
            '-c "SELECT version_num FROM public.alembic_version"'
        ),
    )
    if (
        schema != "0113_document_follow_up"
        or not bound_original(originals["backend"])["State"]["Running"]
    ):
        raise BuildError("worker_resume_requires_original_running_source_release")
    running = set(command("docker", "ps", "-q", "--no-trunc").split())
    if not running <= {item["Id"] for item in originals.values()}:
        raise BuildError("worker_resume_requires_no_running_helper_or_candidate")
    for service in WORKERS:
        current = bound_original(baseline["containers"][service])
        if current["State"]["Running"]:
            continue
        if current["State"].get("ExitCode") != 0 or current["State"].get("OOMKilled"):
            raise BuildError("original_worker_did_not_stop_cleanly")
        running_ids = command("docker", "ps", "-q", "--no-trunc").split()
        running = json.loads(command("docker", "inspect", *running_ids))
        admit_builder(
            running,
            int(command("docker", "info", "--format", "{{.MemTotal}}")),
            current["HostConfig"]["Memory"],
        )
        command("docker", "start", current["Id"])
        memory = capture_memory({service: current}, inspect=bound_original)
        private_json(
            state.directory / f"oom-resumed-{current['Id']}-{uuid.uuid4().hex}.json",
            memory,
        )
        require_zero(memory)
        state.event(
            "original-worker-resumed", service=service, container_id=current["Id"]
        )


def check_build_memory(state: DirectState, containers: dict) -> None:
    before = json.loads((state.directory / "oom-prepare.private.json").read_text())
    after = capture_memory(containers, inspect=bound_original)
    private_json(state.directory / f"oom-build-{uuid.uuid4().hex}.json", after)
    compare_memory(
        {"containers": {key: before["containers"][key] for key in containers}}, after
    )


def build(state: DirectState) -> None:
    from mcp_direct_containers import LocalDocker

    baseline = state.load_baseline()
    if (state.directory / "images.json").exists():
        raise BuildError("built_images_already_retained")
    for original in baseline["containers"].values():
        if not bound_original(original)["State"]["Running"]:
            raise BuildError("initial_build_requires_original_services_running")
    check_build_memory(state, baseline["containers"])
    client = LocalDocker()
    state.event(
        "workers-idle-before-build", counts=require_idle(baseline["containers"])
    )
    try:
        for service in WORKERS:
            original = baseline["containers"][service]
            state.event(
                "original-worker-stopping", service=service, container_id=original["Id"]
            )
            client.graceful_stop(original["Id"], timeout=60)
            current = bound_original(original)
            if current["State"]["Running"] or current["State"].get("ExitCode") != 0:
                raise BuildError("worker_has_not_drained")
            state.event(
                "original-worker-drained", service=service, container_id=original["Id"]
            )
        builder = RetainedBuild(state.source, state.directory, state.revision)
        backend = builder.backend(
            baseline["containers"]["backend"]["Image"],
            state.directory / "base-requirements.lock",
        )
        state.event("backend-image-built", **backend)
        frontend = builder.frontend(
            baseline["containers"]["frontend"]["Image"], "https://tech.gctravels.com"
        )
        state.event("frontend-image-built", **frontend)
        private_json(
            state.directory / "images.json",
            {"revision": state.revision, "backend": backend, "frontend": frontend},
        )
    finally:
        # A timed-out builder can still be alive. Capacity is rechecked before
        # each resume; no attempt silently overcommits or kills that builder.
        check_build_memory(
            state,
            {
                key: row
                for key, row in baseline["containers"].items()
                if key not in WORKERS
            },
        )
        resume_original_workers(state, baseline)
        state.verify_retention(baseline)
    state.event("build-complete-original-services-resumed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=(
            "prepare",
            "build",
            "resume-workers",
            "stage",
            "activate",
            "verify",
            "recover-original",
        ),
    )
    parser.add_argument("--revision", required=True)
    options = parser.parse_args()
    if (
        sys.platform != "linux"
        or os.environ.get("DOCKER_HOST")
        or os.environ.get("DOCKER_CONTEXT")
    ):
        raise BuildError("direct_release_requires_local_linux_docker")
    state = DirectState(
        ROOT / "tmp" / f"mcp-direct-{options.revision}", options.revision
    )
    with release_lock(ROOT / "tmp/compose-release-lock"):
        if options.phase == "prepare":
            state.baseline()
        elif options.phase == "build":
            build(state)
        elif options.phase == "resume-workers":
            resume_original_workers(state, state.load_baseline())
        else:
            from mcp_direct_activate import DirectActivation

            deployment = DirectActivation(state)
            getattr(deployment, options.phase.replace("-", "_"))()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - never print operator credentials/configuration from an exception
        # Command output and original container configuration contain secrets.
        print(
            json.dumps({"status": "stopped", "error_type": type(error).__name__,
                        "reason": str(error) if isinstance(error, BuildError) and
                        re.fullmatch("[a-z_]{1,100}", str(error)) else "operator_check_failed"}),
            flush=True,
        )
        raise SystemExit(1) from None
