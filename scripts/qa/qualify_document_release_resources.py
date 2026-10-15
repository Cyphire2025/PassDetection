"""Qualify the exact document release images with isolated synthetic workloads.

No production credentials, mounts or service changes are used. This receipt is
additional resource evidence; the release executor still requires signed Full CI
images, source admission, a writer fence and fresh production resource readback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from qa.qualify_document_delivery_rebalance import frontend_probe, guard, redis_probe
from qa.qualify_retained_redis_transition import qualify as qualify_redis_transition
from release_document_resources import CHECKS, DATASETS, LIMITS, OVERLAY, PROFILE, qualified_source_hashes, sha256

LABEL = "passdetection.qa.run"
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}")


def command(*args: str, timeout: int = 60) -> str:
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    return result.stdout.strip()


def inspect(reference: str, *, image: bool = False) -> dict:
    return json.loads(command("docker", *(["image"] if image else []), "inspect", reference))[0]


def verify_inputs(revision: str, images: dict[str, str], postgres: str) -> None:
    if not __debug__:
        raise ValueError("optimized_python_cannot_run_resource_qualification")
    if not re.fullmatch(r"[a-f0-9]{40}", revision) or set(images) != {"backend", "frontend", *DATASETS}:
        raise ValueError("exact_revision_and_image_inventory_required")
    if any(not isinstance(value, str) or not IMAGE_ID.fullmatch(value) for value in (*images.values(), postgres)):
        raise ValueError("immutable_local_images_required")
    if command("git", "-C", str(ROOT), "rev-parse", "HEAD") != revision:
        raise ValueError("resource_probe_revision_changed")
    if command("git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("resource_probe_requires_clean_source")
    for name, image_id in images.items():
        metadata = inspect(image_id, image=True)
        if metadata.get("Id") != image_id:
            raise ValueError("resource_probe_image_identity_changed")
        if name in {"backend", "frontend"} and metadata.get("Config", {}).get("Labels", {}).get("org.opencontainers.image.revision") != revision:
            raise ValueError("resource_probe_image_revision_changed")
    if inspect(postgres, image=True).get("Id") != postgres:
        raise ValueError("resource_probe_database_image_changed")


def sender_probe(backend: str, postgres: str) -> dict:
    """One imported Celery parent/child plus a disposable 512 MiB database."""
    run_id = "pd-document-sender-" + uuid.uuid4().hex
    network, database, worker = (run_id + suffix for suffix in ("-net", "-db", "-worker"))
    try:
        guard()
        command("docker", "network", "create", "--internal", "--label", f"{LABEL}={run_id}", network)
        common = ["--label", f"{LABEL}={run_id}", "--network", network, "--cpus", "0.5",
                  "--pids-limit", "256", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true"]
        command("docker", "create", "--name", database, *common, "--memory", "512m", "--memory-swap", "512m",
            "--user", "postgres", "--tmpfs", "/tmp:rw,nosuid,nodev,size=268435456,mode=1777",
            "-e", "PGDATA=/tmp/pgdata", "-e", "POSTGRES_DB=document_sender_qualification",
            "-e", "POSTGRES_USER=synthetic_sender", "-e", "POSTGRES_PASSWORD=synthetic-sender-password", postgres)
        command("docker", "start", database)
        until = time.monotonic() + 60
        while True:
            guard()
            try:
                command("docker", "exec", database, "pg_isready", "-U", "synthetic_sender", "-d", "document_sender_qualification")
                break
            except RuntimeError:
                if time.monotonic() >= until:
                    raise RuntimeError("synthetic_database_did_not_start") from None
                time.sleep(.5)
        environment = {
            "APP_ENV": "development", "APP_SECRET_KEY": "synthetic-sender-qualification-secret-2026",
            "POSTGRES_HOST": database, "POSTGRES_DB": "document_sender_qualification",
            "POSTGRES_USER": "synthetic_sender", "POSTGRES_PASSWORD": "synthetic-sender-password",
            "POSTGRES_POOL_PROFILE": "worker", "DOCUMENT_RESOURCE_PROBE": "synthetic-isolated",
            "PYTHONDONTWRITEBYTECODE": "1", "OMP_THREAD_LIMIT": "1", "OPENBLAS_NUM_THREADS": "1",
            "S3_ACCESS_KEY_ID": "synthetic-sender", "S3_SECRET_ACCESS_KEY": "synthetic-sender-secret",
        }
        env_args = [arg for key, value in environment.items() for arg in ("-e", f"{key}={value}")]
        command("docker", "create", "--name", worker, *common, "--memory", "1024m", "--memory-swap", "1024m",
            "--entrypoint", "python", "--mount", f"type=bind,src={ROOT / 'scripts/qa'},dst=/qa,readonly",
            *env_args, backend, "/qa/probe_document_sender.py")
        command("docker", "start", worker)
        until = time.monotonic() + 720
        while inspect(worker)["State"]["Running"]:
            guard()
            if time.monotonic() > until:
                raise RuntimeError("synthetic_sender_probe_timed_out")
            time.sleep(.5)
        state = inspect(worker)["State"]
        raw = command("docker", "logs", worker)
        if state["ExitCode"] != 0 or state["OOMKilled"]:
            raise RuntimeError("synthetic_sender_probe_failed: " + raw[-2000:])
        values = []
        for line in raw.splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and value.get("passed") is True:
                values.append(value)
        if len(values) != 1:
            raise RuntimeError("one_complete_sender_result_required")
        result = values[0]
        if (result.get("rows") != 700 or result.get("mock_sends") != 698 or result.get("provider_calls") != 0
                or result.get("celery_parent_imported") is not True or result.get("worker_children") != 1
                or result.get("peak_upload_concurrency") != 4
                or result.get("outcomes") != {"submitted": 699, "delivery_unknown": 1}
                or len(result.get("slices", [])) != 28 or any(not 0 <= count <= 25 for count in result["slices"])):
            raise RuntimeError("sender_qualification_incomplete")
        return {**result, "backend_image": backend, "postgres_image": postgres,
                "cap_mib": 1024, "isolated_network": True}
    finally:
        # Discover by this invocation's random label even if Docker committed a
        # create operation immediately before its client call timed out.
        identifiers = command("docker", "ps", "-aq", "--filter", f"label={LABEL}={run_id}").split()
        for identifier in identifiers:
            row = inspect(identifier)
            if (row.get("Name", "").lstrip("/") not in {worker, database}
                    or row["Config"].get("Labels", {}).get(LABEL) != run_id
                    or set(row["NetworkSettings"]["Networks"]) != {network}):
                raise RuntimeError("sender_cleanup_ownership_changed")
            command("docker", "rm", "-f", "-v", row["Id"])
        for identifier in command("docker", "network", "ls", "-q", "--filter", f"label={LABEL}={run_id}").split():
            row = json.loads(command("docker", "network", "inspect", identifier))[0]
            if (row.get("Name") != network or row.get("Labels", {}).get(LABEL) != run_id
                    or not row.get("Internal") or row.get("Containers")):
                raise RuntimeError("sender_cleanup_network_changed")
            command("docker", "network", "rm", identifier)


def require_memory(memory: dict, cap_mib: int, *, peak_key: str = "peak_bytes") -> None:
    if not isinstance(memory, dict) or not isinstance(memory.get("events"), dict):
        raise ValueError("complete_memory_evidence_required")
    peak = memory.get(peak_key)
    ceiling = cap_mib if peak_key == "peak_mib" else cap_mib * 1024**2
    if type(peak) not in {int, float} or not 0 < peak <= ceiling:
        raise ValueError("memory_peak_outside_cap")
    if any(str(memory["events"].get(key)) != "0" for key in ("oom", "oom_kill", "max")):
        raise ValueError("memory_limit_event_during_qualification")


def build_receipt(revision: str, images: dict, evidence: dict) -> dict:
    sender, frontend, redis, lifecycle = (evidence[key] for key in ("sender", "frontend", "redis", "lifecycle"))
    if (sender.get("passed") is not True or type(sender.get("provider_calls")) is not int
            or sender.get("provider_calls") != 0 or frontend.get("result") != "passed"):
        raise ValueError("application_resource_proof_failed")
    if sender.get("backend_image") != images["backend"] or frontend.get("image") != images["frontend"]:
        raise ValueError("application_probe_image_changed")
    if (sender.get("cap_mib") != 1024 or frontend.get("cap_mib") != 256
            or frontend.get("memory", {}).get("running") is not True):
        raise ValueError("application_probe_cap_or_liveness_changed")
    require_memory(sender.get("memory"), 1024)
    require_memory(frontend.get("memory"), 256, peak_key="peak_mib")
    if len(redis) != 2 or {row.get("service") for row in redis} != set(DATASETS) or any(row.get("result") != "passed" for row in redis):
        raise ValueError("redis_pressure_proof_failed")
    broker = next(row for row in redis if row["service"] == "redis-broker")
    if broker.get("rewrite_observed") is not True or not broker.get("rewrite_overwrites"):
        raise ValueError("broker_rewrite_proof_required")
    if len(lifecycle) != 2 or {row.get("service") for row in lifecycle} != set(DATASETS) or any(row.get("passed") is not True for row in lifecycle):
        raise ValueError("redis_retained_lifecycle_proof_failed")
    for row in redis:
        name = row["service"]
        if row.get("image") != images[name] or row.get("cap_mib") != LIMITS[name][1] or row.get("maxmemory_mib") != DATASETS[name]:
            raise ValueError("redis_pressure_binding_changed")
        if row.get("memory", {}).get("running") is not True:
            raise ValueError("redis_pressure_process_not_running")
        require_memory(row.get("memory"), LIMITS[name][1], peak_key="peak_mib")
    for row in lifecycle:
        name = row["service"]
        if row.get("image_id") != images[name] or row.get("cap_mib") != LIMITS[name][1] or any(row.get(key) is not True for key in (
            "original_container_retained", "same_data_volume", "absolute_ttl_preserved", "orphaned_create_recovered", "one_active_writer")):
            raise ValueError("redis_preservation_evidence_incomplete")
        require_memory(row.get("memory"), LIMITS[name][1])
    return {"version": 1, "kind": "document_distribution_resources_v1", "qualified": True,
        "revision": revision, "image_ids": images, "profile_sha256": sha256(ROOT / PROFILE),
        "overlay_sha256": sha256(ROOT / OVERLAY), "source_sha256": qualified_source_hashes(ROOT),
        "limits_mib": {name: pair[1] for name, pair in LIMITS.items()}, "redis_maxmemory_mib": DATASETS,
        "host_reserve_mib": 2048, "provider_calls": 0, "checks": CHECKS,
        "evidence_sha256": {key: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                            for key, value in evidence.items()}}


def write_exclusive(path: Path, value: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def qualify(revision: str, images: dict[str, str], postgres: str, output: Path) -> dict:
    verify_inputs(revision, images, postgres)
    if not output.parent.is_dir() or output.exists() or output.is_symlink():
        raise ValueError("new_private_receipt_path_required")
    evidence_path = output.with_name(output.stem + "-evidence.json")
    if evidence_path.exists() or evidence_path.is_symlink():
        raise ValueError("resource_evidence_already_exists")
    before = qualified_source_hashes(ROOT)
    evidence = {"sender": sender_probe(images["backend"], postgres), "frontend": frontend_probe(images["frontend"]),
        "redis": [redis_probe(images["redis-broker"], durable=True, cap=896, maximum=384),
                  redis_probe(images["redis-cache"], durable=False, cap=192, maximum=128)],
        "lifecycle": qualify_redis_transition({name: images[name] for name in DATASETS})}
    verify_inputs(revision, images, postgres)
    if before != qualified_source_hashes(ROOT):
        raise ValueError("resource_probe_source_changed")
    receipt = build_receipt(revision, images, evidence)
    write_exclusive(evidence_path, evidence)
    write_exclusive(output, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    for name in ("backend", "frontend", "broker", "cache", "postgres"):
        parser.add_argument(f"--{name}-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    images = {"backend": args.backend_image, "frontend": args.frontend_image,
              "redis-broker": args.broker_image, "redis-cache": args.cache_image}
    qualify(args.revision, images, args.postgres_image, args.output.resolve())
    print(json.dumps({"qualified": True, "revision": args.revision, "receipt": str(args.output)}))


if __name__ == "__main__":
    main()
