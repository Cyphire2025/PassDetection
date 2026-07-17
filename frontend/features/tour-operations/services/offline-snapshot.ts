import { useAuthStore } from "@/stores/auth.store";

export function readOfflineSnapshot<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  const scopedKey = getCurrentUserScopedKey(key);
  if (!scopedKey) return fallback;
  try {
    const value = window.localStorage.getItem(scopedKey);
    return value ? (JSON.parse(value) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function writeOfflineSnapshot<T>(key: string, value: T) {
  if (typeof window === "undefined") return;
  const scopedKey = getCurrentUserScopedKey(key);
  if (!scopedKey) return;
  try {
    window.localStorage.setItem(scopedKey, JSON.stringify(value));
  } catch {
    // Storage can be unavailable or full; live server data remains usable.
  }
}

export const offlineSnapshotKeys = {
  myGroups: "passdetection-tour-ops-my-groups",
  myPassengers: (groupId: string) => `passdetection-tour-ops-my-passengers:${groupId}`,
  mySessions: (groupId: string) => `passdetection-tour-ops-my-sessions:${groupId}`,
};

function getCurrentUserScopedKey(key: string) {
  const userId = useAuthStore.getState().user?.id;
  return userId ? `${key}:user:${userId}` : null;
}
