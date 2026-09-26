const STORAGE_KEY = "passdetection-coordinator-device-id";
let transientDeviceId: string | undefined;

/** A correlation ID, never an authorization credential. Survives storage denial per tab. */
export function getCoordinatorDeviceId(): string {
  try {
    const existing = window.localStorage.getItem(STORAGE_KEY);
    if (existing) return existing;
  } catch {
    // Storage may be disabled by browser policy; scanning must still work.
  }
  transientDeviceId ??= typeof globalThis.crypto?.randomUUID === "function"
    ? globalThis.crypto.randomUUID()
    : `device-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  try {
    window.localStorage.setItem(STORAGE_KEY, transientDeviceId);
  } catch {
    // Reuse the in-memory ID for subsequent scans rather than changing identity.
  }
  return transientDeviceId;
}
