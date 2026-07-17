"use client";

/**
 * Coordinates rotating-cookie refresh across browser tabs.
 *
 * Axios' in-memory promise is sufficient within one tab, but two tabs share
 * the same httpOnly cookie. An exclusive browser lock plus a generation marker
 * ensures only one tab rotates that cookie for a given request generation.
 */

const REFRESH_LOCK_NAME = "passdetection-auth-refresh";
const REFRESH_EPOCH_KEY = "passdetection:auth-refresh-epoch";
const REFRESH_LEASE_KEY = "passdetection:auth-refresh-lease";
const LEASE_DURATION_MS = 12_000;
const LEASE_WAIT_LIMIT_MS = 25_000;

interface RefreshLease {
  owner: string;
  expiresAt: number;
}

interface BrowserLockManager {
  request<T>(
    name: string,
    options: { mode: "exclusive" },
    callback: () => Promise<T>,
  ): Promise<T>;
}

export function readRefreshEpoch() {
  if (typeof window === "undefined") return "server";
  try {
    return window.localStorage.getItem(REFRESH_EPOCH_KEY) ?? "initial";
  } catch {
    return "storage-unavailable";
  }
}

export async function runCoordinatedRefresh(
  observedEpoch: string,
  refresh: () => Promise<void>,
) {
  if (typeof window === "undefined") {
    await refresh();
    return;
  }

  const locks = (navigator as Navigator & { locks?: BrowserLockManager }).locks;
  if (locks) {
    await locks.request(
      REFRESH_LOCK_NAME,
      { mode: "exclusive" },
      () => refreshIfStillNeeded(observedEpoch, refresh),
    );
    return;
  }

  await withStorageLease(() => refreshIfStillNeeded(observedEpoch, refresh));
}

async function refreshIfStillNeeded(
  observedEpoch: string,
  refresh: () => Promise<void>,
) {
  if (readRefreshEpoch() !== observedEpoch) return;

  try {
    await refresh();
  } catch (error) {
    // A storage-lease fallback can overlap only if a tab is suspended beyond
    // the bounded lease. If another tab completed meanwhile, use its cookies.
    if (readRefreshEpoch() !== observedEpoch) return;
    throw error;
  }

  publishRefreshEpoch();
}

async function withStorageLease<T>(operation: () => Promise<T>): Promise<T> {
  let storage: Storage;
  try {
    storage = window.localStorage;
    storage.getItem(REFRESH_LEASE_KEY);
  } catch {
    return operation();
  }

  const owner = createOwnerId();
  const deadline = Date.now() + LEASE_WAIT_LIMIT_MS;

  while (Date.now() < deadline) {
    const current = readLease(storage);
    if (!current || current.expiresAt <= Date.now()) {
      const candidate: RefreshLease = {
        owner,
        expiresAt: Date.now() + LEASE_DURATION_MS,
      };
      storage.setItem(REFRESH_LEASE_KEY, JSON.stringify(candidate));
      if (readLease(storage)?.owner === owner) {
        try {
          return await operation();
        } finally {
          if (readLease(storage)?.owner === owner) {
            storage.removeItem(REFRESH_LEASE_KEY);
          }
        }
      }
    }
    await delay(75 + Math.round(Math.random() * 75));
  }

  // A refresh request itself is bounded at ten seconds, so reaching this
  // branch means a stale or continuously contended fallback lease. Do not
  // wait indefinitely; clear it and make the one bounded refresh attempt.
  storage.removeItem(REFRESH_LEASE_KEY);
  return operation();
}

function publishRefreshEpoch() {
  try {
    window.localStorage.setItem(
      REFRESH_EPOCH_KEY,
      `${Date.now()}:${createOwnerId()}`,
    );
  } catch {
    // Same-tab single flight remains available when storage is disabled.
  }
}

function readLease(storage: Storage): RefreshLease | null {
  try {
    const raw = storage.getItem(REFRESH_LEASE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<RefreshLease>;
    return typeof parsed.owner === "string" && typeof parsed.expiresAt === "number"
      ? { owner: parsed.owner, expiresAt: parsed.expiresAt }
      : null;
  } catch {
    return null;
  }
}

function createOwnerId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function delay(milliseconds: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));
}
