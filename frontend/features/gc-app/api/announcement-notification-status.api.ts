import apiClient from "@/lib/api/client";

export interface AnnouncementNotificationStatus {
  announcement_id: string;
  provider_enabled: boolean;
  recipient_counts: Record<"total" | "queued" | "sent" | "failed" | "cancelled" | "read" | "no_active_registration", number>;
  device_delivery_counts: Record<"total" | "submitting" | "retry" | "receipt_pending" | "delivered" | "failed" | "cancelled", number>;
  failures: Array<{ scope: "recipient" | "device"; code: string; count: number }>;
  checked_at: string;
}

export async function getAnnouncementNotificationStatus(
  agencyId: string | null, groupId: string, announcementId: string, signal?: AbortSignal,
): Promise<AnnouncementNotificationStatus> {
  const response = await apiClient.get<AnnouncementNotificationStatus>(
    `/api/v1/gc-app/admin/groups/${encodeURIComponent(groupId)}/announcements/${encodeURIComponent(announcementId)}/notification-status`,
    { params: agencyId ? { agency_id: agencyId } : undefined, signal },
  );
  return response.data;
}
