import * as BackgroundTask from 'expo-background-task';
import * as TaskManager from 'expo-task-manager';

import { bootstrapSession } from '@/core/auth/session-service';
import { useSessionStore } from '@/core/auth/session-store';

import { purgeExpiredTripCaches } from './access-cache';
import { syncAllTrips } from './sync-service';

export const BACKGROUND_SYNC_TASK = 'gc-mobile-background-sync-v1';

if (!TaskManager.isTaskDefined(BACKGROUND_SYNC_TASK)) {
  TaskManager.defineTask(BACKGROUND_SYNC_TASK, async () => {
    try {
      await bootstrapSession();
      if (!useSessionStore.getState().session) return BackgroundTask.BackgroundTaskResult.Failed;
      await purgeExpiredTripCaches();
      await syncAllTrips();
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
