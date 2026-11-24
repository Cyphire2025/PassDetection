import { SCANNER_PATH_PATTERN, SESSION_OWNER_KEY, UUID_PATTERN } from './constants.js';

export function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isUuid(value) {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

export function requiredString(value) {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function validIso(value) {
  return typeof value === "string" && Number.isFinite(Date.parse(value))
    ? value
    : null;
}

export function parseRequiredInstant(value) {
  const parsed = typeof value === "string" ? Date.parse(value) : Number.NaN;
  if (!Number.isFinite(parsed)) throw new Error("Signed time is invalid.");
  return parsed;
}

export function isScanReference(value) {
  return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
}

export function secureRandomUuid() {
  if (typeof window.crypto?.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

export function createClientEventId() {
  return secureRandomUuid();
}

export function readCurrentOwner() {
  try {
    const value = window.localStorage.getItem(SESSION_OWNER_KEY);
    return value && UUID_PATTERN.test(value) ? value : null;
  } catch {
    return null;
  }
}

export function readRequestedSelection() {
  const pathMatch = window.location.pathname.match(SCANNER_PATH_PATTERN);
  const groupId = pathMatch?.[1] && UUID_PATTERN.test(pathMatch[1])
    ? pathMatch[1]
    : null;
  const requestedSessionId = new URLSearchParams(window.location.search).get("sessionId");
  return {
    groupId,
    sessionId: requestedSessionId && UUID_PATTERN.test(requestedSessionId)
      ? requestedSessionId
      : null,
  };
}
