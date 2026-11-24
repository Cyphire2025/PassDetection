/** Serialized browser-lock fixture, including queued cancellation and per-name isolation. */
export function installBrowserLocks() {
  const descriptor = Object.getOwnPropertyDescriptor(navigator, "locks");
  const tails = new Map<string, Promise<void>>();
  const manager = {
    request<T>(name: string, options: { signal?: AbortSignal }, callback: () => Promise<T>): Promise<T> {
      const previous = tails.get(name) ?? Promise.resolve();
      let release!: () => void;
      const tail = new Promise<void>((resolve) => { release = resolve; });
      tails.set(name, tail);
      return new Promise<T>((resolve, reject) => {
        let granted = false;
        let cancelled = options.signal?.aborted ?? false;
        const cancel = () => {
          if (granted) return;
          cancelled = true;
          reject(new DOMException("Lock request aborted", "AbortError"));
        };
        options.signal?.addEventListener("abort", cancel);
        if (cancelled) cancel();
        void previous.then(async () => {
          try {
            if (cancelled) return;
            granted = true;
            resolve(await callback());
          } catch (error) { reject(error); }
          finally {
            options.signal?.removeEventListener("abort", cancel);
            release();
            if (tails.get(name) === tail) tails.delete(name);
          }
        });
      });
    },
  };
  Object.defineProperty(navigator, "locks", { configurable: true, value: manager });
  return {
    manager,
    restore() {
      if (descriptor) Object.defineProperty(navigator, "locks", descriptor);
      else Reflect.deleteProperty(navigator, "locks");
    },
  };
}
