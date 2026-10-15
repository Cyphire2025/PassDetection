"""Exact-image, synthetic document migration proof; never a production database."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from qa.qualify_document_delivery_rebalance import guard
from qa.qualify_document_release_resources import command, inspect, write_exclusive
from release_document_distribution_contract import SOURCE, TARGET, source_contract
from release_mcp_database import digest_json

LABEL = "passdetection.document-migration-qa"
FILES = (
    "document_distribution_release.py", "document_distribution_release_schema.py",
    "release_document_distribution_upgrade.py", "qualify_document_distribution_release.py",
    "qualify_document_distribution_upgrade.py", "mcp_dashboard_write_schema.py",
    "release_travel_tracker_upgrade.py",
)
CHECKS = {"source_upgrade": True, "intermediate_resume": True, "idempotent_target": True,
    "lock_failure": True, "historical_rows_catalog_acl_preserved": True,
    "wrong_baseline_rejected": True, "new_columns_null": True, "runtime_grants_verified": True}
MARKER = "PASSDETECTION_DOCUMENT_MIGRATION="
DATABASE_TMPFS = {"/var/lib/postgresql/data": "rw,size=268435456"}
CLIENT_TMPFS = {"/tmp": "rw,nosuid,size=134217728,mode=1777"}
INNER = """
import hashlib,json,sys
from pathlib import Path
from scripts.document_distribution_release import POLICY,migration_entries
from scripts.qualify_document_distribution_upgrade import qualify
root=Path('/app')
contract={**POLICY,'migrations':migration_entries(root)}
digest=hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(',',':')).encode()).hexdigest()
if digest != sys.argv[1]:
    raise RuntimeError('candidate_contract_mismatch')
for name,expected in json.loads(sys.argv[2]).items():
    path=root/'scripts'/name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise RuntimeError('candidate_helper_source_mismatch')
value=qualify(release_helper=True)
print('PASSDETECTION_DOCUMENT_MIGRATION='+json.dumps({'source_contract_sha256':digest,'result':value}),flush=True)
"""


def verify_inputs(image: str, revision: str, postgres: str) -> None:
    if not __debug__ or os.name != "posix":
        raise ValueError("unoptimized_linux_qualification_required")
    if not re.fullmatch(r"[a-f0-9]{40}", revision) or any(
        not re.fullmatch(r"sha256:[a-f0-9]{64}", value) for value in (image, postgres)):
        raise ValueError("exact_revision_and_image_ids_required")
    context = json.loads(command("docker", "context", "inspect"))[0]
    endpoint = os.environ.get("DOCKER_HOST") or context["Endpoints"]["docker"]["Host"]
    if endpoint not in {"unix:///var/run/docker.sock", "unix:///run/docker.sock"}:
        raise ValueError("local_docker_host_required")
    if command("git", "-C", str(ROOT), "rev-parse", "HEAD") != revision or command(
        "git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("clean_exact_source_required")
    metadata = inspect(image, image=True)
    if metadata.get("Id") != image or metadata.get("Config", {}).get("Labels", {}).get("org.opencontainers.image.revision") != revision:
        raise ValueError("candidate_image_revision_changed")
    verify_image_volumes(metadata, database=False)
    database_image = inspect(postgres, image=True)
    if database_image.get("Id") != postgres:
        raise ValueError("postgres_image_changed")
    verify_image_volumes(database_image, database=True)


def verify_image_volumes(metadata: dict, *, database: bool) -> None:
    # An image VOLUME would create an anonymous Docker volume unless this
    # invocation overrides that exact destination. Only PG16's reviewed data
    # destination is covered by our disposable tmpfs; the backend has none.
    volumes = metadata.get("Config", {}).get("Volumes")
    allowed = set(DATABASE_TMPFS) if database else set()
    if volumes is not None and (not isinstance(volumes, dict) or not set(volumes) <= allowed):
        raise ValueError("unreviewed_probe_image_volume")


def verify_cleanup_mounts(row: dict, *, database: bool) -> None:
    expected = DATABASE_TMPFS if database else CLIENT_TMPFS
    host = row["HostConfig"]
    mounts = row.get("Mounts", [])
    # A create timeout can leave a stopped container with no materialized
    # Mounts entries. Its exact tmpfs create intent must still be present.
    if (host.get("Tmpfs") != expected or host.get("Binds") or host.get("Mounts") or host.get("VolumesFrom")
        or len(mounts) > len(expected)
        or any(mount.get("Type") != "tmpfs" or mount.get("Destination") not in expected
            or mount.get("RW") is not True or mount.get("Name") or mount.get("Source") for mount in mounts)):
        raise RuntimeError("migration_cleanup_mounts_changed")


def validate_result(raw: str, contract_hash: str) -> dict:
    if len(raw) > 262144:
        raise ValueError("migration_output_budget_exceeded")
    rows = [json.loads(line[len(MARKER):]) for line in raw.splitlines() if line.startswith(MARKER)]
    if len(rows) != 1 or rows[0].get("source_contract_sha256") != contract_hash:
        raise ValueError("one_bound_migration_result_required")
    result = rows[0].get("result", {})
    required = ("upgrade_and_retry_passed", "lock_timeout_atomic_rollback_passed", "orm_read_write_rollback_passed",
        "downgrade_reupgrade_passed", "preexisting_rows_and_fields_retained", "synthetic_only")
    helper = result.get("release_helper", {})
    checks = ("original_baseline_retained", "source_and_intermediate_resume_passed", "target_idempotency_passed",
        "invalid_baseline_and_lock_timeout_fail_closed", "changed_rows_catalog_and_early_new_values_rejected")
    if (result.get("source") != SOURCE or result.get("target") != TARGET
        or any(result.get(key) is not True for key in required)
        or any(helper.get(key) is not True for key in checks)
        or helper.get("automatic_downgrade") is not False
        or type(result.get("messages_sent")) is not int or result["messages_sent"] != 0
        or type(helper.get("messages_sent")) is not int or helper["messages_sent"] != 0):
        raise ValueError("incomplete_document_migration_proof")
    return result


def probe(image: str, postgres: str, contract_hash: str, sources: dict[str, str]) -> dict:
    owner = "pd-document-migration-" + uuid.uuid4().hex
    database, client = owner + "-db", owner + "-client"
    server_id = None
    try:
        guard()
        common = ["--label", f"{LABEL}={owner}", "--memory", "512m", "--memory-swap", "512m",
            "--cpus", "0.5", "--pids-limit", "96", "--log-driver", "json-file",
            "--log-opt", "max-size=1m", "--log-opt", "max-file=2"]
        server_id = command("docker", "create", "--name", database, *common, "--network", "none",
            "--tmpfs", next(key + ":" + value for key, value in DATABASE_TMPFS.items()), "-e", "POSTGRES_USER=synthetic",
            "-e", "POSTGRES_PASSWORD=synthetic-disposable-only", "-e", "POSTGRES_DB=passdetection_ci_document_release",
            postgres, "-c", "shared_buffers=32MB", "-c", "max_connections=20")
        command("docker", "start", database)
        until = time.monotonic() + 60
        while True:
            guard()
            try:
                command("docker", "exec", database, "pg_isready", "-U", "synthetic", "-d", "passdetection_ci_document_release")
                break
            except RuntimeError:
                if time.monotonic() > until:
                    raise RuntimeError("synthetic_postgres_readiness_timeout") from None
                time.sleep(.5)
        env = {"POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432", "POSTGRES_USER": "synthetic",
            "POSTGRES_PASSWORD": "synthetic-disposable-only", "POSTGRES_DB": "passdetection_ci_document_release",
            "APP_ENV": "development", "APP_SECRET_KEY": "synthetic-document-release-secret-2026",
            "S3_ACCESS_KEY_ID": "synthetic", "S3_SECRET_ACCESS_KEY": "synthetic",
            "PYTHONDONTWRITEBYTECODE": "1"}
        command("docker", "create", "--name", client, *common, "--network", "container:" + server_id,
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--tmpfs", next(key + ":" + value for key, value in CLIENT_TMPFS.items()), "--workdir", "/app",
            *[arg for key, value in env.items() for arg in ("-e", f"{key}={value}")],
            "--entrypoint", "python", image, "-c", INNER, contract_hash, json.dumps(sources, sort_keys=True))
        command("docker", "start", client)
        until = time.monotonic() + 900
        while inspect(client)["State"]["Running"]:
            guard()
            if time.monotonic() > until:
                raise RuntimeError("document_migration_qualification_timeout")
            time.sleep(.5)
        state = inspect(client)["State"]
        if state["ExitCode"] != 0 or state["OOMKilled"] or inspect(database)["State"]["OOMKilled"]:
            raise RuntimeError("document_migration_image_probe_failed")
        return validate_result(command("docker", "logs", client), contract_hash)
    finally:
        for identifier in command("docker", "ps", "-aq", "--filter", f"label={LABEL}={owner}").split():
            row = inspect(identifier)
            name = row.get("Name", "").lstrip("/")
            expected_network = "none" if name == database else "container:" + str(server_id)
            if (name not in {database, client} or row["Config"].get("Labels", {}).get(LABEL) != owner
                or row["HostConfig"].get("NetworkMode") != expected_network):
                raise RuntimeError("migration_cleanup_ownership_changed")
            verify_cleanup_mounts(row, database=name == database)
            command("docker", "rm", "-f", "-v", row["Id"])


def qualify(image: str, revision: str, postgres: str, output: Path) -> dict:
    verify_inputs(image, revision, postgres)
    if (not output.parent.is_dir() or output.parent.resolve() != output.parent.absolute()
        or output.exists() or output.is_symlink() or (os.name == "posix" and output.parent.stat().st_mode & 0o077)):
        raise ValueError("new_private_receipt_path_required")
    contract_hash = digest_json(source_contract(ROOT))
    sources = {name: hashlib.sha256((ROOT / "backend/scripts" / name).read_bytes()).hexdigest() for name in FILES}
    probe(image, postgres, contract_hash, sources)
    verify_inputs(image, revision, postgres)
    if digest_json(source_contract(ROOT)) != contract_hash or sources != {
        name: hashlib.sha256((ROOT / "backend/scripts" / name).read_bytes()).hexdigest() for name in FILES}:
        raise ValueError("qualification_source_changed")
    receipt = {"version": 1, "status": "passed", "source_revision": revision, "backend_image_id": image,
        "source_contract_sha256": contract_hash, "source_schema": SOURCE, "target_schema": TARGET,
        "full_ci_qualified": False, "owned_resources_removed": True, "checks": CHECKS}
    write_exclusive(output, receipt)
    return receipt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--postgres-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.image, args.revision, args.postgres_image, args.output), sort_keys=True))
