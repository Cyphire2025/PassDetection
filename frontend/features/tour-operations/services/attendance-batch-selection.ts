import type { PendingAttendanceScan } from "./attendance-queue-contracts";
import { isBatchCompatiblePendingScan } from "./attendance-queue-outcomes";
import { isAttendanceAttemptEligible } from "./attendance-retry-policy";

/** Select the next bounded batch from the current snapshot in its existing order. */
export function selectPendingAttendanceBatch(
  scans: readonly PendingAttendanceScan[],
  candidate: PendingAttendanceScan,
  ownerUserId: string,
  handledIds: ReadonlySet<string>,
) {
  const selected: PendingAttendanceScan[] = [];
  // Revisit unhandled rows on each call. A retry deadline or aliased row can
  // change while the preceding asynchronous batch is being reconciled.
  const length = scans.length;
  for (let index = 0; index < length; index++) {
    if (!(index in scans)) continue;
    const scan = scans[index];
    if (
      !handledIds.has(scan.id)
      && scan.ownerUserId === ownerUserId
      && scan.sessionId === candidate.sessionId
      && isAttendanceAttemptEligible(scan.nextAttemptAt, scan.queuedAt)
      && isBatchCompatiblePendingScan(scan)
    ) {
      selected.push(scan);
      if (selected.length === 50) break;
    }
  }
  return selected;
}
