import { useAuthStore } from "@/stores/auth.store";

export const SCHEDULE_EVENT = "passdetection:attendance-queue-schedule-changed";

export const SCHEDULE_CHANNEL = "passdetection-attendance-queue-schedule";

export const MIGRATION_LOCK = "passdetection-attendance-queue-v4-migration";

export const OWNER_LOCK_PREFIX = "passdetection-attendance-owner";

export const DRAIN_LOCK_PREFIX = "passdetection-attendance-drain";

export const fallbackOwnerLanes = new Map<string, Promise<void>>();

export function subscribeAttendanceQueueScheduleChanges(listener: () => void) {
  if (typeof window === "undefined") return () => undefined;
  const handle = () => listener();
  window.addEventListener(SCHEDULE_EVENT, handle);
  let channel: BroadcastChannel | null = null;
  if ("BroadcastChannel" in window) {
    channel = new BroadcastChannel(SCHEDULE_CHANNEL);
    channel.onmessage = handle;
  }
  return () => {
    window.removeEventListener(SCHEDULE_EVENT, handle);
    channel?.close();
  };
}

export function getCurrentUserId() {
  return useAuthStore.getState().user?.id ?? null;
}

export function requireCurrentUserId() {
  const userId = getCurrentUserId();
  if (!userId) throw new Error("An authenticated coordinator session is required.");
  return userId;
}

export function assertCurrentOwner(ownerUserId: string) {
  if (getCurrentUserId() !== ownerUserId) {
    throw new Error("The authenticated attendance queue owner changed.");
  }
}

export function assertAuthenticationSnapshotCurrent(
  authentication: Readonly<{ sessionVersion: number; userId: string }>,
) {
  const current = useAuthStore.getState();
  if (
    current.user?.id !== authentication.userId
    || current.sessionVersion !== authentication.sessionVersion
  ) {
    throw new Error("The coordinator account changed while queue evidence was collected.");
  }
}

export function announceScheduleChanged() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(SCHEDULE_EVENT));
  if ("BroadcastChannel" in window) {
    const channel = new BroadcastChannel(SCHEDULE_CHANNEL);
    channel.postMessage({ changed: true });
    channel.close();
  }
}

export async function withOwnerQueueLock<T>(
  ownerUserId: string,
  task: () => Promise<T>,
): Promise<T> {
  return withBrowserLock(`${OWNER_LOCK_PREFIX}:${ownerUserId}`, task);
}

export async function withBrowserLock<T>(name: string, task: () => Promise<T>): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.locks?.request) {
    return navigator.locks.request(name, { mode: "exclusive" }, task);
  }

  const previous = fallbackOwnerLanes.get(name) ?? Promise.resolve();
  let release: () => void = () => undefined;
  const tail = new Promise<void>((resolve) => {
    release = resolve;
  });
  const queued = previous.catch(() => undefined).then(() => tail);
  fallbackOwnerLanes.set(name, queued);
  await previous.catch(() => undefined);
  try {
    return await task();
  } finally {
    release();
    if (fallbackOwnerLanes.get(name) === queued) fallbackOwnerLanes.delete(name);
  }
}
