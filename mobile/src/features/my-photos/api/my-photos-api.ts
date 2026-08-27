import * as Crypto from 'expo-crypto';

import { apiRequest } from '@/core/api/client';

import {
  AcceptMyPhotosConsentRequestSchema,
  CompleteLivenessSessionRequestSchema,
  DeleteEnrollmentRequestSchema,
  DeleteEnrollmentResponseSchema,
  DownloadAuthorizationRequestSchema,
  DownloadAuthorizationResponseSchema,
  LivenessCompletionSchema,
  LivenessSessionSchema,
  MatchFeedbackRequestSchema,
  MatchFeedbackResponseSchema,
  MatchFilterSchema,
  MyPhotosPageSchema,
  MyPhotosDownloadPlanSchema,
  MyPhotosSearchResponseSchema,
  MyPhotosSummarySchema,
  PreparePhotoRequestSchema,
  PreparePhotoResponseSchema,
  StartLivenessSessionRequestSchema,
  type DownloadQuality,
  type MatchFeedback,
  type MatchFilter,
} from './contracts';

const UuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

// The backend may spend up to 60 seconds waiting for the configured liveness
// provider. Keep a bounded transport margin so the client does not abandon a
// request that the server is still allowed to complete.
export const MY_PHOTOS_LIVENESS_API_TIMEOUT_MS = 75_000;

function uuidSegment(value: string, label: string): string {
  if (!UuidPattern.test(value)) throw new Error(`${label} must be a UUID.`);
  return value;
}

function basePath(groupId: string): string {
  return `/mobile/trips/${uuidSegment(groupId, 'Group')}/my-photos`;
}

export function myPhotosDownloadContentPath(groupId: string, authorizationId: string): string {
  return `/api/v1${basePath(groupId)}/download-authorizations/${uuidSegment(
    authorizationId,
    'Download authorization',
  )}/content`;
}

function idempotencyKey(value = Crypto.randomUUID()): string {
  return uuidSegment(value, 'Idempotency key');
}

export function getMyPhotosSummary(groupId: string, signal?: AbortSignal) {
  return apiRequest(basePath(groupId), {
    schema: MyPhotosSummarySchema,
    ...(signal ? { signal } : {}),
  });
}

export function acceptMyPhotosConsent(
  groupId: string,
  consentVersion: string,
  signal?: AbortSignal,
  requestId?: string,
) {
  const body = AcceptMyPhotosConsentRequestSchema.parse({
    consent_version: consentVersion,
    accepted: true,
    idempotency_key: idempotencyKey(requestId),
  });
  return apiRequest(`${basePath(groupId)}/consent`, {
    method: 'POST', body, schema: MyPhotosSummarySchema, ...(signal ? { signal } : {}),
  });
}

export function startLivenessSession(
  groupId: string,
  challengeMode: 'movement_and_light' | 'movement_only',
  signal?: AbortSignal,
  requestId?: string,
) {
  const body = StartLivenessSessionRequestSchema.parse({
    challenge_mode: challengeMode,
    idempotency_key: idempotencyKey(requestId),
  });
  return apiRequest(`${basePath(groupId)}/liveness-sessions`, {
    method: 'POST',
    body,
    schema: LivenessSessionSchema,
    timeoutMs: MY_PHOTOS_LIVENESS_API_TIMEOUT_MS,
    ...(signal ? { signal } : {}),
  });
}

export function completeLivenessSession(
  groupId: string,
  sessionId: string,
  outcome: 'completed' | 'cancelled' | 'expired' | 'failed',
  signal?: AbortSignal,
  requestId?: string,
) {
  const body = CompleteLivenessSessionRequestSchema.parse({
    outcome,
    idempotency_key: idempotencyKey(requestId),
  });
  return apiRequest(`${basePath(groupId)}/liveness-sessions/${uuidSegment(sessionId, 'Session')}/complete`, {
    method: 'POST',
    body,
    schema: LivenessCompletionSchema,
    timeoutMs: MY_PHOTOS_LIVENESS_API_TIMEOUT_MS,
    ...(signal ? { signal } : {}),
  });
}

export function getMyPhotosSearch(groupId: string, signal?: AbortSignal) {
  return apiRequest(`${basePath(groupId)}/search`, {
    schema: MyPhotosSearchResponseSchema,
    ...(signal ? { signal } : {}),
  });
}

export function getMyPhotosPage(
  groupId: string,
  filter: MatchFilter,
  options: Readonly<{ cursor?: string | null; limit?: number; signal?: AbortSignal }> = {},
) {
  const parsedFilter = MatchFilterSchema.parse(filter);
  const limit = Math.min(Math.max(options.limit ?? 48, 1), 60);
  const query = new URLSearchParams({ filter: parsedFilter, limit: String(limit) });
  if (options.cursor) {
    if (options.cursor.length > 768) throw new Error('Gallery cursor is too long.');
    query.set('cursor', options.cursor);
  }
  return apiRequest(`${basePath(groupId)}/photos?${query.toString()}`, {
    schema: MyPhotosPageSchema,
    ...(options.signal ? { signal: options.signal } : {}),
  });
}

export function submitMyPhotosFeedback(
  groupId: string,
  assetId: string,
  feedback: Exclude<MatchFeedback, 'none'>,
  signal?: AbortSignal,
  requestId?: string,
) {
  const body = MatchFeedbackRequestSchema.parse({
    feedback,
    idempotency_key: idempotencyKey(requestId),
  });
  return apiRequest(`${basePath(groupId)}/photos/${uuidSegment(assetId, 'Asset')}/feedback`, {
    method: 'PUT', body, schema: MatchFeedbackResponseSchema, ...(signal ? { signal } : {}),
  });
}

export function deleteMyPhotosEnrollment(
  groupId: string,
  scope: 'enrollment_only' | 'enrollment_and_search_data',
  signal?: AbortSignal,
  requestId?: string,
) {
  const body = DeleteEnrollmentRequestSchema.parse({ scope, idempotency_key: idempotencyKey(requestId) });
  return apiRequest(`${basePath(groupId)}/enrollment`, {
    method: 'DELETE', body, schema: DeleteEnrollmentResponseSchema, ...(signal ? { signal } : {}),
  });
}

export function prepareMyPhotosAsset(
  groupId: string,
  assetId: string,
  quality: DownloadQuality,
  signal?: AbortSignal,
  requestId?: string,
) {
  const body = PreparePhotoRequestSchema.parse({ quality, idempotency_key: idempotencyKey(requestId) });
  return apiRequest(`${basePath(groupId)}/photos/${uuidSegment(assetId, 'Asset')}/prepare`, {
    method: 'POST', body, schema: PreparePhotoResponseSchema, ...(signal ? { signal } : {}),
  });
}

export function authorizeMyPhotosDownloads(
  groupId: string,
  items: readonly Readonly<{ assetId: string; quality: DownloadQuality }>[],
  signal?: AbortSignal,
  requestId?: string,
) {
  const body = DownloadAuthorizationRequestSchema.parse({
    items: items.map((item) => ({ asset_id: item.assetId, quality: item.quality })),
    idempotency_key: idempotencyKey(requestId),
  });
  return apiRequest(`${basePath(groupId)}/download-authorizations`, {
    method: 'POST', body, schema: DownloadAuthorizationResponseSchema, ...(signal ? { signal } : {}),
  });
}

export function getMyPhotosDownloadPlan(groupId: string, signal?: AbortSignal) {
  return apiRequest(`${basePath(groupId)}/download-plan`, {
    schema: MyPhotosDownloadPlanSchema,
    ...(signal ? { signal } : {}),
  });
}
