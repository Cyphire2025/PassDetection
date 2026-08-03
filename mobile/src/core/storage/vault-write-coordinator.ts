export class TripVaultPurgeInProgressError extends Error {
  constructor() {
    super('Secure trip cleanup is still in progress.');
    this.name = 'TripVaultPurgeInProgressError';
  }
}

type TripVaultWriteState = {
  activeWrites: number;
  activePurges: number;
  durablyAcknowledged: boolean;
  purgePending: boolean;
  drainWaiters: Set<() => void>;
};

/**
 * Process-local writer/purge fence. Durable purge ownership lives in SQLite;
 * this coordinator closes the in-process race between a long download and
 * deletion of the same trip directory.
 */
export class TripVaultWriteCoordinator {
  private readonly states = new Map<string, TripVaultWriteState>();

  beginWrite(key: string): () => void {
    const state = this.state(key);
    if (state.purgePending) throw new TripVaultPurgeInProgressError();
    state.activeWrites += 1;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      state.activeWrites -= 1;
      if (state.activeWrites === 0) {
        for (const resolve of state.drainWaiters) resolve();
        state.drainWaiters.clear();
        this.removeIdleState(key, state);
      }
    };
  }

  async beginPurge(key: string): Promise<void> {
    const state = this.state(key);
    state.purgePending = true;
    state.activePurges += 1;
    if (state.activeWrites === 0) return;
    await new Promise<void>((resolve) => state.drainWaiters.add(resolve));
  }

  endPurgeAttempt(key: string): void {
    const state = this.states.get(key);
    if (!state || state.activePurges === 0) return;
    state.activePurges -= 1;
    this.finishAcknowledgedPurge(key, state);
  }

  completePurge(key: string): void {
    const state = this.states.get(key);
    if (!state) return;
    state.durablyAcknowledged = true;
    this.finishAcknowledgedPurge(key, state);
  }

  discardIdleMatching(prefix: string): void {
    for (const [key, state] of this.states) {
      if (
        key.startsWith(prefix) &&
        state.activeWrites === 0 &&
        state.activePurges === 0
      ) {
        this.states.delete(key);
      }
    }
  }

  private state(key: string): TripVaultWriteState {
    const existing = this.states.get(key);
    if (existing) return existing;
    const created: TripVaultWriteState = {
      activeWrites: 0,
      activePurges: 0,
      durablyAcknowledged: false,
      purgePending: false,
      drainWaiters: new Set(),
    };
    this.states.set(key, created);
    return created;
  }

  private removeIdleState(key: string, state: TripVaultWriteState): void {
    if (
      state.activeWrites === 0 &&
      state.activePurges === 0 &&
      !state.purgePending &&
      state.drainWaiters.size === 0
    ) {
      this.states.delete(key);
    }
  }

  private finishAcknowledgedPurge(key: string, state: TripVaultWriteState): void {
    if (state.durablyAcknowledged && state.activePurges === 0) {
      state.purgePending = false;
    }
    this.removeIdleState(key, state);
  }
}

const TRIP_KEY_SEPARATOR = '\u0000';

/** Coordinates account-wide logout cleanup with every trip-level vault operation. */
export class VaultWriteCoordinator {
  private readonly global = new TripVaultWriteCoordinator();
  private readonly namespaces = new TripVaultWriteCoordinator();
  private readonly trips = new TripVaultWriteCoordinator();
  private readonly namespacePurgeGlobalReleases = new Map<string, (() => void)[]>();

  private static readonly GLOBAL_KEY = 'gc-vault-root';

  beginDocumentWrite(namespace: string, tripId: string): () => void {
    const releaseGlobal = this.global.beginWrite(VaultWriteCoordinator.GLOBAL_KEY);
    let releaseNamespace: (() => void) | null = null;
    let releaseTrip: (() => void) | null = null;
    try {
      releaseNamespace = this.namespaces.beginWrite(namespace);
      releaseTrip = this.trips.beginWrite(this.tripKey(namespace, tripId));
    } catch (error) {
      releaseNamespace?.();
      releaseGlobal();
      throw error;
    }
    return () => {
      releaseTrip?.();
      releaseTrip = null;
      releaseNamespace?.();
      releaseNamespace = null;
      releaseGlobal();
    };
  }

  async beginTripPurge(namespace: string, tripId: string): Promise<() => void> {
    const releaseGlobal = this.global.beginWrite(VaultWriteCoordinator.GLOBAL_KEY);
    let releaseNamespace: (() => void) | null = null;
    try {
      releaseNamespace = this.namespaces.beginWrite(namespace);
      const key = this.tripKey(namespace, tripId);
      await this.trips.beginPurge(key);
      return () => {
        this.trips.endPurgeAttempt(key);
        releaseNamespace?.();
        releaseNamespace = null;
        releaseGlobal();
      };
    } catch (error) {
      releaseNamespace?.();
      releaseGlobal();
      throw error;
    }
  }

  completeTripPurge(namespace: string, tripId: string): void {
    this.trips.completePurge(this.tripKey(namespace, tripId));
  }

  async beginNamespacePurge(namespace: string): Promise<void> {
    const releaseGlobal = this.global.beginWrite(VaultWriteCoordinator.GLOBAL_KEY);
    try {
      await this.namespaces.beginPurge(namespace);
      const releases = this.namespacePurgeGlobalReleases.get(namespace) ?? [];
      releases.push(releaseGlobal);
      this.namespacePurgeGlobalReleases.set(namespace, releases);
    } catch (error) {
      releaseGlobal();
      throw error;
    }
  }

  finishNamespacePurge(namespace: string, acknowledged: boolean): void {
    this.namespaces.endPurgeAttempt(namespace);
    if (acknowledged) {
      this.namespaces.completePurge(namespace);
      // Namespace cleanup waited every download and trip purge through their
      // namespace leases, so obsolete per-trip pending fences can now be dropped.
      this.trips.discardIdleMatching(`${namespace}${TRIP_KEY_SEPARATOR}`);
    }
    const releases = this.namespacePurgeGlobalReleases.get(namespace);
    const releaseGlobal = releases?.shift();
    releaseGlobal?.();
    if (!releases?.length) this.namespacePurgeGlobalReleases.delete(namespace);
  }

  beginGlobalPurge(): Promise<void> {
    return this.global.beginPurge(VaultWriteCoordinator.GLOBAL_KEY);
  }

  finishGlobalPurge(acknowledged: boolean): void {
    this.global.endPurgeAttempt(VaultWriteCoordinator.GLOBAL_KEY);
    if (acknowledged) this.global.completePurge(VaultWriteCoordinator.GLOBAL_KEY);
  }

  private tripKey(namespace: string, tripId: string): string {
    return `${namespace}${TRIP_KEY_SEPARATOR}${tripId}`;
  }
}
