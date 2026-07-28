"""
API v1 Router
=============
Central registration point for versioned API modules.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.presentation.api.v1.routes.admin import router as admin_router
from app.presentation.api.v1.routes.admin_accounts import router as admin_accounts_router
from app.presentation.api.v1.routes.analytics import router as analytics_router
from app.presentation.api.v1.routes.audit_logs import router as audit_logs_router
from app.presentation.api.v1.routes.auth import router as auth_router
from app.presentation.api.v1.routes.client_groups import router as links_router
from app.presentation.api.v1.routes.dashboard import router as dashboard_router
from app.presentation.api.v1.routes.document_distribution import (
    router as document_distribution_router,
)
from app.presentation.api.v1.routes.document_rename import router as document_rename_router
from app.presentation.api.v1.routes.email_integrations import (
    router as email_integrations_router,
)
from app.presentation.api.v1.routes.health import router as health_router
from app.presentation.api.v1.routes.menu import router as menu_router
from app.presentation.api.v1.routes.notifications import router as notifications_router
from app.presentation.api.v1.routes.passport_image_library import (
    router as passport_image_library_router,
)
from app.presentation.api.v1.routes.passports import router as passport_router
from app.presentation.api.v1.routes.rooming import router as rooming_router
from app.presentation.api.v1.routes.search import router as search_router
from app.presentation.api.v1.routes.tour_operations import router as tour_operations_router
from app.presentation.api.v1.routes.whatsapp import router as whatsapp_router

api_v1_router = APIRouter()

api_v1_router.include_router(health_router, prefix="/health", tags=["Health"])
api_v1_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])
api_v1_router.include_router(links_router, prefix="/upload-links", tags=["Upload Links"])
api_v1_router.include_router(passport_router, prefix="/passports", tags=["Passports"])
api_v1_router.include_router(
    passport_image_library_router,
    prefix="/passports",
    tags=["Passports"],
)
api_v1_router.include_router(search_router, prefix="/search", tags=["Search"])
api_v1_router.include_router(tour_operations_router, prefix="/tour-operations", tags=["Tour Operations"])
api_v1_router.include_router(rooming_router, prefix="/rooming", tags=["Rooming Lists"])
api_v1_router.include_router(menu_router, prefix="/menu", tags=["Menu & Meal Planner"])
api_v1_router.include_router(document_distribution_router, prefix="/document-distribution", tags=["Document Distribution"])
api_v1_router.include_router(
    email_integrations_router,
    prefix="/email-integrations",
    tags=["Email Integrations"],
)
api_v1_router.include_router(document_rename_router, prefix="/document-rename", tags=["Document Rename"])
api_v1_router.include_router(admin_router, prefix="/admin", tags=["Admin"])
api_v1_router.include_router(admin_accounts_router, prefix="/admin/accounts", tags=["Account Administration"])
api_v1_router.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])
api_v1_router.include_router(audit_logs_router, prefix="/audit-logs", tags=["Audit Logs"])
api_v1_router.include_router(notifications_router, prefix="/notifications", tags=["Notifications"])
api_v1_router.include_router(whatsapp_router, prefix="/whatsapp", tags=["WhatsApp"])
