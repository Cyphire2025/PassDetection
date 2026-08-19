import { mobileQueryClient } from '@/core/query/query-client';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import { bootstrapSession } from './session-service';
import { invalidateAuthenticationBoundary, useSessionStore } from './session-store';

export type ApplicationBootstrapResult =
  | Readonly<{ ok: true }>
  | Readonly<{ ok: false; errorCode: 'SESSION_BOOTSTRAP_FAILED' }>;

let bootstrapInFlight: Promise<ApplicationBootstrapResult> | null = null;

/**
 * Owns the top-level application bootstrap boundary.
 *
 * Session restoration itself may fail before its internal offline fallback is
 * available (for example, SecureStore or SQLite can reject). This wrapper
 * converts every such rejection into a recoverable, PII-free state and clears
 * all in-memory account-scoped state before the anonymous shell is rendered.
 */
export function bootstrapApplicationSession(): Promise<ApplicationBootstrapResult> {
  if (bootstrapInFlight) return bootstrapInFlight;

  invalidateAuthenticationBoundary();
  useSessionStore.getState().beginBootstrap();
  useSelectedTripStore.getState().clear();
  mobileQueryClient.clear();

  const request = bootstrapSession({ validation: 'background' })
    .then<ApplicationBootstrapResult>(() => {
      return { ok: true };
    })
    .catch<ApplicationBootstrapResult>(() => {
      // Never preserve a previous account in memory when the local identity
      // boundary could not be read safely. Encrypted on-disk data remains
      // isolated and can be recovered by a later successful retry.
      invalidateAuthenticationBoundary();
      useSelectedTripStore.getState().clear();
      mobileQueryClient.clear();
      useSessionStore.getState().failBootstrap();
      return { ok: false, errorCode: 'SESSION_BOOTSTRAP_FAILED' };
    })
    .finally(() => {
      if (bootstrapInFlight === request) bootstrapInFlight = null;
    });
  bootstrapInFlight = request;
  return request;
}
