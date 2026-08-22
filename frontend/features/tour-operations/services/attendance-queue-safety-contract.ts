export type AttendanceQueueLogoutDisposition = "block" | "discard";

export interface BrowserAttendanceQueueSafetySnapshot {
  ownerUserId: string;
  pending: number;
  sending: number;
  retryable: number;
  review: number;
  oldestQueuedAt: string | null;
  nextAttemptAt: string | null;
  storageUnavailable?: boolean;
}

export function hasUnsafeBrowserAttendanceQueue(
  snapshot: BrowserAttendanceQueueSafetySnapshot,
) {
  return snapshot.storageUnavailable === true
    || snapshot.pending > 0
    || snapshot.sending > 0
    || snapshot.retryable > 0
    || snapshot.review > 0;
}

export function unavailableBrowserAttendanceQueueSnapshot(
  ownerUserId: string,
): BrowserAttendanceQueueSafetySnapshot {
  return {
    ownerUserId,
    pending: 0,
    sending: 0,
    retryable: 0,
    review: 0,
    oldestQueuedAt: null,
    nextAttemptAt: null,
    storageUnavailable: true,
  };
}
