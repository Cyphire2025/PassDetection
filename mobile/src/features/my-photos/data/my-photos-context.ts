import { useSessionStore } from '@/core/auth/session-store';
import {
  assertSyncContextActive,
  captureSyncContext,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

export class MyPhotosContextChangedError extends Error {
  readonly code = 'MY_PHOTOS_CONTEXT_CHANGED';

  constructor() {
    super('The active passenger or trip changed while My Photos was loading.');
    this.name = 'MyPhotosContextChangedError';
  }
}

export type MyPhotosContext = ImmutableSyncContext & Readonly<{
  passengerId: string;
  tripId: string;
}>;

export type MyPhotosContextLease = Readonly<{
  context: MyPhotosContext;
  assertActive: () => void;
  release: () => void;
}>;

function currentBoundaryMatches(context: MyPhotosContext): boolean {
  const session = useSessionStore.getState().session;
  return Boolean(
    session
    && session.principal.principalType === 'passenger'
    && session.principal.passengerId === context.passengerId
    && useSelectedTripStore.getState().tripId === context.tripId,
  );
}

/** Read-only publication guard for work that can outlive a React effect. Native
 * transfers must cross this boundary before opening the account database or
 * publishing progress after an account/trip switch. */
export function myPhotosContextStillCurrent(context: MyPhotosContext): boolean {
  return !context.signal.aborted && currentBoundaryMatches(context);
}

export function assertMyPhotosContextStillCurrent(context: MyPhotosContext): void {
  if (!myPhotosContextStillCurrent(context)) throw new MyPhotosContextChangedError();
}

/** Invokes a durable write synchronously only while the captured boundary is
 * current. Returning null is intentional: stale cleanup must leave durable
 * `downloading` rows for same-account crash recovery instead of reopening an
 * old account database. */
export function runWhenMyPhotosContextCurrent<T>(
  context: MyPhotosContext,
  operation: () => Promise<T>,
): Promise<T> | null {
  return myPhotosContextStillCurrent(context) ? operation() : null;
}

/** Captures account + passenger + selected-trip identity. A locator supplied by
 * a screen never becomes authorization and a stale response cannot cross a trip switch. */
export function captureMyPhotosContext(
  tripId: string,
  externalSignal?: AbortSignal,
): MyPhotosContextLease {
  const session = useSessionStore.getState().session;
  const selectedTripId = useSelectedTripStore.getState().tripId;
  if (
    !session
    || session.principal.principalType !== 'passenger'
    || !session.principal.passengerId
  ) throw new Error('A passenger session is required.');
  if (tripId !== selectedTripId) throw new MyPhotosContextChangedError();

  const controller = new AbortController();
  const syncLease = captureSyncContext(externalSignal);
  const signal = AbortSignal.any([syncLease.context.signal, controller.signal]);
  const context: MyPhotosContext = Object.freeze({
    ...syncLease.context,
    signal,
    passengerId: session.principal.passengerId,
    tripId,
  });
  const abortIfChanged = () => {
    if (!currentBoundaryMatches(context) && !controller.signal.aborted) {
      controller.abort(new MyPhotosContextChangedError());
    }
  };
  const unsubscribeSession = useSessionStore.subscribe(abortIfChanged);
  const unsubscribeTrip = useSelectedTripStore.subscribe(abortIfChanged);
  const assertActive = () => {
    assertSyncContextActive(context);
    assertMyPhotosContextStillCurrent(context);
  };
  return Object.freeze({
    context,
    assertActive,
    release: () => {
      unsubscribeTrip();
      unsubscribeSession();
      syncLease.release();
    },
  });
}

export async function withMyPhotosContext<T>(
  tripId: string,
  signal: AbortSignal,
  operation: (context: MyPhotosContext, assertActive: () => void) => Promise<T>,
): Promise<T> {
  const lease = captureMyPhotosContext(tripId, signal);
  try {
    lease.assertActive();
    const result = await operation(lease.context, lease.assertActive);
    lease.assertActive();
    return result;
  } finally {
    lease.release();
  }
}
