import * as BackgroundTask from 'expo-background-task';
import * as TaskManager from 'expo-task-manager';

import { bootstrapSession } from '@/core/auth/session-service';
import { useSessionStore } from '@/core/auth/session-store';
import {
  recordMobileMetric,
  type MobileMetricAttributes,
} from '@/core/observability/mobile-observability';

import { purgeExpiredTripCaches, retryPendingTripPurges } from './access-cache';
import { requestSync } from './sync-trigger';

export const BACKGROUND_SYNC_TASK = 'gc-mobile-background-sync-v1';
export const BACKGROUND_SYNC_DEADLINE_MS = 4 * 60 * 1_000;

class BackgroundSyncDeadlineError extends Error {
  readonly code = 'BACKGROUND_SYNC_DEADLINE';

  constructor() {
    super('Background synchronization reached its execution deadline.');
    this.name = 'BackgroundSyncDeadlineError';
  }
}

function assertBackgroundWorkActive(signal: AbortSignal): void {
  if (!signal.aborted) return;
  throw signal.reason instanceof Error
    ? signal.reason
    : new BackgroundSyncDeadlineError();
}

/**
 * Runs one best-effort OS background window. Every trip sync commits its own
 * durable cursor, so cancellation resumes from the last committed checkpoint
 * instead of restarting a monolithic batch. The selected trip is ordered first
 * by the shared sync service, while the remaining work stays bounded to two
 * concurrent trips.
 */
export async function runBackgroundSyncTask(
  deadlineMs = BACKGROUND_SYNC_DEADLINE_MS,
): Promise<BackgroundTask.BackgroundTaskResult> {
  const startedAtMs = performance.now();
  let outcome: MobileMetricAttributes['outcome'] = 'failure';
  const deadlineController = new AbortController();
  const expire = (): void => {
    if (!deadlineController.signal.aborted) {
      outcome = 'timeout';
      recordMobileMetric('background_expiration', 1, {
        outcome: 'timeout',
        trigger: 'background',
      });
      deadlineController.abort(new BackgroundSyncDeadlineError());
    }
  };
  const deadlineTimer = setTimeout(expire, deadlineMs);
  const expirationSubscription = BackgroundTask.addExpirationListener(expire);

  try {
    await bootstrapSession({ execution: 'native-background' });
    assertBackgroundWorkActive(deadlineController.signal);
    if (!useSessionStore.getState().session) {
      outcome = 'failure';
      return BackgroundTask.BackgroundTaskResult.Failed;
    }
    await retryPendingTripPurges();
    assertBackgroundWorkActive(deadlineController.signal);
    await purgeExpiredTripCaches();
    assertBackgroundWorkActive(deadlineController.signal);
    const summary = await requestSync(
      { scope: 'full', reason: 'native-background' },
      { signal: deadlineController.signal },
    );
    assertBackgroundWorkActive(deadlineController.signal);
    // Ask the operating system to retry partial and total failure. An empty
    // assignment is a valid successful no-op; a non-empty all-failed pool is not.
    if (
      summary.failures.length > 0
      || (summary.requestedTripCount > 0 && summary.results.length === 0)
    ) {
      outcome = 'partial';
      return BackgroundTask.BackgroundTaskResult.Failed;
    }
    outcome = 'success';
    return BackgroundTask.BackgroundTaskResult.Success;
  } catch {
    outcome = deadlineController.signal.reason instanceof BackgroundSyncDeadlineError
      ? 'timeout'
      : deadlineController.signal.aborted
        ? 'cancelled'
        : 'failure';
    return BackgroundTask.BackgroundTaskResult.Failed;
  } finally {
    recordMobileMetric('background_sync_duration', performance.now() - startedAtMs, {
      outcome,
      trigger: 'background',
    });
    clearTimeout(deadlineTimer);
    expirationSubscription.remove();
  }
}

if (!TaskManager.isTaskDefined(BACKGROUND_SYNC_TASK)) {
  TaskManager.defineTask(BACKGROUND_SYNC_TASK, () => runBackgroundSyncTask());
}

export async function registerBackgroundSync(): Promise<boolean> {
  if (!(await TaskManager.isAvailableAsync())) return false;
  if (!(await TaskManager.isTaskRegisteredAsync(BACKGROUND_SYNC_TASK))) {
    await BackgroundTask.registerTaskAsync(BACKGROUND_SYNC_TASK, { minimumInterval: 30 });
  }
  return true;
}

export async function unregisterBackgroundSync(): Promise<void> {
  if (await TaskManager.isTaskRegisteredAsync(BACKGROUND_SYNC_TASK)) {
    await BackgroundTask.unregisterTaskAsync(BACKGROUND_SYNC_TASK);
  }
}
