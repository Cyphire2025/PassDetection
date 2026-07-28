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
from app.infrastructure.observability.metrics import metrics
from app.presentation.dependencies.auth import require_role

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/live",
    summary="Liveness probe",
    description="Returns 200 if the process is alive. Does not check dependencies.",
    status_code=status.HTTP_200_OK,
)
async def liveness(settings: Settings = Depends(get_settings)) -> dict:
    """Liveness probe — always returns 200 if the process is running."""
    return {
        "status": "alive",
        "version": settings.app_version,
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
    overall_healthy = True

    # ── Database check ──────────────────────────────────────────
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error(
            "health_check_db_failed",
            error_type=type(exc).__name__,
        )
        checks["database"] = "unreachable"
        overall_healthy = False

    try:
        await asyncio.to_thread(get_ai_priority_coordinator().snapshot)
        checks["ai_priority_redis"] = "ok"
    except Exception as exc:
        logger.error(
            "health_check_ai_priority_redis_failed",
            error_type=type(exc).__name__,
        )
        checks["ai_priority_redis"] = "unreachable"
        overall_healthy = False

    gemini_checks, gemini_ready = gemini_configuration_readiness(settings)
    checks.update(gemini_checks)
    overall_healthy = overall_healthy and gemini_ready

    worker_checks, workers_ready = await asyncio.to_thread(
        gemini_worker_readiness,
        settings,
    )
    checks.update(worker_checks)
    overall_healthy = overall_healthy and workers_ready

    email_checks, email_ready = await asyncio.to_thread(
        email_runtime_readiness,
        settings,
    )
    checks.update(email_checks)
    overall_healthy = overall_healthy and email_ready

    http_status = status.HTTP_200_OK if overall_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ready" if overall_healthy else "degraded",
            "checks": checks,
            "version": settings.app_version,
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
    operational_metrics = await asyncio.to_thread(metrics.snapshot)

    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ok" if http_status == status.HTTP_200_OK else "degraded",
            "version": settings.app_version,
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
async def metrics_snapshot() -> dict:
    return await asyncio.to_thread(metrics.snapshot)
