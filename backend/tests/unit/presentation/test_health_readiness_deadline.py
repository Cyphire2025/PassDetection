from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.config.settings import Settings
from app.infrastructure.readiness_executor import ReadinessProbeExecutor
from app.infrastructure.runtime_readiness import RuntimeCapabilitySnapshot
from app.presentation.api.v1.routes import health


async def test_slow_probes_share_one_deadline_and_keep_other_capability_results(
    monkeypatch,
) -> None:
    executor = ReadinessProbeExecutor()
    release = threading.Event()
    calls = []
    probe_deadline_seconds = 0.04
    # This batch includes 21 responses and their error logging under coverage.
    # Keep its ceiling below the blocked probes' five-second guard; exact
    # production request latency is verified separately in the Docker rehearsal.
    batch_ceiling_seconds = 2.0

    def stalled(name):
        calls.append(name)
        assert release.wait(5)
        return {}, True

    monkeypatch.setattr(health, "readiness_probe_executor", executor)
    monkeypatch.setattr(health, "READINESS_PROBE_TIMEOUT_SECONDS", probe_deadline_seconds)
    monkeypatch.setattr(
        health,
        "get_ai_priority_coordinator",
        lambda: SimpleNamespace(snapshot=lambda: stalled("priority")),
    )
    monkeypatch.setattr(health, "gemini_worker_readiness", lambda _: stalled("workers"))
    monkeypatch.setattr(health, "email_runtime_readiness", lambda _: stalled("email"))
    monkeypatch.setattr(
        health,
        "get_mobile_realtime_hub",
        lambda: SimpleNamespace(readiness=lambda: ("disabled", True)),
    )
    monkeypatch.setattr(health, "gemini_configuration_readiness", lambda _: ({}, True))
    monkeypatch.setattr(
        health,
        "runtime_capability_readiness",
        AsyncMock(
            return_value=RuntimeCapabilitySnapshot(
                checks={"security_redis": "unreachable"},
                core_ready=False,
                capabilities={
                    "request_protection": {"available": False},
                    "object_storage": {"available": True},
                },
            )
        ),
    )
    settings = Settings(app_secret_key="synthetic-readiness-deadline", _env_file=None)
    try:
        started = time.monotonic()
        responses = await asyncio.gather(
            *[
                health.readiness(db=SimpleNamespace(execute=AsyncMock()), settings=settings)
                for _ in range(20)
            ]
        )
        response = await health.readiness(
            db=SimpleNamespace(execute=AsyncMock()), settings=settings
        )
        assert time.monotonic() - started < batch_ceiling_seconds
        assert sorted(calls) == ["email", "priority", "workers"]
        assert all(response.status_code == 503 for response in responses)
        body = json.loads(response.body)
        assert body["checks"]["ai_priority_redis"] == "probe_timeout"
        assert body["checks"]["gemini_extraction_worker"] == "probe_timeout"
        assert body["checks"]["email_worker"] == "probe_timeout"
        assert body["capabilities"]["request_protection"]["available"] is False
        assert body["capabilities"]["object_storage"]["available"] is True
    finally:
        release.set()
        executor.close()


async def test_slow_database_is_cancelled_before_request_session_is_released(monkeypatch) -> None:
    cancelled = asyncio.Event()

    async def delayed_database(_):
        try:
            await asyncio.sleep(2)
        finally:
            cancelled.set()

    monkeypatch.setattr(health, "READINESS_PROBE_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(
        health, "get_ai_priority_coordinator", lambda: SimpleNamespace(snapshot=lambda: None)
    )
    monkeypatch.setattr(health, "gemini_worker_readiness", lambda _: ({}, True))
    monkeypatch.setattr(health, "email_runtime_readiness", lambda _: ({}, True))
    settings = Settings(app_secret_key="synthetic-readiness-deadline", _env_file=None)
    response = await health.readiness(
        db=SimpleNamespace(execute=delayed_database), settings=settings
    )
    assert response.status_code == 503
    assert cancelled.is_set()
    assert json.loads(response.body)["checks"]["database"] == "probe_timeout"
