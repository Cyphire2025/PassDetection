export type NotificationAudience = "all_active_trips" | "selected_groups";

export interface NotificationDraftInput {
  title: string;
  body: string;
  audience: NotificationAudience;
  group_ids: string[];
}

export const NOTIFICATION_TITLE_LIMIT = 100;
export const NOTIFICATION_BODY_LIMIT = 240;

export interface NotificationDraft extends NotificationDraftInput {
  id: string;
  revision: number;
  status: "draft" | "sent";
  group_names?: string[];
  last_sent_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotificationPage<T> {
  items: T[];
  next_cursor: string | null;
}

export interface NotificationRoleCounts {
  passengers: number;
  client_managers: number;
  coordinators: number;
}

export interface NotificationPreview {
  draft_revision: number;
  preview_token: string;
  expires_at: string;
  group_count: number;
  group_ids: string[];
  group_names: string[];
  recipient_count: number;
  role_counts: NotificationRoleCounts;
  eligible_device_count: number;
  no_active_registration_count: number;
  provider_enabled: boolean;
  android_provider_enabled: boolean;
  ios_provider_enabled: boolean;
  delivery_window_hours: number;
}

export interface NotificationSendInput {
  expected_revision: number;
  preview_token: string;
  request_id: string;
}

export interface NotificationBatch extends NotificationDraftInput {
  id: string;
  notification_id: string;
  request_id: string;
  draft_revision: number;
  group_names: string[];
  role_counts: NotificationRoleCounts;
  created_at: string;
  expires_at: string;
  provider_enabled: boolean;
  recipient_counts: Record<"total" | "queued" | "sent" | "failed" | "cancelled" | "unknown" | "read" | "no_active_registration", number>;
  device_delivery_counts: Record<"total" | "submitting" | "retry" | "receipt_pending" | "provider_accepted" | "delivered" | "failed" | "cancelled" | "unknown", number>;
}
