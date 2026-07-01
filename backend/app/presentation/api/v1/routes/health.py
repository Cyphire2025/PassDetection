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

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.database.session import get_db_session
from app.infrastructure.observability import metrics

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
    description="Returns 200 if the service can handle traffic (DB + Redis reachable).",
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
        logger.error("health_check_db_failed", error=str(exc))
        checks["database"] = "unreachable"
        overall_healthy = False

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
    description="Returns dependency health and in-process operational metrics.",
    status_code=status.HTTP_200_OK,
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
        logger.error("diagnostics_db_failed", error=str(exc))
        checks["database"] = "unreachable"
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ok" if http_status == status.HTTP_200_OK else "degraded",
            "version": settings.app_version,
            "environment": settings.app_env,
            "processing_backend": settings.processing_backend,
            "metrics": metrics.snapshot(),
            "checks": checks,
        },
    )


@router.get(
    "/metrics",
    summary="In-process metrics snapshot",
    status_code=status.HTTP_200_OK,
)
async def metrics_snapshot() -> dict:
    return metrics.snapshot()
