/** Only opaque IDs are persisted. Notification text, audiences and preview tokens stay out of browser storage. */
export interface PendingNotificationSend {
  request_id: string;
  draft_id: string;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const pendingSendKey = (agencyId: string, actorId: string) => `gc-app:pending-notification:${agencyId}:${actorId}`;

export function readPendingSend(key: string): PendingNotificationSend | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object") return null;
    const entry = value as Partial<PendingNotificationSend>;
    if (typeof entry.request_id !== "string" || typeof entry.draft_id !== "string" || !UUID.test(entry.request_id) || !UUID.test(entry.draft_id)) return null;
    return { request_id: entry.request_id, draft_id: entry.draft_id };
  } catch { return null; }
}

export function persistPendingSend(key: string, value: PendingNotificationSend): void {
  window.sessionStorage.setItem(key, JSON.stringify({ request_id: value.request_id, draft_id: value.draft_id }));
}

export function clearPendingSend(key: string): void {
  window.sessionStorage.removeItem(key);
}
