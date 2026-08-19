import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { localTripsInContext } from '@/features/trips/data/trip-repository';

import {
  assertSyncContextActive,
  captureSyncContext,
  SyncContextChangedError,
  type ImmutableSyncContext,
  type SyncContextLease,
} from './sync-context';
import { publishSyncSummary } from './sync-query-publication';
import {
  FULL_TRIP_RECONCILIATION_INTERVAL_MS,
  resolveSyncScope,
} from './sync-runtime-policy';
import {
  syncAllTripsWithSummary,
  syncTripInContext,
  syncTripFailure,
  type SyncAllTripsSummary,
  type SyncResult,
  type SyncTripFailure,
} from './sync-service';
import {
  loadLastSuccessfulFullSyncAt,
  storeLastSuccessfulFullSyncAt,
} from './sync-watermark';

export type SyncTrigger =
  | Readonly<{ scope: 'auto'; tripId: string | null; reason: string }>
  | Readonly<{ scope: 'full'; reason: string }>
  | Readonly<{ scope: 'trip'; tripId: string; reason: string }>;

export type SyncRequestOptions = Readonly<{
  signal?: AbortSignal;
}>;

type SyncWaiter = {
  trigger: SyncTrigger;
  settled: boolean;
  resolve: (summary: SyncAllTripsSummary) => void;
  reject: (error: unknown) => void;
  removeAbortListener: () => void;
};

type SyncBatch = {
  boundaryKey: string;
  controller: AbortController;
  lease: SyncContextLease;
  waiters: SyncWaiter[];
};

type EffectiveRun = Readonly<{
  scope: 'full' | 'trips' | 'none';
  tripIds: readonly string[];
}>;

type RunOutcome = Readonly<{
  effective: EffectiveRun;
  errors: ReadonlyMap<string, unknown>;
  summary: SyncAllTripsSummary;
}>;

export type SyncCoordinatorDependencies = Readonly<{
  captureLease: (signal: AbortSignal) => SyncContextLease;
  currentBoundaryKey: () => string | null;
  executeFull: (syncContext: ImmutableSyncContext) => Promise<SyncAllTripsSummary>;
  executeTrip: (
    tripId: string,
    syncContext: ImmutableSyncContext,
  ) => Promise<SyncResult>;
  failureForTrip: (tripId: string, error: unknown) => SyncTripFailure;
  loadFullWatermark: (syncContext: ImmutableSyncContext) => Promise<number | null>;
  storeFullWatermark: (
    syncContext: ImmutableSyncContext,
    completedAtEpochMs: number,
  ) => Promise<void>;
  publish: (
    summary: SyncAllTripsSummary,
    syncContext: ImmutableSyncContext,
  ) => Promise<void>;
  afterFull: (syncContext: ImmutableSyncContext) => Promise<void>;
  now: () => number;
}>;

const EMPTY_SUMMARY: SyncAllTripsSummary = Object.freeze({
  results: [],
  failures: [],
  requestedTripCount: 0,
  tripsChanged: false,
  removedTripIds: [],
});

const MAX_COORDINATED_TRIP_CONCURRENCY = 2;

function activeBoundaryKey(): string | null {
  const session = useSessionStore.getState().session;
  if (!session) return null;
  return [
    principalAccountNamespace(session.principal),
    session.sessionId,
    session.principal.id,
    session.principal.principalType,
  ].join(':');
}

function contextBoundaryKey(context: ImmutableSyncContext): string {
  return [context.namespace, context.sessionId, context.principalId, context.role].join(':');
}

function abortReason(signal: AbortSignal): Error {
  return signal.reason instanceof Error
    ? signal.reason
    : new Error('Synchronization was cancelled.');
}

export class SyncRequestTripError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly tripId: string;

  constructor(failure: SyncTripFailure) {
    super('The selected trip could not be synchronized.');
    this.name = 'SyncRequestTripError';
    this.code = failure.code;
    this.retryable = failure.retryable;
    this.tripId = failure.tripId;
  }
}

function defaultDependencies(): SyncCoordinatorDependencies {
  return {
    captureLease: (signal) => captureSyncContext(signal),
    currentBoundaryKey: activeBoundaryKey,
    executeFull: (syncContext) => syncAllTripsWithSummary({ signal: syncContext.signal }),
    executeTrip: (tripId, syncContext) => syncTripInContext(tripId, syncContext, {
      documentHydration: 'background',
    }),
    failureForTrip: syncTripFailure,
    loadFullWatermark: loadLastSuccessfulFullSyncAt,
    storeFullWatermark: storeLastSuccessfulFullSyncAt,
    publish: publishSyncSummary,
    afterFull: async (syncContext) => {
      const trips = await localTripsInContext(syncContext);
      assertSyncContextActive(syncContext);
      const { reconcileDepartureReminders } = await import(
        '@/core/notifications/departure-reminders'
      );
      assertSyncContextActive(syncContext);
      await reconcileDepartureReminders(trips);
    },
    now: Date.now,
  };
}

/**
 * One account-aware owner for foreground, background, preload, push, realtime,
 * and explicit refresh synchronization. Requests in the same JavaScript turn
 * coalesce; a full request subsumes trip requests, and matching active work is
 * shared. Failed runs are never cached, so the next trigger performs a retry.
 */
export class SyncCoordinator {
  private readonly dependencies: SyncCoordinatorDependencies;
  private readonly pending = new Map<string, SyncBatch>();
  private readonly order: string[] = [];
  private readonly loadedWatermarkBoundaries = new Set<string>();
  private readonly watermarks = new Map<string, number | null>();
  private active: (SyncBatch & { effective: EffectiveRun }) | null = null;
  private drainScheduled = false;

  constructor(dependencies: SyncCoordinatorDependencies = defaultDependencies()) {
    this.dependencies = dependencies;
  }

  request(
    trigger: SyncTrigger,
    options: SyncRequestOptions = {},
  ): Promise<SyncAllTripsSummary> {
    if (options.signal?.aborted) return Promise.reject(abortReason(options.signal));
    const boundaryKey = this.dependencies.currentBoundaryKey();
    if (!boundaryKey) return Promise.reject(new Error('Authentication is required.'));

    let target: SyncBatch;
    try {
      target = this.active
        && this.active.boundaryKey === boundaryKey
        && !this.active.controller.signal.aborted
        && this.activeCovers(this.active.effective, trigger)
        ? this.active
        : this.pending.get(boundaryKey) ?? this.createBatch(boundaryKey);
    } catch (error) {
      return Promise.reject(error);
    }

    const promise = new Promise<SyncAllTripsSummary>((resolve, reject) => {
      const waiter: SyncWaiter = {
        trigger,
        settled: false,
        resolve,
        reject,
        removeAbortListener: () => undefined,
      };
      const onAbort = () => {
        if (waiter.settled) return;
        waiter.settled = true;
        waiter.removeAbortListener();
        reject(abortReason(options.signal!));
        this.abortUnobservedBatch(target);
      };
      if (options.signal) {
        options.signal.addEventListener('abort', onAbort, { once: true });
        waiter.removeAbortListener = () => options.signal?.removeEventListener('abort', onAbort);
      }
      target.waiters.push(waiter);
      if (options.signal?.aborted) onAbort();
    });

    if (target !== this.active) this.scheduleDrain();
    return promise;
  }

  private createBatch(boundaryKey: string): SyncBatch {
    const controller = new AbortController();
    const lease = this.dependencies.captureLease(controller.signal);
    if (contextBoundaryKey(lease.context) !== boundaryKey) {
      controller.abort(new SyncContextChangedError());
      lease.release();
      throw new SyncContextChangedError();
    }
    const batch: SyncBatch = { boundaryKey, controller, lease, waiters: [] };
    this.pending.set(boundaryKey, batch);
    this.order.push(boundaryKey);
    return batch;
  }

  private activeCovers(effective: EffectiveRun, trigger: SyncTrigger): boolean {
    if (effective.scope === 'full') return true;
    if (effective.scope !== 'trips' || trigger.scope !== 'trip') return false;
    return effective.tripIds.includes(trigger.tripId);
  }

  private abortUnobservedBatch(batch: SyncBatch): void {
    if (batch.waiters.some((waiter) => !waiter.settled)) return;
    if (!batch.controller.signal.aborted) {
      batch.controller.abort(new Error('Every synchronization consumer cancelled.'));
    }
  }

  private scheduleDrain(): void {
    if (this.drainScheduled || this.active) return;
    this.drainScheduled = true;
    void Promise.resolve().then(() => {
      this.drainScheduled = false;
      return this.drain();
    }).catch(() => undefined);
  }

  private async drain(): Promise<void> {
    if (this.active) return;
    let batch: SyncBatch | undefined;
    while (!batch && this.order.length > 0) {
      const boundaryKey = this.order.shift();
      if (!boundaryKey) break;
      batch = this.pending.get(boundaryKey);
      if (batch) this.pending.delete(boundaryKey);
    }
    if (!batch) return;

    try {
      const effective = await this.resolveEffectiveRun(batch);
      this.active = { ...batch, effective };
      const outcome = await this.execute(batch, effective);
      this.settleBatch(batch, outcome);
    } catch (error) {
      this.rejectBatch(batch, error);
    } finally {
      batch.lease.release();
      if (this.active?.lease === batch.lease) this.active = null;
      this.scheduleDrain();
    }
  }

  private async resolveEffectiveRun(batch: SyncBatch): Promise<EffectiveRun> {
    assertSyncContextActive(batch.lease.context);
    const live = batch.waiters.filter((waiter) => !waiter.settled);
    if (live.length === 0) throw abortReason(batch.controller.signal);
    if (live.some((waiter) => waiter.trigger.scope === 'full')) {
      return { scope: 'full', tripIds: [] };
    }

    const tripIds = new Set<string>();
    let automaticTripId: string | null = null;
    for (const waiter of live) {
      if (waiter.trigger.scope === 'trip') tripIds.add(waiter.trigger.tripId);
      if (waiter.trigger.scope === 'auto' && automaticTripId === null) {
        automaticTripId = waiter.trigger.tripId;
      }
    }
    if (live.some((waiter) => waiter.trigger.scope === 'auto')) {
      const watermark = await this.watermarkFor(batch);
      assertSyncContextActive(batch.lease.context);
      const scope = resolveSyncScope({
        forceFull: false,
        selectedTripId: automaticTripId,
        lastFullSyncAt: watermark,
        now: this.dependencies.now(),
      });
      if (scope === 'full') return { scope: 'full', tripIds: [] };
      for (const waiter of live) {
        if (waiter.trigger.scope === 'auto' && waiter.trigger.tripId) {
          tripIds.add(waiter.trigger.tripId);
        }
      }
    }
    return tripIds.size > 0
      ? { scope: 'trips', tripIds: [...tripIds] }
      : { scope: 'none', tripIds: [] };
  }

  private async watermarkFor(batch: SyncBatch): Promise<number | null> {
    if (this.loadedWatermarkBoundaries.has(batch.boundaryKey)) {
      return this.watermarks.get(batch.boundaryKey) ?? null;
    }
    const watermark = await this.dependencies.loadFullWatermark(batch.lease.context);
    assertSyncContextActive(batch.lease.context);
    this.loadedWatermarkBoundaries.add(batch.boundaryKey);
    this.watermarks.set(batch.boundaryKey, watermark);
    return watermark;
  }

  private async execute(batch: SyncBatch, effective: EffectiveRun): Promise<RunOutcome> {
    assertSyncContextActive(batch.lease.context);
    if (effective.scope === 'none') {
      return { effective, errors: new Map(), summary: EMPTY_SUMMARY };
    }

    let summary: SyncAllTripsSummary;
    const errors = new Map<string, unknown>();
    if (effective.scope === 'full') {
      summary = await this.dependencies.executeFull(batch.lease.context);
      assertSyncContextActive(batch.lease.context);
    } else {
      const results: (SyncResult | null)[] = effective.tripIds.map(() => null);
      const failures: (SyncTripFailure | null)[] = effective.tripIds.map(() => null);
      let nextIndex = 0;
      const worker = async () => {
        while (true) {
          assertSyncContextActive(batch.lease.context);
          const index = nextIndex;
          if (index >= effective.tripIds.length) return;
          nextIndex += 1;
          const tripId = effective.tripIds[index];
          if (!tripId) continue;
          try {
            results[index] = await this.dependencies.executeTrip(tripId, batch.lease.context);
          } catch (error) {
            assertSyncContextActive(batch.lease.context);
            errors.set(tripId, error);
            failures[index] = this.dependencies.failureForTrip(tripId, error);
          }
        }
      };
      await Promise.all(Array.from(
        { length: Math.min(MAX_COORDINATED_TRIP_CONCURRENCY, effective.tripIds.length) },
        () => worker(),
      ));
      summary = {
        results: results.filter((result): result is SyncResult => result !== null),
        failures: failures.filter((failure): failure is SyncTripFailure => failure !== null),
        requestedTripCount: effective.tripIds.length,
        tripsChanged: false,
        removedTripIds: [],
      };
    }

    assertSyncContextActive(batch.lease.context);
    await this.dependencies.publish(summary, batch.lease.context);
    assertSyncContextActive(batch.lease.context);
    if (effective.scope === 'full') {
      if (summary.failures.length === 0) {
        const completedAt = this.dependencies.now();
        await this.dependencies.storeFullWatermark(batch.lease.context, completedAt);
        assertSyncContextActive(batch.lease.context);
        this.loadedWatermarkBoundaries.add(batch.boundaryKey);
        this.watermarks.set(batch.boundaryKey, completedAt);
      }
      await this.dependencies.afterFull(batch.lease.context).catch(() => undefined);
      assertSyncContextActive(batch.lease.context);
    }
    return { effective, errors, summary };
  }

  private settleBatch(batch: SyncBatch, outcome: RunOutcome): void {
    for (const waiter of batch.waiters) {
      if (waiter.settled) continue;
      waiter.settled = true;
      waiter.removeAbortListener();
      const tripId = waiter.trigger.scope === 'trip'
        ? waiter.trigger.tripId
        : outcome.effective.scope === 'trips' && waiter.trigger.scope === 'auto'
          ? waiter.trigger.tripId
          : null;
      if (tripId) {
        const original = outcome.errors.get(tripId);
        if (original) {
          waiter.reject(original);
          continue;
        }
        const failure = outcome.summary.failures.find((item) => item.tripId === tripId);
        if (failure) {
          waiter.reject(new SyncRequestTripError(failure));
          continue;
        }
        if (
          outcome.effective.scope === 'full'
          && !outcome.summary.results.some((result) => result.tripId === tripId)
        ) {
          waiter.reject(new SyncRequestTripError({
            tripId,
            category: 'authorization',
            retryable: false,
            code: 'TRIP_NOT_ASSIGNED',
          }));
          continue;
        }
      }
      waiter.resolve(outcome.summary);
    }
  }

  private rejectBatch(batch: SyncBatch, error: unknown): void {
    for (const waiter of batch.waiters) {
      if (waiter.settled) continue;
      waiter.settled = true;
      waiter.removeAbortListener();
      waiter.reject(error);
    }
  }
}

const syncCoordinator = new SyncCoordinator();

export function requestSync(
  trigger: SyncTrigger,
  options: SyncRequestOptions = {},
): Promise<SyncAllTripsSummary> {
  return syncCoordinator.request(trigger, options);
}

export { FULL_TRIP_RECONCILIATION_INTERVAL_MS };
