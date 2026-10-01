"""Reviewed dashboard observations; HTTP GET alone never establishes read authority.

Selectors are fixed here rather than accepting URLs, SQL or arbitrary Python
names. Handlers with send preparation, provider refresh, file transfers or job
redelivery use dedicated observational adapters instead of their HTTP handler.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DashboardRead:
    handler: str
    sections: frozenset[str]
    description: str
    group_parameter: str | None = None


def _read(handler: str, sections: str, description: str, group: str | None = None) -> DashboardRead:
    return DashboardRead(handler, frozenset(sections.split()), description, group)


DASHBOARD_READS: dict[str, DashboardRead] = {
    "group_links": _read("client_groups.list_client_groups", "group_links all_groups old_data", "Upload-link inventory and group configuration; provide agency_id context. Credentials are withheld."),
    "group_details": _read("@group_details", "group_links all_groups whatsapp old_data", "Complete stored group configuration, dates, custom questions and details; group_id identifies a client group.", "group_id"),
    "group_whatsapp_links": _read("client_groups.get_client_group_whatsapp_links", "group_links all_groups whatsapp", "Broadcast links, matching fields and sync configuration for a client group.", "link_id"),
    "group_whatsapp_matches": _read("client_groups.get_client_group_whatsapp_matches", "all_groups whatsapp", "Canonical submitted, missing, multiple, unmatched, replaced and rejected passport matching; native page/page_size filters.", "link_id"),
    "group_replacement_candidates": _read("client_groups.list_replacement_candidates", "all_groups whatsapp", "Existing candidate metadata; reading neither resolves nor replaces a contact.", "link_id"),
    "passport_details": _read("@passport_details", "all_groups old_data", "Full stored passport, staff, family, custom answers, extraction, review and job details by submission_id. No job redelivery or files."),
    "passport_client_details": _read("passport_routes.client_details.get_passport_client_details", "all_groups", "Canonical stored client/staff fields, labels, choices and answer values by submission_id."),
    "passport_view": _read("passport_routes.queries.list_passports_by_group_view", "all_groups old_data", "Canonical full passport page, duplicate metadata and group expiry_alerts; use data_path=['expiry_alerts'] for alerts.", "group_id"),
    "passport_image_metadata": _read("@passport_image_metadata", "all_groups", "Stored image version, crop and source metadata; no image transfers, access URLs or library insertion."),
    "passport_crop_metadata": _read("passport_routes.images.get_passport_image_crop", "all_groups", "Existing crop coordinates, dimensions and revision by submission_id/image_type, without image access."),
    "passport_ai_image_library": _read("passport_routes.visa_ai_library.list_visa_ai_image_library", "all_groups", "Stored AI image library metadata and prompts, without files."),
    "passport_active_ai_image_job": _read("@passport_active_ai_image_job", "all_groups", "Stored current AI image job; no creation, polling workflow refresh or retries."),
    "passport_ai_image_job": _read("@passport_ai_image_job", "all_groups", "Stored AI image job by submission_id and job_id; no recovery or dispatch."),
    "passport_export_fields": _read("passport_routes.excel_exports.get_passport_group_export_fields", "all_groups", "Existing field definitions and display labels only; no spreadsheet creation.", "group_id"),
    "document_groups": _read("document_distribution_groups_read.list_document_groups", "documents all_groups", "Document workspace groups with passenger and assignment counts."),
    "document_review": _read("@document_review", "documents all_groups operations_inbox", "Canonical document assignments, missing documents, matching evidence, rejected files and stored delivery summaries; no signed file links.", "group_id"),
    "document_delivery_summary": _read("document_distribution_delivery.get_document_delivery_tracking", "documents all_groups whatsapp", "Canonical tracking counts and latest rows. Use list_delivery_records for the complete attempt history.", "group_id"),
    "document_delivery_eligibility": _read("@document_delivery_eligibility", "documents all_groups whatsapp", "Current document destination, saved assignments, delivery eligibility and reasons; no intent token, sends or workflow preparation.", "group_id"),
    "document_rename_batch": _read("document_rename.get_rename_batch", "documents", "Full retained rename-item metadata and extracted fields by batch_id; no downloads."),
    "ecr_batch": _read("ecr_checker.get_ecr_batch", "all_groups", "Full stored ECR item results by batch_id; no processing or export."),
    "whatsapp_tracking": _read("whatsapp_recipient_roster.get_broadcast_recipient_roster", "whatsapp all_groups", "Canonical recipient tracking, imported fields, message statuses, rejected/replaced entries and unidentified passport uploads. group_id here means broadcast ID."),
    "whatsapp_broadcast_details": _read("whatsapp_groups_read.get_broadcast_group", "whatsapp all_groups", "Broadcast settings, contacts, source links and stored tracking states. group_id here means broadcast ID."),
    "whatsapp_broadcast_stored": _read("@whatsapp_broadcast_stored", "whatsapp all_groups old_data", "Every stored broadcast field, organizing company, opt-in/archive times, all imported headings including empty columns, and counts of related records. group_id means broadcast ID."),
    "whatsapp_broadcast_records": _read("@whatsapp_broadcast_records", "whatsapp all_groups old_data", "Every stored field of recipients, rejected spreadsheet rows, source contacts, support contacts, group links or phone overrides. Preserves imported field names/values, merged contacts, removed rows and import provenance. Native offset/limit and exact imported_field/imported_value filters; group_id means broadcast ID."),
    "whatsapp_source_groups": _read("whatsapp_source_groups.list_source_groups", "whatsapp all_groups", "All currently eligible source groups and traveller counts."),
    "whatsapp_source_contacts": _read("whatsapp_source_groups.get_broadcast_source_contacts", "whatsapp all_groups", "Canonical source travellers and matching overrides; group_id here means broadcast ID."),
    "whatsapp_source_preview": _read("whatsapp_source_groups.preview_source_group", "whatsapp all_groups", "Existing source roster observation; no broadcast or audience is prepared.", "group_id"),
    "whatsapp_batch_summary": _read("whatsapp_batch_status.get_broadcast_batch_summary", "whatsapp", "Stored batch counts by batch_id; provider acceptance, sent, delivered and read remain separate."),
    "whatsapp_batch_details": _read("whatsapp_batch_status.get_broadcast_batch_status", "whatsapp", "Full stored broadcast attempt result by batch_id; no refresh or retry."),
    "whatsapp_activity": _read("whatsapp_activity.get_whatsapp_activity_summary", "whatsapp documents all_groups tour_ops", "Stored activity summary for kind and batch_id."),
    "whatsapp_activity_failures": _read("whatsapp_activity.get_whatsapp_activity_failures", "whatsapp documents all_groups tour_ops", "Stored failure details for kind and batch_id; no retry."),
    "document_activity_deliveries": _read("whatsapp_activity.get_document_activity_deliveries", "whatsapp documents all_groups", "Document activity delivery rows with native status_filter, q, offset and limit."),
    "delivery_record": _read("@delivery_record", "whatsapp documents tour_ops all_groups old_data", "Full saved attempt fields, message/template content and error detail for document, qr, broadcast or welcome by record_id; no file capabilities or credentials."),
    "delivery_receipts": _read("@delivery_receipts", "whatsapp documents tour_ops all_groups old_data", "Retained verified provider receipt events and binding metadata for document, qr, broadcast or welcome by record_id; native offset/limit, no polling or receipt application."),
    "rooming_workspace": _read("rooming.get_rooming_workspace", "rooming_lists all_groups", "Full hotels, rooms, occupants, unallocated passengers, remarks, preferences and allocation diagnostics.", "group_id"),
    "rooming_priority_fields": _read("rooming.get_rooming_priority_fields", "rooming_lists all_groups", "Canonical field catalog and rooming rules.", "group_id"),
    "rooming_field_values": _read("rooming.get_rooming_roster_field_values", "rooming_lists all_groups", "Resolve the complete values of one rooming grouping field.", "group_id"),
    "hotel_checkins": _read("rooming.get_hotel_checkins", "rooming_lists all_groups", "Stored check-ins and assigned room details by hotel_id; no physical check-in."),
    "menu_workspace": _read("menu.get_menu_workspace", "menu", "Complete categories, dishes and saved meal plans; omitted agency_id context selects the canonical platform library."),
    "tour_groups": _read("tour_operations_assignments.list_tour_operation_groups", "tour_ops coordinators all_groups old_data", "Group assignments, trip dates, coordinator and passenger context."),
    "tour_passengers": _read("tour_operations_assignments.list_group_passengers", "tour_ops coordinators all_groups", "Full operational-passenger details and assignments.", "group_id"),
    "tour_architecture": _read("tour_operations_accounts.get_tour_operations_architecture", "tour_ops coordinators", "Canonical account, assignment and attendance architecture metadata."),
    "group_qr_metadata": _read("@group_qr_metadata", "tour_ops all_groups", "Existing passenger QR status, version and timestamps. Missing QR codes remain not_generated; none are issued and payloads are withheld.", "group_id"),
    "qr_delivery_eligibility": _read("@qr_delivery_eligibility", "tour_ops whatsapp all_groups", "Existing QR delivery outcomes, eligibility and blocking reasons without recovering stale jobs or issuing QR codes.", "group_id"),
    "welcome_delivery_eligibility": _read("@welcome_delivery_eligibility", "whatsapp all_groups", "Stored original welcome text, destinations, outcomes and eligibility; no intent token, sends or file preparation.", "group_id"),
    "coordinators": _read("tour_operations_accounts.list_coordinators", "coordinators staff all_groups", "Coordinator accounts and their current assignments."),
    "my_tour_groups": _read("tour_operations_assignments.list_my_coordinator_groups", "my_tour coordinators tour_ops all_groups", "The connected account's assigned tours; agency context may be required."),
    "my_tour_passengers": _read("tour_operations_assignments.list_my_group_passengers", "my_tour coordinators tour_ops all_groups", "Canonical passengers on an assigned tour.", "group_id"),
    "my_tour_passenger": _read("tour_operations_assignments.get_my_group_passenger_detail", "my_tour coordinators tour_ops all_groups", "Canonical individual tour passenger details.", "group_id"),
    "my_tour_sessions": _read("tour_operations_attendance_sessions.list_my_attendance_sessions", "my_tour tour_ops all_groups", "Existing assigned-tour attendance sessions.", "group_id"),
    "my_tour_session": _read("tour_operations_attendance_sessions.get_my_attendance_session_details", "my_tour tour_ops all_groups", "Full retained session details by session_id; provide agency context."),
    "attendance_overview": _read("tour_operations_attendance_dashboard.get_group_attendance_overview", "tour_ops all_groups", "Canonical activities, sessions, counts and current attendance details.", "group_id"),
    "attendance_closeout": _read("tour_operations_attendance_closeout.get_managed_attendance_closeout_status", "tour_ops all_groups", "Existing attendance closeout requirements and readiness; no closing or physical events.", "group_id"),
    "gc_group_search": _read("gc_app.search_gc_groups", "gc_app all_groups old_data", "GC App group availability, quotas, configuration and lifecycle filters."),
    "gc_agencies": _read("gc_app.list_gc_agencies", "gc_app manager", "Canonical agency options and GC App counts."),
    "gc_group_access": _read("gc_app.get_gc_group_access", "gc_app all_groups old_data", "Stored GC App access configuration, versions and access windows.", "group_id"),
    "gc_organizations": _read("gc_app.search_client_organizations", "gc_app manager", "Client organization configuration and counts; provide agency context."),
    "gc_client_managers": _read("gc_app.list_client_managers", "gc_app manager all_groups old_data", "Client manager profiles, account status and assigned groups."),
    "gc_client_manager_sessions": _read("gc_app.list_client_manager_sessions", "gc_app manager", "Session status/times by profile_id, without tokens or device credentials."),
    "gc_client_manager_audit": _read("gc_app.list_client_manager_audit", "gc_app manager audit_logs", "Retained client-manager account audit history."),
    "gc_itinerary": _read("gc_app_content.preview_itinerary", "gc_app tour_ops all_groups", "Stored itinerary drafts, entries and publication metadata; no preparation or publication.", "group_id"),
    "gc_common_documents": _read("@gc_common_documents", "gc_app documents all_groups", "Every stored draft or published common document with native offset/limit, metadata and publication flags; no file transfer.", "group_id"),
    "gc_announcements": _read("gc_app_content.page_announcements", "gc_app all_groups", "Full stored announcement text and authored notification metadata, with native offset/limit.", "group_id"),
    "gc_announcement_notifications": _read("gc_app_content.get_announcement_notification_status", "gc_app all_groups", "Stored announcement notification outcome; no provider refresh or push.", "group_id"),
    "gc_group_audit": _read("gc_app_content.list_group_gc_audit", "gc_app audit_logs all_groups", "Stored group GC App audit entries with native offset/limit.", "group_id"),
    "gc_notification_drafts": _read("gc_notifications.list_drafts", "gc_app all_groups", "Existing notification drafts and text; native cursor/limit pagination."),
    "gc_notification_draft": _read("gc_notifications.get_draft", "gc_app all_groups", "Complete saved notification draft by draft_id; no changes or sends."),
    "gc_notification_batches": _read("gc_notifications.list_batches", "gc_app all_groups", "Stored notification batches and outcome counts; native cursor/limit pagination."),
    "gc_notification_batch": _read("gc_notifications.get_batch", "gc_app all_groups", "Stored notification batch and delivery details by batch_id."),
    "gc_notification_batch_by_request": _read("gc_notifications.get_batch_by_request", "gc_app all_groups", "Stored notification outcome by the original client request ID; no execution or retry."),
    "managers": _read("admin.list_managers", "manager staff all_groups old_data", "Manager profile, account status and created/assigned groups; native skip/limit."),
    "managed_accounts": _read("admin_accounts.list_managed_accounts", "manager staff", "Canonical managed-account metadata, without activation or credential values."),
    "staff_accounts": _read("admin_accounts.list_staff_accounts", "staff manager", "Canonical staff-account metadata and access status."),
    "staff_access": _read("admin.list_staff_for_access", "staff manager all_groups old_data", "Canonical staff profiles and assigned group access."),
    "admin_groups": _read("admin.list_admin_groups", "manager staff all_groups", "Canonical groups available for existing account access assignment; no assignment changes."),
    "group_broadcast_options": _read("client_groups.list_whatsapp_broadcast_options_for_group", "whatsapp group_links all_groups", "Canonical existing broadcast options for a group's link configuration.", "link_id"),
    "audit_logs": _read("audit_logs.page_audit_logs", "audit_logs", "Canonical audit ledger and filters; native signed cursor/page_size pagination."),
    "platform_settings": _read("admin.get_platform_settings", "settings", "Stored platform business settings and their effective defaults."),
    "whatsapp_templates": _read("admin_whatsapp_templates.get_whatsapp_template_settings", "settings whatsapp", "Effective template names, language, contract descriptions and override metadata; no credentials."),
    "email_connections": _read("email_integration_connections.list_email_connections", "operations_inbox", "The connected account's saved email connection readiness; no provider access, sync or tokens."),
    "email_activity": _read("@email_activity", "operations_inbox all_groups documents", "All stored personally owned email activity and artifact counts, with native offset/limit; no mailbox sync or retrieval."),
    "email_ai_rollout": _read("@email_ai_rollout", "operations_inbox settings", "Every visible staged email-AI rollout target, policy and effective flag. Native offset/limit bypasses the website's latest-200 preview; personally owned connection scope is preserved."),
    "email_operations_inbox": _read("email_ai_inbox.email_operations_inbox", "operations_inbox all_groups", "Stored operations inbox analysis, priorities and linked group context; native cursor/limit."),
    "email_message": _read("email_integration_activity.email_message_detail", "operations_inbox all_groups documents", "Existing personally owned email message, attachment metadata and activity; no provider fetch."),
    "email_message_intelligence": _read("email_ai_inbox.email_message_intelligence", "operations_inbox all_groups documents", "Stored personally owned email analysis, proposed actions, deadlines, candidates and draft text; no analysis or workflow execution."),
    "email_reviews": _read("@email_reviews", "operations_inbox all_groups documents", "Every personally owned review item with native offset/limit; reading never approves, retrieves or distributes attachments."),
    "email_review_options": _read("@email_review_options", "operations_inbox all_groups documents", "Stored visible review/group options and every eligible passenger with native offset/limit; no retrieval or processing.", "group_id"),
    "personal_notifications": _read("notifications.notification_feed", "dashboard", "The connected account's existing notification feed; native cursor/limit. Reading does not mark a notification read."),
    "global_search": _read("search.global_search", "dashboard all_groups group_links old_data", "Canonical name/identifier search across authorized dashboard groups and passports; capped search results are explicitly partial."),
}

DASHBOARD_SECTIONS = frozenset(section for definition in DASHBOARD_READS.values() for section in definition.sections)
