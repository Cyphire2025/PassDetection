export type NotificationPriority =
  | "urgent"
  | "high"
  | "normal"
  | "low";

export interface OperationalNotification {
  id: string;
  type: string;
  title: string;
  message: string;
  entity_type: string | null;
  entity_id: string | null;
  priority: NotificationPriority | string;
  category: string;
  is_read: boolean;
  created_at: string;
  metadata: Record<string, unknown> | null;
}

export interface NotificationFeedResponse {
  items: OperationalNotification[];
  unread_count: number;
  next_cursor: string | null;
}

export interface NotificationFeedParams {
  unreadOnly?: boolean;
  priority?: NotificationPriority;
  limit?: number;
  cursor?: string;
}
