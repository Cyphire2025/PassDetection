import {
  type AttendanceScanRecoveryContext,
  type PendingAttendanceScan,
  type RejectedAttendanceScan,
  type StoredPendingAttendanceScan,
  type StoredRejectedAttendanceScan,
} from "./attendance-queue-contracts";
import { attendanceQueueRowId, createAttendanceScanReference } from "./attendance-queue-privacy";
import { type AuthorizedBrowserOfflineScan } from "./browser-offline-authorization";
import {
  protectBrowserJson,
  type ProtectedBrowserValue,
  unprotectBrowserJson,
} from "./browser-offline-crypto";

export async function protectPendingAttendanceScan(
  scan: PendingAttendanceScan,
): Promise<StoredPendingAttendanceScan> {
  const { qrPayload, recovery, ...metadata } = scan;
  const protectedQrPayload = await protectBrowserJson(
    { qrPayload, ...(recovery ? { recovery } : {}) },
    pendingScanAssociatedData(metadata),
  );
  return {
    ...metadata,
    protectedQrPayload,
    storageVersion: 5,
  };
}

export async function restorePendingAttendanceScan(
  stored: StoredPendingAttendanceScan,
): Promise<PendingAttendanceScan> {
  let qrPayload = stored.qrPayload;
  let recovery = normalizeRecoveryContext(stored.recovery);
  if (!qrPayload && stored.storageVersion === 5 && stored.protectedQrPayload) {
    const decrypted = await unprotectBrowserJson<{
      qrPayload?: unknown;
      recovery?: unknown;
    }>(
      stored.protectedQrPayload,
      pendingScanAssociatedData(stored),
    );
    qrPayload = typeof decrypted.qrPayload === "string" ? decrypted.qrPayload : undefined;
    recovery = normalizeRecoveryContext(decrypted.recovery) ?? recovery;
  }
  if (!qrPayload || !/^pdatt:[A-Za-z0-9_-]{43}$/.test(qrPayload)) {
    throw new Error("A protected attendance queue row is corrupt.");
  }
  const expectedReference = await createAttendanceScanReference({
    ownerUserId: stored.ownerUserId,
    groupId: stored.groupId,
    sessionId: stored.sessionId,
    qrPayload,
  });
  if (
    expectedReference !== stored.scanReference
    || attendanceQueueRowId(expectedReference) !== stored.id
  ) {
    throw new Error("A protected attendance queue row failed its identity check.");
  }
  const restored = { ...stored, qrPayload };
  delete restored.protectedQrPayload;
  delete restored.storageVersion;
  delete restored.recovery;
  return { ...restored, ...(recovery ? { recovery } : {}) };
}

export async function protectRejectedAttendanceScan(
  scan: RejectedAttendanceScan,
): Promise<StoredRejectedAttendanceScan> {
  const { recovery, ...metadata } = scan;
  const protectedRecovery = recovery
    ? await protectBrowserJson(
        { recovery },
        rejectedScanAssociatedData(metadata),
      )
    : undefined;
  return {
    ...metadata,
    ...(protectedRecovery ? { protectedRecovery } : {}),
    storageVersion: 5,
  };
}

export async function restoreRejectedAttendanceScan(
  stored: StoredRejectedAttendanceScan,
): Promise<RejectedAttendanceScan> {
  let recovery = normalizeRecoveryContext(stored.recovery);
  if (stored.storageVersion === 5 && stored.protectedRecovery) {
    const decrypted = await unprotectBrowserJson<{ recovery?: unknown }>(
      stored.protectedRecovery,
      rejectedScanAssociatedData(stored),
    );
    recovery = normalizeRecoveryContext(decrypted.recovery) ?? recovery;
  }
  const restored = { ...stored };
  delete restored.protectedRecovery;
  delete restored.storageVersion;
  delete restored.recovery;
  return { ...restored, ...(recovery ? { recovery } : {}) };
}

export function pendingScanAssociatedData(scan: Readonly<{
  groupId?: string;
  id: string;
  ownerUserId: string;
  sessionId: string;
}>) {
  return JSON.stringify([
    "attendance-pending-v5",
    scan.id,
    scan.ownerUserId,
    scan.groupId ?? "legacy-group",
    scan.sessionId,
  ]);
}

export function rejectedScanAssociatedData(scan: Readonly<{
  id: string;
  ownerUserId: string;
  scanReference: string;
}>) {
  return JSON.stringify([
    "attendance-rejected-v5",
    scan.id,
    scan.ownerUserId,
    scan.scanReference,
  ]);
}

export function isProtectedBrowserValue(value: unknown): value is ProtectedBrowserValue {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ProtectedBrowserValue>;
  return candidate.version === 1
    && candidate.algorithm === "AES-GCM"
    && candidate.keyId === "coordinator-offline-aes-gcm-v1"
    && candidate.ciphertext instanceof ArrayBuffer
    && candidate.iv instanceof Uint8Array;
}

export function recoveryContext(
  authorization: AuthorizedBrowserOfflineScan,
): AttendanceScanRecoveryContext {
  return {
    passengerId: authorization.passengerId,
    passengerLabel: authorization.passengerLabel,
    sessionLabel: authorization.sessionLabel,
  };
}

export function normalizeRecoveryContext(value: unknown): AttendanceScanRecoveryContext | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const candidate = value as Partial<AttendanceScanRecoveryContext>;
  if (
    typeof candidate.passengerId !== "string"
    || candidate.passengerId.length === 0
    || candidate.passengerId.length > 128
    || typeof candidate.passengerLabel !== "string"
    || candidate.passengerLabel.length === 0
    || candidate.passengerLabel.length > 255
    || typeof candidate.sessionLabel !== "string"
    || candidate.sessionLabel.length === 0
    || candidate.sessionLabel.length > 160
  ) {
    return undefined;
  }
  return {
    passengerId: candidate.passengerId,
    passengerLabel: candidate.passengerLabel,
    sessionLabel: candidate.sessionLabel,
  };
}
