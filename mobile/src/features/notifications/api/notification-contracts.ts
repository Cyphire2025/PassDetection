import { z } from 'zod';

const Uuid = z.string().uuid();
const IsoDateTime = z.string().datetime({ offset: true });

export const MobileNotificationSchema = z.object({
  id: Uuid,
  trip_id: Uuid.nullable(),
  notification_type: z.string().min(1).max(80),
  category: z.string().min(1).max(80),
  priority: z.enum(['normal', 'important', 'emergency']),
  title: z.string().min(1).max(255),
  body: z.string().min(1).max(10_000),
  deep_link_path: z.string().startsWith('/').max(500).nullable(),
  payload: z.record(z.string(), z.unknown()),
  available_at: IsoDateTime,
  expires_at: IsoDateTime.nullable(),
  read_at: IsoDateTime.nullable(),
}).strict();

export const MobileNotificationPageSchema = z.object({
  items: z.array(MobileNotificationSchema).max(200),
  next_cursor: z.string().max(256).nullable(),
  unread_count: z.number().int().nonnegative(),
}).strict();

export const MobileNotificationReadSchema = z.object({ id: Uuid, read_at: IsoDateTime }).strict();
export type MobileNotification = z.infer<typeof MobileNotificationSchema>;
