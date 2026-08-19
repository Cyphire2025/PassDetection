import { ApiError } from '@/core/api/client';
import { OfflineDatabaseIntegrityError } from '@/core/storage/database';

import { isSyncContextChanged } from './sync-context';

/**
 * Only known transient transport/provider failures may yield to an already
 * authorized cached workspace. Identity, authorization, cancellation, local
 * integrity, and unknown failures remain blocking and fail closed.
 */
export function canDeferWorkspacePreparationFailure(error: unknown): boolean {
  if (isSyncContextChanged(error) || error instanceof OfflineDatabaseIntegrityError) return false;
  if (
    error instanceof Error
    && error.name === 'SyncRequestTripError'
    && 'retryable' in error
    && typeof error.retryable === 'boolean'
  ) return error.retryable;
  if (error instanceof ApiError) {
    return error.status === 408
      || error.status === 425
      || error.status === 429
      || error.status >= 500;
  }
  if (error instanceof TypeError) {
    // JavaScript programmer errors are also TypeErrors. Only the stable fetch
    // messages emitted by Hermes, iOS, browsers, and React Native may yield to
    // an already-authorized cached workspace.
    return /network request failed|failed to fetch|load failed/i.test(error.message);
  }
  if (!(error instanceof Error)) return false;
  if (error.name === 'AbortError') return false;
  if (error.name === 'TimeoutError') return true;
  return /network|connection|temporar|timed?\s*out|fetch failed/i.test(error.message);
}
