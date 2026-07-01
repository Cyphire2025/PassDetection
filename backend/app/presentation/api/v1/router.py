"""
API v1 Router
=============
Central registration point for versioned API modules.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.presentation.api.v1.routes.admin import router as admin_router
from app.presentation.api.v1.routes.analytics import router as analytics_router
from app.presentation.api.v1.routes.audit_logs import router as audit_logs_router
from app.presentation.api.v1.routes.auth import router as auth_router
from app.presentation.api.v1.routes.client_groups import router as links_router
from app.presentation.api.v1.routes.dashboard import router as dashboard_router
from app.presentation.api.v1.routes.health import router as health_router
from app.presentation.api.v1.routes.notifications import router as notifications_router
from app.presentation.api.v1.routes.passports import router as passport_router

api_v1_router = APIRouter()

api_v1_router.include_router(health_router, prefix="/health", tags=["Health"])
api_v1_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])
api_v1_router.include_router(links_router, prefix="/upload-links", tags=["Upload Links"])
api_v1_router.include_router(passport_router, prefix="/passports", tags=["Passports"])
api_v1_router.include_router(admin_router, prefix="/admin", tags=["Admin"])
api_v1_router.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])
api_v1_router.include_router(audit_logs_router, prefix="/audit-logs", tags=["Audit Logs"])
api_v1_router.include_router(notifications_router, prefix="/notifications", tags=["Notifications"])
