import NetInfo from '@react-native-community/netinfo';
import { useEffect, useReducer } from 'react';
import { AppState } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { registerSessionLockSettlementHook } from '@/core/auth/session-lock';
import { principalAccountNamespace } from '@/core/auth/types';
import { recordMobileMetric } from '@/core/observability/mobile-observability';
import { mobileQueryClient } from '@/core/query/query-client';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import {
  captureMyPhotosContext,
  type MyPhotosContext,
} from '../data/my-photos-context';
import {
  abortPhotoDownloadsForContext,
  drainPhotoDownloadQueue,
  pausePhotoDownloadsForLifecycle,
  photoDownloadExecutions,
  recoverAndReconcilePhotoDownloads,
  resumeUnfinishedDownloadAll,
} from './download-manager';
import { purgeDisabledMyPhotosTrip } from './photo-feature-disable-cleanup';
import {
  nextPhotoDownloadWakeAt,
  recoverPhotoDownloadQueue,
} from './download-repository';
import {
  PhotoDownloadReconciliationGate,
  photoDownloadWakeDelayMs,
} from './photo-download-runtime-policy';
import {
  PhotoDownloadRuntimeLockedError,
  PhotoDownloadRuntimeRegistry,
  type PhotoDownloadRuntimeLease,
} from './photo-download-runtime-registry';
import { useMyPhotosCapabilityDecision } from '../hooks/my-photos-capability-policy';
import { useMyPhotosSummary } from '../hooks/use-my-photos';

const drainListeners = new Set<() => void>();
const RUNTIME_ACTIVATION_RETRY_MS = 1_000;
const RUNTIME_FAILURE_RETRY_MS = 5_000;
const RUNTIME_DOWNLOAD_ALL_CONTINUE_MS = 250;
export const photoDownloadRuntimeOperations = new PhotoDownloadRuntimeRegistry();

registerSessionLockSettlementHook('my-photos-native-transfers', async (namespace) => {
  await photoDownloadRuntimeOperations.abortNamespaceAndWait(
    namespace,
    new Error('The account is locking.'),
  );
  await photoDownloadExecutions.abortNamespaceAndWait(
    namespace,
    new Error('The account is locking.'),
  );
});

export function requestPhotoDownloadDrain(): void {
  for (const listener of drainListeners) listener();
}

export function beginPhotoDownloadNamespaceOperation(
  context: MyPhotosContext,
  parentSignal: AbortSignal,
): PhotoDownloadRuntimeLease {
  return photoDownloadRuntimeOperations.begin(
    context.namespace,
    context.sessionId,
    context.tripId,
    parentSignal,
  );
}

export async function withPhotoDownloadNamespaceOperation<T>(
  context: MyPhotosContext,
  parentSignal: AbortSignal,
  operation: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const lease = beginPhotoDownloadNamespaceOperation(context, parentSignal);
  try {
    return await operation(AbortSignal.any([context.signal, lease.signal]));
  } finally {
    lease.finish();
  }
}

export async function withExclusivePhotoDownloadNamespaceOperation<T>(
  context: MyPhotosContext,
  parentSignal: AbortSignal,
  operation: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  return photoDownloadRuntimeOperations.runExclusiveNamespace(
    context.namespace,
    context.sessionId,
    context.tripId,
    parentSignal,
    new Error('My Photos storage is being cleared.'),
    (signal) => operation(AbortSignal.any([context.signal, signal])),
  );
}

function isOwnedMyPhotosPrivateQuery(
  queryKey: readonly unknown[],
  context: MyPhotosContext,
): boolean {
  const prefix = queryKey[0];
  return typeof prefix === 'string'
    && prefix.startsWith('my-photos-')
    && prefix !== 'my-photos-summary'
    && queryKey.includes(context.namespace)
    && queryKey.includes(context.tripId);
}

export async function purgeServerDisabledMyPhotosTrip(
  context: MyPhotosContext,
  signal: AbortSignal = context.signal,
): Promise<void> {
  await mobileQueryClient.cancelQueries({
    predicate: (query) => isOwnedMyPhotosPrivateQuery(query.queryKey, context),
  });
  await withExclusivePhotoDownloadNamespaceOperation(
    context,
    signal,
    (exclusiveSignal) => purgeDisabledMyPhotosTrip(
      { ...context, signal: AbortSignal.any([context.signal, exclusiveSignal]) },
      exclusiveSignal,
    ),
  );
  mobileQueryClient.removeQueries({
    predicate: (query) => isOwnedMyPhotosPrivateQuery(query.queryKey, context),
  });
}

function connectedNetwork(state: Awaited<ReturnType<typeof NetInfo.fetch>>) {
  return {
    connected: Boolean(state.isConnected && state.isInternetReachable !== false),
    wifi: state.type === 'wifi',
  } as const;
}

/** Foreground-resumable runtime. It intentionally does not claim indefinite
 * terminated/background execution: active work pauses at the lifecycle fence,
 * and durable checkpoints resume when the app becomes active again. */
export function PhotoDownloadRuntime() {
  const [activationAttempt, retryActivation] = useReducer((value: number) => value + 1, 0);
  const session = useSessionStore((state) => state.session);
  const principal = session?.principal ?? null;
  const sessionId = session?.sessionId ?? null;
  const tripId = useSelectedTripStore((state) => state.tripId);
  const passengerId = principal?.principalType === 'passenger'
    ? principal.passengerId ?? null
    : null;
  const accountKey = principal ? principalAccountNamespace(principal) : null;

  useEffect(() => {
    if (!tripId || !passengerId || !accountKey || !sessionId) return;
    try {
      photoDownloadRuntimeOperations.activateNamespace(accountKey, sessionId);
    } catch {
      // A previous authentication boundary is still settling. The namespace
      // remains closed and no database or queue work may begin until the
      // bounded activation retry re-enters this effect.
      const retry = setTimeout(retryActivation, RUNTIME_ACTIVATION_RETRY_MS);
      return () => clearTimeout(retry);
    }
    const activeAccountKey = accountKey;
    const activeSessionId = sessionId;
    const activeTripId = tripId;
    let mounted = true;
    let foreground = AppState.currentState === 'active';
    let running = false;
    let rerun = false;
    let operation: AbortController | null = null;
    let lastContext: MyPhotosContext | null = null;
    let wakeTimer: ReturnType<typeof setTimeout> | null = null;
    const reconciliation = new PhotoDownloadReconciliationGate();

    const clearWakeTimer = (): void => {
      if (wakeTimer) clearTimeout(wakeTimer);
      wakeTimer = null;
    };

    const scheduleWake = (nextAttemptAt: string | null): void => {
      clearWakeTimer();
      if (!mounted || !foreground) return;
      const delay = photoDownloadWakeDelayMs(nextAttemptAt);
      if (delay === null) return;
      wakeTimer = setTimeout(() => {
        wakeTimer = null;
        void run();
      }, delay);
    };

    async function run(): Promise<void> {
      if (!mounted || !foreground) return;
      if (running) {
        rerun = true;
        return;
      }
      running = true;
      operation = new AbortController();
      const activeOperation = operation;
      let runtimeLease: PhotoDownloadRuntimeLease;
      try {
        runtimeLease = photoDownloadRuntimeOperations.begin(
          activeAccountKey,
          activeSessionId,
          activeTripId,
          activeOperation.signal,
        );
      } catch (error) {
        if (!(error instanceof PhotoDownloadRuntimeLockedError)) throw error;
        if (operation === activeOperation) operation = null;
        running = false;
        scheduleWake(new Date(Date.now() + RUNTIME_ACTIVATION_RETRY_MS).toISOString());
        return;
      }
      const lease = captureMyPhotosContext(activeTripId);
      const runSignal = AbortSignal.any([lease.context.signal, runtimeLease.signal]);
      lastContext = lease.context;
      try {
        const network = connectedNetwork(await NetInfo.fetch());
        lease.assertActive();
        await recoverPhotoDownloadQueue(lease.context, network);
        lease.assertActive();
        const downloadAllPending = await resumeUnfinishedDownloadAll(lease.context, runSignal);
        lease.assertActive();
        await drainPhotoDownloadQueue(lease.context, network, runSignal);
        lease.assertActive();
        // The queue is never blocked behind catalog reconciliation. Each
        // activation checks only a persisted, bounded keyset slice.
        if (reconciliation.requiresFullReconciliation()) {
          await recoverAndReconcilePhotoDownloads(lease.context, network, runSignal);
          reconciliation.complete();
        }
        lease.assertActive();
        scheduleWake(downloadAllPending
          ? new Date(Date.now() + RUNTIME_DOWNLOAD_ALL_CONTINUE_MS).toISOString()
          : await nextPhotoDownloadWakeAt(lease.context));
        lease.assertActive();
        await Promise.all([
          mobileQueryClient.invalidateQueries({ queryKey: ['my-photos-downloads'] }),
          mobileQueryClient.invalidateQueries({ queryKey: ['my-photos-download-storage'] }),
        ]);
      } catch {
        if (!activeOperation.signal.aborted) {
          recordMobileMetric('my_photos_download_event', 1, {
            my_photos_download_event: 'failed',
          });
          scheduleWake(new Date(Date.now() + RUNTIME_FAILURE_RETRY_MS).toISOString());
        }
      } finally {
        lease.release();
        runtimeLease.finish();
        if (operation === activeOperation) operation = null;
        running = false;
        if (rerun && mounted && foreground) {
          rerun = false;
          void run();
        }
      }
    }

    const appState = AppState.addEventListener('change', (state) => {
      foreground = state === 'active';
      if (foreground) {
        void run();
        return;
      }
      clearWakeTimer();
      const activeOperation = operation;
      activeOperation?.abort(new Error('My Photos paused while the app is inactive.'));
      if (lastContext) {
        const context = lastContext;
        void withPhotoDownloadNamespaceOperation(
          context,
          context.signal,
          () => pausePhotoDownloadsForLifecycle(context, 'APP_BACKGROUND'),
        ).catch((error: unknown) => {
          if (!(error instanceof PhotoDownloadRuntimeLockedError)) {
            recordMobileMetric('my_photos_download_event', 1, {
              my_photos_download_event: 'failed',
            });
          }
        });
      }
    });
    const unsubscribeNetwork = NetInfo.addEventListener((state) => {
      if (foreground && state.isConnected && state.isInternetReachable !== false) void run();
    });
    const drainListener = () => { void run(); };
    drainListeners.add(drainListener);
    void run();

    return () => {
      mounted = false;
      foreground = false;
      appState.remove();
      unsubscribeNetwork();
      drainListeners.delete(drainListener);
      clearWakeTimer();
      operation?.abort(new Error('My Photos account or trip changed.'));
      if (lastContext) {
        abortPhotoDownloadsForContext(
          lastContext,
          new Error('My Photos account or trip changed.'),
        );
      }
    };
  }, [accountKey, activationAttempt, passengerId, sessionId, tripId]);

  return null;
}

/** Keeps the authoritative disabled summary subscribed so a realtime sync
 * hint can reveal the feature again, while native photo work exists only for
 * a fresh server-enabled capability. */
export function MyPhotosCapabilityRuntime() {
  const tripId = useSelectedTripStore((state) => state.tripId);
  const summary = useMyPhotosSummary(tripId);
  const capability = useMyPhotosCapabilityDecision(summary.data, summary.error);
  const disabledServerTime = capability.confirmedNetworkDisabled
    ? summary.data?.value.server_time ?? null
    : null;

  useEffect(() => {
    if (!tripId || !capability.confirmedNetworkDisabled || !disabledServerTime) return;
    const controller = new AbortController();
    let lease: ReturnType<typeof captureMyPhotosContext> | null = null;
    try {
      lease = captureMyPhotosContext(tripId, controller.signal);
    } catch {
      return;
    }
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      lease?.release();
    };
    void purgeServerDisabledMyPhotosTrip(lease.context, controller.signal)
      .catch(() => {
        recordMobileMetric('my_photos_download_event', 1, {
          my_photos_download_event: 'failed',
        });
      })
      .finally(release);
    return () => {
      controller.abort(new Error('My Photos capability changed.'));
      release();
    };
  }, [capability.confirmedNetworkDisabled, disabledServerTime, tripId]);

  return capability.visible ? <PhotoDownloadRuntime /> : null;
}
