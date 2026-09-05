"""Compatibility contracts for the decomposed WhatsApp route facade."""

from __future__ import annotations

import ast
import inspect

from app.presentation.api.v1.routes import (
    whatsapp,
    whatsapp_composer_support,
    whatsapp_contact_support,
    whatsapp_delivery_support,
    whatsapp_roster_support,
)

_EXPECTED_ROUTES = [
    (("GET",), "/webhook", "verify_whatsapp_webhook"),
    (("POST",), "/webhook", "receive_whatsapp_webhook"),
    (("POST",), "/contacts/preview", "preview_excel_contacts"),
    (("GET",), "/groups", "list_broadcast_groups"),
    (("GET",), "/groups/{group_id}", "get_broadcast_group"),
    (("GET",), "/groups/{group_id}/recipient-roster", "get_broadcast_recipient_roster"),
    (("GET",), "/groups/{group_id}/rejected-contacts", "list_broadcast_rejected_contacts"),
    (
        ("POST",),
        "/groups/{group_id}/rejected-contacts/{rejected_contact_id}/resolve",
        "resolve_broadcast_rejected_contact",
    ),
    (("POST",), "/groups/{group_id}/welcome-media", "upload_welcome_media"),
    (("POST",), "/groups/{group_id}/preview", "preview_broadcast_message"),
    (("POST",), "/groups", "create_broadcast_group"),
    (("PATCH",), "/groups/{group_id}", "update_broadcast_group"),
    (("POST",), "/groups/{group_id}/recipients", "add_broadcast_recipients"),
    (
        ("PATCH",),
        "/groups/{group_id}/recipients/{recipient_id}",
        "update_broadcast_recipient_phone",
    ),
    (
        ("DELETE",),
        "/groups/{group_id}/recipients/{recipient_id}",
        "remove_broadcast_recipient",
    ),
    (
        ("POST",),
        "/groups/{group_id}/recipients/{recipient_id}/resend",
        "resend_recipient_message",
    ),
    (("DELETE",), "/groups/{group_id}", "delete_broadcast_group"),
    (("POST",), "/groups/{group_id}/send", "send_broadcast_message"),
    (("GET",), "/batches/{batch_id}/summary", "get_broadcast_batch_summary"),
    (("GET",), "/batches/{batch_id}", "get_broadcast_batch_status"),
]

_FACADE_NAMES = {
    whatsapp_delivery_support: (
        "_iter_webhook_values",
        "_extract_status_error",
        "_parse_provider_status_at",
        "_is_stale_provider_status",
        "_apply_provider_status_to_delivery_state",
        "_apply_provider_status_to_message_log",
        "_provider_status_state_predicates",
        "_agency_filter",
        "_broadcast_batch_summary_statement",
    ),
    whatsapp_contact_support: (
        "_WhatsAppExcelContactParseResult",
        "_normalize_phone",
        "_clean_name",
        "_clean_required_name",
        "_validate_excel_archive",
        "_excel_cell_text",
        "_excel_header_label",
        "_excel_field_key",
        "_safe_imported_fields",
        "_is_excel_phone_header",
        "_is_excel_name_header",
        "_excel_header_columns",
        "_find_excel_contact_header",
        "_excel_name_from_row",
        "_excel_raw_name_from_row",
        "_bounded_excel_raw_value",
        "_is_repeated_excel_header",
        "_row_has_contact_identity",
        "_excel_fields_from_row",
        "_merge_recipient_inputs",
        "_excel_contact_preview_response",
        "_parse_manual_contacts",
        "_rejected_contact_fingerprint",
        "_parse_rejected_contacts",
        "_positive_int",
        "_roster_source_sort_key",
        "_new_roster_display_orders",
        "_next_roster_display_order",
        "_add_rejected_contact_models",
        "_normalized_recipient_inputs",
        "_activate_recipient_models",
        "_parse_support_contacts",
        "_recipient_response",
        "_rejected_contact_response",
        "_support_contact_response",
    ),
    whatsapp_roster_support: (
        "_support_contacts_for_group",
        "_recipient_delivery_state_maps",
        "_group_detail",
        "_group_recipients",
        "_select_group_recipients",
        "_select_support_contacts",
        "_recipient_delivery_counts",
    ),
    whatsapp_composer_support: (
        "_WhatsAppComposerSnapshot",
        "_as_message_type",
        "_resolve_message_content",
        "_resolve_send_message_content",
        "_resolve_passport_intro",
        "_resolve_send_passport_intro",
        "_resolve_send_header_image",
        "_validate_passport_link",
        "_message_values",
        "_split_rendered_support_block",
        "_decode_legacy_template_snapshot",
        "_template_snapshot_from_log",
        "_composer_snapshot_from_log",
        "_latest_composer_snapshot",
        "_merge_composer_snapshot",
    ),
}


def _decorated_route_names(module: object) -> list[str]:
    tree = ast.parse(inspect.getsource(module))
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            function = decorator.func
            if (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id == "router"
            ):
                names.append(node.name)
                break
    return names


def test_whatsapp_route_order_and_names_remain_stable() -> None:
    actual = [
        (tuple(sorted(route.methods or ())), route.path, route.name)
        for route in whatsapp.router.routes
    ]
    assert actual == _EXPECTED_ROUTES
    assert _decorated_route_names(whatsapp) == []
    for route in whatsapp.router.routes:
        assert route.endpoint is getattr(whatsapp, route.name)
        assert route.endpoint.__module__.startswith(whatsapp.__name__ + "_")


def test_support_modules_do_not_register_routes() -> None:
    for module in _FACADE_NAMES:
        assert _decorated_route_names(module) == []


def test_whatsapp_facade_preserves_extracted_helper_identities() -> None:
    for support_module, names in _FACADE_NAMES.items():
        for name in names:
            assert getattr(whatsapp, name) is getattr(support_module, name)
