import { type AttendanceSyncUpdate } from "./attendance-sync-policy";
import { type ProtectedBrowserValue } from "./browser-offline-crypto";

export interface AttendanceScanInput {
  groupId: string;
  sessionId: string;
  qrPayload: string;
  clientEventId: string;
  scannedAt: string;
  deviceId: string;
  /** Registered browser runtime; omitted only for compatibility with legacy rows. */
  runtimeId?: string;
}

export type AttendanceScanRecoveryContext = Readonly<{
  passengerId: string;
  passengerLabel: string;
  sessionLabel: string;
}>;

export interface PendingAttendanceScan extends Omit<AttendanceScanInput, "groupId"> {
  // Optional only for records written before group-scoped queue version 3.
  groupId?: string;
  id: string;
  scanReference: string;
  ownerUserId: string;
  queuedAt: string;
  attemptCount: number;
  nextAttemptAt: string;
  lastAttemptAt?: string;
  deliveryState: "pending" | "sending";
  deliveryStartedAt?: string;
  recovery?: AttendanceScanRecoveryContext;
}

export interface RejectedAttendanceScan {
  id: string;
  scanReference: string;
  ownerUserId: string;
  groupId?: string;
  sessionId: string;
  clientEventId: string;
  scannedAt: string;
  deviceId: string;
  queuedAt: string;
  rejectedAt: string;
  errorCode: string;
  attemptCount?: number;
  lastAttemptAt?: string;
  recovery?: AttendanceScanRecoveryContext;
}

export interface StoredPendingAttendanceScan extends Omit<PendingAttendanceScan, "qrPayload" | "recovery"> {
  protectedQrPayload?: ProtectedBrowserValue;
  // Present only while a legacy row is awaiting copy/verify migration.
  qrPayload?: string;
  recovery?: AttendanceScanRecoveryContext;
  storageVersion?: 5;
}

export interface StoredRejectedAttendanceScan extends Omit<RejectedAttendanceScan, "recovery"> {
  protectedRecovery?: ProtectedBrowserValue;
  // Present only until a verified encrypted replacement is written.
  recovery?: AttendanceScanRecoveryContext;
  storageVersion?: 5;
}

export class AttendanceQueueCapacityError extends Error {
  readonly code = "ATTENDANCE_QUEUE_CAPACITY_REACHED";

  constructor() {
    super("Offline attendance storage reached its safe device limit. Reconnect and synchronize before scanning more passengers.");
    this.name = "AttendanceQueueCapacityError";
  }
}

export type AttendanceDiscardReason =
  | "coordinator_confirmed_rescan"
  | "duplicate_local_evidence"
  | "passenger_not_attending"
  | "privacy_or_data_error"
  | "server_terminal_rejection";

export interface AttendanceDiscardTombstone {
  id: string;
  discardEventId: string;
  ownerUserId: string;
  groupId: string;
  sessionId: string;
  installationRuntimeId: string;
  discardedAt: string;
  capturedAt: string;
  reasonCategory: AttendanceDiscardReason;
  scanReference: string;
  syncState: "pending" | "sending" | "rejected" | "synchronized";
  attemptCount: number;
  nextAttemptAt: string;
  lastAttemptAt?: string;
  synchronizedAt?: string;
  serverErrorCode?: string;
}

export interface AttendanceScanSyncResult {
  synced: number;
  failed: number;
  discarded: number;
  updates: AttendanceSyncUpdate[];
  nextAttemptAt: string | null;
}

export type AttendanceScanSyncUpdate = AttendanceSyncUpdate;

export const MAX_PENDING_ATTENDANCE_SCANS_PER_OWNER = 5_000;

export type AttendanceSyncChunkResult = Omit<AttendanceScanSyncResult, "nextAttemptAt"> & {
  stop: boolean;
};
