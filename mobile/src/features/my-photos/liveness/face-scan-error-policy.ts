import { ApiError } from '@/core/api/client';

import type { FaceScanFailure } from '../model/face-scan-machine';

const STABLE_API_FAILURES: Readonly<Record<string, FaceScanFailure>> = Object.freeze({
  NO_FACE: 'no_face',
  MULTIPLE_FACES: 'multiple_faces',
  FACE_TOO_CLOSE: 'face_too_close',
  FACE_TOO_FAR: 'face_too_far',
  POOR_LIGHTING: 'poor_lighting',
  EXCESSIVE_MOVEMENT: 'excessive_movement',
  SESSION_EXPIRED: 'session_expired',
  LIVENESS_REJECTED: 'liveness_rejected',
  PROVIDER_TIMEOUT: 'provider_timeout',
  PROVIDER_UNAVAILABLE: 'provider_unavailable',
  PROVIDER_NOT_CONFIGURED: 'provider_unavailable',
  SESSION_PROCESSING: 'provider_unavailable',
  PROVIDER_THROTTLED: 'rate_limited',
  RATE_LIMITED: 'rate_limited',
  COOLDOWN: 'rate_limited',
  DEVICE_UNSUPPORTED: 'device_unsupported',
});

export function normalizeMyPhotosErrorCode(code: string | null): string {
  return (code ?? '').replace(/^MY_PHOTOS_/, '');
}

export function faceScanFailureFromStableCode(code: string | null): FaceScanFailure | null {
  return STABLE_API_FAILURES[normalizeMyPhotosErrorCode(code)] ?? null;
}

/** A completion request may have reached the server/provider even when its
 * response was lost. These errors must replay the same session, outcome, and
 * idempotency key; creating another liveness session would conflict with the
 * server-owned active session. */
export function shouldReplayLivenessCompletion(error: unknown): boolean {
  if (error instanceof ApiError) {
    const code = normalizeMyPhotosErrorCode(error.code);
    return error.status === 0
      || error.status === 408
      || error.status >= 500
      || error.code === 'NETWORK_ERROR'
      || code === 'PROVIDER_UNAVAILABLE'
      || code === 'PROVIDER_TIMEOUT'
      || code === 'SESSION_PROCESSING';
  }
  return error instanceof TypeError || (
    error instanceof Error
    && (error.name === 'TimeoutError' || error.name === 'AbortError')
  );
}

export function shouldReplayLivenessCompletionResult(
  code: string | null,
  retryable: boolean,
): boolean {
  if (!retryable) return false;
  const normalized = normalizeMyPhotosErrorCode(code);
  return normalized === 'PROVIDER_UNAVAILABLE'
    || normalized === 'PROVIDER_TIMEOUT'
    || normalized === 'SESSION_PROCESSING';
}
