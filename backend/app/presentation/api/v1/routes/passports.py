"""Stable passport API facade; implementations live in focused modules.

Route ordering is preserved for legacy clients and OpenAPI generation.
"""

import asyncio as asyncio

from fastapi import APIRouter

from app.domain.entities.entities import UserRole as UserRole
from app.infrastructure.imports.passport_excel_importer import (
    ImportedPassportRow as ImportedPassportRow,
)

from .passport_routes import (
    bulk_actions,
    covers,
    document_import,
    excel_exports,
    excel_import,
    export_history,
    image_exports,
    images,
    public_upload,
    queries,
    selected_exports,
    submission_review,
    visa_ai_edits,
    visa_ai_jobs,
    visa_ai_library,
)
from .passport_routes.bulk_actions import (
    _active_roster_resolution_references as _active_roster_resolution_references,
)
from .passport_routes.bulk_actions import (
    _lock_active_bulk_approval_actor as _lock_active_bulk_approval_actor,
)
from .passport_routes.bulk_actions import (
    bulk_delete_passport_submissions as bulk_delete_passport_submissions,
)
from .passport_routes.bulk_actions import (
    bulk_staff_approve_passport_submissions as bulk_staff_approve_passport_submissions,
)
from .passport_routes.constants import (
    _AGENCY_MATCH_SIMILARITY_THRESHOLD as _AGENCY_MATCH_SIMILARITY_THRESHOLD,
)
from .passport_routes.constants import _FIXED_IMPORTED_EXPORT_KEYS as _FIXED_IMPORTED_EXPORT_KEYS
from .passport_routes.constants import (
    _WHATSAPP_EMAIL_IMPORTED_KEYS as _WHATSAPP_EMAIL_IMPORTED_KEYS,
)
from .passport_routes.constants import (
    _WHATSAPP_PHONE_IMPORTED_KEYS as _WHATSAPP_PHONE_IMPORTED_KEYS,
)
from .passport_routes.constants import (
    _WHATSAPP_SOURCE_METADATA_KEYS as _WHATSAPP_SOURCE_METADATA_KEYS,
)
from .passport_routes.constants import _ZONE_IMPORTED_KEYS as _ZONE_IMPORTED_KEYS
from .passport_routes.constants import PASSPORT_BULK_SELECTION_MAX as PASSPORT_BULK_SELECTION_MAX
from .passport_routes.constants import (
    PASSPORT_COMBINED_EXPORT_MAX_ROWS as PASSPORT_COMBINED_EXPORT_MAX_ROWS,
)
from .passport_routes.constants import (
    PASSPORT_DELETE_INLINE_CLEANUP_MAX_OBJECTS as PASSPORT_DELETE_INLINE_CLEANUP_MAX_OBJECTS,
)
from .passport_routes.constants import (
    PASSPORT_EXCEL_UPLOAD_READ_CHUNK_BYTES as PASSPORT_EXCEL_UPLOAD_READ_CHUNK_BYTES,
)
from .passport_routes.constants import (
    SELECTED_PASSPORT_IMAGE_EXPORT_MAX_BYTES as SELECTED_PASSPORT_IMAGE_EXPORT_MAX_BYTES,
)
from .passport_routes.constants import _agency_match_export_field as _agency_match_export_field
from .passport_routes.constants import _agency_match_similarity as _agency_match_similarity
from .passport_routes.constants import _AgencyExportMatches as _AgencyExportMatches
from .passport_routes.constants import _apply_agency_export_matches as _apply_agency_export_matches
from .passport_routes.constants import (
    _apply_passport_excel_row_to_submission as _apply_passport_excel_row_to_submission,
)
from .passport_routes.constants import _apply_pending_export_fields as _apply_pending_export_fields
from .passport_routes.constants import (
    _build_passport_excel_existing_indexes as _build_passport_excel_existing_indexes,
)
from .passport_routes.constants import (
    _canonical_excel_passport_number as _canonical_excel_passport_number,
)
from .passport_routes.constants import _canonical_excel_staff_code as _canonical_excel_staff_code
from .passport_routes.constants import (
    _combined_export_field_catalog as _combined_export_field_catalog,
)
from .passport_routes.constants import (
    _deduplicate_passport_excel_rows as _deduplicate_passport_excel_rows,
)
from .passport_routes.constants import _excel_identity_key as _excel_identity_key
from .passport_routes.constants import _excel_scalar_text as _excel_scalar_text
from .passport_routes.constants import _export_additional_values as _export_additional_values
from .passport_routes.constants import (
    _export_agency_match_field_catalog as _export_agency_match_field_catalog,
)
from .passport_routes.constants import _export_agency_matches as _export_agency_matches
from .passport_routes.constants import (
    _export_effective_whatsapp_matches as _export_effective_whatsapp_matches,
)
from .passport_routes.constants import _export_field_catalog as _export_field_catalog
from .passport_routes.constants import _export_group_details as _export_group_details
from .passport_routes.constants import _export_people_snapshot as _export_people_snapshot
from .passport_routes.constants import _export_whatsapp_contacts as _export_whatsapp_contacts
from .passport_routes.constants import _export_whatsapp_match_rows as _export_whatsapp_match_rows
from .passport_routes.constants import _export_zone_names as _export_zone_names
from .passport_routes.constants import (
    _export_zone_names_from_match_rows as _export_zone_names_from_match_rows,
)
from .passport_routes.constants import _group_export_details as _group_export_details
from .passport_routes.constants import _imported_zone_name as _imported_zone_name
from .passport_routes.constants import (
    _international_airport_is_enabled as _international_airport_is_enabled,
)
from .passport_routes.constants import _merge_excel_fields as _merge_excel_fields
from .passport_routes.constants import _merge_export_field_catalogs as _merge_export_field_catalogs
from .passport_routes.constants import (
    _normalized_agency_match_value as _normalized_agency_match_value,
)
from .passport_routes.constants import (
    _normalized_excel_mapping_items as _normalized_excel_mapping_items,
)
from .passport_routes.constants import (
    _normalized_imported_field_key as _normalized_imported_field_key,
)
from .passport_routes.constants import (
    _passport_excel_row_fingerprint as _passport_excel_row_fingerprint,
)
from .passport_routes.constants import (
    _passport_number_for_import_row as _passport_number_for_import_row,
)
from .passport_routes.constants import (
    _PassportExcelExistingIndexes as _PassportExcelExistingIndexes,
)
from .passport_routes.constants import _PassportExcelImportConflict as _PassportExcelImportConflict
from .passport_routes.constants import (
    _pending_recipient_export_rows as _pending_recipient_export_rows,
)
from .passport_routes.constants import _preferred_submission_value as _preferred_submission_value
from .passport_routes.constants import _recipient_export_value as _recipient_export_value
from .passport_routes.constants import _recipient_old_given_name as _recipient_old_given_name
from .passport_routes.constants import (
    _resolve_existing_passport_excel_submission as _resolve_existing_passport_excel_submission,
)
from .passport_routes.constants import _same_passport_submission as _same_passport_submission
from .passport_routes.constants import (
    _select_whatsapp_tracking_export_payload as _select_whatsapp_tracking_export_payload,
)
from .passport_routes.constants import _staff_code_for_import_row as _staff_code_for_import_row
from .passport_routes.constants import _staff_code_for_submission as _staff_code_for_submission
from .passport_routes.constants import _stored_resolution_uuid_list as _stored_resolution_uuid_list
from .passport_routes.constants import (
    _strict_passport_number_for_submission as _strict_passport_number_for_submission,
)
from .passport_routes.constants import (
    _strict_staff_code_for_submission as _strict_staff_code_for_submission,
)
from .passport_routes.constants import (
    _submission_agency_dealership_name as _submission_agency_dealership_name,
)
from .passport_routes.constants import (
    _validated_export_history_ids as _validated_export_history_ids,
)
from .passport_routes.constants import (
    _validated_export_history_people as _validated_export_history_people,
)
from .passport_routes.constants import _validated_export_kind as _validated_export_kind
from .passport_routes.constants import _validated_export_mode as _validated_export_mode
from .passport_routes.constants import (
    _whatsapp_tracking_export_rows as _whatsapp_tracking_export_rows,
)
from .passport_routes.dependencies import (
    _get_client_submit_passport_use_case as _get_client_submit_passport_use_case,
)
from .passport_routes.dependencies import (
    _get_confirm_passport_use_case as _get_confirm_passport_use_case,
)
from .passport_routes.dependencies import _get_get_passport_use_case as _get_get_passport_use_case
from .passport_routes.dependencies import (
    _get_list_passport_groups_use_case as _get_list_passport_groups_use_case,
)
from .passport_routes.dependencies import (
    _get_list_passports_by_group_use_case as _get_list_passports_by_group_use_case,
)
from .passport_routes.dependencies import (
    _get_list_passports_use_case as _get_list_passports_use_case,
)
from .passport_routes.dependencies import (
    _get_reconcile_passport_upload_use_case as _get_reconcile_passport_upload_use_case,
)
from .passport_routes.dependencies import (
    _get_reextract_passport_use_case as _get_reextract_passport_use_case,
)
from .passport_routes.dependencies import (
    _get_retry_post_submission_verification_use_case as _get_retry_post_submission_verification_use_case,
)
from .passport_routes.dependencies import (
    _get_retry_public_extraction_use_case as _get_retry_public_extraction_use_case,
)
from .passport_routes.dependencies import (
    _get_staff_approve_passport_use_case as _get_staff_approve_passport_use_case,
)
from .passport_routes.dependencies import (
    _get_submit_passport_use_case as _get_submit_passport_use_case,
)
from .passport_routes.document_import import (
    _authorized_passport_document_group as _authorized_passport_document_group,
)
from .passport_routes.document_import import (
    _passport_document_preview as _passport_document_preview,
)
from .passport_routes.document_import import (
    _passport_document_upload_sources as _passport_document_upload_sources,
)
from .passport_routes.document_import import (
    _queue_ocr_for_complete_staff_bundles as _queue_ocr_for_complete_staff_bundles,
)
from .passport_routes.document_import import (
    preview_passport_documents_by_group as preview_passport_documents_by_group,
)
from .passport_routes.document_import import (
    save_passport_documents_by_group as save_passport_documents_by_group,
)
from .passport_routes.excel_exports import export_passports_by_group as export_passports_by_group
from .passport_routes.excel_exports import (
    export_whatsapp_tracking_by_group as export_whatsapp_tracking_by_group,
)
from .passport_routes.excel_exports import (
    get_passport_group_export_fields as get_passport_group_export_fields,
)
from .passport_routes.excel_import import (
    _lock_and_reauthorize_passport_excel_import as _lock_and_reauthorize_passport_excel_import,
)
from .passport_routes.excel_import import (
    _lock_passport_excel_group_import as _lock_passport_excel_group_import,
)
from .passport_routes.excel_import import _parse_passport_excel_rows as _parse_passport_excel_rows
from .passport_routes.excel_import import (
    _read_bounded_passport_excel_upload as _read_bounded_passport_excel_upload,
)
from .passport_routes.excel_import import import_passports_by_group as import_passports_by_group
from .passport_routes.export_context import (
    _current_group_export_submissions as _current_group_export_submissions,
)
from .passport_routes.export_context import (
    _require_new_export_request as _require_new_export_request,
)
from .passport_routes.export_context import _resolve_export_group_by as _resolve_export_group_by
from .passport_routes.export_context import (
    _resolve_group_export_payload as _resolve_group_export_payload,
)
from .passport_routes.export_context import (
    _without_rejected_roster_submissions as _without_rejected_roster_submissions,
)
from .passport_routes.export_history import (
    complete_passport_group_export_history as complete_passport_group_export_history,
)
from .passport_routes.export_history import (
    get_passport_group_export_history_detail as get_passport_group_export_history_detail,
)
from .passport_routes.export_history import (
    list_passport_group_export_history as list_passport_group_export_history,
)
from .passport_routes.image_exports import (
    export_passport_images_by_group as export_passport_images_by_group,
)
from .passport_routes.image_exports import (
    export_selected_passport_images_by_group as export_selected_passport_images_by_group,
)
from .passport_routes.image_support import (
    _authorized_staff_passport_image as _authorized_staff_passport_image,
)
from .passport_routes.image_support import _crop_response as _crop_response
from .passport_routes.image_support import _dashboard_thumbnail_cache as _dashboard_thumbnail_cache
from .passport_routes.image_support import (
    _delete_crop_derivative_best_effort as _delete_crop_derivative_best_effort,
)
from .passport_routes.image_support import (
    _delete_ephemeral_edit_source_best_effort as _delete_ephemeral_edit_source_best_effort,
)
from .passport_routes.image_support import (
    _delete_unreferenced_passport_image_keys_best_effort as _delete_unreferenced_passport_image_keys_best_effort,
)
from .passport_routes.image_support import (
    _load_effective_passport_image as _load_effective_passport_image,
)
from .passport_routes.image_support import _visa_ai_input_storage_key as _visa_ai_input_storage_key
from .passport_routes.images import get_passport_image_crop as get_passport_image_crop
from .passport_routes.images import get_passport_image_edit_source as get_passport_image_edit_source
from .passport_routes.images import get_passport_image_original as get_passport_image_original
from .passport_routes.images import get_passport_image_thumbnail as get_passport_image_thumbnail
from .passport_routes.images import get_passport_image_view as get_passport_image_view
from .passport_routes.images import reset_passport_image_crop as reset_passport_image_crop
from .passport_routes.images import update_passport_image_crop as update_passport_image_crop
from .passport_routes.processing_support import _dispatch_processing_job as _dispatch_processing_job
from .passport_routes.public_security import (
    _require_public_upload_credential as _require_public_upload_credential,
)
from .passport_routes.public_security import _validated_upload_file as _validated_upload_file
from .passport_routes.public_upload import discard_public_upload as discard_public_upload
from .passport_routes.public_upload import (
    get_public_upload_passport_document as get_public_upload_passport_document,
)
from .passport_routes.public_upload import (
    get_public_upload_passport_image as get_public_upload_passport_image,
)
from .passport_routes.public_upload import get_upload_passport_status as get_upload_passport_status
from .passport_routes.public_upload import reconcile_passport_upload as reconcile_passport_upload
from .passport_routes.public_upload import scan_again_public_upload as scan_again_public_upload
from .passport_routes.public_upload import upload_passport as upload_passport
from .passport_routes.queries import list_passport_groups as list_passport_groups
from .passport_routes.queries import list_passports as list_passports
from .passport_routes.queries import list_passports_by_group as list_passports_by_group
from .passport_routes.queries import list_passports_by_group_view as list_passports_by_group_view
from .passport_routes.response_support import _apply_manager_visibility as _apply_manager_visibility
from .passport_routes.response_support import _effective_crop as _effective_crop
from .passport_routes.response_support import _ensure_submission_qr as _ensure_submission_qr
from .passport_routes.response_support import _owner_scope_for as _owner_scope_for
from .passport_routes.response_support import _passport_image_api_url as _passport_image_api_url
from .passport_routes.response_support import (
    _passport_image_edit_source_api_url as _passport_image_edit_source_api_url,
)
from .passport_routes.response_support import _passport_qr_status as _passport_qr_status
from .passport_routes.response_support import (
    _passport_visa_ai_library_image_api_url as _passport_visa_ai_library_image_api_url,
)
from .passport_routes.response_support import _response_from_dto as _response_from_dto
from .passport_routes.response_support import _response_from_submission as _response_from_submission
from .passport_routes.response_support import _safe_presigned_url as _safe_presigned_url
from .passport_routes.response_support import _staff_image_urls as _staff_image_urls
from .passport_routes.response_support import _stream_binary_file as _stream_binary_file
from .passport_routes.response_support import _submitted_statuses as _submitted_statuses
from .passport_routes.selected_exports import (
    _selected_groups_export_context as _selected_groups_export_context,
)
from .passport_routes.selected_exports import export_selected_groups as export_selected_groups
from .passport_routes.selected_exports import export_selected_passports as export_selected_passports
from .passport_routes.selected_exports import (
    get_selected_groups_export_fields as get_selected_groups_export_fields,
)
from .passport_routes.submission_review import (
    _cleanup_uncommitted_promotions as _cleanup_uncommitted_promotions,
)
from .passport_routes.submission_review import (
    _staff_approval_conflict_response as _staff_approval_conflict_response,
)
from .passport_routes.submission_review import (
    cancel_passport_processing as cancel_passport_processing,
)
from .passport_routes.submission_review import client_submit_passport as client_submit_passport
from .passport_routes.submission_review import confirm_passport as confirm_passport
from .passport_routes.submission_review import get_passport as get_passport
from .passport_routes.submission_review import reextract_passport as reextract_passport
from .passport_routes.submission_review import (
    retry_post_submission_verification as retry_post_submission_verification,
)
from .passport_routes.submission_review import staff_approve_passport as staff_approve_passport
from .passport_routes.visa_ai_edits import apply_visa_ai_image_edit as apply_visa_ai_image_edit
from .passport_routes.visa_ai_edits import preview_visa_ai_image_edit as preview_visa_ai_image_edit
from .passport_routes.visa_ai_jobs import create_visa_ai_image_job as create_visa_ai_image_job
from .passport_routes.visa_ai_jobs import (
    get_active_visa_ai_image_job as get_active_visa_ai_image_job,
)
from .passport_routes.visa_ai_jobs import get_visa_ai_image_job as get_visa_ai_image_job
from .passport_routes.visa_ai_library import (
    create_visa_ai_library_image as create_visa_ai_library_image,
)
from .passport_routes.visa_ai_library import get_visa_ai_library_image as get_visa_ai_library_image
from .passport_routes.visa_ai_library import (
    list_visa_ai_image_library as list_visa_ai_image_library,
)
from .passport_routes.visa_ai_library import use_visa_ai_library_image as use_visa_ai_library_image
from .passport_routes.visa_ai_support import (
    _dispatch_queued_visa_ai_job as _dispatch_queued_visa_ai_job,
)
from .passport_routes.visa_ai_support import (
    _recover_and_dispatch_visa_ai_job as _recover_and_dispatch_visa_ai_job,
)
from .passport_routes.visa_ai_support import (
    _visa_ai_edit_http_exception as _visa_ai_edit_http_exception,
)
from .passport_routes.visa_ai_support import _visa_ai_job_response as _visa_ai_job_response
from .passport_routes.visa_ai_support import _visa_ai_library_response as _visa_ai_library_response

_ROUTE_ORDER = (
    "upload_passport",
    "reconcile_passport_upload",
    "get_upload_passport_status",
    "scan_again_public_upload",
    "get_public_upload_passport_image",
    "get_public_upload_passport_document",
    "discard_public_upload",
    "list_passport_groups",
    "list_passports_by_group",
    "list_passports_by_group_view",
    "bulk_delete_passport_submissions",
    "bulk_staff_approve_passport_submissions",
    "list_passports",
    "list_passport_group_export_history",
    "get_passport_group_export_history_detail",
    "complete_passport_group_export_history",
    "get_passport_group_export_fields",
    "export_whatsapp_tracking_by_group",
    "export_passports_by_group",
    "export_passport_images_by_group",
    "export_selected_passport_images_by_group",
    "import_passports_by_group",
    "preview_passport_documents_by_group",
    "save_passport_documents_by_group",
    "export_selected_passports",
    "get_selected_groups_export_fields",
    "export_selected_groups",
    "get_passport_image_edit_source",
    "get_passport_image_view",
    "get_passport_image_thumbnail",
    "get_passport_image_original",
    "get_passport_image_crop",
    "update_passport_image_crop",
    "preview_visa_ai_image_edit",
    "create_visa_ai_image_job",
    "get_active_visa_ai_image_job",
    "get_visa_ai_image_job",
    "list_visa_ai_image_library",
    "get_visa_ai_library_image",
    "create_visa_ai_library_image",
    "use_visa_ai_library_image",
    "apply_visa_ai_image_edit",
    "reset_passport_image_crop",
    "get_passport_cover",
    "get_passport",
    "client_submit_passport",
    "staff_approve_passport",
    "retry_post_submission_verification",
    "reextract_passport",
    "cancel_passport_processing",
    "confirm_passport",
)

router = APIRouter()
for _module in (
    bulk_actions,
    covers,
    document_import,
    excel_exports,
    excel_import,
    export_history,
    image_exports,
    images,
    public_upload,
    queries,
    selected_exports,
    submission_review,
    visa_ai_edits,
    visa_ai_jobs,
    visa_ai_library,
):
    router.routes.extend(_module.router.routes)
_route_positions = {name: position for position, name in enumerate(_ROUTE_ORDER)}
router.routes.sort(key=lambda route: _route_positions[getattr(route, "name", "")])
