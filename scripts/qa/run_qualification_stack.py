"""Build-independent orchestration for the disposable production-image QA lane.

All commands are restricted to the fixed qualification Compose project and its
synthetic database. This script never reads .env or targets the production stack.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage_identity import storage_identity

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs" / "qualification"
COMPOSE = ["docker", "compose", "--env-file", str(ROOT / ".env.example"), "-p", "passdetection-qualification", "-f", str(ROOT / "docker-compose.qualification.yml")]
ADMIN = ["-e", "APP_ENV=development", "-e", "POSTGRES_USER=qualification_admin", "-e", "POSTGRES_PASSWORD=qualification-admin-937"]


def run(arguments: list[str], name: str) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / f"{name}.log").open("w", encoding="utf-8") as output:
        result = subprocess.run(arguments, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f"Qualification {name} failed; see outputs/qualification/{name}.log")


def start() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    identity = OUTPUT / "storage-identities.json"
    identity.write_text(storage_identity({
        "S3_BUCKET_NAME": "passdetection-passports",
        "OBJECT_STORAGE_ADMIN_ACCESS_KEY": "qualification-storage-admin",
        "OBJECT_STORAGE_ADMIN_SECRET_KEY": "qualification-storage-admin-secret-937",
        "S3_ACCESS_KEY_ID": "qualification-storage",
        "S3_SECRET_ACCESS_KEY": "qualification-storage-secret-937",
    }), encoding="utf-8")
    identity.chmod(0o600)
    run([*COMPOSE, "config", "--quiet"], "compose-validation")
    run([*COMPOSE, "up", "-d", "--wait", "--wait-timeout", "600", "postgres", "redis", "object-storage", "clamav", "statsd", "prometheus"], "dependencies")
    isolated = [*COMPOSE, "run", "--rm", "--no-deps", *ADMIN, "backend"]
    run([*isolated, "python", "/workspace/scripts/qa/qualification_storage_bootstrap.py"], "storage-bootstrap")
    run([*isolated, "alembic", "upgrade", "head"], "migrations")
    run([*COMPOSE, "run", "--rm", "--no-deps", *ADMIN,
         "-e", "POSTGRES_RUNTIME_USER=qualification_runtime", "-e", "POSTGRES_RUNTIME_PASSWORD=qualification-runtime-937",
         "-e", "POSTGRES_MIGRATION_USER=qualification_migrator", "-e", "POSTGRES_MIGRATION_PASSWORD=qualification-migrator-937",
         "backend", "python", "scripts/provision_database_roles.py"], "roles")
    run([*isolated, "python", "/workspace/scripts/qa/seed_enterprise_browser_stack.py"], "seed")
    run([*COMPOSE, "up", "-d", "backend", "worker", "ecr-worker", "scheduler", "frontend", "nginx"], "application")
    # Only the generated, ephemeral localhost TLS certificate is self-signed.
    context = ssl._create_unverified_context()
    for attempt in range(60):
        try:
            with urllib.request.urlopen("https://localhost:58443/api/v1/health/live", context=context, timeout=2) as response:
                payload = json.load(response)
                if payload.get("environment") == "production":
                    break
        except (OSError, ValueError):
            pass
        if attempt == 59:
            raise RuntimeError("Production-image API failed to start within 120 seconds")
        time.sleep(2)
    evidence()


def evidence() -> None:
    run([*COMPOSE, "ps", "--format", "json"], "services")
    run(["docker", "image", "inspect", "passdetection-qualification-backend:local", "passdetection-qualification-frontend:local"], "images")
    run([*COMPOSE, "logs", "--no-color", "--tail", "250"], "service-logs")
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
         "backend", "frontend", "scripts", "monitoring", ".github", "docker-compose.qualification.yml"],
        cwd=ROOT,
    ).decode().split("\0")
    hashes = {}
    for relative in sorted(set(filter(None, paths))):
        path = ROOT / relative
        if path.is_file():
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            hashes[relative] = "deleted"
    encoded = json.dumps(hashes, sort_keys=True).encode()
    source = {
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "scope": "working tree source at evidence capture; image IDs retained separately",
        "source_sha256": hashlib.sha256(encoded).hexdigest(), "files": hashes,
    }
    (OUTPUT / "source-evidence.json").write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "evidence", "stop"])
    action = parser.parse_args().action
    if action == "start":
        start()
    elif action == "evidence":
        evidence()
    else:
        # The file and project name are constants; neither production Compose
        # files nor external named volumes are accepted as inputs.
        run([*COMPOSE, "down", "--volumes", "--remove-orphans"], "teardown")


if __name__ == "__main__":
    main()
