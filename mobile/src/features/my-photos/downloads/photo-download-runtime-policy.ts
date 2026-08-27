const MAX_RETRY_WAKE_DELAY_MS = 60_000;

export function photoDownloadWakeDelayMs(
  nextAttemptAt: string | null,
  nowMs = Date.now(),
): number | null {
  if (!nextAttemptAt) return null;
  const due = Date.parse(nextAttemptAt);
  if (!Number.isFinite(due)) return 0;
  return Math.max(0, Math.min(MAX_RETRY_WAKE_DELAY_MS, due - nowMs));
}

export function photoDownloadRuntimeBoundaryKey(
  accountKey: string,
  tripId: string,
  passengerId: string,
): string {
  if (!accountKey || !tripId || !passengerId) throw new Error('Photo runtime boundary is incomplete.');
  return `${accountKey}|${tripId}|${passengerId}`;
}

/** One gate is constructed per account/trip effect activation. Full ciphertext
 * reconciliation is retried after failure, then permanently replaced by the
 * lightweight queue recovery path for subsequent drain/wake/network events. */
export class PhotoDownloadReconciliationGate {
  private completed = false;

  requiresFullReconciliation(): boolean {
    return !this.completed;
  }

  complete(): void {
    this.completed = true;
  }
}
