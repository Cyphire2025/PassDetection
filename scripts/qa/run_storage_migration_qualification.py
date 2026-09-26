"""Run storage snapshot regressions with two disposable maintained providers.

This CI lane checks the copy protocol, not legacy MinIO compatibility. The
separate retained MinIO-to-SeaweedFS evidence establishes that compatibility;
the archived MinIO registry no longer permits an unauthenticated fresh pull.
Only fixed synthetic credentials and this script's newly created containers
are used. No production environment file or existing Docker volume is read.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from storage_identity import storage_identity
from storage_release import STORAGE_IMAGE

PREFIX = "passdetection-storage-migration-ci"
OUTPUT = ROOT / "outputs" / "storage-migration-ci"
BACKEND_IMAGE = "passdetection-qualification-backend:local"
LABEL = "passdetection.qualification=storage-migration"


def run(*arguments: str, timeout: int = 120) -> str:
    result = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=True,
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"Qualification command failed: {arguments[:3]}\n{result.stderr[-4000:]}")
    return result.stdout.strip()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    run("docker", "image", "inspect", BACKEND_IMAGE)
    names = [f"{PREFIX}-{suffix}" for suffix in ("source", "target", "copy")]
    existing = set(run("docker", "ps", "-a", "--format", "{{.Names}}").splitlines())
    if existing.intersection(names):
        raise RuntimeError("An existing qualification container needs review; nothing was stopped")
    networks = set(run("docker", "network", "ls", "--format", "{{.Name}}").splitlines())
    if PREFIX in networks:
        raise RuntimeError("An existing qualification network needs review; nothing was removed")
    run("docker", "network", "create", "--internal", "--label", LABEL, PREFIX)
    created: list[str] = []
    try:
        for index, (alias, port, access, secret) in enumerate((
            ("storage-source", "9000", "synthetic-source", "synthetic-source-secret"),
            ("object-storage", "8333", "synthetic-admin", "synthetic-admin-secret"),
        )):
            identity = OUTPUT / f"{index}-identities.json"
            identity.write_text(storage_identity({
                "S3_BUCKET_NAME": "passdetection-ci-storage",
                "OBJECT_STORAGE_ADMIN_ACCESS_KEY": access,
                "OBJECT_STORAGE_ADMIN_SECRET_KEY": secret,
                "S3_ACCESS_KEY_ID": "synthetic-runtime",
                "S3_SECRET_ACCESS_KEY": "synthetic-runtime-secret",
            }), encoding="utf-8")
            identity.chmod(0o600)
            run("docker", "create", "--name", names[index], "--label", LABEL,
                "--network", PREFIX, "--network-alias", alias,
                "--mount", f"type=bind,source={identity},target=/run/secrets/s3.json,readonly",
                "--health-cmd", f"nc -z 127.0.0.1 {port}", "--health-interval", "2s",
                "--health-retries", "60", STORAGE_IMAGE,
                "server", "-dir=/data", "-ip=127.0.0.1", "-ip.bind=127.0.0.1",
                "-filer", "-filer.exposeDirectoryData=false", "-master.telemetry=false",
                "-volume.max=0", "-master.volumeSizeLimitMB=1024", "-s3",
                "-s3.ip.bind=0.0.0.0", f"-s3.port={port}",
                "-s3.config=/run/secrets/s3.json", "-s3.iam.config=/run/secrets/s3.json",
                "-s3.iam=false", "-s3.port.iceberg=0", "-s3.port.lance=0",
                "-s3.allowDeleteBucketNotEmpty=false", "-s3.autoCreateBucket=false", timeout=600)
            created.append(names[index])
            run("docker", "start", names[index])
        # Docker health checks supply the wait; this is an isolated QA process.
        import time
        for attempt in range(90):
            statuses = [run("docker", "inspect", "--format", "{{.State.Health.Status}}", name) for name in names[:2]]
            if statuses == ["healthy", "healthy"]:
                break
            if attempt == 89:
                raise RuntimeError(f"Synthetic storage failed readiness: {statuses}")
            time.sleep(2)
        run("docker", "create", "--name", names[2], "--label", LABEL,
            "--network", PREFIX, "--user", "0:0",
            "--env", "QUALIFICATION_SOURCE_PROVIDER=SeaweedFS 4.47",
            "--mount", f"type=bind,source={ROOT / 'backend' / 'scripts'},target=/migration,readonly",
            "--mount", f"type=bind,source={ROOT / 'scripts' / 'qa'},target=/qa,readonly",
            "--mount", f"type=bind,source={OUTPUT},target=/evidence",
            BACKEND_IMAGE, "python", "/qa/qualify_storage_migration.py")
        created.append(names[2])
        with (OUTPUT / "qualification.log").open("w", encoding="utf-8") as output:
            subprocess.run(["docker", "start", "--attach", names[2]], cwd=ROOT,
                           stdout=output, stderr=subprocess.STDOUT, timeout=1200, check=True)
        code = run("docker", "inspect", "--format", "{{.State.ExitCode}}", names[2])
        if code != "0":
            raise RuntimeError("Migration qualification failed; inspect outputs/storage-migration-ci/qualification.log")
        evidence = json.loads((OUTPUT / "migration-evidence.json").read_text())
        if evidence.get("qualification_complete") is not True:
            raise RuntimeError("Migration qualification returned incomplete evidence")
        print("PASS: maintained-provider copy regression, including 1,001 retained versions and failure cases")
    finally:
        for name in reversed(created):
            # Only containers newly created above are eligible for cleanup.
            run("docker", "logs", name)
            run("docker", "rm", "--force", "--volumes", name)
        run("docker", "network", "rm", PREFIX)


if __name__ == "__main__":
    main()
