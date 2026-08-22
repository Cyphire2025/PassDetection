const MAX_RETRY_AFTER_MS = 15 * 60 * 1_000;

/**
 * Parse the standard Retry-After delta-seconds or HTTP-date forms. The value
 * is bounded so a malformed/upstream response cannot strand a durable queue
 * indefinitely.
 */
export function parseRetryAfterMs(
  value: unknown,
  nowMs = Date.now(),
): number | undefined {
  const candidate = Array.isArray(value) ? value[0] : value;
  if (typeof candidate !== "string" && typeof candidate !== "number") {
    return undefined;
  }

  const normalized = String(candidate).trim();
  if (!normalized) return undefined;

  let delayMs: number;
  if (/^\d+(?:\.\d+)?$/.test(normalized)) {
    delayMs = Number(normalized) * 1_000;
  } else {
    const retryAtMs = Date.parse(normalized);
    if (!Number.isFinite(retryAtMs)) return undefined;
    delayMs = retryAtMs - nowMs;
  }

  if (!Number.isFinite(delayMs)) return undefined;
  return Math.min(MAX_RETRY_AFTER_MS, Math.max(0, Math.ceil(delayMs)));
}

export function retryAfterHeaderValue(headers: unknown): unknown {
  if (!headers || typeof headers !== "object") return undefined;
  const maybeHeaders = headers as {
    get?: (name: string) => unknown;
    [key: string]: unknown;
  };
  if (typeof maybeHeaders.get === "function") {
    const value = maybeHeaders.get("retry-after");
    if (value !== undefined && value !== null) return value;
  }
  return maybeHeaders["retry-after"] ?? maybeHeaders["Retry-After"];
}
