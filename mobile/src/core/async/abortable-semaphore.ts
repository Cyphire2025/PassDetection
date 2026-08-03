type Waiter = {
  resolve: () => void;
  reject: (reason: Error) => void;
  signal?: AbortSignal;
  onAbort?: () => void;
};

function defaultAbortError(signal?: AbortSignal): Error {
  if (signal?.reason instanceof Error) return signal.reason;
  const error = new Error('Operation was cancelled.');
  error.name = 'AbortError';
  return error;
}

/** FIFO, cancellation-aware concurrency limiter with direct permit handoff. */
export class AbortableSemaphore {
  private active = 0;
  private readonly waiters: Waiter[] = [];

  constructor(
    private readonly capacity: number,
    private readonly abortError: (signal?: AbortSignal) => Error = defaultAbortError,
  ) {
    if (!Number.isSafeInteger(capacity) || capacity < 1) {
      throw new Error('Semaphore capacity must be a positive integer.');
    }
  }

  async acquire(signal?: AbortSignal): Promise<() => void> {
    if (signal?.aborted) throw this.abortError(signal);
    if (this.active < this.capacity) {
      this.active += 1;
      if (signal?.aborted) {
        this.releasePermit();
        throw this.abortError(signal);
      }
    } else {
      await new Promise<void>((resolve, reject) => {
        const waiter: Waiter = { resolve, reject, ...(signal ? { signal } : {}) };
        this.waiters.push(waiter);
        if (signal) {
          waiter.onAbort = () => {
            const index = this.waiters.indexOf(waiter);
            if (index >= 0) this.waiters.splice(index, 1);
            signal.removeEventListener('abort', waiter.onAbort!);
            reject(this.abortError(signal));
          };
          signal.addEventListener('abort', waiter.onAbort, { once: true });
          // Close the small race between the initial check and listener registration.
          if (signal.aborted) waiter.onAbort();
        }
      });
      if (signal?.aborted) {
        this.releasePermit();
        throw this.abortError(signal);
      }
    }

    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.releasePermit();
    };
  }

  private releasePermit(): void {
    while (this.waiters.length) {
      const waiter = this.waiters.shift();
      if (!waiter) break;
      if (waiter.onAbort) waiter.signal?.removeEventListener('abort', waiter.onAbort);
      if (waiter.signal?.aborted) {
        waiter.reject(this.abortError(waiter.signal));
        continue;
      }
      // Transfer the reservation directly. Keeping active unchanged closes the race where a new
      // caller could steal the permit before this queued waiter resumes.
      waiter.resolve();
      return;
    }
    this.active = Math.max(0, this.active - 1);
  }
}
