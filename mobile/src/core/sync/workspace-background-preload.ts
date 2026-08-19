import { captureSyncContext, assertSyncContextActive } from '@/core/sync/sync-context';
import { preloadManagerTrip } from '@/features/content/data/manager-preload';
import { preloadCoordinatorTrip } from '@/features/coordinator/data/coordinator-preload';
import type { Trip } from '@/features/trips/model/trip';

export const WORKSPACE_BACKGROUND_PRELOAD_CONCURRENCY = 2;

export type WorkspaceBackgroundPreloadResult = Readonly<{
  attemptedTrips: number;
  failedTrips: number;
}>;

type StaffRole = 'client_manager' | 'coordinator';

/**
 * Continues staff workspace preparation after navigation without retaining the
 * preparation screen as the owner of every assigned trip.
 *
 * Each trip sync uses the one immutable account context captured for this
 * lane. Successful trips commit their durable cursors independently, so a
 * later runtime reconciliation can safely resume any unfinished trip after an
 * app stop or transport failure. A failure isolated to one trip cannot prevent
 * the rest of the assigned workspace from being attempted.
 */
async function runWorkspaceBackgroundPreload(
  role: StaffRole,
  trips: readonly Trip[],
  syncContext: ReturnType<typeof captureSyncContext>['context'],
): Promise<WorkspaceBackgroundPreloadResult> {
  let nextTripIndex = 0;
  let attemptedTrips = 0;
  let failedTrips = 0;

  const worker = async (): Promise<void> => {
    while (true) {
      assertSyncContextActive(syncContext);
      const tripIndex = nextTripIndex;
      if (tripIndex >= trips.length) return;
      nextTripIndex += 1;
      const trip = trips[tripIndex];
      if (!trip) continue;
      attemptedTrips += 1;

      try {
        if (role === 'client_manager') {
          await preloadManagerTrip(trip, () => undefined, syncContext);
        } else {
          await preloadCoordinatorTrip(trip, () => undefined, syncContext);
        }
        assertSyncContextActive(syncContext);
      } catch {
        // Authentication changes cancel the entire old-account lane. Other
        // errors are trip-local: syncTrip already records/purges as required,
        // and the next durable reconciliation can retry that trip.
        if (syncContext.signal.aborted) {
          assertSyncContextActive(syncContext);
        }
        failedTrips += 1;
      }
    }
  };

  await Promise.all(Array.from(
    { length: Math.min(WORKSPACE_BACKGROUND_PRELOAD_CONCURRENCY, trips.length) },
    () => worker(),
  ));
  assertSyncContextActive(syncContext);
  return { attemptedTrips, failedTrips };
}

/**
 * Captures and owns the current staff account boundary until all queued work
 * settles. The returned promise is intentionally not awaited by the login
 * screen, but is returned for deterministic lifecycle tests and diagnostics.
 */
export function scheduleRemainingWorkspacePreparation(
  role: StaffRole,
  trips: readonly Trip[],
): Promise<WorkspaceBackgroundPreloadResult> {
  if (trips.length === 0) {
    return Promise.resolve({ attemptedTrips: 0, failedTrips: 0 });
  }

  const lease = captureSyncContext();
  try {
    assertSyncContextActive(lease.context);
    if (lease.context.role !== role) {
      throw new Error('The background workspace role changed before preparation started.');
    }
    return runWorkspaceBackgroundPreload(role, trips, lease.context).finally(lease.release);
  } catch (error) {
    lease.release();
    return Promise.reject(error);
  }
}
