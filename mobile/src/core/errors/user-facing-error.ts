import { ApiError } from '@/core/api/client';

const RATE_LIMIT_CODES = new Set([
  'APP_RATE_LIMITED',
  'PROXY_RATE_LIMITED',
  'RATE_LIMITED',
]);

const ACCESS_DENIED_CODES = new Set([
  'AUTHORIZATION_ERROR',
  'FORBIDDEN',
]);

const STALE_STATE_CODES = new Set([
  'AUTH_CONTEXT_CHANGED',
  'DOCUMENT_METADATA_CONFLICT',
  'DOCUMENT_VERSION_CHANGED',
]);

/**
 * Converts internal/native/provider failures into stable copy that is safe to
 * render. Raw Error.message values can contain SQLite statements, native
 * module names, storage paths, or provider diagnostics and must never cross
 * the UI boundary.
 */
export function userFacingErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 429 || RATE_LIMIT_CODES.has(error.code)) {
      return 'Please wait a moment before trying again.';
    }
    if (error.status === 401) return 'Your secure session has expired. Sign in again.';
    if (error.status === 403 || ACCESS_DENIED_CODES.has(error.code)) {
      return 'You no longer have access to this information.';
    }
    if (error.status === 404 || error.code === 'NOT_FOUND') {
      return 'This information is no longer available.';
    }
    if (error.status === 409 || STALE_STATE_CODES.has(error.code)) {
      return 'This information changed. Refresh and try again.';
    }
    if (error.status === 408 || error.status === 425) {
      return 'The request timed out. Check your connection and try again.';
    }
    if (error.status >= 500) return 'The server could not complete this request. Try again.';
    if (error.status === 422) return 'Please check the information and try again.';
    return fallback;
  }

  if (error instanceof TypeError) {
    return 'Check your connection and try again.';
  }
  if (error instanceof Error && error.name === 'AbortError') {
    return 'The request timed out. Check your connection and try again.';
  }
  return fallback;
}
