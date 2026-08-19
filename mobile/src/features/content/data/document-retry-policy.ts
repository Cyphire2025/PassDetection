import { ApiError } from '@/core/api/client';

export const MAX_DOCUMENT_DOWNLOAD_ATTEMPTS = 3;
export type DocumentRetryAction = 'refresh_metadata' | 'retry' | 'fail';

export function isDocumentMetadataConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

export function documentRetryAction(
  error: unknown,
  failedAttempt: number,
  metadataAlreadyRefreshed: boolean,
): DocumentRetryAction {
  if (failedAttempt >= MAX_DOCUMENT_DOWNLOAD_ATTEMPTS) return 'fail';
  if (isDocumentMetadataConflict(error)) {
    return metadataAlreadyRefreshed ? 'fail' : 'refresh_metadata';
  }
  return isRetryableDocumentError(error) ? 'retry' : 'fail';
}

export function isRetryableDocumentError(error: unknown): boolean {
  if (
    typeof error === 'object'
    && error !== null
    && 'code' in error
    && error.code === 'LOCAL_OFFLINE_CIPHERTEXT_CORRUPT'
  ) return true;
  if (error instanceof ApiError) {
    return error.code === 'DOWNLOAD_AUTH_EXPIRED'
      || ((error.status === 404 || error.status === 410) && error.code === `HTTP_${error.status}`)
      || error.status === 408
      || error.status === 425
      || error.status === 429
      || error.status >= 500;
  }
  if (error instanceof TypeError) {
    // A programming defect can also surface as TypeError. Retry only the stable
    // transport messages emitted by fetch implementations on supported runtimes.
    return /network request failed|failed to fetch|load failed/i.test(error.message);
  }
  if (!(error instanceof Error)) return false;
  if (error.name === 'AbortError' || error.name === 'TimeoutError') return true;
  return /network|connection|temporar|timed?\s*out|fetch failed/i.test(error.message);
}

export function documentRetryDelayMs(failedAttempt: number, random = Math.random): number {
  const attempt = Math.max(1, Math.min(failedAttempt, MAX_DOCUMENT_DOWNLOAD_ATTEMPTS));
  const base = Math.min(2_000, 250 * (2 ** (attempt - 1)));
  return base + Math.floor(Math.max(0, Math.min(1, random())) * 200);
}
