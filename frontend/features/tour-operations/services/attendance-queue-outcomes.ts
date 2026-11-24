import {
  attendanceBatchItemDisposition,
  isMatchingAttendanceBatchEnvelope,
} from "./attendance-batch-policy";
import {
  type AttendanceScanSyncUpdate,
  type AttendanceSyncChunkResult,
  type PendingAttendanceScan,
} from "./attendance-queue-contracts";
import {
  claimPendingAttendanceDelivery,
  markPendingAttendanceRetry,
  quarantineRejectedAttendanceScan,
  releasePendingAttendanceDelivery,
} from "./attendance-queue-delivery-state";
import { getErrorCode } from "./attendance-queue-errors";
import {
  announceScheduleChanged,
  assertCurrentOwner,
  getCurrentUserId,
  withOwnerQueueLock,
} from "./attendance-queue-runtime";
import { removePendingForOwner } from "./attendance-queue-storage";
import { writeAttendanceSessionProgress } from "./attendance-session-progress";
import {
  isPermanentAttendanceScanError,
  isSuccessfulAttendanceReplayStatus,
} from "./attendance-sync-policy";
import {
  type AttendanceScanResponse,
  operationsApi,
} from "@/features/operations/api/operations.api";

export async function syncPendingAttendanceScanBatch(
  candidates: PendingAttendanceScan[],
  ownerUserId: string,
): Promise<AttendanceSyncChunkResult> {
  const claimed: PendingAttendanceScan[] = [];
  for (const candidate of candidates) {
    if (getCurrentUserId() !== ownerUserId) break;
    const scan = await withOwnerQueueLock(
      ownerUserId,
      () => claimPendingAttendanceDelivery(candidate.id, ownerUserId),
    );
    if (scan) claimed.push(scan);
  }
  if (claimed.length === 0) return emptySyncChunkResult();
  announceScheduleChanged();

  let response: Awaited<ReturnType<typeof operationsApi.scanMyAttendanceSessionBatch>>;
  const batchId = createAttendanceScanBatchId();
  try {
    assertCurrentOwner(ownerUserId);
    response = await operationsApi.scanMyAttendanceSessionBatch({
      sessionId: claimed[0].sessionId,
      batchId,
      expectedOwnerUserId: ownerUserId,
      scans: claimed.map((scan) => ({
        clientEventId: scan.clientEventId,
        qrPayload: scan.qrPayload,
        scannedAt: scan.scannedAt,
      })),
    });
    assertCurrentOwner(ownerUserId);
  } catch (error) {
    try {
      for (const scan of claimed) {
        await withOwnerQueueLock(
          ownerUserId,
          () => markPendingAttendanceRetry(scan, error, ownerUserId),
        );
      }
    } catch (storageError) {
      await releaseAttendanceBatchClaims(claimed, ownerUserId);
      throw storageError;
    }
    announceScheduleChanged();
    return {
      synced: 0,
      failed: claimed.length,
      discarded: 0,
      updates: [],
      stop: true,
    };
  }

  const envelopeValid = isMatchingAttendanceBatchEnvelope({
    response,
    expectedBatchId: batchId,
    expectedClientEventIds: claimed.map((scan) => scan.clientEventId),
  });
  const byEventId = envelopeValid
    ? new Map(response.items.map((item) => [item.client_event_id, item]))
    : new Map();
  let synced = 0;
  let failed = 0;
  let discarded = 0;
  let stop = false;
  const updates: AttendanceScanSyncUpdate[] = [];

  try {
    for (const scan of claimed) {
      const item = byEventId.get(scan.clientEventId);
      const disposition = attendanceBatchItemDisposition(item);

      if (disposition === "success") {
        const scanResponse = item.scan as AttendanceScanResponse;
        await withOwnerQueueLock(
          ownerUserId,
          () => removePendingForOwner(scan.id, ownerUserId),
        );
        publishAttendanceProgress(ownerUserId, scan, scanResponse, updates);
        synced += 1;
      } else if (disposition === "terminal-rejection") {
        await withOwnerQueueLock(
          ownerUserId,
          () => quarantineRejectedAttendanceScan(
            scan,
            item.error_code as string,
            ownerUserId,
          ),
        );
        discarded += 1;
      } else {
        await withOwnerQueueLock(
          ownerUserId,
          () => markPendingAttendanceRetry(
            scan,
            { code: item?.error_code ?? "ATTENDANCE_SCAN_BATCH_INVALID_RESPONSE" },
            ownerUserId,
          ),
        );
        failed += 1;
        stop = true;
      }
    }
  } catch (storageError) {
    await releaseAttendanceBatchClaims(claimed, ownerUserId);
    throw storageError;
  }
  announceScheduleChanged();
  return { synced, failed, discarded, updates, stop };
}

export async function syncLegacyPendingAttendanceScan(
  candidate: PendingAttendanceScan,
  ownerUserId: string,
): Promise<AttendanceSyncChunkResult> {
  const scan = await withOwnerQueueLock(
    ownerUserId,
    () => claimPendingAttendanceDelivery(candidate.id, ownerUserId),
  );
  if (!scan) return emptySyncChunkResult();
  announceScheduleChanged();

  let response: AttendanceScanResponse;
  try {
    assertCurrentOwner(ownerUserId);
    response = await operationsApi.scanMyAttendanceSession({
      sessionId: scan.sessionId,
      qrPayload: scan.qrPayload,
      clientEventId: scan.clientEventId,
      scannedAt: scan.scannedAt,
      deviceId: scan.deviceId,
      runtimeId: scan.runtimeId,
      syncSource: "offline",
      expectedOwnerUserId: ownerUserId,
    });
    assertCurrentOwner(ownerUserId);
  } catch (error) {
    const permanent = isPermanentAttendanceScanError(getErrorCode(error));
    try {
      await withOwnerQueueLock(ownerUserId, () => permanent
        ? quarantineRejectedAttendanceScan(scan, getErrorCode(error), ownerUserId)
        : markPendingAttendanceRetry(scan, error, ownerUserId));
    } catch (storageError) {
      await withOwnerQueueLock(
        ownerUserId,
        () => releasePendingAttendanceDelivery(scan.id, ownerUserId),
      ).catch(() => undefined);
      throw storageError;
    }
    announceScheduleChanged();
    return {
      synced: 0,
      failed: permanent ? 0 : 1,
      discarded: permanent ? 1 : 0,
      updates: [],
      // A recoverable failure will usually affect every following row too.
      stop: !permanent,
    };
  }

  try {
    await withOwnerQueueLock(ownerUserId, () => isSuccessfulAttendanceReplayStatus(response.status)
      ? removePendingForOwner(scan.id, ownerUserId)
      : quarantineRejectedAttendanceScan(
        scan,
        `ATTENDANCE_${response.status.toUpperCase().replace(/[^A-Z0-9_]/g, "_")}`,
        ownerUserId,
      ));
  } catch (storageError) {
    await withOwnerQueueLock(
      ownerUserId,
      () => releasePendingAttendanceDelivery(scan.id, ownerUserId),
    ).catch(() => undefined);
    throw storageError;
  }
  const updates: AttendanceScanSyncUpdate[] = [];
  publishAttendanceProgress(ownerUserId, scan, response, updates);
  announceScheduleChanged();
  return {
    synced: isSuccessfulAttendanceReplayStatus(response.status) ? 1 : 0,
    failed: 0,
    discarded: isSuccessfulAttendanceReplayStatus(response.status) ? 0 : 1,
    updates,
    stop: false,
  };
}

export function publishAttendanceProgress(
  ownerUserId: string,
  scan: PendingAttendanceScan,
  response: AttendanceScanResponse,
  updates: AttendanceScanSyncUpdate[],
) {
  if (getCurrentUserId() !== ownerUserId) return;
  if (scan.groupId) {
    writeAttendanceSessionProgress(scan.groupId, scan.sessionId, {
      scanned_count: response.scanned_count,
      assigned_count: response.assigned_count,
    });
  }
  updates.push({
    sessionId: scan.sessionId,
    status: response.status,
    message: response.message,
    scannedCount: response.scanned_count,
    assignedCount: response.assigned_count,
  });
}

export function isBatchCompatiblePendingScan(scan: PendingAttendanceScan): boolean {
  return /^[A-Za-z0-9:_-]{8,128}$/.test(scan.clientEventId)
    && /^pdatt:[A-Za-z0-9_-]{43}$/.test(scan.qrPayload)
    && Number.isFinite(Date.parse(scan.scannedAt))
    && /(?:Z|[+-]\d{2}:\d{2})$/.test(scan.scannedAt);
}

export function createAttendanceScanBatchId(): string {
  return crypto.randomUUID();
}

export async function releaseAttendanceBatchClaims(
  scans: PendingAttendanceScan[],
  ownerUserId: string,
) {
  for (const scan of scans) {
    await withOwnerQueueLock(
      ownerUserId,
      () => releasePendingAttendanceDelivery(scan.id, ownerUserId),
    ).catch(() => undefined);
  }
}

export function emptySyncChunkResult(): AttendanceSyncChunkResult {
  return { synced: 0, failed: 0, discarded: 0, updates: [], stop: false };
}
