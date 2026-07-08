export function readOfflineSnapshot<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const value = window.localStorage.getItem(key);
    return value ? (JSON.parse(value) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function writeOfflineSnapshot<T>(key: string, value: T) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key, JSON.stringify(value));
}

export const offlineSnapshotKeys = {
  myGroups: "passdetection-tour-ops-my-groups",
  myPassengers: (groupId: string) => `passdetection-tour-ops-my-passengers:${groupId}`,
};
