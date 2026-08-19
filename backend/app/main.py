"""
FastAPI Application Factory
===========================
Constructs and configures the FastAPI application instance.

Uses the application factory pattern so:
  - The app can be instantiated multiple times for testing.
  - Middleware, routers, and event handlers are registered in one place.
  - Configuration is injected from settings, never hardcoded.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    import sentry_sdk
except ModuleNotFoundError:  # pragma: no cover - dev safety fallback
    sentry_sdk = None

from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import configure_logging, get_logger
from app.infrastructure.ai_priority.identity import gemini_runtime_identity
from app.infrastructure.mobile_realtime import (
    start_mobile_realtime,
    stop_mobile_realtime,
)
from app.infrastructure.observability.sentry import sentry_init_options
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.verification.dispatcher import (
    post_submission_verification_recovery_loop,
)
from app.presentation.api.v1.router import api_v1_router
from app.presentation.middleware.error_handler import register_exception_handlers
from app.presentation.middleware.metrics import MetricsMiddleware
from app.presentation.middleware.rate_limit import RateLimitMiddleware
from app.presentation.middleware.request_id import RequestIDMiddleware
from app.presentation.middleware.safe_gzip import SafeGZipMiddleware
from app.presentation.middleware.security_headers import SecurityHeadersMiddleware

logger = get_logger(__name__)

OPENAPI_TAGS = [
    {
        "name": "Authentication",
        "description": "JWT login, refresh, logout, and current-user endpoints.",
    },
    {"name": "Dashboard", "description": "Agency dashboard metrics and recent passport activity."},
    {"name": "Upload Links", "description": "Secure client group upload links."},
    {
        "name": "Passports",
        "description": "Passport upload, extraction, review, export, and confirmation workflows.",
    },
    {
        "name": "Tour Operations",
        "description": "Coordinator-led tour attendance planning and operations workflows.",
    },
    {"name": "Admin", "description": "Role-gated administrative overview endpoints."},
    {"name": "Analytics", "description": "Processing quality and operational analytics."},
    {"name": "Audit Logs", "description": "Security and operational audit trail."},
    {"name": "Notifications", "description": "Agency-facing workflow notifications."},
    {"name": "Health", "description": "Liveness and readiness checks."},
]


def create_application(
    settings: Settings | None = None,
    *,
    initialize_rate_limit_redis: bool = True,
) -> FastAPI:
    """
    Application factory.

    Args:
        settings: Optional Settings override (useful for testing).
        initialize_rate_limit_redis: Initialize the process-wide Redis client
            used by rate limiting. Tests may disable this to avoid leaking an
            external client across short-lived application instances.

    Returns:
        Configured FastAPI application instance.
    """
    if settings is None:
        settings = get_settings()

    configure_logging()

    if settings.sentry_dsn and settings.is_production:
        if sentry_sdk is None:
            logger.warning("sentry_sdk_missing", dsn_configured=True)
        else:
            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                traces_sample_rate=0.1,
                environment=settings.app_env,
                release=settings.app_version,
                **sentry_init_options(),
            )
            logger.info("sentry_initialized", dsn_configured=True)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Enterprise-grade Passport MRZ Processing Platform with secure upload links, "
            "passport MRZ extraction, client review, Excel export, analytics, "
            "audit logging, and agency notifications."
        ),
        contact={"name": "Global Connects Dashboard Engineering"},
        license_info={"name": "Proprietary"},
        openapi_tags=OPENAPI_TAGS,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[
            "Content-Disposition",
            "X-Passport-Export-History-ID",
        ],
    )
    app.add_middleware(SafeGZipMiddleware, minimum_size=1000)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        settings=settings,
        initialize_redis=initialize_rate_limit_redis,
    )
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestIDMiddleware)

    register_exception_handlers(app)
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)

    @app.on_event("startup")
    async def on_startup() -> None:
        await start_mobile_realtime(settings)
        try:
            await MinioStorageRepository().ensure_bucket_exists()
        except Exception:
            await stop_mobile_realtime()
            raise
        app.state.post_submission_verification_recovery_task = asyncio.create_task(
            post_submission_verification_recovery_loop()
        )
        logger.info(
            "application_started",
            version=settings.app_version,
            environment=settings.app_env,
            debug=settings.app_debug,
        )
        identity = gemini_runtime_identity(settings)
        logger.info(
            "gemini_runtime_configuration",
            **identity.to_safe_dict(),
        )
        if not identity.project_alias_configured:
            logger.warning(
                "gemini_project_alias_not_configured",
                config_version=identity.config_version,
            )

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        recovery_task = getattr(
            app.state,
            "post_submission_verification_recovery_task",
            None,
        )
        if recovery_task is not None:
            recovery_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await recovery_task
        await stop_mobile_realtime()
        logger.info("application_shutdown")

    return app


app = create_application()
