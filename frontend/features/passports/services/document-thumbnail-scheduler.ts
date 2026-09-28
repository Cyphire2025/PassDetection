const PASSPORT_IMAGE_PATH = /^\/api\/v1\/passports\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/images\/(?:visa_photo|passport_front|passport_back|passport_cover|passport_back_cover)\/?$/i;
const LEGACY_COVER_PATH = /^(\/api\/v1\/passports\/[0-9a-f-]{36})\/covers\/(cover|back_cover)\/?$/i;

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
let nextStartAt = 0;
let pausedUntil = 0;
let startIntervalMs = 40;
let wakeTimer: ReturnType<typeof setTimeout> | null = null;

function abortError() {
  const error = new Error("Document thumbnail request was cancelled.");
  error.name = "AbortError";
  return error;
}

function removePendingSlot(pending: PendingSlot) {
  const index = pendingSlots.indexOf(pending);
  if (index >= 0) pendingSlots.splice(index, 1);
  drainQueue();
}

function drainQueue() {
  if (wakeTimer !== null) {
    globalThis.clearTimeout(wakeTimer);
    wakeTimer = null;
  }
  while (
    activeSlots < DOCUMENT_THUMBNAIL_MAX_CONCURRENCY
    && pendingSlots.length > 0
  ) {
    const delay = Math.max(nextStartAt, pausedUntil) - Date.now();
    if (delay > 0) {
      wakeTimer = globalThis.setTimeout(drainQueue, delay);
      return;
    }
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
    nextStartAt = Date.now() + startIntervalMs;
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
 * image response has been consumed (or the load/error event for a direct URL).
 * Start times are paced as well as concurrency, including for cached thumbnails.
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
  const imagePath = path.replace(LEGACY_COVER_PATH, "$1/images/passport_$2");
  if (!PASSPORT_IMAGE_PATH.test(imagePath)) return url;
  return `${imagePath.replace(/\/$/, "")}/thumbnail${query}`;
}

export function isManagedDocumentThumbnail(url: string): boolean {
  const path = url.split("?")[0];
  return path.endsWith("/thumbnail") && PASSPORT_IMAGE_PATH.test(path.slice(0, -10));
}

/** Adapt every queued preview to the account's actual server-side allowance. */
export function updateDocumentThumbnailAllowance(headers: Headers) {
  const refill = Number(headers.get("X-RateLimit-Refill-Per-Second"));
  const limit = Number(headers.get("X-RateLimit-Limit"));
  const resetAfter = Number(headers.get("X-RateLimit-Reset-After"));
  if (Number.isFinite(refill) && refill > 0) {
    // Leave headroom for full-size images and other tabs using this account.
    startIntervalMs = Math.max(20, Math.ceil(1_000 / (refill * 0.8)));
    if (limit > 0 && resetAfter > 0) {
      startIntervalMs = Math.max(startIntervalMs, Math.ceil(60_000 / (limit * 0.8)));
    }
  }
  if (headers.get("X-RateLimit-Remaining") === "0" && resetAfter > 0) {
    pauseDocumentThumbnails(resetAfter * 1_000);
  }
}

export function pauseDocumentThumbnails(delayMs: number) {
  pausedUntil = Math.max(pausedUntil, Date.now() + delayMs);
  drainQueue();
}
