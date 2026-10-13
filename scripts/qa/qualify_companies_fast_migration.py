"""Targeted candidate-image populated PostgreSQL migration rehearsal, never Full CI.

Creates a disposable internal network, tmpfs PostgreSQL 16 and bounded helpers.
No production environment, database, host port, daemon socket or app-source
overlay is passed to any helper. Only randomly owned resources are removed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import signal
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from qa.bounded_qualification_output import capture
from qa.companies_fast_migration_receipt import validate_inner
from qa.postgresql_client_fixture import (
    MOUNT,
    POSTGRES_IMAGE,
    extract_clients,
)
from qa.qualify_postgresql_client import (
    OWNER_LABEL,
    QualificationError,
    cancel_qualification,
    inspect_image,
    remove_owned,
    run,
)
from release_code_update import validate_capacity
from release_companies_traveller_contract import (
    SOURCE,
    TARGET,
    source_contract,
)
from release_mcp_database import digest_json
from release_traveller_whatsapp import ReleaseError

MIB = 1024 * 1024
REHEARSAL_FILES = (
    "rehearse_companies_traveller_upgrade.py", "companies_rehearsal_fixture.py",
    "companies_restore_comparison.py", "companies_client_data_fixture.py",
    "companies_traveller_release_schema.py", "companies_traveller_reuse_release.py",
    "rehearse_postgresql_upgrade.py", "release_companies_traveller_upgrade.py", "release_travel_tracker_upgrade.py",
)
INNER = r"""
import hashlib, json, sys
from pathlib import Path
from scripts.companies_traveller_reuse_release import POLICY, migration_entries
from scripts.rehearse_companies_traveller_upgrade import rehearse
root = Path('/app')
contract = {**POLICY, 'migrations': migration_entries(root)}
digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
if digest != sys.argv[1]:
    raise RuntimeError('Candidate migration contract mismatch')
for name, expected in json.loads(sys.argv[2]).items():
    source = root / 'scripts' / name
    if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Candidate rehearsal source mismatch')
value = rehearse(Path('/tmp/companies-rehearsal.json'))
print('PASSDETECTION_COMPANIES_REHEARSAL=' + json.dumps({'source_contract_sha256': digest, 'rehearsal': value}, sort_keys=True))
"""


def admit_memory(additional_mib: int = 1024) -> dict[str, int]:
    """Admit peak 2 x 512 MiB helpers against every live cap and a 2 GiB reserve."""
    if os.name != "posix":
        raise QualificationError("Migration qualification requires the local Linux Docker host")
    context = json.loads(run(["docker", "context", "inspect"]).stdout)[0]
    endpoint = os.environ.get("DOCKER_HOST") or context["Endpoints"]["docker"]["Host"]
    if endpoint not in {"unix:///var/run/docker.sock", "unix:///run/docker.sock"}:
        raise QualificationError("Only the local Linux Docker daemon may run the rehearsal")
    info = Path("/proc/meminfo").read_text()
    values = {key: int(value) * 1024 for key, value in re.findall(r"^(MemTotal|MemAvailable):\s+(\d+) kB$", info, re.MULTILINE)}
    ids = run(["docker", "ps", "--quiet", "--no-trunc"]).stdout.split()
    running = json.loads(run(["docker", "inspect", *ids]).stdout) if ids else []
    if values.get("MemAvailable", 0) < (additional_mib + 256) * MIB:
        raise QualificationError("Insufficient available memory for the bounded rehearsal")
    return cast(dict[str, int], validate_capacity(running, set(), additional_mib * MIB, values["MemTotal"]))


def create_database(name: str, network: str, owner: str, env_file: Path) -> str:
    # Full-model fixture teardown locks tables, indexes and dependencies in one
    # transaction. Size its lock table independently of the 24-connection cap.
    value: str = run(["docker", "create", "--name", name, "--network", network,
        "--log-driver", "json-file", "--log-opt", "max-size=1m", "--log-opt", "max-file=2",
        "--label", f"{OWNER_LABEL}={owner}", "--memory", "512m", "--memory-swap", "512m",
        "--cpus", "1", "--pids-limit", "128", "--security-opt", "no-new-privileges:true",
        "--cap-drop", "ALL", "--cap-add", "CHOWN", "--cap-add", "SETUID", "--cap-add", "SETGID",
        "--cap-add", "DAC_OVERRIDE", "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,size=384m",
        "--env-file", str(env_file), POSTGRES_IMAGE, "postgres", "-c", "shared_buffers=32MB",
        "-c", "work_mem=4MB", "-c", "maintenance_work_mem=32MB", "-c", "max_connections=24",
        "-c", "max_locks_per_transaction=256",
        "-c", "max_wal_size=128MB", "-c", "min_wal_size=32MB", "-c", "password_encryption=scram-sha-256"]).stdout.strip()
    if re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise QualificationError("Disposable database has no immutable container identity")
    run(["docker", "start", value])
    deadline = time.monotonic() + 90
    while run(["docker", "exec", value, "pg_isready", "-h", "127.0.0.1", "-U", "qualification", "-d", "native_migration"],
              timeout=10, check=False).returncode:
        if time.monotonic() >= deadline:
            raise QualificationError("Disposable PostgreSQL did not become ready before its deadline")
        time.sleep(1)
    return value


def run_rehearsal(name: str, image: str, server: str, owner: str, env_file: Path,
                  client_directory: Path, contract_hash: str, sources: dict[str, str],
                  diagnostic_path: Path | None = None) -> dict[str, Any]:
    run(["docker", "create", "--name", name, "--network", f"container:{server}",
         "--log-driver", "json-file", "--log-opt", "max-size=1m", "--log-opt", "max-file=2",
         "--label", f"{OWNER_LABEL}={owner}", "--read-only", "--cap-drop", "ALL",
         "--security-opt", "no-new-privileges:true", "--memory", "512m", "--memory-swap", "512m",
         "--cpus", "1", "--pids-limit", "96", "--user", "1001:1001",
         "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m,uid=1001,gid=1001,mode=700",
         "--env-file", str(env_file), "--workdir", "/app",
         "--mount", f"type=bind,source={client_directory},target={MOUNT},readonly",
         "--env", f"PATH={MOUNT}/bin:/opt/venv/bin:/usr/local/bin:/usr/bin:/bin",
         "--entrypoint", "python", image, "-c", INNER, contract_hash, json.dumps(sources, sort_keys=True)])
    output = capture(["docker", "start", "--attach", name], timeout=1800, diagnostic_path=diagnostic_path)
    return cast(dict[str, Any], validate_inner(output, contract_hash))


def write_environment(path: Path, values: dict[str, str]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        path.chmod(0o600)
        stream.write("".join(f"{key}={value}\n" for key, value in values.items()))


def qualify(image: str, revision: str, diagnostic_path: Path | None = None) -> dict[str, Any]:
    if re.fullmatch(r"sha256:[a-f0-9]{64}", image) is None or inspect_image(image, revision) != image:
        raise QualificationError("An exact candidate backend image ID is required")
    budget = admit_memory()
    contract_hash = digest_json(source_contract(ROOT))
    sources = {name: hashlib.sha256((ROOT / "backend/scripts" / name).read_bytes()).hexdigest() for name in REHEARSAL_FILES}
    run(["docker", "pull", POSTGRES_IMAGE], timeout=180)
    owner = uuid.uuid4().hex
    network = "pd-companies-rehearsal-" + owner
    names = {key: network + "-" + key for key in ("clients", "db", "migration", "test-deps", "contact")}
    with tempfile.TemporaryDirectory(prefix="pd-companies-rehearsal-") as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        credentials = {"POSTGRES_USER": "qualification", "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
                       "POSTGRES_DB": "native_migration", "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432"}
        server_env, client_env = directory / "server.env", directory / "client.env"
        write_environment(server_env, {**credentials, "POSTGRES_INITDB_ARGS": "--auth-host=scram-sha-256"})
        write_environment(client_env, {**credentials, "APP_ENV": "development", "APP_SECRET_KEY": secrets.token_urlsafe(48),
            "REDIS_HOST": "127.0.0.1", "REDIS_PASSWORD": "", "S3_ACCESS_KEY_ID": "synthetic-ci-access",
            "S3_SECRET_ACCESS_KEY": "synthetic-ci-secret", "PYTHONDONTWRITEBYTECODE": "1",
            "MIGRATION_REHEARSAL_ALLOW_EPHEMERAL_DATABASE_DELETION": "1"})
        cleanup_errors = []
        try:
            client_proof = extract_clients(names["clients"], owner, directory / "clients")
            run(["docker", "network", "create", "--internal", "--label", f"{OWNER_LABEL}={owner}", network])
            server_id = create_database(names["db"], network, owner, server_env)
            admit_memory(512)
            proof = run_rehearsal(names["migration"], image, server_id, owner, client_env,
                                  directory / "clients", contract_hash, sources, diagnostic_path)
            from qa.companies_contact_qualification import run_contact_tests
            admit_memory(512)
            contact = run_contact_tests(image=image, server_id=server_id, owner=owner, tempdir=directory,
                env_file=client_env, container_name=names["contact"], dependency_container_name=names["test-deps"],
                source_root=ROOT, source_commit=revision,
                diagnostic_path=diagnostic_path.with_name("fast-contact-check.private.log") if diagnostic_path else None)
            if contact.get("contact_concurrency_tests") != 2 or contact.get("contact_concurrency_verified") is not True:
                raise QualificationError("Both targeted contact concurrency tests must pass without skips")
        finally:
            for kind, name in [("container", name) for name in reversed(list(names.values()))] + [("network", network)]:
                try:
                    remove_owned(kind, name, owner)
                except (QualificationError, ValueError, KeyError):
                    cleanup_errors.append(name)
            if cleanup_errors:
                raise QualificationError("Owned rehearsal resources could not all be removed")
    proof["checks"]["contact_concurrency_verified"] = True
    return {"version": 1, "status": "passed", "source_revision": revision, "backend_image_id": image,
        "source_contract_sha256": contract_hash, "source_schema": SOURCE, "target_schema": TARGET,
        "full_ci_qualified": False, "owned_resources_removed": True, **proof,
        "contact_concurrency_tests": 2, "contact_evidence": contact,
        "rehearsal_source_sha256": digest_json(sources), "private_clients_sha256": digest_json(client_proof),
        "postgres_image": POSTGRES_IMAGE, "resource_admission": budget,
        "limitation": "700 synthetic roster people and two contact races; not Full CI, production data, or capacity qualification."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, cancel_qualification)
    parent = args.evidence_output.absolute().parent
    if parent.resolve(strict=True) != parent or not parent.is_dir() or (
            os.name == "posix" and parent.stat().st_mode & 0o077):
        raise QualificationError("Evidence requires an existing private regular directory")
    # Refuse existing evidence before any disposable resources are started.
    descriptor = os.open(args.evidence_output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        try:
            receipt = qualify(args.image, args.revision, args.evidence_output.with_suffix(".migration-private.log"))
        except QualificationError as error:
            receipt = {"version": 1, "status": "failed", "source_revision": args.revision,
                       "backend_image_id": args.image, "full_ci_qualified": False,
                       "reason": str(error)}
        except (ReleaseError, ValueError, KeyError, IndexError, TypeError, OSError):
            receipt = {"version": 1, "status": "failed", "source_revision": args.revision,
                       "backend_image_id": args.image, "full_ci_qualified": False,
                       "reason": "targeted_migration_qualification_failed_diagnostics_redacted"}
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(receipt, sort_keys=True))
    if receipt["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
