import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  NotificationFeedParams,
  NotificationFeedResponse,
  OperationalNotification,
} from "../types";

export const notificationsApi = {
  feed: async ({
    unreadOnly = false,
    priority,
    limit = 12,
    cursor,
  }: NotificationFeedParams = {}): Promise<NotificationFeedResponse> => {
    const { data } = await apiClient.get<NotificationFeedResponse>(
      API_ENDPOINTS.notifications.feed,
      {
        params: {
          unread_only: unreadOnly || undefined,
          priority,
          limit,
          cursor,
        },
      },
    );
    return data;
  },

  markRead: async (notificationId: string): Promise<OperationalNotification> => {
    const { data } = await apiClient.post<OperationalNotification>(
      API_ENDPOINTS.notifications.read(notificationId),
    );
    return data;
  },

  markAllRead: async (): Promise<void> => {
    await apiClient.post(API_ENDPOINTS.notifications.readAll);
  },
};
