type RuntimeExecution = Readonly<{
  controller: AbortController;
  tripId: string;
  settled: Promise<void>;
  resolveSettled: () => void;
}>;

type NamespaceRuntimeState = {
  blocked: boolean;
  namespaceExclusive: boolean;
  activeSessionId: string | null;
  readonly executions: Set<RuntimeExecution>;
};

export type PhotoDownloadRuntimeLease = Readonly<{
  signal: AbortSignal;
  finish: () => void;
}>;

export class PhotoDownloadRuntimeLockedError extends Error {
  constructor() {
    super('My Photos runtime is locked for this account.');
    this.name = 'PhotoDownloadRuntimeLockedError';
  }
}

/** Fences the complete account-owned queue runtime, including recovery,
 * Download All enumeration, claims, transfers, reconciliation and cache
 * invalidation. Namespace lock remains closed until a later authenticated
 * runtime explicitly activates it. */
export class PhotoDownloadRuntimeRegistry {
  private readonly namespaces = new Map<string, NamespaceRuntimeState>();

  activateNamespace(namespace: string, sessionId: string): void {
    const state = this.state(namespace);
    this.assertSessionId(sessionId);
    if (state.blocked) {
      if (state.activeSessionId === sessionId) throw new PhotoDownloadRuntimeLockedError();
      if (state.executions.size > 0) {
        throw new Error('My Photos runtime cannot activate while an earlier account run is settling.');
      }
    } else if (
      state.activeSessionId !== null
      && state.activeSessionId !== sessionId
      && state.executions.size > 0
    ) {
      throw new Error('My Photos runtime cannot switch sessions while an earlier run is settling.');
    }
    state.activeSessionId = sessionId;
    state.blocked = false;
  }

  begin(
    namespace: string,
    sessionId: string,
    tripId: string,
    parent: AbortSignal,
  ): PhotoDownloadRuntimeLease {
    const state = this.state(namespace);
    this.assertSessionId(sessionId);
    this.assertTripId(tripId);
    if (!state.blocked && state.activeSessionId === null) state.activeSessionId = sessionId;
    if (
      state.blocked
      || state.activeSessionId !== sessionId
      || state.namespaceExclusive
    ) {
      throw new PhotoDownloadRuntimeLockedError();
    }
    const controller = new AbortController();
    let resolveSettled!: () => void;
    const settled = new Promise<void>((resolve) => { resolveSettled = resolve; });
    const execution = { controller, tripId, settled, resolveSettled };
    state.executions.add(execution);
    let finished = false;
    return {
      signal: AbortSignal.any([parent, controller.signal]),
      finish: () => {
        if (finished) return;
        finished = true;
        state.executions.delete(execution);
        resolveSettled();
      },
    };
  }

  /** Temporarily closes the complete account namespace, aborts and settles
   * every producer/consumer, then runs a destructive operation alone. The
   * global plaintext-view cache is shared by trips, so a trip-only fence would
   * permit another trip to recreate a file while the cache is being swept. */
  async runExclusiveNamespace<T>(
    namespace: string,
    sessionId: string,
    tripId: string,
    parent: AbortSignal,
    reason: Error,
    operation: (signal: AbortSignal) => Promise<T>,
    timeoutMs = 30_000,
  ): Promise<T> {
    const state = this.state(namespace);
    this.assertSessionId(sessionId);
    this.assertTripId(tripId);
    if (!state.blocked && state.activeSessionId === null) state.activeSessionId = sessionId;
    if (
      state.blocked
      || state.activeSessionId !== sessionId
      || state.namespaceExclusive
    ) {
      throw new PhotoDownloadRuntimeLockedError();
    }

    // Closing the namespace before the first await is the producer race fence.
    state.namespaceExclusive = true;
    const priorExecutions = [...state.executions];
    const controller = new AbortController();
    let resolveSettled!: () => void;
    const settled = new Promise<void>((resolve) => { resolveSettled = resolve; });
    const exclusiveExecution = { controller, tripId, settled, resolveSettled };
    state.executions.add(exclusiveExecution);
    for (const execution of priorExecutions) execution.controller.abort(reason);

    const signal = AbortSignal.any([parent, controller.signal]);
    let priorExecutionsSettled = priorExecutions.length === 0;
    const priorSettlement = Promise.all(
      priorExecutions.map((execution) => execution.settled),
    ).then(() => {
      priorExecutionsSettled = true;
    });
    let released = false;
    const releaseExclusive = (): void => {
      if (released) return;
      released = true;
      state.executions.delete(exclusiveExecution);
      state.namespaceExclusive = false;
      resolveSettled();
    };
    let timeout: ReturnType<typeof setTimeout> | null = null;
    try {
      if (priorExecutions.length > 0) {
        await Promise.race([
          priorSettlement,
          new Promise<never>((_resolve, reject) => {
            timeout = setTimeout(
              () => reject(new Error('My Photos runtime did not settle before storage clearing.')),
              timeoutMs,
            );
          }),
        ]);
      }
      if (signal.aborted) {
        throw signal.reason instanceof Error
          ? signal.reason
          : new Error('My Photos storage clearing was cancelled.');
      }
      const result = await operation(signal);
      if (signal.aborted || state.activeSessionId !== sessionId) {
        throw signal.reason instanceof Error
          ? signal.reason
          : new Error('The authenticated My Photos session changed during storage clearing.');
      }
      return result;
    } finally {
      if (timeout) clearTimeout(timeout);
      if (priorExecutionsSettled) {
        releaseExclusive();
      } else {
        // A timed-out predecessor must not cause an unsafe same-session reopen.
        // Keep the trip closed and the exclusive execution visible to account
        // locking until the predecessor eventually acknowledges cancellation.
        void priorSettlement.then(releaseExclusive, releaseExclusive);
      }
    }
  }

  async abortNamespaceAndWait(
    namespace: string,
    reason: Error,
    timeoutMs = 30_000,
  ): Promise<void> {
    const state = this.state(namespace);
    // Synchronous closure is the critical race fence: after this line no
    // listener, rerun or timer can begin another database/queue operation.
    state.blocked = true;
    const executions = [...state.executions];
    for (const execution of executions) execution.controller.abort(reason);
    if (!executions.length) return;
    let timeout: ReturnType<typeof setTimeout> | null = null;
    try {
      await Promise.race([
        Promise.all(executions.map((execution) => execution.settled)).then(() => undefined),
        new Promise<never>((_resolve, reject) => {
          timeout = setTimeout(
            () => reject(new Error('My Photos runtime did not settle before the account locked.')),
            timeoutMs,
          );
        }),
      ]);
    } finally {
      if (timeout) clearTimeout(timeout);
    }
  }

  private state(namespace: string): NamespaceRuntimeState {
    if (!namespace || namespace.length > 512) {
      throw new Error('My Photos runtime namespace is invalid.');
    }
    const existing = this.namespaces.get(namespace);
    if (existing) return existing;
    const created: NamespaceRuntimeState = {
      blocked: false,
      namespaceExclusive: false,
      activeSessionId: null,
      executions: new Set(),
    };
    this.namespaces.set(namespace, created);
    return created;
  }

  private assertSessionId(sessionId: string): void {
    if (!sessionId || sessionId.length > 512) {
      throw new Error('My Photos runtime session is invalid.');
    }
  }

  private assertTripId(tripId: string): void {
    if (!tripId || tripId.length > 128) {
      throw new Error('My Photos runtime trip is invalid.');
    }
  }
}
