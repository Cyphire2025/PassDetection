"""Qualify application persistence and inject worker faults in the fixed QA stack."""

from __future__ import annotations

import json
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

from run_qualification_stack import COMPOSE, OUTPUT, ROOT, run

EXEC = [*COMPOSE, "exec", "-T", "backend", "python"]


def last_json(output: str) -> dict:
    return json.loads(output.strip().splitlines()[-1])


def readiness(*, ecr_available: bool, timeout: int = 90) -> dict:
    deadline = time.monotonic() + timeout
    context = ssl._create_unverified_context()  # fixed localhost ephemeral certificate only
    while time.monotonic() < deadline:
        try:
            response = urllib.request.urlopen("https://localhost:58443/api/v1/health/ready", context=context, timeout=8)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            payload = json.load(response)
            capability = payload.get("capabilities", {}).get("ecr_checks", {})
            # Real AI credentials/capacity are intentionally absent. Verify that
            # all other traffic gates stay healthy across the optional fault,
            # without falsifying overall production readiness for that omission.
            unavailable = {name for name, value in payload.get("capabilities", {}).items()
                           if value.get("traffic_gate") and not value.get("available")}
            consumer_state_matches = ecr_available or capability.get("worker_available") is False
            if (response.status in {200, 503} and unavailable <= {"gemini_processing"}
                    and capability.get("available") is ecr_available and consumer_state_matches):
                assert capability["traffic_gate"] is False
                return payload
        time.sleep(2)
    raise AssertionError(f"Unrelated capabilities failed with ECR available={ecr_available}: {payload}")


def main() -> None:
    run([*EXEC, "/workspace/scripts/qa/qualification_application_journey.py"], "application-journey")
    before = readiness(ecr_available=True)
    try:
        run([*COMPOSE, "stop", "ecr-worker"], "ecr-worker-stop")
        seeded_ecr = subprocess.check_output([*EXEC, "/workspace/scripts/qa/qualification_worker_job.py", "ecr-seed"], cwd=ROOT, text=True)
        ecr_queued = last_json(seeded_ecr)
        degraded = readiness(ecr_available=False)
        run([*EXEC, "/workspace/scripts/qa/qualification_alert_probe.py", "firing"], "ecr-alerts-firing")
    finally:
        run([*COMPOSE, "start", "ecr-worker"], "ecr-worker-restart")
    with (OUTPUT / "ecr-worker-completion.log").open("w", encoding="utf-8") as output:
        subprocess.run([*EXEC, "/workspace/scripts/qa/qualification_worker_job.py", "ecr-verify"], cwd=ROOT,
                       input=json.dumps(ecr_queued), text=True, stdout=output, stderr=subprocess.STDOUT, check=True)
    recovered = readiness(ecr_available=True)
    run([*EXEC, "/workspace/scripts/qa/qualification_alert_probe.py", "resolved"], "ecr-alerts-resolved")
    try:
        run([*COMPOSE, "stop", "worker"], "general-worker-stop")
        seeded = subprocess.check_output([*EXEC, "/workspace/scripts/qa/qualification_worker_job.py", "seed"], cwd=ROOT, text=True)
        queued = last_json(seeded)
        (OUTPUT / "queued-worker-job.log").write_text(json.dumps(queued) + "\n", encoding="utf-8")
    finally:
        run([*COMPOSE, "start", "worker"], "general-worker-restart")
    with (OUTPUT / "worker-completion.log").open("w", encoding="utf-8") as output:
        subprocess.run([*EXEC, "/workspace/scripts/qa/qualification_worker_job.py", "verify"],
                       cwd=ROOT, input=json.dumps(queued), text=True, stdout=output, stderr=subprocess.STDOUT, check=True)
    readiness(ecr_available=True)
    result = {
        "finished_at": datetime.now(UTC).isoformat(), "synthetic": True,
        "application": last_json((OUTPUT / "application-journey.log").read_text(encoding="utf-8")),
        "ecr_fault": {"before": before["capabilities"]["ecr_checks"],
                      "during": degraded["capabilities"]["ecr_checks"],
                      "after": recovered["capabilities"]["ecr_checks"], "other_configured_capabilities_available": True},
        "worker": last_json((OUTPUT / "worker-completion.log").read_text(encoding="utf-8")),
        "ecr_durable_result": last_json((OUTPUT / "ecr-worker-completion.log").read_text(encoding="utf-8")),
        "alert_firing": last_json((OUTPUT / "ecr-alerts-firing.log").read_text(encoding="utf-8")),
        "alert_resolution": last_json((OUTPUT / "ecr-alerts-resolved.log").read_text(encoding="utf-8")),
        "production_fault_injected": False,
        "external_ai_readiness_available": before["capabilities"]["gemini_processing"]["available"],
    }
    (OUTPUT / "joined-journey-evidence.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("Real upload, private reads, durable worker recovery and optional ECR degradation passed")


if __name__ == "__main__":
    main()
