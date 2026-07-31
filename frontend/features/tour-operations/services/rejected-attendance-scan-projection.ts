export interface RejectedAttendanceScanStorageRecord {
  groupId?: string;
  sessionId: string;
  clientEventId: string;
  scannedAt: string;
  deviceId: string;
  ownerUserId: string;
  queuedAt: string;
  id: string;
  rejectedAt: string;
  errorCode: string;
}

interface RejectedAttendanceScanProjectionOptions {
  errorCode?: string;
  rejectedAt?: string;
  fallbackClientEventId?: string;
}

export function projectRejectedAttendanceScanForStorage(
  value: unknown,
  options: RejectedAttendanceScanProjectionOptions = {},
): RejectedAttendanceScanStorageRecord | null {
  if (!isRecord(value)) return null;

  const ownerUserId = requiredString(value.ownerUserId);
  const sessionId = requiredString(value.sessionId);
  const clientEventId = requiredString(value.clientEventId)
    ?? requiredString(options.fallbackClientEventId);
  if (!ownerUserId || !sessionId || !clientEventId) return null;

  const groupId = optionalString(value.groupId);
  const rejectedAt = requiredString(options.rejectedAt)
    ?? requiredString(value.rejectedAt)
    ?? new Date().toISOString();
  const queuedAt = requiredString(value.queuedAt) ?? rejectedAt;

  return {
    groupId,
    sessionId,
    clientEventId,
    scannedAt: requiredString(value.scannedAt) ?? queuedAt,
    deviceId: requiredString(value.deviceId) ?? "unknown",
    ownerUserId,
    queuedAt,
    id: `${ownerUserId}:${groupId ?? "legacy"}:${sessionId}:${clientEventId}`,
    rejectedAt,
    errorCode: requiredString(options.errorCode)
      ?? requiredString(value.errorCode)
      ?? "UNKNOWN",
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function requiredString(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function optionalString(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}
