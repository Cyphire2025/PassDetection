"""Prove a detached synthetic copy process is stopped through Docker, without data."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from release_traveller_whatsapp import PROJECT_LABEL, SERVICE_LABEL, Release  # noqa: E402
from storage_writer_fence import StorageWriterFence  # noqa: E402


def main():
    token = uuid.uuid4().hex
    name = "passdetection-copy-process-qualification-" + token
    project = "passdetection-copy-process-qualification"
    evidence = ROOT / "outputs/storage-qualification/writer-fence" / token
    evidence.mkdir(parents=True)
    # Deliberately outlive the Docker client. It has no S3 clients or data I/O.
    sleeping_script = evidence / "copy_storage_snapshot.py"
    sleeping_script.write_text("import time\ntime.sleep(3600)\n")
    environment = {"S3_BUCKET_NAME": "synthetic-no-data", "STORAGE_SOURCE_ENDPOINT": "http://unused-source.invalid",
                   "STORAGE_DESTINATION_ENDPOINT": "http://unused-target.invalid"}
    command = ["docker", "run", "--detach", "--rm", "--name", name, "--network", "none"]
    for key, value in {
        PROJECT_LABEL: project, SERVICE_LABEL: "storage-copy",
        "com.docker.compose.project.working_dir": str(ROOT), "passdetection.storage-copy-token": token,
    }.items():
        command.extend(["--label", f"{key}={value}"])
    for key, value in environment.items():
        command.extend(["--env", f"{key}={value}"])
    command.extend([
        "--mount", f"type=bind,source={evidence},target=/evidence",
        "--mount", f"type=bind,source={sleeping_script},target=/app/scripts/copy_storage_snapshot.py,readonly",
        "passdetection-qualification-backend:local", "python", "scripts/copy_storage_snapshot.py",
    ])
    identifier = subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()
    release = Release("a" * 40, ROOT)
    try:
        container = release.inspect(identifier)
        assert container["State"]["Running"]
        mount = next(item for item in container["Mounts"] if item["Destination"] == "/evidence")
        # Docker Desktop rewrites Windows bind sources. This test consumes the
        # daemon's synthetic mount spelling; production uses native Linux paths.
        record = {"project": project, "copy": {
            "name": name, "token": token, "image": container["Image"],
            "evidence_directory": mount["Source"], "environment": environment,
        }}
        StorageWriterFence(release)._stop_copy(record)
        remaining = release.run("docker", "ps", "--all", "--quiet", "--filter", f"name=^/{name}$")
        assert not remaining, "Auto-removed copy remained after stop"
        report = {"synthetic": True, "detached_process_outlived_client": True,
                  "verified_exact_process_stopped": True, "auto_removed_after_stop": True,
                  "network": "none", "source_or_target_data_used": False}
        (evidence.parent.parent / "copy-process-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    finally:
        # The ID was created exclusively for this test; never discover or stop
        # unrelated containers, and never remove a volume or source object.
        subprocess.run(["docker", "stop", "--time", "2", identifier], capture_output=True, text=True, check=False)


if __name__ == "__main__":
    main()
