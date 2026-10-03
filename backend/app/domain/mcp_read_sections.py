"""Explicit observational tool and sidebar boundaries for the minimum release.

These names are reviewed authority, not derived from tool annotations. Queries
with shared projections require every domain they can return; retained-capable
queries conservatively also require Old Data rather than silently leaking it.
"""

from __future__ import annotations

from app.domain.mcp_dashboard_reads import DASHBOARD_READS, DASHBOARD_SECTIONS

READ_TOOL_SECTIONS: dict[str, frozenset[str]] = {
    "connection_status": frozenset(),
    "list_groups": frozenset({"all_groups", "whatsapp", "old_data"}),
    "resolve_group": frozenset({"all_groups", "whatsapp"}),
    "list_group_passports": frozenset({"all_groups"}),
    "get_dashboard_summary": frozenset({"dashboard", "all_groups", "group_links", "old_data"}),
    "get_passport_analytics_summary": frozenset({"analytics", "all_groups", "old_data"}),
    "get_group_attendance_summary": frozenset({"tour_ops", "all_groups"}),
    "list_missing_attendance_passengers": frozenset({"tour_ops", "all_groups"}),
    "list_ecr_batches": frozenset({"all_groups"}),
    "get_ecr_batch": frozenset({"all_groups"}),
    "list_document_rename_batches": frozenset({"documents"}),
    "get_document_rename_batch": frozenset({"documents"}),
    "get_group_passport_retention": frozenset({"old_data", "all_groups"}),
    "get_email_integration_status": frozenset({"operations_inbox"}),
    "get_my_email_integration_summary": frozenset({"operations_inbox"}),
    "get_admin_overview": frozenset({"manager", "staff", "all_groups", "old_data"}),
    "list_whatsapp_broadcasts": frozenset({"whatsapp", "all_groups"}),
    "list_submission_phone_differences": frozenset({"whatsapp", "all_groups"}),
    "list_whatsapp_audience": frozenset({"whatsapp", "all_groups"}),
    "get_whatsapp_batch": frozenset({"whatsapp"}),
    "list_group_documents": frozenset({"documents", "all_groups", "old_data"}),
    "list_travel_tracker_groups": frozenset({"documents", "all_groups"}),
    "get_travel_tracker_roster": frozenset({"documents", "all_groups"}),
    "list_group_document_batches": frozenset({"documents", "all_groups", "old_data"}),
    "list_group_processing_jobs": frozenset({"all_groups", "old_data"}),
    "list_tour_records": frozenset({"tour_ops", "coordinators", "all_groups", "old_data"}),
    "list_rooming_records": frozenset({"rooming_lists", "all_groups", "old_data"}),
    "list_menu_records": frozenset({"menu"}),
    "list_organization_directory": frozenset({"manager", "staff", "coordinators", "all_groups"}),
    "list_gc_app_records": frozenset({"gc_app", "all_groups", "documents", "tour_ops", "old_data"}),
    "list_gc_notification_records": frozenset({"gc_app", "all_groups"}),
    "list_email_records": frozenset({"operations_inbox"}),
    "list_group_export_history": frozenset({"old_data", "all_groups"}),
    "get_group_export_history": frozenset({"old_data", "all_groups"}),
    "list_dashboard_read_views": frozenset(),
    # This dispatcher enforces the selected fixed view's full live section
    # union before resolving identity or loading any business data.
    "read_dashboard_view": frozenset(),
    "list_delivery_records": frozenset({"whatsapp", "documents", "tour_ops", "all_groups", "old_data"}),
    "inspect_client_details": frozenset({"all_groups"}),
    "inspect_group_access": frozenset({"all_groups", "staff", "manager"}),
    "inspect_group_broadcast_addition": frozenset({"all_groups", "group_links", "whatsapp"}),
    "get_gc_announcement_change_context": frozenset({"all_groups", "gc_app"}),
    "inspect_gc_push": frozenset({"all_groups", "gc_app"}),
    "inspect_whatsapp_intent": frozenset({"all_groups", "whatsapp"}),
    "list_my_notifications": frozenset({"gc_app"}),
    "get_passenger_qr": frozenset({"tour_ops", "all_groups"}),
    "list_attendance_activity_records": frozenset({"tour_ops", "all_groups"}),
}

SECTION_DESCRIPTIONS: tuple[tuple[str, str, str], ...] = (
    ("dashboard", "Dashboard", "Current account passport counts and five-row preview; canonical retained totals and active-link counts also require All Groups, Group Links and Old Data."),
    ("my_tour", "My Tour", "Canonical assigned-tour groups, passengers and attendance-session details through the dashboard read catalog."),
    ("all_groups", "All Groups", "Group discovery, passport rosters, OCR/ECR observations and shared group projections. Group discovery includes WhatsApp counts; retained-capable reads also require Old Data."),
    ("group_links", "Group Links", "Upload-link inventory, full group configuration, custom definitions and broadcast links; credentials are withheld."),
    ("whatsapp", "WhatsApp", "Canonical tracking, unidentified uploads, imported fields, matching, stored message states and complete delivery history. No preparation, provider refresh or send."),
    ("operations_inbox", "Operations Inbox", "Integration readiness and retained personally owned mailbox metadata. No provider fetch, sync, approval, retrieval or send."),
    ("documents", "Documents", "Canonical assignments, review/matching evidence, missing/rejected documents, stored delivery and rename history; no file bytes, access links, upload or export."),
    ("coordinators", "Coordinators", "Retained coordinator assignments and organization directory identities; shared tour/directory queries need their other sections."),
    ("rooming_lists", "Rooming Lists", "Stored hotels, rooms, selections, allocations and check-in evidence with group passenger context. No allocations, scans, key issue or export."),
    ("menu", "Menu", "Stored menu categories, dishes, plans and entries. No generation, changes or export."),
    ("tour_ops", "Tour Ops", "Retained assignments, activities, attendance and GC itinerary metadata. No physical events, workflow actions or changes."),
    ("gc_app", "GC App", "Retained app access, publication versions and authored notification history. No preparation, publication, progress refresh or push."),
    ("manager", "Manager", "Administrative counts and organization directory metadata with Staff and All Groups dependencies. No account management."),
    ("codex_access", "Codex access", "Connection metadata only through connection_status; not business-section authority."),
    ("staff", "Staff", "Directory user identities and global administrative user counts; no credential, session or account management."),
    ("analytics", "Analytics", "Passport analytics using All Groups data; no cross-domain aggregate bypass."),
    ("audit_logs", "Audit Logs", "Canonical business audit ledger with filters and native continuation, plus scoped GC/account audit history. Runtime diagnostics are excluded."),
    ("old_data", "Old Data", "Retained/deleted-capable projections, completed export checkpoint metadata and stored passport-retention schedules. No files, recovery, purge or cleanup."),
    ("settings", "Settings", "Effective platform business settings, defaults and WhatsApp template configuration. Credential values and setting changes are excluded."),
)
SUPPORTED_READ_SECTIONS = frozenset(section for required in READ_TOOL_SECTIONS.values() for section in required) | DASHBOARD_SECTIONS


def read_section_catalog() -> list[dict[str, object]]:
    return [
        {
            "id": section, "label": label, "supported": section in SUPPORTED_READ_SECTIONS,
            "coverage_description": description,
            "tool_names": sorted({name for name, required in READ_TOOL_SECTIONS.items() if section in required}
                | ({"read_dashboard_view"} if section in DASHBOARD_SECTIONS else set())),
            "tool_requirements": [
                {"name": name, "required_sections": sorted(required)}
                for name, required in sorted(READ_TOOL_SECTIONS.items()) if section in required
            ],
            "metadata_only": section == "codex_access",
            "dashboard_views": [{"name": name, "required_sections": sorted(definition.sections)}
                for name, definition in sorted(DASHBOARD_READS.items()) if section in definition.sections],
        }
        for section, label, description in SECTION_DESCRIPTIONS
    ]


def validate_read_sections(values: list[str]) -> list[str]:
    if set(values) - SUPPORTED_READ_SECTIONS:
        raise ValueError("Select only supported read sections")
    return sorted(set(values))
