"""Verify request-protection readiness only in the isolated dashboard Docker stack."""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.audit.yml"
ORIGIN = "http://127.0.0.1:58000"


def probe(path: str) -> dict[str, object]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(f"{ORIGIN}{path}", timeout=6) as response:
            return {"status": response.status, "body": json.load(response),
                    "elapsed_seconds": round(time.monotonic() - started, 3)}
    except urllib.error.HTTPError as error:
        return {"status": error.code, "body": json.load(error),
                "elapsed_seconds": round(time.monotonic() - started, 3)}


def wait_for(status: int) -> dict[str, object]:
    deadline = time.monotonic() + 45
    while True:
        result = probe("/api/v1/health/ready")
        protection = result.get("body", {}).get("capabilities", {}).get("request_protection", {})
        if result["status"] == status and protection.get("available") is (status == 200):
            return result
        if time.monotonic() >= deadline:
            raise AssertionError(f"Expected readiness HTTP {status}: {result}")
        time.sleep(2)


def compose(action: str) -> None:
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), action, "redis"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )


def main() -> None:
    if "name: passdetection-audit" not in COMPOSE.read_text(encoding="utf-8"):
        raise RuntimeError("This rehearsal only supports the isolated audit project")
    report = {"baseline": wait_for(200)}
    print("Baseline readiness is healthy", flush=True)
    try:
        compose("stop")
        report["security_redis_unavailable"] = wait_for(503)
        assert report["security_redis_unavailable"]["elapsed_seconds"] < 5
        report["liveness_during_outage"] = probe("/api/v1/health/live")
        assert report["liveness_during_outage"]["status"] == 200
        print("Security Redis outage removes readiness while liveness stays healthy", flush=True)
    finally:
        compose("start")
    report["recovered"] = wait_for(200)
    destination = ROOT / "outputs/dashboard-qa/readiness-rehearsal.json"
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Readiness recovers after Redis returns", flush=True)


if __name__ == "__main__":
    main()
