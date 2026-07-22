const PASSPORT_IMAGE_PATH = /^\/api\/v1\/passports\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/images\/(?:visa_photo|passport_front|passport_back)\/?$/i;

export const DOCUMENT_THUMBNAIL_MAX_CONCURRENCY = 6;

type ReleaseSlot = () => void;

interface PendingSlot {
  signal?: AbortSignal;
  resolve: (release: ReleaseSlot) => void;
  reject: (reason: Error) => void;
  abortListener?: () => void;
}

let activeSlots = 0;
const pendingSlots: PendingSlot[] = [];

function abortError() {
  const error = new Error("Document thumbnail request was cancelled.");
  error.name = "AbortError";
  return error;
}

function removePendingSlot(pending: PendingSlot) {
  const index = pendingSlots.indexOf(pending);
  if (index >= 0) pendingSlots.splice(index, 1);
}

function drainQueue() {
  while (
    activeSlots < DOCUMENT_THUMBNAIL_MAX_CONCURRENCY
    && pendingSlots.length > 0
  ) {
    const pending = pendingSlots.shift();
    if (!pending) return;
    if (pending.abortListener && pending.signal) {
      pending.signal.removeEventListener("abort", pending.abortListener);
    }
    if (pending.signal?.aborted) {
      pending.reject(abortError());
      continue;
    }

    activeSlots += 1;
    let released = false;
    pending.resolve(() => {
      if (released) return;
      released = true;
      activeSlots = Math.max(0, activeSlots - 1);
      globalThis.queueMicrotask(drainQueue);
    });
  }
}

/**
 * Acquire one browser-wide image slot. A slot stays active until the caller's
 * image load/error event fires, which bounds real network concurrency rather
 * than just the number of mounted React components.
 */
export function acquireDocumentThumbnailSlot(
  signal?: AbortSignal,
): Promise<ReleaseSlot> {
  if (signal?.aborted) return Promise.reject(abortError());

  return new Promise<ReleaseSlot>((resolve, reject) => {
    const pending: PendingSlot = { signal, resolve, reject };
    if (signal) {
      pending.abortListener = () => {
        removePendingSlot(pending);
        reject(abortError());
      };
      signal.addEventListener("abort", pending.abortListener, { once: true });
    }
    pendingSlots.push(pending);
    drainQueue();
  });
}

/** Convert only server-owned same-origin passport image paths to thumbnails. */
export function documentThumbnailUrl(url: string): string {
  const queryIndex = url.indexOf("?");
  const path = queryIndex >= 0 ? url.slice(0, queryIndex) : url;
  const query = queryIndex >= 0 ? url.slice(queryIndex) : "";
  if (!PASSPORT_IMAGE_PATH.test(path)) return url;
  return `${path.replace(/\/$/, "")}/thumbnail${query}`;
}
