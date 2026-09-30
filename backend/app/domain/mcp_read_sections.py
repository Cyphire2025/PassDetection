"""Explicit observational tool and sidebar boundaries for the minimum release.

These names are reviewed authority, not derived from tool annotations. Queries
with shared projections require every domain they can return; retained-capable
queries conservatively also require Old Data rather than silently leaking it.
"""

from __future__ import annotations

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
    "list_whatsapp_audience": frozenset({"whatsapp", "all_groups"}),
    "get_whatsapp_batch": frozenset({"whatsapp"}),
    "list_group_documents": frozenset({"documents", "all_groups", "old_data"}),
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
}

SECTION_DESCRIPTIONS: tuple[tuple[str, str, str], ...] = (
    ("dashboard", "Dashboard", "Current account passport counts and five-row preview; canonical retained totals and active-link counts also require All Groups, Group Links and Old Data."),
    ("my_tour", "My Tour", "No dedicated personal coordinator-session read tool in this release."),
    ("all_groups", "All Groups", "Group discovery, passport rosters, OCR/ECR observations and shared group projections. Group discovery includes WhatsApp counts; retained-capable reads also require Old Data."),
    ("group_links", "Group Links", "Only the Dashboard active visible-group/link count; no link credentials or complete link inventory."),
    ("whatsapp", "WhatsApp", "Stored broadcasts, audience and batch status; broadcast source flags and audience require All Groups, while shared group queries include WhatsApp counters. No preparation, media support, workflow progress refresh or send."),
    ("operations_inbox", "Operations Inbox", "Integration readiness and retained personally owned mailbox metadata. No provider fetch, sync, approval, retrieval or send."),
    ("documents", "Documents", "Stored document metadata, distribution and rename history; GC publication document metadata. No file bytes, links, upload or export."),
    ("coordinators", "Coordinators", "Retained coordinator assignments and organization directory identities; shared tour/directory queries need their other sections."),
    ("rooming_lists", "Rooming Lists", "Stored hotels, rooms, selections, allocations and check-in evidence with group passenger context. No allocations, scans, key issue or export."),
    ("menu", "Menu", "Stored menu categories, dishes, plans and entries. No generation, changes or export."),
    ("tour_ops", "Tour Ops", "Retained assignments, activities, attendance and GC itinerary metadata. No physical events, workflow actions or changes."),
    ("gc_app", "GC App", "Retained app access, publication versions and authored notification history. No preparation, publication, progress refresh or push."),
    ("manager", "Manager", "Administrative counts and organization directory metadata with Staff and All Groups dependencies. No account management."),
    ("codex_access", "Codex access", "Connection metadata only through connection_status; not business-section authority."),
    ("staff", "Staff", "Directory user identities and global administrative user counts; no credential, session or account management."),
    ("analytics", "Analytics", "Passport analytics using All Groups data; no cross-domain aggregate bypass."),
    ("audit_logs", "Audit Logs", "No business audit-log read tool in this release; runtime diagnostics are excluded."),
    ("old_data", "Old Data", "Retained/deleted-capable projections, completed export checkpoint metadata and stored passport-retention schedules. No files, recovery, purge or cleanup."),
    ("settings", "Settings", "No business settings read tool in this release. Codex read-access controls are dashboard-only."),
)
SUPPORTED_READ_SECTIONS = frozenset(section for required in READ_TOOL_SECTIONS.values() for section in required)


def read_section_catalog() -> list[dict[str, object]]:
    return [
        {
            "id": section, "label": label, "supported": section in SUPPORTED_READ_SECTIONS,
            "coverage_description": description,
            "tool_names": sorted(name for name, required in READ_TOOL_SECTIONS.items() if section in required),
            "tool_requirements": [
                {"name": name, "required_sections": sorted(required)}
                for name, required in sorted(READ_TOOL_SECTIONS.items()) if section in required
            ],
            "metadata_only": section == "codex_access",
        }
        for section, label, description in SECTION_DESCRIPTIONS
    ]


def validate_read_sections(values: list[str]) -> list[str]:
    if set(values) - SUPPORTED_READ_SECTIONS:
        raise ValueError("Select only supported read sections")
    return sorted(set(values))
