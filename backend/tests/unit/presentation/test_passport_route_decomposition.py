from __future__ import annotations

import pytest

from app.presentation.api.v1.routes import (
    passport_excel_import_support,
    passport_export_support,
    passports,
)

_ROUTE_SIGNATURES = (
    (("POST",), "/upload/{token}", "upload_passport"),
    (("PUT",), "/upload/{token}", "reconcile_passport_upload"),
    (("GET",), "/upload/{token}/{submission_id}/status", "get_upload_passport_status"),
    (("POST",), "/upload/{token}/{submission_id}/scan-again", "scan_again_public_upload"),
    (("GET",), "/upload/{token}/{submission_id}/image", "get_public_upload_passport_image"),
    (
        ("GET",),
        "/upload/{token}/{submission_id}/image/{document_type}",
        "get_public_upload_passport_document",
    ),
    (("DELETE",), "/upload/{token}/{submission_id}", "discard_public_upload"),
    (("GET",), "/groups", "list_passport_groups"),
    (("GET",), "/groups/{group_id}", "list_passports_by_group"),
    (("GET",), "/groups/{group_id}/submissions-view", "list_passports_by_group_view"),
    (("POST",), "/groups/{group_id}/bulk-delete", "bulk_delete_passport_submissions"),
    (
        ("POST",),
        "/groups/{group_id}/bulk-staff-approve",
        "bulk_staff_approve_passport_submissions",
    ),
    (("GET",), "", "list_passports"),
    (("GET",), "/groups/{group_id}/export-history", "list_passport_group_export_history"),
    (
        ("GET",),
        "/groups/{group_id}/export-history/{history_id}",
        "get_passport_group_export_history_detail",
    ),
    (
        ("POST",),
        "/groups/{group_id}/export-history/{history_id}/complete",
        "complete_passport_group_export_history",
    ),
    (("GET",), "/groups/{group_id}/export-fields", "get_passport_group_export_fields"),
    (
        ("GET",),
        "/groups/{group_id}/whatsapp-tracking/export.xlsx",
        "export_whatsapp_tracking_by_group",
    ),
    (("GET",), "/groups/{group_id}/export.xlsx", "export_passports_by_group"),
    (("GET",), "/groups/{group_id}/export-images", "export_passport_images_by_group"),
    (
        ("POST",),
        "/groups/{group_id}/export-images/selected",
        "export_selected_passport_images_by_group",
    ),
    (("POST",), "/groups/{group_id}/import.xlsx", "import_passports_by_group"),
    (
        ("POST",),
        "/groups/{group_id}/import-passports/preview",
        "preview_passport_documents_by_group",
    ),
    (
        ("POST",),
        "/groups/{group_id}/import-passports/save",
        "save_passport_documents_by_group",
    ),
    (("POST",), "/export.xlsx", "export_selected_passports"),
    (("POST",), "/groups/export-fields", "get_selected_groups_export_fields"),
    (("POST",), "/groups/export.xlsx", "export_selected_groups"),
    (
        ("GET",),
        "/{submission_id}/images/{image_type}/edit-source",
        "get_passport_image_edit_source",
    ),
    (("GET",), "/{submission_id}/images/{image_type}", "get_passport_image_view"),
    (
        ("GET",),
        "/{submission_id}/images/{image_type}/thumbnail",
        "get_passport_image_thumbnail",
    ),
    (
        ("GET",),
        "/{submission_id}/images/{image_type}/original",
        "get_passport_image_original",
    ),
    (("GET",), "/{submission_id}/images/{image_type}/crop", "get_passport_image_crop"),
    (("PUT",), "/{submission_id}/images/{image_type}/crop", "update_passport_image_crop"),
    (
        ("POST",),
        "/{submission_id}/images/visa_photo/ai-preview",
        "preview_visa_ai_image_edit",
    ),
    (
        ("POST",),
        "/{submission_id}/images/visa_photo/ai-jobs",
        "create_visa_ai_image_job",
    ),
    (
        ("GET",),
        "/{submission_id}/images/visa_photo/ai-jobs/active",
        "get_active_visa_ai_image_job",
    ),
    (
        ("GET",),
        "/{submission_id}/images/visa_photo/ai-jobs/{job_id}",
        "get_visa_ai_image_job",
    ),
    (
        ("GET",),
        "/{submission_id}/images/visa_photo/ai-library",
        "list_visa_ai_image_library",
    ),
    (
        ("GET",),
        "/{submission_id}/images/visa_photo/ai-library/{generation_id}/image",
        "get_visa_ai_library_image",
    ),
    (
        ("POST",),
        "/{submission_id}/images/visa_photo/ai-library",
        "create_visa_ai_library_image",
    ),
    (
        ("POST",),
        "/{submission_id}/images/visa_photo/ai-library/{generation_id}/use",
        "use_visa_ai_library_image",
    ),
    (
        ("POST",),
        "/{submission_id}/images/visa_photo/ai-apply",
        "apply_visa_ai_image_edit",
    ),
    (("DELETE",), "/{submission_id}/images/{image_type}/crop", "reset_passport_image_crop"),
    (("GET",), "/{submission_id}/covers/{cover_type}", "get_passport_cover"),
    (("GET",), "/{submission_id}", "get_passport"),
    (("POST",), "/{submission_id}/client-submit", "client_submit_passport"),
    (("POST",), "/{submission_id}/staff-approve", "staff_approve_passport"),
    (
        ("POST",),
        "/{submission_id}/retry-ai-verification",
        "retry_post_submission_verification",
    ),
    (("POST",), "/{submission_id}/reextract", "reextract_passport"),
    (("POST",), "/{submission_id}/cancel-processing", "cancel_passport_processing"),
    (("POST",), "/{submission_id}/confirm", "confirm_passport"),
)

_EXCEL_FACADE_NAMES = (
    "_PassportExcelExistingIndexes",
    "_PassportExcelImportConflict",
    "_apply_passport_excel_row_to_submission",
    "_build_passport_excel_existing_indexes",
    "_deduplicate_passport_excel_rows",
    "_merge_excel_fields",
    "_resolve_existing_passport_excel_submission",
    "_staff_code_for_submission",
)

_EXPORT_FACADE_NAMES = (
    "_AgencyExportMatches",
    "_agency_match_export_field",
    "_apply_agency_export_matches",
    "_apply_pending_export_fields",
    "_combined_export_field_catalog",
    "_export_additional_values",
    "_export_agency_match_field_catalog",
    "_export_agency_matches",
    "_export_effective_whatsapp_matches",
    "_export_field_catalog",
    "_export_group_details",
    "_export_whatsapp_contacts",
    "_export_whatsapp_match_rows",
    "_export_zone_names",
    "_group_export_details",
    "_pending_recipient_export_rows",
    "_recipient_export_value",
    "_resolve_export_group_by",
    "_select_whatsapp_tracking_export_payload",
    "_whatsapp_tracking_export_rows",
)


def test_passport_router_keeps_the_pre_decomposition_contract_and_order() -> None:
    actual = tuple(
        (tuple(sorted(route.methods or ())), route.path, route.name)
        for route in passports.router.routes
    )

    assert actual == _ROUTE_SIGNATURES


@pytest.mark.parametrize("name", _EXCEL_FACADE_NAMES)
def test_excel_support_remains_available_through_the_passports_facade(name: str) -> None:
    assert getattr(passports, name) is getattr(passport_excel_import_support, name)


@pytest.mark.parametrize(
    "name",
    tuple(name for name in _EXPORT_FACADE_NAMES if name != "_resolve_export_group_by"),
)
def test_export_support_remains_available_through_the_passports_facade(name: str) -> None:
    assert getattr(passports, name) is getattr(passport_export_support, name)


def test_export_grouping_helper_remains_in_the_router_facade() -> None:
    assert passports._resolve_export_group_by("none", ["zone_name"]) is None
