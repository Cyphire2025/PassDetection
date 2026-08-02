import { z } from 'zod';

const Uuid = z.string().uuid();
const IsoDateTime = z.string().datetime({ offset: true });

export const ItineraryItemSchema = z
  .object({
    id: Uuid,
    title: z.string().min(1).max(255),
    description: z.string().max(4_000).nullable(),
    starts_at: IsoDateTime.nullable(),
    ends_at: IsoDateTime.nullable(),
    location_name: z.string().max(255).nullable(),
    latitude: z.number().min(-90).max(90).nullable(),
    longitude: z.number().min(-180).max(180).nullable(),
    sort_order: z.number().int().nonnegative(),
  })
  .strict();

export const ItineraryDaySchema = z
  .object({
    id: Uuid,
    day_number: z.number().int().min(1).max(365),
    date: z.string().date().nullable(),
    title: z.string().max(255).nullable(),
    sort_order: z.number().int().nonnegative(),
    items: z.array(ItineraryItemSchema).max(250),
  })
  .strict();

export const ItinerarySchema = z
  .object({
    trip_id: Uuid,
    version: z.number().int().positive(),
    title: z.string().min(1).max(255),
    published_at: IsoDateTime,
    days: z.array(ItineraryDaySchema).max(365),
  })
  .strict();

export type Itinerary = z.infer<typeof ItinerarySchema>;

export const AnnouncementSchema = z
  .object({
    id: Uuid,
    trip_id: Uuid,
    version: z.number().int().positive(),
    title: z.string().min(1).max(255),
    message: z.string().min(1).max(10_000),
    priority: z.enum(['normal', 'important', 'emergency']),
    published_at: IsoDateTime,
    available_until: IsoDateTime.nullable(),
    is_read: z.boolean().default(false),
  })
  .strict();

export const AnnouncementListSchema = z
  .object({
    items: z.array(AnnouncementSchema).max(200),
    next_cursor: z.string().max(256).nullable(),
  })
  .strict();

export type Announcement = z.infer<typeof AnnouncementSchema>;

export const DocumentMetadataSchema = z
  .object({
    id: Uuid,
    trip_id: Uuid,
    passenger_id: Uuid.nullable(),
    scope: z.enum(['personal', 'common', 'coordinator']),
    category: z.string().min(1).max(80),
    display_name: z.string().min(1).max(255),
    content_type: z.enum([
      'application/pdf',
      'image/jpeg',
      'image/png',
      'image/webp',
      'application/octet-stream',
    ]),
    size_bytes: z.number().int().positive().max(25 * 1024 * 1024).nullable(),
    version: z.number().int().positive(),
    checksum_sha256: z.string().regex(/^[0-9a-f]{64}$/i).nullable(),
    offline_available: z.boolean(),
    metadata_state: z.enum(['ready', 'pending']),
    updated_at: IsoDateTime,
    revoked_at: IsoDateTime.nullable(),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.metadata_state === 'ready' && (!value.size_bytes || !value.checksum_sha256)) {
      context.addIssue({
        code: 'custom',
        message: 'Ready document metadata requires a verified size and checksum.',
      });
    }
    if (value.metadata_state === 'pending' && value.offline_available) {
      context.addIssue({
        code: 'custom',
        message: 'Pending document metadata cannot be available offline.',
      });
    }
  });

export const DocumentListSchema = z
  .object({
    items: z.array(DocumentMetadataSchema).max(200),
    next_cursor: z.string().max(256).nullable(),
  })
  .strict();

export type DocumentMetadata = z.infer<typeof DocumentMetadataSchema>;

export const CommonDocumentSchema = z.object({
  id: Uuid,
  logical_document_id: Uuid,
  trip_id: Uuid,
  category: z.string().min(1).max(80),
  title: z.string().min(1).max(255),
  description: z.string().max(2_000).nullable(),
  media_type: z.enum(['application/pdf', 'image/jpeg', 'image/png', 'image/webp', 'application/octet-stream']),
  byte_size: z.number().int().positive().max(25 * 1024 * 1024),
  checksum_sha256: z.string().regex(/^[0-9a-f]{64}$/i),
  version: z.number().int().positive(),
  offline_available: z.boolean(),
  published_at: IsoDateTime,
  updated_at: IsoDateTime,
}).strict();

export const CommonDocumentListSchema = z.object({
  items: z.array(CommonDocumentSchema).max(200),
  next_cursor: z.string().max(256).nullable(),
}).strict();

export const PersonalQrSchema = z
  .object({
    id: Uuid,
    trip_id: Uuid,
    passenger_id: Uuid,
    signed_payload: z.string().min(16).max(4096),
    version: z.number().int().positive(),
    valid_from: IsoDateTime.nullable(),
    valid_until: IsoDateTime.nullable(),
    offline_allowed: z.boolean(),
    updated_at: IsoDateTime,
  })
  .strict();

export const RoomSchema = z
  .object({
    id: Uuid,
    trip_id: Uuid,
    passenger_id: Uuid.nullable(),
    hotel_name: z.string().max(255).nullable(),
    room_number: z.string().max(80).nullable(),
    roommate_summary: z.string().max(500).nullable(),
    version: z.number().int().nonnegative(),
    updated_at: IsoDateTime,
  })
  .strict();

export const MealSchema = z
  .object({
    id: Uuid,
    trip_id: Uuid,
    passenger_id: Uuid.nullable(),
    preference: z.string().max(255).nullable(),
    notes: z.string().max(1000).nullable(),
    version: z.number().int().nonnegative(),
    updated_at: IsoDateTime,
  })
  .strict();

export const ReadinessSchema = z
  .object({
    trip_id: Uuid,
    passenger_count: z.number().int().nonnegative(),
    passports_complete: z.number().int().nonnegative(),
    visas_available: z.number().int().nonnegative(),
    tickets_available: z.number().int().nonnegative(),
    items_needing_attention: z.number().int().nonnegative(),
    rooms_assigned: z.number().int().nonnegative(),
    meals_confirmed: z.number().int().nonnegative(),
    version: z.number().int().nonnegative(),
    updated_at: IsoDateTime,
  })
  .strict();
