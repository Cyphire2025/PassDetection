import * as BackgroundTask from 'expo-background-task';
import * as TaskManager from 'expo-task-manager';

import { bootstrapSession } from '@/core/auth/session-service';
import { useSessionStore } from '@/core/auth/session-store';

import { purgeExpiredTripCaches, retryPendingTripPurges } from './access-cache';
import { syncAllTrips } from './sync-service';

export const BACKGROUND_SYNC_TASK = 'gc-mobile-background-sync-v1';

if (!TaskManager.isTaskDefined(BACKGROUND_SYNC_TASK)) {
  TaskManager.defineTask(BACKGROUND_SYNC_TASK, async () => {
    try {
      await bootstrapSession();
      if (!useSessionStore.getState().session) return BackgroundTask.BackgroundTaskResult.Failed;
      await retryPendingTripPurges();
      await purgeExpiredTripCaches();
      const summary = await syncAllTrips();
      // Ask the operating system to retry partial and total failure. An empty
      // assignment is a valid successful no-op; a non-empty all-failed pool is not.
      if (
        summary.failures.length > 0
        || (summary.requestedTripCount > 0 && summary.results.length === 0)
      ) {
        return BackgroundTask.BackgroundTaskResult.Failed;
      }
      return BackgroundTask.BackgroundTaskResult.Success;
    } catch {
      return BackgroundTask.BackgroundTaskResult.Failed;
    }
  });
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
