export const ATTENDANCE_SCAN_REFERENCE_PREFIX = "sha256:";

export interface AttendanceTerminalScanSource {
  scanReference: string;
  ownerUserId: string;
  groupId?: string;
  sessionId: string;
  clientEventId: string;
  scannedAt: string;
  deviceId: string;
  queuedAt: string;
}

export interface SanitizedRejectedAttendanceScan extends AttendanceTerminalScanSource {
  id: string;
  rejectedAt: string;
  errorCode: string;
}

export async function createAttendanceScanReference({
  ownerUserId,
  groupId,
  sessionId,
  qrPayload,
}: {
  ownerUserId: string;
  groupId?: string;
  sessionId: string;
  qrPayload: string;
}) {
  return hashAttendanceReference([
    "attendance-scan-v4",
    ownerUserId,
    groupId ?? "legacy-group",
    sessionId,
    qrPayload,
  ]);
}

export function attendanceQueueRowId(scanReference: string) {
  return `attendance-scan:${scanReference}`;
}

export function createRejectedAttendanceScan(
  scan: AttendanceTerminalScanSource,
  errorCode: string,
  rejectedAt = new Date().toISOString(),
): SanitizedRejectedAttendanceScan {
  return {
    id: `attendance-rejected:${scan.scanReference}`,
    scanReference: scan.scanReference,
    ownerUserId: scan.ownerUserId,
    ...(scan.groupId ? { groupId: scan.groupId } : {}),
    sessionId: scan.sessionId,
    clientEventId: scan.clientEventId,
    scannedAt: scan.scannedAt,
    deviceId: scan.deviceId,
    queuedAt: scan.queuedAt,
    rejectedAt,
    errorCode,
  };
}

export async function sanitizeLegacyRejectedAttendanceScan(
  candidate: Record<string, unknown>,
): Promise<SanitizedRejectedAttendanceScan | null> {
  const ownerUserId = requiredString(candidate.ownerUserId);
  const sessionId = requiredString(candidate.sessionId);
  const clientEventId = requiredString(candidate.clientEventId);
  const scannedAt = requiredString(candidate.scannedAt);
  const deviceId = requiredString(candidate.deviceId);
  const queuedAt = requiredString(candidate.queuedAt);
  const rejectedAt = requiredString(candidate.rejectedAt);
  const errorCode = requiredString(candidate.errorCode);
  if (
    !ownerUserId
    || !sessionId
    || !clientEventId
    || !scannedAt
    || !deviceId
    || !queuedAt
    || !rejectedAt
    || !errorCode
  ) {
    return null;
  }

  const groupId = optionalString(candidate.groupId);
  const existingReference = optionalString(candidate.scanReference);
  const qrPayload = optionalString(candidate.qrPayload);
  const legacyId = optionalString(candidate.id);
  const scanReference = isAttendanceScanReference(existingReference)
    ? existingReference
    : qrPayload
      ? await createAttendanceScanReference({ ownerUserId, groupId, sessionId, qrPayload })
      : await hashAttendanceReference([
          "attendance-terminal-v4",
          ownerUserId,
          groupId ?? "legacy-group",
          sessionId,
          clientEventId,
          legacyId ?? "missing-id",
        ]);

  return createRejectedAttendanceScan({
    scanReference,
    ownerUserId,
    ...(groupId ? { groupId } : {}),
    sessionId,
    clientEventId,
    scannedAt,
    deviceId,
    queuedAt,
  }, errorCode, rejectedAt);
}

export function isAttendanceScanReference(value: string | undefined): value is string {
  return Boolean(value && /^sha256:[0-9a-f]{64}$/.test(value));
}

async function hashAttendanceReference(parts: string[]) {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Secure SHA-256 support is required for offline attendance storage.");
  }
  const material = JSON.stringify(parts);
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(material),
  );
  const hex = Array.from(new Uint8Array(digest), (byte) => (
    byte.toString(16).padStart(2, "0")
  )).join("");
  return `${ATTENDANCE_SCAN_REFERENCE_PREFIX}${hex}`;
}

function requiredString(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function optionalString(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}
