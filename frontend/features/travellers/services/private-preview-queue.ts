/** At most two private image transfers per browser tab; no byte cache. */
let running = 0;
const waiting: Array<() => void> = [];

export async function queuedPrivatePreview<T>(load: () => Promise<T>, signal: AbortSignal): Promise<T> {
  if (running < 2) running++;
  else await new Promise<void>((resolve, reject) => {
    const abort = () => { const index = waiting.indexOf(start); if (index >= 0) waiting.splice(index, 1); reject(new DOMException("Aborted", "AbortError")); };
    const start = () => { signal.removeEventListener("abort", abort); resolve(); };
    waiting.push(start);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
  try {
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    return await load();
  } finally {
    const next = waiting.shift();
    if (next) next(); else running--;
  }
}
