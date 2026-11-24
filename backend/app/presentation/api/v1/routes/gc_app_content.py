"""Compatibility imports and resource routers for GC content."""

from fastapi import APIRouter

from app.presentation.api.v1.routes.gc_app_announcement_publication import (
    delete_announcement as delete_announcement,
)
from app.presentation.api.v1.routes.gc_app_announcement_publication import (
    publish_announcement as publish_announcement,
)
from app.presentation.api.v1.routes.gc_app_announcement_publication import (
    router as _gc_app_announcement_publication_router,
)
from app.presentation.api.v1.routes.gc_app_announcement_publication import (
    unpublish_announcement as unpublish_announcement,
)
from app.presentation.api.v1.routes.gc_app_announcements import (
    _create_announcement_version as _create_announcement_version,
)
from app.presentation.api.v1.routes.gc_app_announcements import (
    create_announcement as create_announcement,
)
from app.presentation.api.v1.routes.gc_app_announcements import (
    get_announcement_notification_status as get_announcement_notification_status,
)
from app.presentation.api.v1.routes.gc_app_announcements import (
    list_announcements as list_announcements,
)
from app.presentation.api.v1.routes.gc_app_announcements import (
    page_announcements as page_announcements,
)
from app.presentation.api.v1.routes.gc_app_announcements import (
    router as _gc_app_announcements_router,
)
from app.presentation.api.v1.routes.gc_app_announcements import (
    update_announcement as update_announcement,
)
from app.presentation.api.v1.routes.gc_app_common_documents import (
    list_common_documents as list_common_documents,
)
from app.presentation.api.v1.routes.gc_app_common_documents import (
    reorder_common_documents as reorder_common_documents,
)
from app.presentation.api.v1.routes.gc_app_common_documents import (
    replace_common_document as replace_common_document,
)
from app.presentation.api.v1.routes.gc_app_common_documents import (
    router as _gc_app_common_documents_router,
)
from app.presentation.api.v1.routes.gc_app_common_documents import (
    upload_common_document as upload_common_document,
)
from app.presentation.api.v1.routes.gc_app_common_preview import (
    _GC_PREVIEW_STREAM_SLOTS as _GC_PREVIEW_STREAM_SLOTS,
)
from app.presentation.api.v1.routes.gc_app_common_preview import (
    _CommonDocumentPreviewPlan as _CommonDocumentPreviewPlan,
)
from app.presentation.api.v1.routes.gc_app_common_preview import (
    preview_common_document_content as preview_common_document_content,
)
from app.presentation.api.v1.routes.gc_app_common_preview import (
    router as _gc_app_common_preview_router,
)
from app.presentation.api.v1.routes.gc_app_common_publication import (
    delete_common_document as delete_common_document,
)
from app.presentation.api.v1.routes.gc_app_common_publication import (
    publish_common_document as publish_common_document,
)
from app.presentation.api.v1.routes.gc_app_common_publication import (
    router as _gc_app_common_publication_router,
)
from app.presentation.api.v1.routes.gc_app_common_publication import (
    unpublish_common_document as unpublish_common_document,
)
from app.presentation.api.v1.routes.gc_app_common_staging import (
    _discard_staged_common_document as _discard_staged_common_document,
)
from app.presentation.api.v1.routes.gc_app_common_staging import (
    _stage_common_document as _stage_common_document,
)
from app.presentation.api.v1.routes.gc_app_common_staging import (
    _StagedCommonDocument as _StagedCommonDocument,
)
from app.presentation.api.v1.routes.gc_app_common_staging import (
    _store_common_document_version as _store_common_document_version,
)
from app.presentation.api.v1.routes.gc_app_common_staging import (
    _validated_common_pdf as _validated_common_pdf,
)
from app.presentation.api.v1.routes.gc_app_content_audit import (
    list_group_gc_audit as list_group_gc_audit,
)
from app.presentation.api.v1.routes.gc_app_content_audit import (
    router as _gc_app_content_audit_router,
)
from app.presentation.api.v1.routes.gc_app_content_lookup import (
    _get_announcement as _get_announcement,
)
from app.presentation.api.v1.routes.gc_app_content_lookup import (
    _get_common_document as _get_common_document,
)
from app.presentation.api.v1.routes.gc_app_content_lookup import (
    _get_itinerary as _get_itinerary,
)
from app.presentation.api.v1.routes.gc_app_content_lookup import (
    _latest_itinerary as _latest_itinerary,
)
from app.presentation.api.v1.routes.gc_app_content_projection import (
    _announcement_response as _announcement_response,
)
from app.presentation.api.v1.routes.gc_app_content_projection import (
    _common_document_response as _common_document_response,
)
from app.presentation.api.v1.routes.gc_app_content_projection import (
    _itinerary_response as _itinerary_response,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    GC_CONTENT_ROLES as GC_CONTENT_ROLES,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    _admin_access_context as _admin_access_context,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    _content_audit as _content_audit,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    _content_status as _content_status,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    _itinerary_status as _itinerary_status,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    _json_checksum as _json_checksum,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    _require_access_revision as _require_access_revision,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    _require_publishable_group as _require_publishable_group,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    _validate_window as _validate_window,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    logger as logger,
)
from app.presentation.api.v1.routes.gc_app_itineraries import (
    create_itinerary_draft as create_itinerary_draft,
)
from app.presentation.api.v1.routes.gc_app_itineraries import (
    preview_itinerary as preview_itinerary,
)
from app.presentation.api.v1.routes.gc_app_itineraries import (
    publish_itinerary as publish_itinerary,
)
from app.presentation.api.v1.routes.gc_app_itineraries import router as _gc_app_itineraries_router
from app.presentation.api.v1.routes.gc_app_itineraries import (
    unpublish_itinerary as unpublish_itinerary,
)
from app.presentation.api.v1.schemas.announcement_notification_status import (
    AnnouncementNotificationStatusResponse as AnnouncementNotificationStatusResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    AnnouncementCreateRequest as AnnouncementCreateRequest,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    AnnouncementPageResponse as AnnouncementPageResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    AnnouncementResponse as AnnouncementResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    CommonDocumentCategory as CommonDocumentCategory,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    CommonDocumentReorderRequest as CommonDocumentReorderRequest,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    CommonDocumentResponse as CommonDocumentResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCAppAuditPageResponse as GCAppAuditPageResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ItineraryDayInput as ItineraryDayInput,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ItineraryDraftRequest as ItineraryDraftRequest,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ItineraryItemInput as ItineraryItemInput,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ItineraryVersionResponse as ItineraryVersionResponse,
)

router = APIRouter()
router.include_router(_gc_app_itineraries_router)
router.include_router(_gc_app_common_documents_router)
router.include_router(_gc_app_common_publication_router)
router.include_router(_gc_app_common_preview_router)
router.include_router(_gc_app_announcements_router)
router.include_router(_gc_app_announcement_publication_router)
router.include_router(_gc_app_content_audit_router)
