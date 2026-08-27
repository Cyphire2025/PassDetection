import { z } from 'zod';

import { MY_PHOTOS_MAX_ITEM_BYTES } from '../limits';

const Uuid = z.string().uuid();
const IsoDateTime = z.string().datetime({ offset: true });
const NullableIsoDateTime = IsoDateTime.nullable();
const BoundedCount = z.number().int().nonnegative().max(1_000_000);
const ShortCode = z.string().min(1).max(64).regex(/^[A-Z0-9_]+$/);
const ConsentCopy = z.string().min(10).max(500);
const Sha256 = z.string().regex(/^[0-9a-f]{64}$/);

export function isSafeMyPhotosResourcePath(value: string): boolean {
  if (
    !value.startsWith('/api/v1/mobile/')
    || value.includes('?')
    || value.includes('#')
    || value.includes('\\')
    || value.includes('//')
    || /[\u0000-\u001f\u007f]/.test(value)
  ) return false;
  for (const segment of value.split('/').slice(1)) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(segment);
    } catch {
      return false;
    }
    if (
      decoded === '.'
      || decoded === '..'
      || decoded.includes('/')
      || decoded.includes('\\')
      || /[\u0000-\u001f\u007f]/.test(decoded)
    ) return false;
  }
  return true;
}

export const MyPhotosExperienceStateSchema = z.enum([
  'feature_unavailable',
  'provider_not_configured',
  'gallery_not_uploaded',
  'gallery_processing',
  'gallery_indexing',
  'consent_required',
  'camera_permission_required',
  'ready_to_scan',
  'scan_running',
  'scan_cancelled',
  'session_expired',
  'liveness_rejected',
  'cooldown',
  'device_unsupported',
  'provider_unavailable',
  'search_queued',
  'searching',
  'no_matches',
  'matches_preparing',
  'matches_ready',
  'offline_results',
  'partial_offline_results',
  'access_expired',
  'access_revoked',
  'recoverable_error',
  'nonrecoverable_error',
  'enrollment_deleted',
]);

export const ChallengeModeSchema = z.enum(['movement_and_light', 'movement_only']);
export const ClientFlowSchema = z.enum(['unavailable', 'development_simulator', 'native']);
export const GalleryStatusSchema = z.enum([
  'not_uploaded', 'awaiting_upload', 'processing', 'indexing', 'ready', 'failed', 'removed',
]);
export const EnrollmentStatusSchema = z.enum([
  'consent_required', 'ready', 'session_pending', 'processing', 'enrolled',
  'rejected', 'cooldown', 'revoked', 'deleted',
]);
export const SearchStatusSchema = z.enum(['queued', 'searching', 'complete', 'failed', 'cancelled']);
export const MatchFilterSchema = z.enum(['best', 'possible', 'all']);
export const MatchTierSchema = z.enum(['best', 'possible']);
export const MatchFeedbackSchema = z.enum(['none', 'this_is_me', 'not_me']);
export const DownloadQualitySchema = z.enum(['original', 'optimized']);
export const MediaAvailabilitySchema = z.enum([
  'registered', 'awaiting_upload', 'processing', 'indexed', 'preview_available',
  'original_available_online', 'archived_offline', 'rehydration_requested',
  'preparing_delivery', 'delivery_available', 'expired', 'failed', 'removed',
]);

export const MediaVariantDescriptorSchema = z.object({
  state: MediaAvailabilitySchema,
  transport: z.enum([
    'unavailable', 'development_fixture', 'authenticated_api', 'direct_object_storage',
  ]),
  cache_key: z.string().min(8).max(192).regex(/^[A-Za-z0-9._:-]+$/),
  max_width: z.number().int().min(1).max(4_096),
  max_height: z.number().int().min(1).max(4_096),
  resource_path: z.string()
    .min(1)
    .max(512)
    .refine(isSafeMyPhotosResourcePath, 'Unsafe media resource path.')
    .nullable(),
  authorization_id: Uuid.nullable(),
  expires_at: NullableIsoDateTime,
}).strict().superRefine((value, context) => {
  if (value.transport === 'unavailable' && (value.resource_path || value.authorization_id)) {
    context.addIssue({ code: 'custom', message: 'Unavailable media cannot expose delivery data.' });
  }
  if (value.transport === 'development_fixture' && (value.resource_path || value.authorization_id)) {
    context.addIssue({ code: 'custom', message: 'Development fixture media must remain local.' });
  }
  if (value.transport === 'authenticated_api' && !value.resource_path) {
    context.addIssue({ code: 'custom', message: 'Authenticated media requires a relative API resource.' });
  }
  if (value.transport === 'direct_object_storage' && !value.authorization_id) {
    context.addIssue({ code: 'custom', message: 'Direct delivery requires an opaque authorization.' });
  }
  if (value.transport === 'direct_object_storage' && value.resource_path) {
    context.addIssue({ code: 'custom', message: 'Direct delivery must be resolved by its native adapter.' });
  }
});

export const MyPhotosSearchSchema = z.object({
  id: Uuid,
  status: SearchStatusSchema,
  processed_face_count: BoundedCount,
  total_face_count: BoundedCount,
  progress_percent: z.number().int().min(0).max(100),
  matched_photo_count: BoundedCount,
  best_match_count: BoundedCount,
  possible_match_count: BoundedCount,
  started_at: NullableIsoDateTime,
  completed_at: NullableIsoDateTime,
  error_code: ShortCode.nullable(),
}).strict().superRefine((value, context) => {
  if (value.processed_face_count > value.total_face_count) {
    context.addIssue({ code: 'custom', message: 'Search progress exceeds the indexed face count.' });
  }
  if (value.best_match_count + value.possible_match_count !== value.matched_photo_count) {
    context.addIssue({ code: 'custom', message: 'Match tier counts must equal the matched-photo count.' });
  }
});

export const MyPhotosSummarySchema = z.object({
  group_id: Uuid,
  group_name: z.string().min(1).max(255),
  experience_state: MyPhotosExperienceStateSchema,
  server_time: IsoDateTime,
  capability: z.object({
    feature_enabled: z.boolean(),
    provider_ready: z.boolean(),
    provider_state: z.enum(['ready', 'not_configured', 'temporarily_unavailable']),
    client_flow: ClientFlowSchema,
    supported_challenge_modes: z.array(ChallengeModeSchema).max(2),
    retryable: z.boolean(),
  }).strict(),
  gallery: z.object({
    status: GalleryStatusSchema,
    published_revision: z.number().int().nonnegative(),
    media_version: z.number().int().nonnegative(),
    face_index_version: z.number().int().nonnegative(),
    total_asset_count: BoundedCount,
    indexed_asset_count: BoundedCount,
    failed_asset_count: BoundedCount,
    all_group_photos_enabled: z.boolean(),
    published_at: NullableIsoDateTime,
    updated_at: IsoDateTime,
  }).strict(),
  consent: z.object({
    required: z.boolean(),
    required_version: z.string().min(1).max(64),
    accepted_version: z.string().min(1).max(64).nullable(),
    accepted_at: NullableIsoDateTime,
    purpose: ConsentCopy,
    biometric_data_used: ConsentCopy,
    retention: ConsentCopy,
    provider_processing: ConsentCopy,
    deletion: ConsentCopy,
  }).strict(),
  enrollment: z.object({
    status: EnrollmentStatusSchema,
    reference_version: z.number().int().positive().nullable(),
    attempts_remaining: z.number().int().nonnegative().max(20),
    cooldown_until: NullableIsoDateTime,
    enrolled_at: NullableIsoDateTime,
    updated_at: IsoDateTime,
  }).strict(),
  search: MyPhotosSearchSchema.nullable(),
  results: z.object({
    snapshot_revision: z.number().int().nonnegative(),
    match_count: BoundedCount,
    new_photo_count: BoundedCount,
    downloadable_count: BoundedCount,
    preparing_count: BoundedCount,
    last_updated_at: NullableIsoDateTime,
  }).strict(),
}).strict().superRefine((value, context) => {
  if (
    (value.capability.provider_state === 'ready') !== value.capability.provider_ready
    || (value.capability.provider_state === 'ready' && value.capability.client_flow === 'unavailable')
  ) {
    context.addIssue({ code: 'custom', message: 'Provider readiness state is contradictory.' });
  }
  if (value.capability.provider_state === 'not_configured' && (
    value.capability.client_flow !== 'unavailable'
    || value.capability.retryable
  )) {
    context.addIssue({ code: 'custom', message: 'An unconfigured provider must fail closed.' });
  }
  if (value.capability.provider_state === 'temporarily_unavailable' && (
    value.capability.client_flow === 'unavailable'
    || !value.capability.retryable
  )) {
    context.addIssue({ code: 'custom', message: 'A transient provider state must retain its configured client flow.' });
  }
  if (!value.capability.feature_enabled && value.experience_state !== 'feature_unavailable') {
    context.addIssue({ code: 'custom', message: 'A disabled group must fail closed.' });
  }
  if (value.gallery.indexed_asset_count + value.gallery.failed_asset_count > value.gallery.total_asset_count) {
    context.addIssue({ code: 'custom', message: 'Indexed assets exceed registered assets.' });
  }
  if (
    value.results.snapshot_revision > value.gallery.published_revision
    || (value.results.match_count > 0 && value.results.snapshot_revision === 0)
    || (
      value.capability.feature_enabled
      && value.gallery.status === 'ready'
      && value.results.snapshot_revision === 0
    )
  ) {
    context.addIssue({ code: 'custom', message: 'Passenger result snapshot revision is inconsistent.' });
  }
});

export const AcceptMyPhotosConsentRequestSchema = z.object({
  consent_version: z.string().min(1).max(64),
  accepted: z.literal(true),
  idempotency_key: Uuid,
}).strict();

export const StartLivenessSessionRequestSchema = z.object({
  challenge_mode: ChallengeModeSchema,
  idempotency_key: Uuid,
}).strict();

export const LivenessSessionSchema = z.object({
  session_id: Uuid,
  status: z.literal('created'),
  challenge_mode: ChallengeModeSchema,
  client_flow: z.enum(['development_simulator', 'native']),
  native_launch_handle: z.string()
    .min(1)
    .max(2_048)
    .refine((value) => !/[\u0000-\u001f\u007f]/.test(value), 'Native launch handle contains control characters.')
    .nullable(),
  expires_at: IsoDateTime,
  attempts_remaining: z.number().int().nonnegative().max(20),
  photosensitivity_warning: z.string().min(1).max(1_000),
}).strict().superRefine((value, context) => {
  if (value.client_flow === 'native' && !value.native_launch_handle) {
    context.addIssue({ code: 'custom', message: 'Native Face Scan requires an opaque launch handle.' });
  }
  if (value.client_flow === 'development_simulator' && value.native_launch_handle !== null) {
    context.addIssue({ code: 'custom', message: 'Development Face Scan cannot receive a native launch handle.' });
  }
});

export const CompleteLivenessSessionRequestSchema = z.object({
  outcome: z.enum(['completed', 'cancelled', 'expired', 'failed']),
  idempotency_key: Uuid,
}).strict();

export const LivenessCompletionSchema = z.object({
  session_id: Uuid,
  session_status: z.enum(['completed', 'cancelled', 'expired', 'rejected', 'failed']),
  enrollment_status: EnrollmentStatusSchema,
  search_run_id: Uuid.nullable(),
  search_status: z.enum(['not_started', 'queued']),
  retryable: z.boolean(),
  error_code: ShortCode.nullable(),
  cooldown_until: NullableIsoDateTime,
}).strict();

export const MyPhotosSearchResponseSchema = z.object({
  search: MyPhotosSearchSchema.nullable(),
}).strict();

export const MyPhotosAssetSchema = z.object({
  asset_id: Uuid,
  match_id: Uuid.nullable(),
  tier: MatchTierSchema.nullable(),
  feedback: MatchFeedbackSchema,
  width: z.number().int().positive().max(100_000),
  height: z.number().int().positive().max(100_000),
  aspect_ratio: z.number().positive().max(100),
  captured_at: NullableIsoDateTime,
  thumbnail_state: MediaAvailabilitySchema,
  preview_state: MediaAvailabilitySchema,
  thumbnail: MediaVariantDescriptorSchema,
  preview: MediaVariantDescriptorSchema,
  original_state: MediaAvailabilitySchema,
  availability_state: MediaAvailabilitySchema,
  download_qualities: z.array(DownloadQualitySchema).max(2),
  original_byte_size: z.number().int().positive().max(MY_PHOTOS_MAX_ITEM_BYTES),
  original_checksum_sha256: Sha256,
  preparing: z.boolean(),
}).strict();

export const MyPhotosPageSchema = z.object({
  snapshot_revision: z.number().int().positive(),
  filter: MatchFilterSchema,
  items: z.array(MyPhotosAssetSchema).max(60),
  next_cursor: z.string().min(16).max(768).nullable(),
  page_size: z.number().int().min(1).max(60),
  total_count: BoundedCount,
}).strict().superRefine((value, context) => {
  if (value.items.length > value.page_size) {
    context.addIssue({ code: 'custom', message: 'Page contains more items than its declared size.' });
  }
  if (new Set(value.items.map((item) => item.asset_id)).size !== value.items.length) {
    context.addIssue({ code: 'custom', message: 'Page contains duplicate media assets.' });
  }
});

export const MatchFeedbackRequestSchema = z.object({
  feedback: z.enum(['this_is_me', 'not_me']),
  idempotency_key: Uuid,
}).strict();
export const MatchFeedbackResponseSchema = z.object({
  asset_id: Uuid,
  feedback: z.enum(['this_is_me', 'not_me']),
  updated_at: IsoDateTime,
}).strict();

export const DeleteEnrollmentRequestSchema = z.object({
  scope: z.enum(['enrollment_only', 'enrollment_and_search_data']),
  idempotency_key: Uuid,
}).strict();
export const DeleteEnrollmentResponseSchema = z.object({
  enrollment_status: z.literal('deleted'),
  removed_search_data: z.boolean(),
  local_downloads_affected: z.literal(false),
  provider_deletion_status: z.enum(['not_required', 'pending', 'complete', 'failed']),
  provider_deletion_retryable: z.boolean(),
  deleted_at: IsoDateTime,
}).strict();

export const PreparePhotoRequestSchema = z.object({
  quality: DownloadQualitySchema,
  idempotency_key: Uuid,
}).strict();
export const PreparePhotoResponseSchema = z.object({
  asset_id: Uuid,
  state: z.enum(['rehydration_requested', 'preparing_delivery', 'delivery_available']),
  preparation_id: Uuid.nullable(),
  retry_after_seconds: z.number().int().min(1).max(86_400).nullable(),
}).strict();

export const DownloadAuthorizationRequestSchema = z.object({
  items: z.array(z.object({
    asset_id: Uuid,
    quality: DownloadQualitySchema,
  }).strict()).min(1).max(50),
  idempotency_key: Uuid,
}).strict().superRefine((value, context) => {
  const keys = value.items.map((item) => `${item.asset_id}:${item.quality}`);
  if (new Set(keys).size !== keys.length) {
    context.addIssue({ code: 'custom', message: 'Duplicate download authorization item.' });
  }
});
export const DownloadAuthorizationResponseSchema = z.object({
  authorizations: z.array(z.object({
    asset_id: Uuid,
    authorization_id: Uuid.nullable(),
    quality: DownloadQualitySchema,
    delivery_version: z.number().int().positive(),
    state: z.enum(['preparing', 'available', 'unavailable']),
    transport: z.enum(['unavailable', 'development_fixture', 'direct_object_storage']),
    resource_path: z.string().min(1).max(512).refine(isSafeMyPhotosResourcePath).nullable(),
    content_type: z.enum(['image/jpeg', 'image/png', 'image/webp']).nullable(),
    expected_size_bytes: z.number().int().positive().max(MY_PHOTOS_MAX_ITEM_BYTES).nullable(),
    checksum_sha256: Sha256.nullable(),
    supports_ranges: z.boolean(),
    expires_at: NullableIsoDateTime,
    retry_after_seconds: z.number().int().min(1).max(86_400).nullable(),
  }).strict().superRefine((value, context) => {
    const requiredDeliveryMetadata = [
      value.authorization_id,
      value.content_type,
      value.expected_size_bytes,
      value.checksum_sha256,
      value.expires_at,
    ];
    if (value.state === 'available' && requiredDeliveryMetadata.some((entry) => entry === null)) {
      context.addIssue({ code: 'custom', message: 'Available photo delivery metadata is incomplete.' });
    }
    if (value.state !== 'available' && [...requiredDeliveryMetadata, value.resource_path].some((entry) => entry !== null)) {
      context.addIssue({ code: 'custom', message: 'Unavailable photo cannot expose delivery metadata.' });
    }
    if (value.transport === 'development_fixture' && value.state === 'available' && !value.resource_path) {
      context.addIssue({ code: 'custom', message: 'Development delivery requires an authenticated resource.' });
    }
    if (value.transport === 'direct_object_storage' && value.resource_path) {
      context.addIssue({ code: 'custom', message: 'Direct delivery is resolved by its native adapter.' });
    }
  })).min(1).max(50),
}).strict();

export const MyPhotosDownloadPlanSchema = z.object({
  snapshot_revision: z.number().int().positive(),
  matched_item_count: BoundedCount,
  downloadable_item_count: BoundedCount,
  preparing_item_count: BoundedCount,
  qualities: z.array(z.object({
    quality: DownloadQualitySchema,
    supported_item_count: BoundedCount,
    exact_byte_total: z.number().int().nonnegative().max(1_000_000_000_000_000),
    maximum_item_bytes: z.number().int().nonnegative().max(MY_PHOTOS_MAX_ITEM_BYTES),
    estimate_complete: z.boolean(),
  }).strict()).length(2),
}).strict().superRefine((value, context) => {
  if (new Set(value.qualities.map((item) => item.quality)).size !== 2) {
    context.addIssue({ code: 'custom', message: 'Download plan must include both unique qualities.' });
  }
  if (value.downloadable_item_count + value.preparing_item_count > value.matched_item_count) {
    context.addIssue({ code: 'custom', message: 'Download availability exceeds matched items.' });
  }
  for (const quality of value.qualities) {
    if (quality.supported_item_count > value.matched_item_count) {
      context.addIssue({ code: 'custom', message: 'Download quality support exceeds matched items.' });
    }
    if (quality.estimate_complete !== (quality.supported_item_count === value.matched_item_count)) {
      context.addIssue({ code: 'custom', message: 'Download estimate completeness is inconsistent.' });
    }
  }
});

export type MyPhotosSummary = z.infer<typeof MyPhotosSummarySchema>;
export type MyPhotosSearch = z.infer<typeof MyPhotosSearchSchema>;
export type MyPhotosAsset = z.infer<typeof MyPhotosAssetSchema>;
export type MyPhotosPage = z.infer<typeof MyPhotosPageSchema>;
export type MatchFilter = z.infer<typeof MatchFilterSchema>;
export type MatchFeedback = z.infer<typeof MatchFeedbackSchema>;
export type DownloadQuality = z.infer<typeof DownloadQualitySchema>;
export type LivenessSession = z.infer<typeof LivenessSessionSchema>;
export type LivenessCompletion = z.infer<typeof LivenessCompletionSchema>;
export type DownloadAuthorization = z.infer<typeof DownloadAuthorizationResponseSchema>['authorizations'][number];
export type MyPhotosDownloadPlan = z.infer<typeof MyPhotosDownloadPlanSchema>;
