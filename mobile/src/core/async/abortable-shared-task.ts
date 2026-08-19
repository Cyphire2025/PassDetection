type SharedTaskEntry<T> = {
  controller: AbortController;
  consumers: number;
  promise: Promise<T>;
  settled: boolean;
};

function abortError(signal: AbortSignal): Error {
  return signal.reason instanceof Error
    ? signal.reason
    : new Error('The operation was cancelled.');
}

/**
 * Coalesces identical expensive work without making one caller's cancellation
 * cancel work that another active caller still needs.
 *
 * The underlying task is aborted only after every joined consumer has left.
 * Entries are removed after settlement, so failures never poison future runs.
 */
export class AbortableSharedTaskRegistry<Key, Value> {
  private readonly entries = new Map<Key, SharedTaskEntry<Value>>();

  run(
    key: Key,
    task: (signal: AbortSignal) => Promise<Value>,
    signal?: AbortSignal,
  ): Promise<Value> {
    if (signal?.aborted) return Promise.reject(abortError(signal));

    let entry = this.entries.get(key);
    if (!entry) {
      const controller = new AbortController();
      const created: SharedTaskEntry<Value> = {
        controller,
        consumers: 0,
        promise: Promise.resolve().then(() => task(controller.signal)),
        settled: false,
      };
      entry = created;
      this.entries.set(key, created);
      void created.promise.finally(() => {
        created.settled = true;
        if (this.entries.get(key) === created) this.entries.delete(key);
      }).catch(() => undefined);
    }

    const joined = entry;
    joined.consumers += 1;
    return new Promise<Value>((resolve, reject) => {
      let finished = false;
      const finish = (complete: () => void): void => {
        if (finished) return;
        finished = true;
        signal?.removeEventListener('abort', onAbort);
        joined.consumers -= 1;
        if (joined.consumers === 0 && !joined.settled && !joined.controller.signal.aborted) {
          joined.controller.abort(new Error('Every consumer cancelled the shared operation.'));
        }
        complete();
      };
      const onAbort = (): void => finish(() => reject(abortError(signal!)));

      signal?.addEventListener('abort', onAbort, { once: true });
      if (signal?.aborted) {
        onAbort();
        return;
      }
      joined.promise.then(
        (value) => finish(() => resolve(value)),
        (error: unknown) => finish(() => reject(error)),
      );
    });
  }
}
