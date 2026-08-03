import { QueryClient } from '@tanstack/react-query';

import { ApiError } from '@/core/api/client';

const NON_RETRYABLE_CONTRACT_CODES = new Set([
  'INVALID_CONTENT_TYPE',
  'INVALID_RESPONSE',
  'PAYLOAD_TOO_LARGE',
]);

export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false;
  if (error instanceof ApiError) {
    if (NON_RETRYABLE_CONTRACT_CODES.has(error.code)) return false;
    return error.status === 408
      || error.status === 425
      || error.status === 429
      || error.status >= 500;
  }
  if (error instanceof Error && (
    error.name === 'AbortError'
    || error.name === 'OfflineDatabaseIntegrityError'
    || error.name === 'SyncContextChangedError'
  )) {
    return false;
  }
  // Native fetch rejects transport failures as TypeError. Unknown runtime
  // errors get one bounded retry, then surface rather than looping silently.
  return error instanceof TypeError || failureCount === 0;
}

export function queryRetryDelay(attemptIndex: number, error: unknown): number {
  if (error instanceof ApiError && error.retryAfterSeconds !== null) {
    return Math.min(60_000, Math.max(0, error.retryAfterSeconds * 1_000));
  }
  const base = Math.min(30_000, 750 * 2 ** Math.min(Math.max(attemptIndex, 0), 6));
  return Math.round(base * (0.8 + Math.random() * 0.4));
}

export const mobileQueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 10 * 60_000,
      retry: shouldRetryQuery,
      retryDelay: queryRetryDelay,
      // SyncRuntime owns reconnect refreshes. React Query still receives native
      // online state so offline queries pause, but it must not issue a second
      // refetch beside the manifest-driven synchronization pass.
      refetchOnReconnect: false,
      refetchOnWindowFocus: false,
    },
    mutations: { retry: 0 },
  },
});
