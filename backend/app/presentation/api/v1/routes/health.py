"""
Health Check Routes
===================
Essential in production — used by:
  - Docker health checks
  - Kubernetes liveness/readiness probes
  - Uptime monitoring (Datadog, Pingdom, etc.)
  - Load balancer health checks (Nginx upstream)

Endpoints:
  GET /api/v1/health/live   — Is the process alive?
  GET /api/v1/health/ready  — Can the process serve traffic? (checks DB + Redis)
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import UserRole
from app.infrastructure.ai_priority import get_ai_priority_coordinator
from app.infrastructure.ai_priority.identity import gemini_configuration_readiness
from app.infrastructure.ai_priority.worker_readiness import (
    gemini_worker_readiness,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.email.readiness import email_runtime_readiness
from app.infrastructure.mobile_realtime import get_mobile_realtime_hub
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.readiness_executor import readiness_probe_executor
from app.infrastructure.runtime_readiness import (
    RuntimeCapabilitySnapshot,
    runtime_capability_readiness,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()
logger = get_logger(__name__)
READINESS_PROBE_TIMEOUT_SECONDS = 3.75


async def _database_runtime_probe(
    db: AsyncSession, settings: Settings
) -> tuple[str, RuntimeCapabilitySnapshot]:
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("health_check_db_failed", error_type=type(exc).__name__)
        return "unreachable", _failed_runtime_snapshot(settings, "database_unreachable")
    return "ok", await runtime_capability_readiness(db=db, settings=settings)


def _failed_runtime_snapshot(settings: Settings, reason: str) -> RuntimeCapabilitySnapshot:
    security_required = any(
        (
            settings.dashboard_rate_limit_require_redis,
            settings.login_lockout_require_redis,
            settings.public_upload_rate_limit_require_redis,
        )
    )
    return RuntimeCapabilitySnapshot(
        checks={"runtime_capabilities": reason},
        core_ready=False,
        capabilities={
            "runtime": {
                "required": True,
                "available": False,
                "traffic_gate": True,
                "status": reason,
            },
            "request_protection": {
                "required": security_required,
                "available": False,
                "traffic_gate": security_required,
                "status": reason,
            },
        },
    )


def _probe_checks(result: object, keys: tuple[str, ...]) -> tuple[dict[str, str], bool]:
    if isinstance(result, tuple) and len(result) == 2:
        return result
    reason = "probe_timeout" if isinstance(result, TimeoutError) else "probe_failed"
    return {key: reason for key in keys}, False


@router.get(
    "/live",
    summary="Liveness probe",
    description="Returns 200 if the process is alive. Does not check dependencies.",
    status_code=status.HTTP_200_OK,
)
async def liveness(
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Liveness probe — always returns 200 if the process is running."""
    return {
        "status": "alive",
        "version": settings.app_version,
        "revision": settings.app_revision,
        "environment": settings.app_env,
    }


@router.get(
    "/ready",
    summary="Readiness probe",
    description=(
        "Returns 200 when the database, AI scheduler/configuration, and "
        "required Celery queue consumers are ready."
    ),
    status_code=status.HTTP_200_OK,
)
async def readiness(
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """
    Readiness probe — verifies connectivity to critical dependencies.
    Returns 503 if any dependency is unreachable.
    """
    checks: dict[str, str] = {}
    capabilities: dict[str, dict[str, object]] = {}
    overall_healthy = True

    # Independent dependency checks share one deadline window. Database work
    # stays sequential within its own task because AsyncSession cannot execute
    # simultaneous queries. Timed-out sync work remains single-flight in the
    # dedicated bounded executor instead of accumulating detached threads.
    priority_result, worker_result, email_result, runtime_result = await asyncio.gather(
        readiness_probe_executor.run(
            "ai_priority",
            lambda: get_ai_priority_coordinator().snapshot(),
            timeout_seconds=READINESS_PROBE_TIMEOUT_SECONDS,
            configuration=settings,
        ),
        readiness_probe_executor.run(
            "gemini_workers",
            lambda: gemini_worker_readiness(settings),
            timeout_seconds=READINESS_PROBE_TIMEOUT_SECONDS,
            configuration=settings,
        ),
        readiness_probe_executor.run(
            "email_runtime",
            lambda: email_runtime_readiness(settings),
            timeout_seconds=READINESS_PROBE_TIMEOUT_SECONDS,
            configuration=settings,
        ),
        asyncio.wait_for(
            _database_runtime_probe(db, settings), timeout=READINESS_PROBE_TIMEOUT_SECONDS
        ),
        return_exceptions=True,
    )
    if not isinstance(priority_result, BaseException):
        checks["ai_priority_redis"] = "ok"
    else:
        logger.error(
            "health_check_ai_priority_redis_failed",
            error_type=type(priority_result).__name__,
        )
        checks["ai_priority_redis"] = (
            "probe_timeout" if isinstance(priority_result, TimeoutError) else "unreachable"
        )
        overall_healthy = False

    realtime_status, realtime_ready = get_mobile_realtime_hub().readiness()
    checks["mobile_realtime"] = realtime_status
    overall_healthy = overall_healthy and realtime_ready
    # Production/staging settings validation has already cryptographically
    # checked the Ed25519 private/public key match before the app can start.
    checks["mobile_offline_authorization"] = "configured" if settings.mobile.enabled else "disabled"

    gemini_checks, gemini_ready = gemini_configuration_readiness(settings)
    checks.update(gemini_checks)
    overall_healthy = overall_healthy and gemini_ready

    worker_checks, workers_ready = _probe_checks(
        worker_result,
        ("celery_worker_control", "gemini_extraction_worker", "gemini_verification_worker"),
    )
    checks.update(worker_checks)
    overall_healthy = overall_healthy and workers_ready

    email_checks, email_ready = _probe_checks(
        email_result,
        (
            "email_provider_configuration",
            "email_worker",
            "email_ai_worker",
            "email_ai_configuration",
            "email_scheduler",
            "email_malware_scanner",
        ),
    )
    checks.update(email_checks)
    overall_healthy = overall_healthy and email_ready

    if isinstance(runtime_result, tuple):
        checks["database"], runtime_snapshot = runtime_result
    else:
        logger.error(
            "health_check_runtime_capabilities_failed",
            error_type=type(runtime_result).__name__,
        )
        reason = "probe_timeout" if isinstance(runtime_result, TimeoutError) else "probe_failed"
        checks["database"] = reason
        runtime_snapshot = _failed_runtime_snapshot(settings, reason)
    checks.update(runtime_snapshot.checks)
    capabilities.update(runtime_snapshot.capabilities)
    overall_healthy = overall_healthy and runtime_snapshot.core_ready

    capabilities.update(
        {
            "mobile_realtime": {
                "required": settings.mobile.enabled,
                "available": realtime_ready,
                "traffic_gate": settings.mobile.enabled,
                "status": realtime_status,
            },
            "gemini_processing": {
                "required": True,
                "available": gemini_ready and workers_ready,
                "traffic_gate": True,
                "status": ("available" if gemini_ready and workers_ready else "degraded"),
            },
            "email_integrations": {
                "required": settings.email_integrations_enabled,
                "available": email_ready,
                "traffic_gate": settings.email_integrations_enabled,
                "status": (
                    "available"
                    if email_ready and settings.email_integrations_enabled
                    else (
                        "not_required_feature_disabled"
                        if not settings.email_integrations_enabled
                        else "degraded"
                    )
                ),
            },
        }
    )

    http_status = status.HTTP_200_OK if overall_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ready" if overall_healthy else "degraded",
            "checks": checks,
            "capabilities": capabilities,
            "version": settings.app_version,
            "revision": settings.app_revision,
        },
    )


@router.get(
    "/diagnostics",
    summary="Runtime diagnostics",
    description=(
        "Returns dependency health, local process metrics, and shared AI "
        "scheduler/provider metrics."
    ),
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_role([UserRole.SUPER_ADMIN]))],
)
async def diagnostics(
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    checks: dict[str, str] = {}
    http_status = status.HTTP_200_OK
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error(
            "diagnostics_db_failed",
            error_type=type(exc).__name__,
        )
        checks["database"] = "unreachable"
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    realtime_status, realtime_ready = get_mobile_realtime_hub().readiness()
    checks["mobile_realtime"] = realtime_status
    if not realtime_ready:
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    operational_metrics = await asyncio.to_thread(metrics.snapshot)

    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ok" if http_status == status.HTTP_200_OK else "degraded",
            "version": settings.app_version,
            "revision": settings.app_revision,
            "environment": settings.app_env,
            "processing_backend": settings.processing_backend,
            "metrics": operational_metrics,
            "checks": checks,
        },
    )


@router.get(
    "/metrics",
    summary="Local and shared metrics snapshot",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_role([UserRole.SUPER_ADMIN]))],
)
async def metrics_snapshot() -> dict[str, object]:
    return await asyncio.to_thread(metrics.snapshot)
