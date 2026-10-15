"""Qualify final-image SCRAM and verified TLS using only disposable Docker resources.

No host ports, production environment files, existing databases or persistent
volumes are used. Commands and readiness waits are bounded. Only resources with
this invocation's random ownership label can be removed. Driver errors remain
captured; the receipt never includes passwords, private keys or raw TLS errors.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from types import FrameType

POSTGRES_IMAGE = "postgres:16-alpine@sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb"
OWNER_LABEL = "io.passdetection.native-client-qualification"
PROBE_PATH = "/usr/local/share/passdetection/verify_postgresql_client.py"
ROOT = Path(__file__).resolve().parents[2]


class QualificationError(RuntimeError):
    """A safe diagnostic without captured command output or credentials."""


def create_tls_fixture(directory: Path, server: str) -> None:
    # Docker lifecycle helpers are also used by migration qualification, whose
    # host needs only stdlib; certificate dependencies belong to this TLS path.
    try:
        from .postgres_tls_fixture import create_tls_fixture as create
    except ImportError:
        from postgres_tls_fixture import create_tls_fixture as create
    create(directory, server)


def run(arguments: list[str], *, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise QualificationError("Qualification command could not finish within its resource boundary") from None
    if check and result.returncode:
        raise QualificationError("Qualification command failed; captured diagnostics were redacted")
    return result


def inspect_image(image: str, revision: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise QualificationError("An exact source revision is required")
    details = json.loads(run(["docker", "image", "inspect", image]).stdout)[0]
    image_id = details.get("Id", "")
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise QualificationError("Final image has no immutable identity")
    labels = details.get("Config", {}).get("Labels") or {}
    if labels.get("org.opencontainers.image.revision") != revision:
        raise QualificationError("Final image does not match the selected source revision")
    return image_id


def validate_success(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    if result.returncode:
        raise QualificationError("Verified PostgreSQL connection failed; driver diagnostics were redacted")
    try:
        receipt = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise QualificationError("Database probe returned invalid evidence") from None
    required = ("openssl_linked", "unneeded_auth_libraries_absent", "bundled_driver_libraries_absent",
                "scram_authentication", "database_round_trip", "tls_in_use", "tls_hostname_and_chain_verified")
    if not isinstance(receipt, dict) or receipt.get("status") != "passed" or any(receipt.get(key) is not True for key in required):
        raise QualificationError("Database probe did not prove every required runtime condition")
    expected = json.loads((ROOT / "backend/docker/postgresql_client_build.json").read_text())
    if receipt.get("libpq_version") != expected["libpq_version"] or receipt.get("source_sha256") != expected["source"]["sha256"]:
        raise QualificationError("Database probe does not match the reviewed PostgreSQL client source")
    if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("libpq_sha256", ""))):
        raise QualificationError("Database probe omitted the actual native library fingerprint")
    return {key: receipt[key] for key in (*required, "libpq_version", "source_sha256", "libpq_sha256")}


def require_wrong_ca_rejection(result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode == 0:
        raise QualificationError("Database client accepted an untrusted certificate authority")
    if "certificate verify failed" not in result.stderr.lower():
        raise QualificationError("Wrong-CA probe failed for an unverified reason; diagnostics were redacted")


def remove_owned(kind: str, name: str, owner: str) -> None:
    details = run(["docker", kind, "inspect", name], check=False)
    if details.returncode:
        if "no such" in details.stderr.lower():
            return
        raise QualificationError("Could not verify ownership during qualification cleanup")
    value = json.loads(details.stdout)[0]
    labels = value.get("Labels", {}) if kind == "network" else value.get("Config", {}).get("Labels", {})
    if (labels or {}).get(OWNER_LABEL) != owner:
        raise QualificationError("Refused to remove a Docker resource owned by another invocation")
    identifier = value.get("Id", "")
    if not re.fullmatch(r"[0-9a-f]{64}", identifier):
        raise QualificationError("Owned Docker resource has no immutable cleanup identity")
    run(["docker", kind, "rm", *([] if kind == "network" else ["--force"]), identifier])


def wait_ready(server: str, *, deadline_seconds: int = 90) -> None:
    deadline = time.monotonic() + deadline_seconds
    while True:
        result = run(["docker", "exec", server, "pg_isready", "-h", server, "-U", "qualification", "-d", "native_client"],
                     timeout=10, check=False)
        if result.returncode == 0:
            return
        if time.monotonic() >= deadline:
            raise QualificationError("Isolated PostgreSQL did not become ready before its deadline")
        time.sleep(1)


def create_server(name: str, network: str, owner: str, directory: Path) -> None:
    # Copy the temporary synthetic key into container-owned tmpfs so its owner
    # and mode satisfy PostgreSQL independently of the host's numeric UID.
    # Set permissions while root still owns it: CAP_CHOWN does not grant the
    # CAP_FOWNER required to chmod a file after transferring its ownership.
    entrypoint = (
        "cp /tls/server.crt /tls/server.key /run/pg-tls/; "
        "chmod 600 /run/pg-tls/server.key; chown postgres:postgres /run/pg-tls/*; "
        "exec docker-entrypoint.sh postgres -c ssl=on -c ssl_min_protocol_version=TLSv1.2 "
        "-c ssl_cert_file=/run/pg-tls/server.crt -c ssl_key_file=/run/pg-tls/server.key "
        "-c hba_file=/tls/pg_hba.conf -c password_encryption=scram-sha-256"
    )
    run(["docker", "create", "--name", name, "--hostname", name, "--network", network,
         "--label", f"{OWNER_LABEL}={owner}", "--memory", "512m", "--cpus", "1", "--pids-limit", "128",
         "--security-opt", "no-new-privileges:true", "--cap-drop", "ALL",
         "--cap-add", "CHOWN", "--cap-add", "SETUID", "--cap-add", "SETGID", "--cap-add", "DAC_OVERRIDE",
         "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,size=256m",
         "--tmpfs", "/run/pg-tls:rw,noexec,nosuid,size=1m",
         "--env-file", str(directory / "server.env"),
         "--mount", f"type=bind,source={directory / 'server'},target=/tls,readonly",
         "--entrypoint", "sh", POSTGRES_IMAGE, "-ec", entrypoint])
    run(["docker", "start", name])


def run_client(name: str, image: str, network: str, owner: str, directory: Path, *, trusted: bool) -> subprocess.CompletedProcess[str]:
    certificate_directory = directory / ("trusted" if trusted else "untrusted")
    run(["docker", "create", "--name", name, "--network", network, "--label", f"{OWNER_LABEL}={owner}",
         "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
         "--memory", "256m", "--cpus", "1", "--pids-limit", "32", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
         "--env-file", str(directory / "client.env"),
         "--mount", f"type=bind,source={certificate_directory},target=/tls,readonly",
         "--entrypoint", "python", image, PROBE_PATH, "--database", "--require-tls"])
    return run(["docker", "start", "--attach", name], timeout=60, check=False)


def qualify(image: str, revision: str) -> dict[str, object]:
    image_id = inspect_image(image, revision)
    run(["docker", "pull", POSTGRES_IMAGE], timeout=180)
    owner = uuid.uuid4().hex
    network = "pd-native-pg-" + owner
    server = network + "-db"
    clients = [network + "-trusted", network + "-untrusted"]
    with tempfile.TemporaryDirectory(prefix="pd-native-pg-") as temporary:
        directory = Path(temporary)
        create_tls_fixture(directory, server)
        password = secrets.token_urlsafe(32)
        for filename, values in (
            ("server.env", {"POSTGRES_USER": "qualification", "POSTGRES_PASSWORD": password,
                            "POSTGRES_DB": "native_client", "POSTGRES_INITDB_ARGS": "--auth-host=scram-sha-256"}),
            ("client.env", {"POSTGRES_HOST": server, "POSTGRES_PORT": "5432", "POSTGRES_DB": "native_client",
                            "POSTGRES_USER": "qualification", "POSTGRES_PASSWORD": password, "PGSSLROOTCERT": "/tls/ca.crt"}),
        ):
            path = directory / filename
            path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
            path.chmod(0o600)
        cleanup_errors = []
        try:
            run(["docker", "network", "create", "--internal", "--label", f"{OWNER_LABEL}={owner}", network])
            create_server(server, network, owner, directory)
            wait_ready(server)
            positive = validate_success(run_client(clients[0], image_id, network, owner, directory, trusted=True))
            require_wrong_ca_rejection(run_client(clients[1], image_id, network, owner, directory, trusted=False))
            validate_success(run(["docker", "start", "--attach", clients[0]], timeout=60, check=False))
        finally:
            # Names are registered before creation so a timed-out create can be
            # recovered, but exact ownership must be proven before any removal.
            for kind, name in [("container", name) for name in reversed([server, *clients])] + [("network", network)]:
                try:
                    remove_owned(kind, name, owner)
                except (QualificationError, ValueError, KeyError):
                    cleanup_errors.append(name)
            if cleanup_errors:
                raise QualificationError("Some owned qualification resources could not be cleaned up")
    return {"status": "passed", "image_id": image_id, "source_revision": revision,
            "postgres_image": POSTGRES_IMAGE, **positive, "untrusted_ca_rejected": True,
            "trusted_recheck_after_rejection": True,
            "internal_network": True, "host_ports_published": False, "owned_resources_removed": True,
            "limitation": "Two synthetic SCRAM and verified-TLS connections, not capacity or production-service evidence."}


def cancel_qualification(_signum: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="passdetection-backend:ci")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, cancel_qualification)
    try:
        receipt = qualify(args.image, args.revision)
    except QualificationError as error:
        receipt = {"status": "failed", "source_revision": args.revision, "error": str(error)}
    except (ValueError, KeyError, IndexError, OSError):
        receipt = {"status": "failed", "source_revision": args.revision,
                   "error": "Native PostgreSQL qualification failed; raw driver diagnostics are not retained."}
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    if receipt["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
