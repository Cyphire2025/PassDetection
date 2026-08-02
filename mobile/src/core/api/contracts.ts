import { z } from 'zod';

const Uuid = z.string().uuid();
const IsoDateTime = z.string().datetime({ offset: true });

export const MobileDeviceSchema = z
  .object({
    installation_id: z.string().min(16).max(128),
    platform: z.enum(['android', 'ios']),
    app_version: z.string().min(1).max(40),
    device_name: z.string().max(120).nullable().optional(),
  })
  .strict();

export type MobileDeviceInput = z.infer<typeof MobileDeviceSchema>;

export const PrincipalSchema = z
  .object({
    id: Uuid,
    principal_type: z.enum(['passenger', 'client_manager', 'coordinator']),
    agency_id: Uuid,
    display_name: z.string().min(1).max(255),
    email: z.string().email().max(320).nullable().optional().default(null),
    phone_number: z.string().min(3).max(32).nullable().optional().default(null),
    force_password_change: z.boolean().default(false),
  })
  .strict();

export const TokenResponseSchema = z
  .object({
    access_token: z.string().min(32),
    refresh_token: z.string().min(32),
    token_type: z.literal('bearer'),
    access_token_expires_at: IsoDateTime,
    refresh_token_expires_at: IsoDateTime,
    session_id: Uuid,
    principal: PrincipalSchema,
  })
  .strict();

export type TokenResponse = z.infer<typeof TokenResponseSchema>;

export const OtpRequestResponseSchema = z
  .object({
    accepted: z.literal(true),
    challenge_id: Uuid,
    expires_in_seconds: z.number().int().positive().max(3600),
    resend_after_seconds: z.number().int().nonnegative().max(3600),
  })
  .strict();

export const TripClaimSchema = z
  .object({
    claim_id: Uuid,
    group_id: Uuid,
    group_name: z.string().min(1).max(255),
    destination: z.string().max(255).nullable(),
    travel_date: z.string().date().nullable(),
    return_date: z.string().date().nullable(),
    requires_secondary_verification: z.boolean(),
  })
  .strict();

export const OtpVerifyResponseSchema = z
  .object({
    status: z.enum([
      'claim_selection_required',
      'secondary_verification_required',
      'authenticated',
    ]),
    claims: z.array(TripClaimSchema).max(50),
    tokens: TokenResponseSchema.nullable(),
  })
  .strict();

export const TripSummarySchema = z
  .object({
    id: Uuid,
    name: z.string().min(1).max(255),
    destination: z.string().max(255).nullable(),
    travel_date: z.string().date().nullable(),
    return_date: z.string().date().nullable(),
    role: z.enum(['passenger', 'client_manager', 'coordinator']),
    access_generation: z.number().int().nonnegative(),
    itinerary_version: z.number().int().nonnegative(),
    common_document_version: z.number().int().nonnegative(),
    announcement_version: z.number().int().nonnegative(),
  })
  .strict();

export const TripListSchema = z
  .object({
    items: z.array(TripSummarySchema).max(100),
    next_cursor: z.string().max(256).nullable(),
  })
  .strict();

export const SyncChangeSchema = z
  .object({
    sequence: z.number().int().nonnegative(),
    group_id: Uuid,
    entity_type: z.string().min(1).max(80),
    entity_id: Uuid.nullable(),
    operation: z.enum(['upsert', 'delete', 'revoke']),
    version: z.number().int().nonnegative(),
    occurred_at: IsoDateTime,
    payload: z.unknown().optional(),
  })
  .strict();

export const SyncPageSchema = z
  .object({
    changes: z.array(SyncChangeSchema).max(500),
    next_cursor: z.number().int().nonnegative(),
    has_more: z.boolean(),
  })
  .strict();

export const SyncAckResponseSchema = z
  .object({
    trip_id: Uuid,
    cursor: z.number().int().nonnegative(),
    access_generation: z.number().int().nonnegative(),
    acknowledged_at: IsoDateTime,
  })
  .strict();

export const ManifestSchema = z
  .object({
    trip: TripSummarySchema,
    sync_cursor: z.number().int().nonnegative(),
    server_time: IsoDateTime,
    access_expires_at: IsoDateTime.nullable(),
    versions: z.object({
      manifest: z.number().int().nonnegative(),
      itinerary: z.number().int().nonnegative(),
      common_documents: z.number().int().nonnegative(),
      personal_documents: z.number().int().nonnegative(),
      announcements: z.number().int().nonnegative(),
      rooming: z.number().int().nonnegative(),
      meals: z.number().int().nonnegative(),
      qr: z.number().int().nonnegative(),
      readiness: z.number().int().nonnegative(),
      roster: z.number().int().nonnegative(),
    }).strict(),
    resources: z.object({
      itinerary: z.string().startsWith('/api/v1/mobile/').max(500),
      announcements: z.string().startsWith('/api/v1/mobile/').max(500),
      common_documents: z.string().startsWith('/api/v1/mobile/').max(500),
      personal_documents: z.string().startsWith('/api/v1/mobile/').max(500),
      room: z.string().startsWith('/api/v1/mobile/').max(500),
      meals: z.string().startsWith('/api/v1/mobile/').max(500),
      qr: z.string().startsWith('/api/v1/mobile/').max(500),
      sync_changes: z.string().startsWith('/api/v1/mobile/').max(500),
    }).strict(),
  })
  .strict();

export const ApiErrorBodySchema = z
  .object({
    detail: z.union([
      z.string().max(500),
      z.object({ code: z.string().max(100), message: z.string().max(500) }).passthrough(),
    ]),
  })
  .passthrough();

export const DocumentDownloadAuthorizationSchema = z
  .object({
    document_id: Uuid,
    version: z.number().int().positive(),
    content_path: z
      .string()
      .min(1)
      .max(1_024)
      .regex(/^\/(?!\/)[^\\\s#]+$/, 'Expected a safe root-relative content path.'),
    download_token: z.string().min(32).max(4_096).regex(/^[A-Za-z0-9._~-]+$/),
    expires_at: IsoDateTime,
  })
  .strict();
