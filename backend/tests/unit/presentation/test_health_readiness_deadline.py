from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.config.settings import Settings
from app.infrastructure import runtime_readiness
from app.infrastructure.readiness_executor import ReadinessProbeExecutor
from app.infrastructure.runtime_readiness import RuntimeCapabilitySnapshot
from app.presentation.api.v1.routes import health


async def test_cold_readiness_admits_every_dependency_before_caching_capabilities(
    monkeypatch,
) -> None:
    executor = ReadinessProbeExecutor()
    release = threading.Event()
    calls: list[str] = []
    run = executor.run

    async def observed_run(name, operation, **kwargs):
        if name == "ecr_worker":
            # Keep earlier dependency I/O in flight until the final admission
            # attempt. This reproduces a cold probe without timing assumptions.
            asyncio.get_running_loop().call_soon(release.set)
        return await run(name, operation, **kwargs)

    def dependency(name, result):
        calls.append(name)
        assert release.wait(5)
        return result

    monkeypatch.setattr(executor, "run", observed_run)
    monkeypatch.setattr(health, "readiness_probe_executor", executor)
    monkeypatch.setattr(runtime_readiness, "readiness_probe_executor", executor)
    monkeypatch.setattr(runtime_readiness, "_runtime_probe", runtime_readiness.RuntimeReadinessProbe())
    monkeypatch.setattr(
        health,
        "get_ai_priority_coordinator",
        lambda: SimpleNamespace(snapshot=lambda: dependency("priority", None)),
    )
    monkeypatch.setattr(
        health, "gemini_worker_readiness", lambda _: dependency("gemini", ({}, True))
    )
    monkeypatch.setattr(
        health, "email_runtime_readiness", lambda _: dependency("email", ({}, True))
    )
    monkeypatch.setattr(
        health,
        "get_mobile_realtime_hub",
        lambda: SimpleNamespace(readiness=lambda: ("disabled", True)),
    )
    monkeypatch.setattr(health, "gemini_configuration_readiness", lambda _: ({}, True))
    monkeypatch.setattr(
        runtime_readiness, "_probe_object_storage", lambda: dependency("storage", True)
    )
    monkeypatch.setattr(
        runtime_readiness,
        "_probe_malware_scanner",
        lambda _: dependency("scanner", ("available", True)),
    )
    monkeypatch.setattr(
        runtime_readiness,
        "_probe_worker_and_scheduler",
        lambda _: dependency("worker", ("available", True, "heartbeat_recent", True)),
    )
    monkeypatch.setattr(
        runtime_readiness,
        "_probe_my_photos",
        lambda _: dependency("photos", ("available", True, True)),
    )
    monkeypatch.setattr(
        runtime_readiness,
        "_probe_security_redis",
        lambda _: dependency("security", ("available", True)),
    )
    monkeypatch.setattr(
        runtime_readiness,
        "_probe_ecr_worker",
        lambda _: dependency("ecr", ("available", True)),
    )
    monkeypatch.setattr(
        runtime_readiness, "_schema_readiness", AsyncMock(return_value=("compatible", True))
    )
    monkeypatch.setattr(
        runtime_readiness,
        "_cleanup_backlog",
        AsyncMock(return_value=runtime_readiness._CleanupBacklog(0, 0, 0)),
    )
    monkeypatch.setattr(
        runtime_readiness,
        "ecr_backlog",
        AsyncMock(return_value={
            "pending_count": 0,
            "failed_count": 0,
            "retry_count": 0,
            "oldest_pending_seconds": 0,
        }),
    )
    settings = Settings(app_secret_key="synthetic-readiness-cold-start", _env_file=None)
    try:
        for _ in range(2):
            response = await health.readiness(
                db=SimpleNamespace(execute=AsyncMock()), settings=settings
            )
            body = json.loads(response.body)
            assert response.status_code == 200
            assert body["capabilities"]["ecr_checks"]["required"] is True
            assert body["capabilities"]["ecr_checks"]["available"] is True
            assert body["capabilities"]["ecr_checks"]["worker_available"] is True
            assert all(item["available"] for item in body["capabilities"].values())
        assert sorted(calls) == sorted([
            "priority", "gemini", "email", "priority", "gemini", "email",
            "storage", "scanner", "worker", "photos", "security", "ecr",
        ])
    finally:
        release.set()
        executor.close()


async def test_slow_probes_share_one_deadline_and_keep_other_capability_results(
    monkeypatch,
) -> None:
    executor = ReadinessProbeExecutor()
    release = threading.Event()
    calls = []
    admissions = []
    admissions_at_completion = []
    run = executor.run
    probe_deadline_seconds = 0.04
    # This batch includes 21 responses and their error logging under coverage.
    # Keep its ceiling below the blocked probes' five-second guard; exact
    # production request latency is verified separately in the Docker rehearsal.
    batch_ceiling_seconds = 2.0

    def stalled(name):
        calls.append(name)
        assert release.wait(5)
        return {}, True

    async def observed_run(name, operation, **kwargs):
        admissions.append((name, kwargs["timeout_seconds"], kwargs["configuration"]))
        try:
            return await run(name, operation, **kwargs)
        finally:
            admissions_at_completion.append({item[0] for item in admissions})

    monkeypatch.setattr(executor, "run", observed_run)
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
    mobile_property = Settings.mobile
    mobile_reads = []

    def observed_mobile(instance):
        mobile_reads.append(instance)
        return mobile_property.__get__(instance, Settings)

    monkeypatch.setattr(Settings, "mobile", property(observed_mobile))
    # Fixture construction is not part of dependency scheduling or response
    # latency. All real readiness work and error logging remain inside the timer.
    databases = [SimpleNamespace(execute=AsyncMock()) for _ in range(21)]
    try:
        started = time.monotonic()
        responses = await asyncio.gather(
            *[health.readiness(db=db, settings=settings) for db in databases[:20]]
        )
        response = await health.readiness(db=databases[20], settings=settings)
        assert time.monotonic() - started < batch_ceiling_seconds
        expected_probes = {"ai_priority", "gemini_workers", "email_runtime"}
        # This fails if probes become sequential, without relying on tiny
        # differences between one 40ms timeout and three sequential timeouts.
        assert admissions_at_completion[0] == expected_probes
        assert len(admissions) == 63
        assert all(
            timeout == probe_deadline_seconds and configuration is settings
            for _, timeout, configuration in admissions
        )
        assert all(sum(name == probe for name, _, _ in admissions) == 21 for probe in expected_probes)
        assert len(mobile_reads) == 21
        assert all(instance is settings for instance in mobile_reads)
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
