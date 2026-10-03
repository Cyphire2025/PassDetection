"""Code-owned effect boundaries; neither tool names nor sections confer OAuth scopes."""

from app.domain.mcp_read_sections import SECTION_DESCRIPTIONS, read_section_catalog

WRITE_CAPABILITIES = frozenset({"mcp:change", "mcp:upload", "mcp:export", "mcp:communicate"})

# Every required section is checked. Adding an adapter here does not enable it:
# deployment scope, global tool allowlist and device policy must all allow it.
WRITE_TOOL_SECTIONS: dict[str, frozenset[str]] = {
    "set_travel_tracker_status": frozenset({"documents", "all_groups"}),
    "preview_travel_tracker_workbook": frozenset({"documents", "all_groups", "group_excel_imports"}),
    "apply_travel_tracker_workbook": frozenset({"documents", "all_groups", "group_excel_imports"}),
    "create_group": frozenset({"group_links"}),
    "configure_group_link": frozenset({"group_links"}),
    "create_whatsapp_broadcast": frozenset({"whatsapp_broadcasts"}),
    "update_broadcast_details": frozenset({"whatsapp_broadcasts"}),
    "add_broadcast_contacts": frozenset({"whatsapp_broadcasts"}),
    "correct_client_details": frozenset({"all_groups"}),
    "create_menu_category": frozenset({"menu"}),
    "create_menu_dish": frozenset({"menu"}),
    "create_meal_plan": frozenset({"menu"}),
    "create_rooming_hotel": frozenset({"rooming_lists"}),
    "configure_rooming_hotel": frozenset({"rooming_lists"}),
    "select_rooming_passengers": frozenset({"rooming_lists"}),
    "set_rooming_vip": frozenset({"rooming_lists"}),
    "allocate_rooming_rooms": frozenset({"rooming_lists"}),
    "update_menu_category": frozenset({"menu"}),
    "update_menu_dish": frozenset({"menu"}),
    "update_meal_plan": frozenset({"menu"}),
    "update_meal_plan_entry": frozenset({"menu"}),
    "add_group_coordinators": frozenset({"tour_ops"}),
    "create_attendance_activity": frozenset({"tour_ops"}),
    "create_gc_itinerary_draft": frozenset({"gc_app"}),
    "create_workforce_account": frozenset(),
    "create_gc_client_manager_account": frozenset({"gc_app"}),
    "configure_gc_group_access": frozenset({"gc_app"}),
    "configure_gc_my_photos": frozenset({"gc_app"}),
    "publish_gc_itinerary": frozenset({"gc_app"}),
    "add_staff_group_access": frozenset({"staff"}),
    "add_manager_group_access": frozenset({"manager"}),
    "add_group_broadcast_link": frozenset({"group_links"}),
    "create_contact_broadcast": frozenset({"whatsapp_broadcasts"}),
    "inspect_contact_workbook": frozenset({"whatsapp_broadcasts"}),
    "preview_contact_broadcast": frozenset({"whatsapp_broadcasts"}),
    "create_gc_announcement_draft": frozenset({"gc_app"}),
    "create_gc_announcement_revision": frozenset({"gc_app"}),
    "create_gc_push_draft": frozenset({"gc_app"}),
    "prepare_gc_push": frozenset({"gc_app"}),
    "confirm_gc_push": frozenset({"gc_app"}),
    "cancel_gc_push": frozenset({"gc_app"}),
    "prepare_whatsapp_reminder": frozenset({"whatsapp_broadcasts"}),
    "prepare_whatsapp_message": frozenset({"whatsapp_broadcasts"}),
    "confirm_whatsapp_send": frozenset({"whatsapp_broadcasts"}),
    "cancel_whatsapp_intent": frozenset({"whatsapp_broadcasts"}),
    "acknowledge_my_notification": frozenset({"gc_app"}),
    "inspect_document_pdf_ingestion": frozenset({"document_delivery"}),
    "ingest_document_pdf": frozenset({"document_delivery"}),
    "resume_document_pdf_ingestion": frozenset({"document_delivery"}),
    "upload_document_pdf": frozenset({"document_delivery"}),
    "upload_contact_workbook": frozenset({"whatsapp_broadcasts"}),
    "upload_group_workbook": frozenset({"group_excel_imports"}),
    "upload_whatsapp_header": frozenset({"whatsapp_broadcasts"}),
    "recover_whatsapp_header": frozenset({"whatsapp_broadcasts"}),
    "import_group_excel": frozenset({"group_excel_imports"}),
    "preview_group_workbook_import": frozenset({"group_excel_imports"}),
    "import_group_workbook": frozenset({"group_excel_imports"}),
    "save_document_assignments": frozenset({"document_delivery"}),
    "inspect_document_assignments": frozenset({"document_delivery"}),
    "list_dashboard_write_workflows": frozenset(),
    "inspect_dashboard_write": frozenset(),
    "create_native_upload": frozenset(),
    "inspect_native_transfer": frozenset(),
    "create_native_download": frozenset(),
    "read_native_artifact": frozenset(),
}
for family, sections in {
    "excel": {"exports"},
    "image": {"exports"},
    "tracking": {"exports"},
    "rooming": {"exports"},
    "document_assignment": {"exports"},
    "travel_tracker": {"documents", "all_groups", "exports"},
}.items():
    for action in ("inspect", "prepare", "resume", "generate"):
        WRITE_TOOL_SECTIONS[f"{action}_{family}_export"] = frozenset(sections)
WRITE_TOOL_SECTIONS["inspect_excel_export_options"] = frozenset({"exports"})
WRITE_TOOL_SECTIONS["prepare_passport_excel"] = WRITE_TOOL_SECTIONS["prepare_excel_export"]
WRITE_TOOL_SECTIONS["prepare_passport_images"] = WRITE_TOOL_SECTIONS["prepare_image_export"]
WRITE_TOOL_SECTIONS["download_export"] = frozenset({"exports"})
WRITE_TOOL_SECTIONS["acknowledge_export_delivery"] = frozenset({"exports"})
for family in ("reminder", "document_delivery", "message"):
    WRITE_TOOL_SECTIONS[f"prepare_whatsapp_{family}"] = frozenset({"document_delivery" if family == "document_delivery" else "whatsapp_broadcasts"})
    WRITE_TOOL_SECTIONS[f"confirm_whatsapp_{family}"] = WRITE_TOOL_SECTIONS[f"prepare_whatsapp_{family}"]

SUPPORTED_WRITE_SECTIONS = frozenset(section for required in WRITE_TOOL_SECTIONS.values() for section in required)
DYNAMIC_WRITE_TOOL_SECTIONS = {
    "create_workforce_account": frozenset({"coordinators", "staff", "manager"}),
    "create_native_upload": frozenset({"group_excel_imports", "document_delivery", "whatsapp_broadcasts"}),
    "inspect_native_transfer": frozenset({"group_excel_imports", "document_delivery", "whatsapp_broadcasts", "exports"}),
    "create_native_download": frozenset({"exports"}),
    "read_native_artifact": frozenset({"exports"}),
}
SUPPORTED_WRITE_SECTIONS |= frozenset(section for allowed in DYNAMIC_WRITE_TOOL_SECTIONS.values() for section in allowed)
_EXTRA_SECTIONS = (
    ("whatsapp_broadcasts", "WhatsApp broadcasts"),
    ("document_delivery", "Document delivery"),
    ("group_excel_imports", "Group Excel imports"),
    ("exports", "Exports"),
)


def validate_write_sections(values: list[str]) -> list[str]:
    if set(values) - SUPPORTED_WRITE_SECTIONS:
        raise ValueError("Select only supported write sections")
    return sorted(set(values))


def validate_write_tools(values: list[str]) -> list[str]:
    if set(values) - WRITE_TOOL_SECTIONS.keys():
        raise ValueError("Select only reviewed write tools")
    return sorted(set(values))


def write_tool_requirements() -> list[dict[str, object]]:
    return [{"name": name, "required_sections": sorted(required)} for name, required in sorted(WRITE_TOOL_SECTIONS.items())]


def section_permission_catalog() -> list[dict[str, object]]:
    reads = {str(row["id"]): row for row in read_section_catalog()}
    descriptions = [(key, label, description) for key, label, description in SECTION_DESCRIPTIONS]
    descriptions.extend((key, label, "") for key, label in _EXTRA_SECTIONS)
    return [{
        "id": key, "label": label, "read_supported": bool(reads.get(key, {}).get("supported", False)),
        "write_supported": key in SUPPORTED_WRITE_SECTIONS, "read_description": description,
        "write_description": "Explicitly approved changes, uploads, exports or communications through the listed tools only. Current application permissions still apply." if key in SUPPORTED_WRITE_SECTIONS else "No reviewed write adapter.",
        "read_tool_names": reads.get(key, {}).get("tool_names", []),
        "write_tool_names": sorted(name for name, required in WRITE_TOOL_SECTIONS.items() if key in required or key in DYNAMIC_WRITE_TOOL_SECTIONS.get(name, frozenset())),
    } for key, label, description in descriptions]
