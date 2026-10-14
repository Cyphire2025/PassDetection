"""
API v1 Router
=============
Central registration point for versioned API modules.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.presentation.api.v1.routes.admin import router as admin_router
from app.presentation.api.v1.routes.admin_accounts import router as admin_accounts_router
from app.presentation.api.v1.routes.admin_whatsapp_templates import (
    router as admin_whatsapp_templates_router,
)
from app.presentation.api.v1.routes.analytics import router as analytics_router
from app.presentation.api.v1.routes.attendance_runtime import router as attendance_runtime_router
from app.presentation.api.v1.routes.audit_logs import router as audit_logs_router
from app.presentation.api.v1.routes.auth import router as auth_router
from app.presentation.api.v1.routes.client_groups import router as links_router
from app.presentation.api.v1.routes.companies import router as companies_router
from app.presentation.api.v1.routes.company_data_exports import (
    router as company_data_exports_router,
)
from app.presentation.api.v1.routes.company_document_uploads import (
    router as company_document_uploads_router,
)
from app.presentation.api.v1.routes.company_match_review import (
    router as company_match_review_router,
)
from app.presentation.api.v1.routes.company_passports import router as company_passports_router
from app.presentation.api.v1.routes.company_people import router as company_people_router
from app.presentation.api.v1.routes.company_reassignments import (
    router as company_reassignments_router,
)
from app.presentation.api.v1.routes.company_reuse_setup import router as company_reuse_setup_router
from app.presentation.api.v1.routes.company_review_tasks import (
    router as company_review_tasks_router,
)
from app.presentation.api.v1.routes.company_submissions import router as company_submissions_router
from app.presentation.api.v1.routes.company_traveller_history import (
    router as company_traveller_history_router,
)
from app.presentation.api.v1.routes.dashboard import router as dashboard_router
from app.presentation.api.v1.routes.dashboard_realtime import (
    router as dashboard_realtime_router,
)
from app.presentation.api.v1.routes.document_distribution import (
    router as document_distribution_router,
)
from app.presentation.api.v1.routes.document_rename import router as document_rename_router
from app.presentation.api.v1.routes.ecr_checker import router as ecr_checker_router
from app.presentation.api.v1.routes.email_ai_inbox import (
    router as email_ai_inbox_router,
)
from app.presentation.api.v1.routes.email_ai_rollout_admin import (
    router as email_ai_rollout_admin_router,
)
from app.presentation.api.v1.routes.email_integrations import (
    router as email_integrations_router,
)
from app.presentation.api.v1.routes.frontend_errors import router as frontend_errors_router
from app.presentation.api.v1.routes.gc_app import router as gc_app_router
from app.presentation.api.v1.routes.gc_app_content import router as gc_app_content_router
from app.presentation.api.v1.routes.gc_app_group_removal import (
    router as gc_app_group_removal_router,
)
from app.presentation.api.v1.routes.gc_notifications import router as gc_notifications_router
from app.presentation.api.v1.routes.health import router as health_router
from app.presentation.api.v1.routes.mcp_admin import router as mcp_admin_router
from app.presentation.api.v1.routes.mcp_read_access import router as mcp_read_access_router
from app.presentation.api.v1.routes.menu import router as menu_router
from app.presentation.api.v1.routes.mobile_associations import (
    router as mobile_associations_router,
)
from app.presentation.api.v1.routes.mobile_auth import router as mobile_auth_router
from app.presentation.api.v1.routes.mobile_integrity import router as mobile_integrity_router
from app.presentation.api.v1.routes.mobile_journey import router as mobile_journey_router
from app.presentation.api.v1.routes.mobile_my_photos import router as mobile_my_photos_router
from app.presentation.api.v1.routes.mobile_ops import router as mobile_ops_router
from app.presentation.api.v1.routes.mobile_realtime import router as mobile_realtime_router
from app.presentation.api.v1.routes.mobile_resources import router as mobile_resources_router
from app.presentation.api.v1.routes.notifications import router as notifications_router
from app.presentation.api.v1.routes.passport_image_library import (
    router as passport_image_library_router,
)
from app.presentation.api.v1.routes.passports import router as passport_router
from app.presentation.api.v1.routes.returning_claims import router as returning_claims_router
from app.presentation.api.v1.routes.returning_completion import (
    router as returning_completion_router,
)
from app.presentation.api.v1.routes.returning_contact import router as returning_contact_router
from app.presentation.api.v1.routes.returning_draft import router as returning_draft_router
from app.presentation.api.v1.routes.draft_lifecycle import router as draft_lifecycle_router
from app.presentation.api.v1.routes.fresh_draft import router as fresh_draft_router
from app.presentation.api.v1.routes.fresh_draft_contact import router as fresh_draft_contact_router
from app.presentation.api.v1.routes.fresh_draft_completion import router as fresh_draft_completion_router
from app.presentation.api.v1.routes.returning_detection import router as returning_detection_router
from app.presentation.api.v1.routes.returning_history import router as returning_history_router
from app.presentation.api.v1.routes.returning_replacement import (
    router as returning_replacement_router,
)
from app.presentation.api.v1.routes.returning_selection import router as returning_selection_router
from app.presentation.api.v1.routes.rooming import router as rooming_router
from app.presentation.api.v1.routes.search import router as search_router
from app.presentation.api.v1.routes.tour_operations import router as tour_operations_router
from app.presentation.api.v1.routes.tour_operations_qr_delivery import (
    router as tour_operations_qr_delivery_router,
)
from app.presentation.api.v1.routes.travel_tracker import router as travel_tracker_router
from app.presentation.api.v1.routes.traveller_admin import router as traveller_admin_router
from app.presentation.api.v1.routes.whatsapp import router as whatsapp_router
from app.presentation.api.v1.routes.whatsapp_activity import (
    router as whatsapp_activity_router,
)

api_v1_router = APIRouter()
api_v1_router.include_router(returning_claims_router, prefix="/returning", tags=["Returning Travellers"])
api_v1_router.include_router(returning_history_router, prefix="/returning", tags=["Returning Travellers"])
api_v1_router.include_router(returning_contact_router, prefix="/returning", tags=["Returning Travellers"])
api_v1_router.include_router(returning_draft_router, prefix="/returning", tags=["Returning Travellers"])
api_v1_router.include_router(draft_lifecycle_router, tags=["Traveller Drafts"])
api_v1_router.include_router(fresh_draft_router, prefix="/public-drafts", tags=["Traveller Drafts"])
api_v1_router.include_router(fresh_draft_contact_router, prefix="/public-drafts", tags=["Traveller Drafts"])
api_v1_router.include_router(fresh_draft_completion_router, prefix="/public-drafts", tags=["Traveller Drafts"])
api_v1_router.include_router(returning_detection_router, prefix="/returning", tags=["Returning Travellers"])
api_v1_router.include_router(returning_completion_router, prefix="/returning", tags=["Returning Travellers"])
api_v1_router.include_router(returning_replacement_router, prefix="/returning", tags=["Returning Travellers"])
api_v1_router.include_router(returning_selection_router, prefix="/returning", tags=["Returning Travellers"])
api_v1_router.include_router(company_review_tasks_router, prefix="/companies", tags=["Company Review Tasks"])
api_v1_router.include_router(company_passports_router, prefix="/companies", tags=["Company Documents"])
api_v1_router.include_router(company_match_review_router, prefix="/companies", tags=["Company Match Review"])
api_v1_router.include_router(company_traveller_history_router, prefix="/companies", tags=["Companies"])
api_v1_router.include_router(company_submissions_router, prefix="/companies", tags=["Companies / Clients"])
api_v1_router.include_router(company_people_router, prefix="/companies", tags=["Companies / Clients"])
api_v1_router.include_router(company_data_exports_router, prefix="/companies", tags=["Companies / Clients"])
api_v1_router.include_router(company_document_uploads_router, prefix="/companies", tags=["Company Documents"])
api_v1_router.include_router(traveller_admin_router, prefix="/companies", tags=["Company Travellers"])
api_v1_router.include_router(companies_router, prefix="/companies", tags=["Companies / Clients"])
api_v1_router.include_router(company_reuse_setup_router, prefix="/companies", tags=["Companies / Clients"])
api_v1_router.include_router(company_reassignments_router, prefix="/companies", tags=["Companies / Clients"])
api_v1_router.include_router(travel_tracker_router, prefix="/travel-tracker", tags=["Travel Tracker"])
api_v1_router.include_router(mcp_read_access_router, prefix="/mcp", tags=["MCP Read Access"])
api_v1_router.include_router(mcp_admin_router, prefix="/admin/mcp", tags=["MCP Administration"])
api_v1_router.include_router(frontend_errors_router, prefix="/observability", tags=["Observability"])
api_v1_router.include_router(ecr_checker_router, prefix="/ecr-checker", tags=["ECR Checker"])
api_v1_router.include_router(admin_whatsapp_templates_router, prefix="/admin", tags=["Admin"])

api_v1_router.include_router(health_router, prefix="/health", tags=["Health"])
api_v1_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(
    mobile_auth_router,
    prefix="/mobile/auth",
    tags=["GC Mobile Authentication"],
)
api_v1_router.include_router(
    mobile_associations_router,
    prefix="/mobile",
    tags=["GC Mobile Association"],
)
api_v1_router.include_router(
    mobile_resources_router,
    prefix="/mobile",
    tags=["GC Mobile Resources"],
)
api_v1_router.include_router(
    mobile_journey_router,
    prefix="/mobile",
    tags=["GC Mobile Journey"],
)
api_v1_router.include_router(
    mobile_integrity_router,
    prefix="/mobile",
    tags=["GC Mobile Integrity"],
)
api_v1_router.include_router(
    mobile_my_photos_router,
    prefix="/mobile",
    tags=["GC Mobile My Photos"],
)
api_v1_router.include_router(
    mobile_realtime_router,
    prefix="/mobile",
    tags=["GC Mobile Realtime"],
)
api_v1_router.include_router(
    mobile_ops_router,
    prefix="/mobile",
    tags=["GC Mobile Operations"],
)
api_v1_router.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])
api_v1_router.include_router(
    dashboard_realtime_router,
    prefix="/dashboard",
    tags=["Dashboard Realtime"],
)
api_v1_router.include_router(links_router, prefix="/upload-links", tags=["Upload Links"])
api_v1_router.include_router(passport_router, prefix="/passports", tags=["Passports"])
api_v1_router.include_router(
    passport_image_library_router,
    prefix="/passports",
    tags=["Passports"],
)
api_v1_router.include_router(search_router, prefix="/search", tags=["Search"])
api_v1_router.include_router(
    tour_operations_router, prefix="/tour-operations", tags=["Tour Operations"]
)
api_v1_router.include_router(
    attendance_runtime_router,
    prefix="/tour-operations",
    tags=["Tour Operations"],
)
api_v1_router.include_router(
    tour_operations_qr_delivery_router,
    prefix="/tour-operations",
    tags=["Tour Operations"],
)
api_v1_router.include_router(rooming_router, prefix="/rooming", tags=["Rooming Lists"])
api_v1_router.include_router(menu_router, prefix="/menu", tags=["Menu & Meal Planner"])
api_v1_router.include_router(
    document_distribution_router, prefix="/document-distribution", tags=["Document Distribution"]
)
api_v1_router.include_router(
    email_integrations_router,
    prefix="/email-integrations",
    tags=["Email Integrations"],
)
api_v1_router.include_router(
    email_ai_inbox_router,
    prefix="/email-integrations",
    tags=["AI Travel Operations Inbox"],
)
api_v1_router.include_router(
    email_ai_rollout_admin_router,
    prefix="/admin/email-ai-rollout",
    tags=["AI Travel Operations Rollout"],
)
api_v1_router.include_router(
    document_rename_router, prefix="/document-rename", tags=["Document Rename"]
)
api_v1_router.include_router(admin_router, prefix="/admin", tags=["Admin"])
api_v1_router.include_router(
    admin_accounts_router, prefix="/admin/accounts", tags=["Account Administration"]
)
api_v1_router.include_router(
    gc_app_router,
    prefix="/gc-app/admin",
    tags=["GC App Administration"],
)
api_v1_router.include_router(
    gc_app_group_removal_router, prefix="/gc-app/admin", tags=["GC App Administration"]
)
api_v1_router.include_router(
    gc_app_content_router,
    prefix="/gc-app/admin",
    tags=["GC App Content Publishing"],
)
api_v1_router.include_router(
    gc_notifications_router, prefix="/gc-app/admin", tags=["GC App Notifications"]
)
api_v1_router.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])
api_v1_router.include_router(audit_logs_router, prefix="/audit-logs", tags=["Audit Logs"])
api_v1_router.include_router(notifications_router, prefix="/notifications", tags=["Notifications"])
api_v1_router.include_router(
    whatsapp_activity_router,
    prefix="/whatsapp",
    tags=["WhatsApp"],
)
api_v1_router.include_router(whatsapp_router, prefix="/whatsapp", tags=["WhatsApp"])
