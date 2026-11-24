export function gcAppErrorMessage(error: unknown, fallback: string): string {
  if (
    typeof error === "object"
    && error !== null
    && "message" in error
    && typeof error.message === "string"
    && error.message.trim()
  ) {
    return error.message.slice(0, 300);
  }
  return fallback;
}

export function gcSessionState(session: { status: string; revoked_at: string | null; expires_at: string | null }, now: number): string {
  if (session.revoked_at || session.status === "revoked") return "Revoked";
  if (session.status === "expired" || (session.expires_at && Date.parse(session.expires_at) <= now)) return "Expired";
  const state = session.status.replaceAll("_", " ");
  return state ? state.charAt(0).toUpperCase() + state.slice(1) : "Unknown";
}

export function formatGcDateTime(value: string | null): string {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not available";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function toApiDateTime(localValue: string): string | null {
  if (!localValue) return null;
  const date = new Date(localValue);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function toLocalDateTime(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function createClientId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

export function gcPublicationState(item: {
  is_published: boolean;
  available_from: string | null;
  available_until: string | null;
}, now: number): { label: string; variant: "outline" | "success" | "warning" } {
  if (!item.is_published) return { label: "Draft", variant: "outline" };
  if (item.available_until && Date.parse(item.available_until) <= now) return { label: "Expired", variant: "warning" };
  if (item.available_from && Date.parse(item.available_from) > now) return { label: "Scheduled", variant: "outline" };
  return { label: "Published", variant: "success" };
}
