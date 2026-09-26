"""Observe actual StatsD/Prometheus alert firing or recovery in the disposable stack."""

from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx
from qualification_application_journey import isolated

EXPECTED = {"PassDetectionEcrUnavailable", "PassDetectionEcrBacklog"}


async def main() -> None:
    isolated()
    firing = sys.argv[1] == "firing"
    if sys.argv[1] not in {"firing", "resolved"}:
        raise RuntimeError("Expected an explicit alert state")
    started = time.monotonic()
    deadline = started + (400 if firing else 90)
    async with httpx.AsyncClient(timeout=10, verify=False) as client:
        while time.monotonic() < deadline:
            # A real API probe emits the production metrics. No injected metric
            # samples or shortened alert thresholds are used in this lane.
            health = (await client.get("https://nginx/api/v1/health/ready")).json()
            capability = health["capabilities"]["ecr_checks"]
            assert capability["traffic_gate"] is False
            response = await client.get("http://prometheus:9090/api/v1/alerts")
            response.raise_for_status()
            alerts = response.json()["data"]["alerts"]
            active = {alert["labels"]["alertname"] for alert in alerts if alert["labels"]["alertname"] in EXPECTED}
            fired = {alert["labels"]["alertname"] for alert in alerts if alert["state"] == "firing"}
            if (firing and EXPECTED <= fired) or (not firing and not active):
                if firing:
                    assert capability["backlog"]["oldest_pending_seconds"] > 900
                    assert capability["backlog"]["pending_count"] >= 1
                else:
                    assert capability["available"] and capability["backlog"]["pending_count"] == 0
                print(json.dumps({"synthetic": True, "collector": "real Prometheus", "state": sys.argv[1],
                                  "alerts": sorted(EXPECTED), "elapsed_seconds": round(time.monotonic() - started, 2),
                                  "actual_production_thresholds": True, "human_notification_tested": False}))
                return
            await asyncio.sleep(5)
    raise AssertionError(f"Actual ECR alerts did not reach {sys.argv[1]} within the bounded deadline")


if __name__ == "__main__":
    asyncio.run(main())
