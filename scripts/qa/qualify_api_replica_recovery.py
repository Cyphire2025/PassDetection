"""Restart only the originating API in the fixed disposable qualification stack."""
from __future__ import annotations

import json
import subprocess
import time

from run_qualification_stack import COMPOSE, OUTPUT, ROOT

PEER = "passdetection-qualification-api-peer"
SCRIPT = "/workspace/scripts/qa/qualification_api_replica_journey.py"


def command(*args: str, data: dict | None = None) -> str:
    return subprocess.check_output(args, input=json.dumps(data) if data else None, text=True, cwd=ROOT).strip()


def wait_live(container: str) -> None:
    for attempt in range(60):
        probe = subprocess.run(["docker", "exec", container, "python", "-c",
            "import urllib.request;assert urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live',timeout=3).status==200"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if probe.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("Synthetic API did not become live")


def main() -> None:
    identifiers = command(*COMPOSE, "ps", "--quiet", "backend").splitlines()
    assert len(identifiers) == 1
    original = identifiers[0]
    state = json.loads(command("docker", "inspect", original))[0]
    labels = state["Config"]["Labels"]
    env = dict(item.split("=", 1) for item in state["Config"]["Env"] if "=" in item)
    assert labels["com.docker.compose.project"] == "passdetection-qualification"
    assert env["POSTGRES_DB"] == "passdetection_ci_browser" and env["APP_ENV"] == "production"
    assert not command("docker", "ps", "--all", "--quiet", "--filter", f"name=^/{PEER}$"), "A prior peer is still retained; inspect before retry"
    started = False
    try:
        command(*COMPOSE, "run", "-d", "--no-deps", "--name", PEER, "backend")
        started = True
        peer_state = json.loads(command("docker", "inspect", PEER))[0]
        assert peer_state["Image"] == state["Image"], "Both replicas must execute the identical candidate image"
        wait_live(PEER)
        proof = json.loads(command("docker", "exec", PEER, "python", SCRIPT, "first").splitlines()[-1])
        command(*COMPOSE, "stop", "backend")
        survivor = json.loads(command("docker", "exec", "-i", PEER, "python", SCRIPT, "survivor", data=proof).splitlines()[-1])
        command(*COMPOSE, "start", "backend")
        wait_live(original)
        restarted = json.loads(command("docker", "exec", "-i", PEER, "python", SCRIPT, "restarted", data=proof).splitlines()[-1])
        receipt = {"result": "passed", "image_id": state["Image"], "actual_api_instances": 2,
                   "accepted_submission_id": proof["submission_id"], **survivor, **restarted,
                   "limitation": "One local Docker host sharing PostgreSQL/Redis/private S3. Proves API process loss and shared authorization/data, not host failure or cross-region availability."}
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (ROOT / "docs/remediation/api-replica-evidence.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt, indent=2))
    finally:
        # Restore the same fixture API even if an assertion fails. No volumes or
        # business data are removed. Keep the stopped peer for failure inspection.
        command(*COMPOSE, "start", "backend")
        if started:
            command("docker", "stop", PEER)


if __name__ == "__main__":
    main()
