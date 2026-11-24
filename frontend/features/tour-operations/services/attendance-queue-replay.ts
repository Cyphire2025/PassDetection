import {
  enqueueAttendanceScan,
  getNextPendingAttendanceAttemptAt,
} from "./attendance-queue-commands";
import { recoverInterruptedAttendanceDeliveries } from "./attendance-queue-delivery-state";
import { selectPendingAttendanceBatch } from "./attendance-batch-selection";
import {
  type AttendanceScanInput,
  type AttendanceScanSyncResult,
  type AttendanceScanSyncUpdate,
  type AttendanceSyncChunkResult,
  type PendingAttendanceScan,
} from "./attendance-queue-contracts";
import { isLikelyNetworkFailure } from "./attendance-queue-errors";
import {
  isBatchCompatiblePendingScan,
  syncLegacyPendingAttendanceScan,
  syncPendingAttendanceScanBatch,
} from "./attendance-queue-outcomes";
import {
  announceScheduleChanged,
  assertCurrentOwner,
  DRAIN_LOCK_PREFIX,
  getCurrentUserId,
  requireCurrentUserId,
  withBrowserLock,
  withOwnerQueueLock,
} from "./attendance-queue-runtime";
import { listPendingForOwner } from "./attendance-queue-storage";
import {
  earliestAttendanceAttemptAt,
  isAttendanceAttemptEligible,
} from "./attendance-retry-policy";
import { getBrowserAttendanceRuntimeHint } from "./browser-offline-authorization";
import {
  type AttendanceScanResponse,
  operationsApi,
} from "@/features/operations/api/operations.api";

export let activeSync:
  | { ownerUserId: string; promise: Promise<AttendanceScanSyncResult> }
  | null = null;

export function syncPendingAttendanceScans(): Promise<AttendanceScanSyncResult> {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return Promise.resolve(emptySyncResult());
  if (activeSync?.ownerUserId === ownerUserId) return activeSync.promise;
  if (activeSync) {
    return activeSync.promise
      .catch(() => undefined)
      .then(() => syncPendingAttendanceScans());
  }
  if (!navigator.onLine) {
    return getNextPendingAttendanceAttemptAt().then((nextAttemptAt) => ({
      ...emptySyncResult(),
      nextAttemptAt,
    }));
  }

  const request = withBrowserLock(
    `${DRAIN_LOCK_PREFIX}:${ownerUserId}`,
    () => performPendingAttendanceScanSync(ownerUserId),
  ).finally(() => {
    if (activeSync?.promise === request) activeSync = null;
  });
  activeSync = { ownerUserId, promise: request };
  return request;
}

export async function performPendingAttendanceScanSync(
  ownerUserId: string,
): Promise<AttendanceScanSyncResult> {
  if (getCurrentUserId() !== ownerUserId) return emptySyncResult();
  const scans = await withOwnerQueueLock(
    ownerUserId,
    async () => {
      // The enclosing drain lock excludes an active sender in another tab.
      // Replay keeps original event identity so an unknown server outcome is
      // reconciled by the existing idempotency and authorization contract.
      assertCurrentOwner(ownerUserId);
      const pending = await listPendingForOwner(ownerUserId);
      assertCurrentOwner(ownerUserId);
      await recoverInterruptedAttendanceDeliveries(ownerUserId, pending);
      assertCurrentOwner(ownerUserId);
      return pending;
    },
  );
  let synced = 0;
  let failed = 0;
  let discarded = 0;
  const updates: AttendanceScanSyncUpdate[] = [];
  const handledIds = new Set<string>();

  for (const candidate of scans) {
    if (handledIds.has(candidate.id)) continue;
    if (getCurrentUserId() !== ownerUserId || candidate.ownerUserId !== ownerUserId) break;
    if (!isAttendanceAttemptEligible(candidate.nextAttemptAt, candidate.queuedAt)) continue;
    let chunkResult: AttendanceSyncChunkResult;
    if (isBatchCompatiblePendingScan(candidate)) {
      const batchCandidates = selectPendingAttendanceBatch(
        scans, candidate, ownerUserId, handledIds,
      );
      batchCandidates.forEach((scan) => handledIds.add(scan.id));
      chunkResult = await syncPendingAttendanceScanBatch(batchCandidates, ownerUserId);
    } else {
      handledIds.add(candidate.id);
      // Rows created against an older contract remain deliverable through the
      // original single-scan endpoint. New compatible rows always use the
      // bounded batch contract.
      chunkResult = await syncLegacyPendingAttendanceScan(candidate, ownerUserId);
    }
    synced += chunkResult.synced;
    failed += chunkResult.failed;
    discarded += chunkResult.discarded;
    updates.push(...chunkResult.updates);
    if (chunkResult.stop) break;
  }

  const remaining = await withOwnerQueueLock(
    ownerUserId,
    () => listPendingForOwner(ownerUserId),
  );
  if (getCurrentUserId() !== ownerUserId) return emptySyncResult();
  const nextAttemptAt = earliestAttendanceAttemptAt(
    remaining.filter((row) => row.deliveryState !== "sending"),
  );
  announceScheduleChanged();
  return { synced, failed, discarded, updates, nextAttemptAt };
}

export async function tryRecordAttendanceScan(scan: AttendanceScanInput): Promise<
  | { mode: "online"; response: AttendanceScanResponse }
  | { mode: "queued"; pending: PendingAttendanceScan; duplicate: boolean }
> {
  const ownerUserId = requireCurrentUserId();
  if (!navigator.onLine) {
    const queued = await enqueueAttendanceScan(scan);
    assertCurrentOwner(ownerUserId);
    return { mode: "queued", pending: queued.pending, duplicate: queued.duplicate };
  }

  // The HttpOnly runtime cookie is authoritative. Its paired UUID is sent as
  // an additive continuity hint; absence keeps older/legacy clients working.
  const runtimeId = scan.runtimeId
    ?? await getBrowserAttendanceRuntimeHint().catch(() => null)
    ?? undefined;

  try {
    assertCurrentOwner(ownerUserId);
    const response = await operationsApi.scanMyAttendanceSession({
      sessionId: scan.sessionId,
      qrPayload: scan.qrPayload,
      clientEventId: scan.clientEventId,
      scannedAt: scan.scannedAt,
      deviceId: scan.deviceId,
      runtimeId,
      syncSource: "online",
      expectedOwnerUserId: ownerUserId,
    });
    assertCurrentOwner(ownerUserId);
    return { mode: "online", response };
  } catch (error) {
    assertCurrentOwner(ownerUserId);
    if (isLikelyNetworkFailure(error)) {
      const queued = await enqueueAttendanceScan(scan, error);
      assertCurrentOwner(ownerUserId);
      return { mode: "queued", pending: queued.pending, duplicate: queued.duplicate };
    }
    throw error;
  }
}

export function emptySyncResult(): AttendanceScanSyncResult {
  return {
    synced: 0,
    failed: 0,
    discarded: 0,
    updates: [],
    nextAttemptAt: null,
  };
}
