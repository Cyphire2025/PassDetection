import { applicationRouteTemplate } from "@/lib/navigation/application-route";

export type RenderErrorBoundary = "shared" | "route" | "global";
type ErrorKind = "Error" | "TypeError" | "RangeError" | "Unknown";
const MAX_PAGE_REPORTS = 10;
const reports = new Map<string, Promise<string | null>>();

function receiptId(receipt: unknown): string | null {
  const recordedId = typeof receipt === "object" && receipt !== null && "event_id" in receipt ? receipt.event_id : null;
  return typeof recordedId === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(recordedId)
    ? recordedId : null;
}

function errorKind(error: unknown): ErrorKind {
  if (error instanceof TypeError) return "TypeError";
  if (error instanceof RangeError) return "RangeError";
  return error instanceof Error ? "Error" : "Unknown";
}

/** Deliberately exclude messages, stacks, URL parameters, identifiers and user data. */
export function renderErrorMetadata(error: unknown, boundary: RenderErrorBoundary) {
  const configuredRelease = process.env.NEXT_PUBLIC_APP_REVISION ?? "unknown";
  return {
    route: applicationRouteTemplate(window.location.pathname),
    release: /^[A-Za-z0-9._-]{1,64}$/.test(configuredRelease) ? configuredRelease : "unknown",
    boundary,
    error_kind: errorKind(error),
  };
}

export function reportRenderError(error: unknown, boundary: RenderErrorBoundary): Promise<string | null> {
  if (typeof window === "undefined") return Promise.resolve(null);
  const metadata = renderErrorMetadata(error, boundary);
  const key = JSON.stringify(metadata);
  const prior = reports.get(key);
  if (prior) return prior;
  if (reports.size >= MAX_PAGE_REPORTS) return Promise.resolve(null);
  const report = send(metadata, key);
  reports.set(key, report);
  return report;
}

async function send(metadata: ReturnType<typeof renderErrorMetadata>, key: string): Promise<string | null> {
  try {
    const eventId = crypto.randomUUID();
    // The fingerprint groups only public metadata; hashing exception text could still leak PII.
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(key));
    const fingerprint = Array.from(new Uint8Array(digest).slice(0, 16), (byte) => byte.toString(16).padStart(2, "0")).join("");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 3_000);
    try {
      const response = await fetch("/api/v1/observability/frontend-errors", {
        method: "POST",
        credentials: "omit",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...metadata, event_id: eventId, fingerprint }),
        signal: controller.signal,
        cache: "no-store",
        referrerPolicy: "no-referrer",
      });
      // An unreceived event is not shown as a searchable support reference.
      if (response.status !== 202) return null;
      return receiptId(await response.json());
    } finally {
      window.clearTimeout(timeout);
    }
  } catch {
    // The error fallback remains usable when collection, crypto or the network fails.
    return null;
  }
}
