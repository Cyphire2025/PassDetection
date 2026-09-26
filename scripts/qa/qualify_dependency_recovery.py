"""Stop/start only the fixed disposable PostgreSQL container and preserve its data."""
from __future__ import annotations

import json
import subprocess
import time

from qualify_api_replica_recovery import SCRIPT, command
from run_qualification_stack import COMPOSE, ROOT


def inspect(identifier: str) -> dict:
    return json.loads(command("docker", "inspect", identifier))[0]


def main() -> None:
    database = command(*COMPOSE, "ps", "--quiet", "postgres")
    backend = command(*COMPOSE, "ps", "--quiet", "backend")
    assert database and backend and "\n" not in database and "\n" not in backend
    original = inspect(database)
    labels = original["Config"]["Labels"]
    environment = dict(value.split("=", 1) for value in original["Config"]["Env"] if "=" in value)
    assert labels["com.docker.compose.project"] == "passdetection-qualification"
    assert labels["com.docker.compose.service"] == "postgres"
    assert environment["POSTGRES_DB"] == "passdetection_ci_browser"
    assert original["State"]["Running"]
    api = inspect(backend)
    assert api["Config"]["Labels"]["com.docker.compose.project"] == "passdetection-qualification"
    proof = json.loads(command("docker", "exec", backend, "python", SCRIPT, "dependency-before").splitlines()[-1])
    stopped = False
    started = time.monotonic()
    try:
        command("docker", "stop", "--time", "30", database)
        stopped = True
        assert not inspect(database)["State"]["Running"]
        down = json.loads(command("docker", "exec", "-i", backend, "python", SCRIPT,
                                  "dependency-down", data=proof).splitlines()[-1])
        verified_down = time.monotonic()
        command("docker", "start", database)
        restart_requested = time.monotonic()
        for attempt in range(60):
            result = subprocess.run(["docker", "exec", database, "pg_isready", "-U", "qualification_admin",
                                     "-d", "passdetection_ci_browser"], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                break
            if attempt == 59:
                raise RuntimeError("The same synthetic PostgreSQL container did not recover")
            time.sleep(1)
        restored = json.loads(command("docker", "exec", "-i", backend, "python", SCRIPT,
                                      "dependency-restored", data=proof).splitlines()[-1])
        finished = time.monotonic()
        current = inspect(database)
        assert current["Id"] == original["Id"] and current["Mounts"] == original["Mounts"]
        receipt = {"result": "passed", "backend_image": api["Image"], "database_image": original["Image"],
                   "same_database_container_and_mounts": True, "accepted_submission_id": proof["submission_id"],
                   "down_verified_seconds_after_stop_request": round(verified_down-started, 3),
                   "restored_checks_seconds_after_start_request": round(finished-restart_requested, 3),
                   "controlled_unavailability_window_seconds": round(finished-started, 3), **down, **restored,
                   "limitation": "Functional single-host dependency interruption, including probe and container command overhead. It is not a host-failure recovery, failover, throughput or enterprise uptime claim. No database reset, volume replacement or object deletion occurred."}
        (ROOT / "docs/remediation/dependency-recovery-evidence.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt, indent=2))
    finally:
        if stopped and not inspect(database)["State"]["Running"]:
            command("docker", "start", database)


if __name__ == "__main__":
    main()
