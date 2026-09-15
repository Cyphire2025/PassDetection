import type { NotificationBatch, NotificationDraft, NotificationPreview } from "./notification-types";
import type { GcAppGroupControl } from "../types";

export const agencyId = "10000000-0000-4000-8000-000000000001";
export const actorId = "20000000-0000-4000-8000-000000000001";
export const groupId = "30000000-0000-4000-8000-000000000001";
export const group: GcAppGroupControl = {
  id: groupId, name: "Synthetic Hill Trip", lifecycle: "closed", destination: "Hills", start_date: null, end_date: null,
  company: { id: "company-1", name: "Synthetic Company" }, gc_app_enabled: true, my_photos_enabled: false,
  passenger_access_enabled: true, client_manager_access_enabled: true, coordinator_access_enabled: true,
  access_starts_at: null, access_expires_at: null, access_revoked_at: null, revision: 1, organization_id: "company-1",
  active_mobile_users: 12, synced_device_count: 8, last_successful_sync_at: null, app_availability: "active",
  versions: { itinerary_version: 1, common_document_version: 1, announcement_version: 1 },
};
export const draft: NotificationDraft = {
  id: "40000000-0000-4000-8000-000000000001", title: "Lobby meeting", body: "Meet in the lobby at 8 AM.",
  audience: "selected_groups", group_ids: [groupId], group_names: ["Synthetic Hill Trip"], revision: 1,
  status: "draft", last_sent_at: null, created_at: "2026-09-15T10:00:00Z", updated_at: "2026-09-15T10:00:00Z",
};
export const preview = (): NotificationPreview => ({
  draft_revision: 1, preview_token: "synthetic-preview-token", expires_at: new Date(Date.now() + 600_000).toISOString(),
  group_count: 1, group_ids: [groupId], group_names: ["Synthetic Hill Trip"], recipient_count: 12,
  role_counts: { passengers: 10, client_managers: 1, coordinators: 1 }, eligible_device_count: 8,
  no_active_registration_count: 4, provider_enabled: true, android_provider_enabled: true,
  ios_provider_enabled: false, delivery_window_hours: 24,
});
export const batch: NotificationBatch = {
  id: "50000000-0000-4000-8000-000000000001", notification_id: draft.id,
  request_id: "60000000-0000-4000-8000-000000000001", draft_revision: 1,
  title: draft.title, body: draft.body, audience: draft.audience, group_ids: draft.group_ids,
  group_names: ["Synthetic Hill Trip"], role_counts: { passengers: 10, client_managers: 1, coordinators: 1 },
  created_at: "2026-09-15T10:05:00Z", expires_at: "2026-09-16T10:05:00Z", provider_enabled: true,
  recipient_counts: { total: 12, queued: 9, sent: 2, failed: 0, cancelled: 0, unknown: 1, read: 1, no_active_registration: 4 },
  device_delivery_counts: { total: 8, submitting: 2, retry: 0, receipt_pending: 0, provider_accepted: 2, delivered: 0, failed: 0, cancelled: 0, unknown: 1 },
};
