"""Compose bounded dependency results without changing traffic or feature gates."""

from __future__ import annotations

import asyncio

from app.core.config.settings import Settings
from app.infrastructure.readiness_executor import readiness_probe_executor
from app.infrastructure.runtime_readiness_contracts import (
    BLOCKING_PROBE_TIMEOUT_SECONDS,
    _BlockingSnapshot,
)
from app.infrastructure.runtime_readiness_probes import (
    _my_photos_selected,
    _probe_ecr_worker,
    _probe_malware_scanner,
    _probe_my_photos,
    _probe_object_storage,
    _probe_security_redis,
    _probe_worker_and_scheduler,
)


async def _refresh_blocking_capabilities(settings: Settings) -> _BlockingSnapshot:
    (
        storage_result,
        scanner_result,
        runtime_result,
        provider_result,
        security_result,
        ecr_result,
    ) = await asyncio.gather(
        readiness_probe_executor.run(
            "object_storage",
            _probe_object_storage,
            timeout_seconds=BLOCKING_PROBE_TIMEOUT_SECONDS,
            configuration=settings,
        ),
        readiness_probe_executor.run(
            "malware_scanner",
            lambda: _probe_malware_scanner(settings),
            timeout_seconds=BLOCKING_PROBE_TIMEOUT_SECONDS,
            configuration=settings,
        ),
        readiness_probe_executor.run(
            "worker_scheduler",
            lambda: _probe_worker_and_scheduler(settings),
            timeout_seconds=BLOCKING_PROBE_TIMEOUT_SECONDS,
            configuration=settings,
        ),
        readiness_probe_executor.run(
            "my_photos",
            lambda: _probe_my_photos(settings),
            timeout_seconds=BLOCKING_PROBE_TIMEOUT_SECONDS,
            configuration=settings,
        ),
        readiness_probe_executor.run(
            "security_redis",
            lambda: _probe_security_redis(settings),
            timeout_seconds=BLOCKING_PROBE_TIMEOUT_SECONDS,
            configuration=settings,
        ),
        readiness_probe_executor.run(
            "ecr_worker",
            lambda: _probe_ecr_worker(settings),
            timeout_seconds=BLOCKING_PROBE_TIMEOUT_SECONDS,
            configuration=settings,
        ),
        return_exceptions=True,
    )

    storage_ready = storage_result is True
    security_status, security_ready = _probe_result(security_result, failure_status="unreachable")
    malware_status, malware_ready = _probe_result(
        scanner_result,
        failure_status="unreachable",
    )
    if not isinstance(runtime_result, tuple):
        worker_status, worker_ready = "probe_failed", False
        scheduler_status, scheduler_ready = "probe_failed", False
    else:
        worker_status, worker_ready, scheduler_status, scheduler_ready = runtime_result

    if not isinstance(provider_result, tuple):
        my_photos_status, my_photos_ready, my_photos_required = (
            "probe_failed",
            False,
            _my_photos_selected(settings),
        )
    else:
        my_photos_status, my_photos_ready, my_photos_required = provider_result

    return _BlockingSnapshot(
        checks={
            "security_redis": security_status,
            "object_storage": "available" if storage_ready else "unreachable",
            "malware_scanner": malware_status,
            "general_processing_worker": worker_status,
            "platform_scheduler": scheduler_status,
            "my_photos": my_photos_status,
            "ecr_worker": _probe_result(ecr_result, failure_status="probe_failed")[0],
        },
        object_storage_ready=storage_ready,
        security_ready=security_ready,
        malware_ready=malware_ready,
        general_worker_ready=worker_ready,
        scheduler_ready=scheduler_ready,
        my_photos_ready=my_photos_ready,
        my_photos_required=my_photos_required,
        ecr_worker=_probe_result(ecr_result, failure_status="probe_failed"),
    )


def _probe_result(
    result: object,
    *,
    failure_status: str,
) -> tuple[str, bool]:
    if isinstance(result, tuple) and len(result) == 2:
        status, ready = result
        if isinstance(status, str) and isinstance(ready, bool):
            return status, ready
    return failure_status, False


def _timed_out_snapshot(settings: Settings) -> _BlockingSnapshot:
    my_photos_required = _my_photos_selected(settings)
    return _BlockingSnapshot(
        checks={
            "security_redis": "probe_timeout",
            "object_storage": "probe_timeout",
            "malware_scanner": "probe_timeout",
            "general_processing_worker": "probe_timeout",
            "platform_scheduler": "probe_timeout",
            "my_photos": (
                "probe_timeout" if my_photos_required else "not_required_feature_disabled"
            ),
        },
        object_storage_ready=False,
        security_ready=False,
        malware_ready=False,
        general_worker_ready=False,
        scheduler_ready=False,
        my_photos_ready=not my_photos_required,
        my_photos_required=my_photos_required,
    )


def _capability(
    *,
    required: bool,
    available: bool,
    traffic_gate: bool,
    status: str,
) -> dict[str, object]:
    return {
        "required": required,
        "available": available,
        "traffic_gate": traffic_gate,
        "status": status,
    }
