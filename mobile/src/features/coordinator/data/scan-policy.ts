export type RecentAttendanceScan = {
  sessionId: string;
  value: string;
  at: number;
};

export type OptimisticAttendanceCount = {
  sessionId: string | null;
  confirmedCount: number;
  pendingCount: number;
};

export const EMPTY_OPTIMISTIC_ATTENDANCE_COUNT: OptimisticAttendanceCount = {
  sessionId: null,
  confirmedCount: 0,
  pendingCount: 0,
};

export function attendanceScanTimestamp(): number {
  return Date.now();
}

export function isRapidRepeatScan(
  previous: RecentAttendanceScan | null,
  sessionId: string,
  value: string,
  now: number,
  windowMs = 2_000,
): boolean {
  return Boolean(
    previous
      && previous.sessionId === sessionId
      && previous.value === value
      && now >= previous.at
      && now - previous.at < windowMs,
  );
}

export function reconcileAttendanceCount(
  current: OptimisticAttendanceCount,
  sessionId: string,
  serverCount: number,
): OptimisticAttendanceCount {
  const boundedServerCount = Math.max(0, serverCount);
  if (current.sessionId !== sessionId) {
    return {
      sessionId,
      confirmedCount: boundedServerCount,
      pendingCount: 0,
    };
  }

  const serverAdvance = Math.max(0, boundedServerCount - current.confirmedCount);
  const acknowledgedPending = Math.min(current.pendingCount, serverAdvance);
  return {
    sessionId,
    confirmedCount: Math.max(current.confirmedCount, boundedServerCount),
    pendingCount: current.pendingCount - acknowledgedPending,
  };
}

export function recordOptimisticAttendanceScan(
  current: OptimisticAttendanceCount,
  sessionId: string,
  serverCount: number,
): OptimisticAttendanceCount {
  const reconciled = reconcileAttendanceCount(current, sessionId, serverCount);
  return { ...reconciled, pendingCount: reconciled.pendingCount + 1 };
}

export function visibleAttendanceCount(
  current: OptimisticAttendanceCount,
  sessionId: string,
  serverCount: number,
): number {
  const reconciled = reconcileAttendanceCount(current, sessionId, serverCount);
  return reconciled.confirmedCount + reconciled.pendingCount;
}
