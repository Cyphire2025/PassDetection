/**
 * Browser session state
 * =====================
 * Coordinates cleanup for data that must never survive an account change or
 * logout. The owner-scoped attendance queue is deliberately excluded: auth
 * loss preserves it for same-account recovery, while queue APIs fence access
 * to the currently authenticated owner. Authentication cookies remain
 * backend-owned and httpOnly.
 */

export const SENSITIVE_STATE_RESET_EVENT = "passdetection:sensitive-state-reset";

const SESSION_OWNER_KEY = "passdetection:session-owner";
const SESSION_RESET_CHANNEL = "passdetection-session-reset";
const SESSION_RESET_STORAGE_KEY = "pd:session-reset";
const APP_STORAGE_PREFIX = "passdetection";
const APP_CACHE_PREFIX = "passdetection-";

export type SensitiveStateResetReason = "account_changed" | "logout" | "session_expired";

export function prepareSensitiveBrowserStateForUser(userId: string) {
  if (typeof window === "undefined") return;

  try {
    const previousOwner = window.localStorage.getItem(SESSION_OWNER_KEY);
    const hasLegacySensitiveState = previousOwner === null && hasAppOwnedStorage();
    const accountChanged = previousOwner !== null && previousOwner !== userId;

    if (accountChanged || hasLegacySensitiveState) {
      clearAppOwnedWebStorage();
      dispatchSensitiveStateReset("account_changed");
      void clearPersistentAppData();
    }

    window.localStorage.setItem(SESSION_OWNER_KEY, userId);
  } catch {
    // Browsers can disable storage independently of cookies. Authentication
    // remains usable; no offline snapshot can be read in that mode.
  }
}

export async function clearSensitiveBrowserState(
  reason: SensitiveStateResetReason,
  notifyOtherTabs = true,
) {
  if (typeof window === "undefined") return;

  try {
    clearAppOwnedWebStorage();
  } catch {
    // Continue with in-memory/query cleanup even if browser storage is denied.
  }
  dispatchSensitiveStateReset(reason);
  if (notifyOtherTabs) broadcastSessionReset(reason);
  await clearPersistentAppData();
}

export async function clearServerSessionCookies() {
  if (typeof window === "undefined") return;

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 3_000);
  try {
    await window.fetch("/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      keepalive: true,
      signal: controller.signal,
    });
  } catch {
    // Local state must still be cleared if the network is unavailable.
  } finally {
    window.clearTimeout(timeout);
  }
}

export function dispatchSensitiveStateReset(reason: SensitiveStateResetReason) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(SENSITIVE_STATE_RESET_EVENT, {
      detail: { reason },
    }),
  );
}

export function subscribeToSessionResets(
  listener: (reason: SensitiveStateResetReason) => void,
) {
  if (typeof window === "undefined") return () => undefined;

  const handleStorage = (event: StorageEvent) => {
    if (event.key !== SESSION_RESET_STORAGE_KEY || !event.newValue) return;
    const reason = parseResetReason(event.newValue);
    if (reason) listener(reason);
  };
  window.addEventListener("storage", handleStorage);

  let channel: BroadcastChannel | null = null;
  if ("BroadcastChannel" in window) {
    channel = new BroadcastChannel(SESSION_RESET_CHANNEL);
    channel.onmessage = (event: MessageEvent<unknown>) => {
      const reason = parseResetReason(event.data);
      if (reason) listener(reason);
    };
  }

  return () => {
    window.removeEventListener("storage", handleStorage);
    channel?.close();
  };
}

function broadcastSessionReset(reason: SensitiveStateResetReason) {
  const payload = JSON.stringify({ reason, at: Date.now() });
  try {
    const channel = new BroadcastChannel(SESSION_RESET_CHANNEL);
    channel.postMessage(payload);
    channel.close();
  } catch {
    // The storage event below is the compatibility path.
  }
  try {
    window.localStorage.setItem(SESSION_RESET_STORAGE_KEY, payload);
    window.localStorage.removeItem(SESSION_RESET_STORAGE_KEY);
  } catch {
    // Same-tab state has already been cleared.
  }
}

function parseResetReason(value: unknown): SensitiveStateResetReason | null {
  try {
    const parsed = typeof value === "string" ? JSON.parse(value) : value;
    const reason = (parsed as { reason?: unknown } | null)?.reason;
    return reason === "account_changed"
      || reason === "logout"
      || reason === "session_expired"
      ? reason
      : null;
  } catch {
    return null;
  }
}

function hasAppOwnedStorage() {
  return storageHasAppOwnedKey(window.localStorage) || storageHasAppOwnedKey(window.sessionStorage);
}

function storageHasAppOwnedKey(storage: Storage) {
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key?.startsWith(APP_STORAGE_PREFIX) && key !== SESSION_OWNER_KEY) {
      return true;
    }
  }
  return false;
}

function clearAppOwnedWebStorage() {
  removeAppOwnedKeys(window.localStorage);
  removeAppOwnedKeys(window.sessionStorage);
}

function removeAppOwnedKeys(storage: Storage) {
  const keys: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key?.startsWith(APP_STORAGE_PREFIX)) keys.push(key);
  }
  keys.forEach((key) => storage.removeItem(key));
}

async function clearPersistentAppData() {
  const tasks: Promise<unknown>[] = [];

  // Snapshot cleanup is deliberately store-specific. The owner-scoped
  // attendance queue and unsynchronized discard evidence live in separate
  // stores and must survive authentication loss/account recovery.
  tasks.push(
    import("@/features/tour-operations/services/offline-snapshot")
      .then(({ purgeAllCoordinatorOfflineSnapshots }) => (
        purgeAllCoordinatorOfflineSnapshots()
      )),
    import("@/features/tour-operations/services/browser-offline-authorization")
      .then(({ purgeAllBrowserOfflineAuthorizations }) => (
        purgeAllBrowserOfflineAuthorizations()
      )),
  );

  if ("caches" in window) {
    tasks.push(
      window.caches.keys().then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(APP_CACHE_PREFIX))
            .map((key) => window.caches.delete(key)),
        ),
      ),
    );
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.controller?.postMessage({ type: "CLEAR_SENSITIVE_CACHES" });
  }

  await Promise.allSettled(tasks);
}
