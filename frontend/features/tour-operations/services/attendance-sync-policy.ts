export interface AttendanceSyncUpdate {
  sessionId: string;
  status: string;
  message: string;
  scannedCount: number;
  assignedCount: number;
}

export type AttendanceCompletionBlocker =
  | "offline"
  | "pending"
  | "failed"
  | "rejected"
  | null;

export function getLatestSessionSyncUpdate(
  updates: AttendanceSyncUpdate[],
  sessionId: string,
) {
  for (let index = updates.length - 1; index >= 0; index -= 1) {
    if (updates[index].sessionId === sessionId) return updates[index];
  }
  return null;
}

export function getAuthoritativeAttendanceCount(update: AttendanceSyncUpdate) {
  return Math.max(0, Math.trunc(update.scannedCount));
}

export function reconcileLiveAttendanceCount(
  optimisticCount: number | null,
  serverCount: number,
) {
  const normalizedServerCount = Math.max(0, Math.trunc(serverCount));
  if (optimisticCount === null) return null;
  return Math.max(optimisticCount, normalizedServerCount);
}

export function getAttendanceCompletionBlocker({
  isOnline,
  pending,
  failed,
  rejected,
}: {
  isOnline: boolean;
  pending: number;
  failed: number;
  rejected: number;
}): AttendanceCompletionBlocker {
  if (!isOnline) return "offline";
  if (rejected > 0) return "rejected";
  if (failed > 0) return "failed";
  if (pending > 0) return "pending";
  return null;
}

export function isPermanentAttendanceScanError(code: string) {
  if (/^HTTP_(?:400|404|409|410|422)$/.test(code)) return true;
  return /(?:BAD_REQUEST|NOT_FOUND|CONFLICT|GONE|VALIDATION)/.test(code);
}

export function isRecoverableAttendanceScanError(code: string) {
  return /^HTTP_(?:408|425|429|5\d{2})$/.test(code);
}

export function isSuccessfulAttendanceReplayStatus(status: string) {
  return status === "counted" || status === "duplicate";
}

export function selectVisibleAttendanceSessions<T>(
  serverSucceeded: boolean,
  serverSessions: T[],
  cachedSessions: T[],
  mergeCachedProgress: (sessions: T[]) => T[],
) {
  if (serverSucceeded) return serverSessions;
  return mergeCachedProgress(cachedSessions);
}
