import { z } from 'zod';

import {
  DEFAULT_TRIP_TIME_ZONE,
  IanaTimeZoneSchema,
} from '@/core/localization/time-zone';

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

export const MobileIntegrityChallengeResponseSchema = z
  .object({
    status: z.enum(['disabled', 'issued']),
    mode: z.enum(['disabled', 'monitor', 'enforce']),
    required: z.boolean(),
    provider: z.enum(['play_integrity', 'app_attest']),
    challenge_id: Uuid.nullable(),
    provider_request_hash: z
      .string()
      .regex(/^[A-Za-z0-9_-]{43}$/)
      .nullable(),
    expires_at: IsoDateTime.nullable(),
  })
  .strict()
  .superRefine((value, context) => {
    const issued = value.status === 'issued';
    if (
      issued !== (value.challenge_id !== null)
      || issued !== (value.provider_request_hash !== null)
      || issued !== (value.expires_at !== null)
    ) {
      context.addIssue({
        code: 'custom',
        message: 'Integrity challenge fields did not match the server policy state.',
      });
    }
  });

export const MobileAppAttestRegistrationResponseSchema = z
  .object({ registered: z.literal(true) })
  .strict();

export const PrincipalSchema = z
  .object({
    id: Uuid,
    account_id: Uuid,
    principal_type: z.enum(['passenger', 'client_manager', 'coordinator']),
    agency_id: Uuid,
    // Optional during a rolling backend/mobile deployment; passenger resource
    // access still fails closed until the authoritative record ID is present.
    passenger_id: Uuid.nullable().optional(),
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
    offline_authorization_lease: z
      .string()
      .min(256)
      .max(4_096)
      .regex(/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/),
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
    // Missing is accepted only for a rolling deployment against the previous
    // backend contract. An explicitly invalid timezone always rejects.
    timezone: IanaTimeZoneSchema.optional().default(DEFAULT_TRIP_TIME_ZONE),
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
    timezone: IanaTimeZoneSchema.optional().default(DEFAULT_TRIP_TIME_ZONE),
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

export const MobileResourceVersionsSchema = z
  .object({
    manifest: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    itinerary: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    common_documents: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    personal_documents: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    announcements: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    rooming: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    meals: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    qr: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    readiness: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    roster: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
  })
  .strict();

export const ManifestSchema = z
  .object({
    trip: TripSummarySchema,
    sync_cursor: z.number().int().nonnegative(),
    server_time: IsoDateTime,
    access_expires_at: IsoDateTime.nullable(),
    versions: MobileResourceVersionsSchema,
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

const SnapshotResourcePathSchema = z
  .string()
  .startsWith('/api/v1/mobile/')
  .max(500);

export const SyncSnapshotSchema = z
  .object({
    strategy: z.literal('full_rebase'),
    trip: TripSummarySchema,
    baseline_cursor: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    access_generation: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    server_time: IsoDateTime,
    access_expires_at: IsoDateTime.nullable(),
    versions: MobileResourceVersionsSchema,
    resources: z
      .object({
        manifest: SnapshotResourcePathSchema,
        itinerary: SnapshotResourcePathSchema,
        announcements: SnapshotResourcePathSchema,
        common_documents: SnapshotResourcePathSchema,
        personal_documents: SnapshotResourcePathSchema.nullable(),
        room: SnapshotResourcePathSchema.nullable(),
        meals: SnapshotResourcePathSchema.nullable(),
        qr: SnapshotResourcePathSchema.nullable(),
        readiness: SnapshotResourcePathSchema.nullable(),
        roster: SnapshotResourcePathSchema.nullable(),
        attendance_sessions: SnapshotResourcePathSchema.nullable(),
        sync_changes: SnapshotResourcePathSchema,
        acknowledge: SnapshotResourcePathSchema,
      })
      .strict(),
    resource_counts: z
      .object({
        announcements: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
        common_documents: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
        personal_documents: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER).nullable(),
        roster: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER).nullable(),
        attendance_sessions: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER).nullable(),
      })
      .strict(),
    max_incremental_changes: z
      .number()
      .int()
      .positive()
      .max(Number.MAX_SAFE_INTEGER),
    max_group_passengers: z
      .number()
      .int()
      .positive()
      .max(Number.MAX_SAFE_INTEGER),
    max_attendance_sessions_per_group: z
      .number()
      .int()
      .positive()
      .max(Number.MAX_SAFE_INTEGER),
  })
  .strict();

export type MobileResourceVersions = z.infer<typeof MobileResourceVersionsSchema>;
export type SyncSnapshot = z.infer<typeof SyncSnapshotSchema>;

const ApiErrorDescriptorSchema = z
  .object({
    code: z.string().min(1).max(100),
    message: z.string().min(1).max(500),
  })
  .strict();

/**
 * The backend domain-error envelope and FastAPI's detail envelope are separate,
 * explicit wire contracts. Keeping each descriptor strict prevents an error
 * response from becoming an unbounded carrier for provider or debug metadata.
 */
export const ApiErrorBodySchema = z.union([
  z.object({ error: ApiErrorDescriptorSchema }).strict(),
  z.object({
    detail: z.union([z.string().min(1).max(500), ApiErrorDescriptorSchema]),
  }).strict(),
]);

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
    size_bytes: z.number().int().positive().max(25 * 1024 * 1024),
    checksum_sha256: z.string().regex(/^[0-9a-f]{64}$/i),
    content_type: z.enum([
      'application/pdf',
      'image/jpeg',
      'image/png',
      'image/webp',
    ]),
  })
  .strict();
