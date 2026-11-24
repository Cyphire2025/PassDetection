import {
  type AttendanceDiscardReason,
  type AttendanceDiscardTombstone,
} from "./attendance-queue-contracts";
import { getRetryAfterMs } from "./attendance-queue-errors";
import {
  announceScheduleChanged,
  assertCurrentOwner,
  getCurrentUserId,
  withOwnerQueueLock,
} from "./attendance-queue-runtime";
import {
  listDiscardTombstonesForOwner,
  purgeExpiredSynchronizedDiscardTombstones,
  updateDiscardTombstones,
} from "./attendance-queue-storage";
import { attendanceRetryState, isAttendanceAttemptEligible } from "./attendance-retry-policy";
import apiClient from "@/lib/api/client";
import { ownerBoundRequestConfig } from "@/lib/api/request-owner";

export async function countPendingAttendanceDiscardAudits(
  groupId?: string,
  sessionId?: string,
) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return 0;
  const rows = await listDiscardTombstonesForOwner(ownerUserId);
  return rows.filter((row) => (
    row.syncState !== "synchronized"
    && (!groupId || row.groupId === groupId)
    && (!sessionId || row.sessionId === sessionId)
  )).length;
}

export interface AttendanceDiscardBatchResponse {
  items: Array<Readonly<{
    discard_event_id: string;
    reason_code: string | null;
    status: "accepted" | "already_applied" | "rejected";
  }>>;
}

/**
 * Synchronizes privacy-safe discard evidence independently from raw scans. The
 * server contract is additive; older backends leave rows retryable instead of
 * causing local deletion.
 */
export async function syncAttendanceDiscardTombstones(): Promise<Readonly<{
  synchronized: number;
  rejected: number;
  pending: number;
}>> {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId || !navigator.onLine) {
    return { synchronized: 0, rejected: 0, pending: ownerUserId
      ? await countPendingAttendanceDiscardAudits()
      : 0 };
  }
  return withOwnerQueueLock(ownerUserId, async () => {
    assertCurrentOwner(ownerUserId);
    await purgeExpiredSynchronizedDiscardTombstones(ownerUserId);
    const allRows = await listDiscardTombstonesForOwner(ownerUserId);
    const candidates = allRows
      .filter((row) => (
        (row.syncState === "pending" || (
          row.syncState === "sending" && Boolean(navigator.locks?.request)
        ))
        && isAttendanceAttemptEligible(row.nextAttemptAt, row.discardedAt)
      ))
      .slice(0, 50);
    if (candidates.length === 0) {
      return {
        synchronized: 0,
        rejected: 0,
        pending: allRows.filter((row) => row.syncState !== "synchronized").length,
      };
    }
    await updateDiscardTombstones(ownerUserId, candidates.map((row) => ({
      ...row,
      syncState: "sending" as const,
      lastAttemptAt: new Date().toISOString(),
    })));
    let response: AttendanceDiscardBatchResponse;
    try {
      assertCurrentOwner(ownerUserId);
      const result = await apiClient.post<AttendanceDiscardBatchResponse>(
        "/api/v1/tour-operations/coordinator/attendance/discards",
        {
          items: candidates.map((row) => ({
            captured_at: row.capturedAt,
            discard_event_id: row.discardEventId,
            discarded_at: row.discardedAt,
            group_id: row.groupId,
            // The backend must derive the authoritative runtime from the
            // httpOnly registration cookie. This is a privacy-safe continuity
            // hint for rolling compatibility, not an authorization claim.
            installation_runtime_id: row.installationRuntimeId,
            reason_category: row.reasonCategory,
            scan_reference: row.scanReference,
            session_id: row.sessionId,
          })),
        },
        ownerBoundRequestConfig(ownerUserId),
      );
      assertCurrentOwner(ownerUserId);
      response = result.data;
    } catch (error) {
      const retryRows = candidates.map((row) => {
        const retry = attendanceRetryState({
          previousAttemptCount: row.attemptCount,
          retryAfterMs: getRetryAfterMs(error),
        });
        return {
          ...row,
          ...retry,
          lastAttemptAt: new Date().toISOString(),
          syncState: "pending" as const,
        };
      });
      await updateDiscardTombstones(ownerUserId, retryRows);
      announceScheduleChanged();
      throw error;
    }
    assertCurrentOwner(ownerUserId);
    const byEventId = new Map(response.items.map((item) => [item.discard_event_id, item]));
    let synchronized = 0;
    let rejected = 0;
    const updated = candidates.map((row) => {
      const item = byEventId.get(row.discardEventId);
      if (item?.status === "accepted" || item?.status === "already_applied") {
        synchronized += 1;
        return {
          ...row,
          syncState: "synchronized" as const,
          synchronizedAt: new Date().toISOString(),
          lastAttemptAt: new Date().toISOString(),
          serverErrorCode: undefined,
        };
      }
      rejected += 1;
      return {
        ...row,
        syncState: "rejected" as const,
        lastAttemptAt: new Date().toISOString(),
        serverErrorCode: item?.reason_code ?? "DISCARD_RECEIPT_INVALID_RESPONSE",
      };
    });
    await updateDiscardTombstones(ownerUserId, updated);
    announceScheduleChanged();
    return {
      synchronized,
      rejected,
      pending: allRows.filter((row) => row.syncState !== "synchronized").length
        - synchronized,
    };
  });
}

export function createDiscardTombstone(
  scan: Readonly<{
    deviceId: string;
    groupId?: string;
    ownerUserId: string;
    scanReference: string;
    scannedAt: string;
    sessionId: string;
  }>,
  reasonCategory: AttendanceDiscardReason,
): AttendanceDiscardTombstone {
  if (!scan.groupId) throw new Error("A group-scoped scan is required for discard evidence.");
  const discardEventId = crypto.randomUUID();
  const discardedAt = new Date().toISOString();
  return {
    id: `attendance-discard:${discardEventId}`,
    discardEventId,
    ownerUserId: scan.ownerUserId,
    groupId: scan.groupId,
    sessionId: scan.sessionId,
    installationRuntimeId: scan.deviceId,
    discardedAt,
    capturedAt: scan.scannedAt,
    reasonCategory,
    scanReference: scan.scanReference,
    syncState: "pending",
    attemptCount: 0,
    nextAttemptAt: discardedAt,
  };
}
