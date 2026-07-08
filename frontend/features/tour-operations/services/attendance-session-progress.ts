import type { AttendanceSession } from "@/features/operations/api/operations.api";

interface AttendanceSessionProgress {
  scanned_count: number;
  assigned_count: number;
  status?: string;
  updated_at: string;
}

const STORAGE_KEY = "passdetection-attendance-session-progress";

export function readAttendanceSessionProgress(sessionId: string): AttendanceSessionProgress | null {
  return readProgressMap()[sessionId] ?? null;
}

export function writeAttendanceSessionProgress(
  sessionId: string,
  progress: Pick<AttendanceSessionProgress, "scanned_count" | "assigned_count"> & { status?: string },
) {
  const map = readProgressMap();
  map[sessionId] = {
    scanned_count: progress.scanned_count,
    assigned_count: progress.assigned_count,
    status: progress.status,
    updated_at: new Date().toISOString(),
  };
  writeProgressMap(map);
}

export function mergeAttendanceSessionProgress(sessions: AttendanceSession[]): AttendanceSession[] {
  const map = readProgressMap();
  return sessions.map((session) => {
    const local = map[session.id];
    if (!local) return session;

    return {
      ...session,
      scanned_count: Math.max(session.scanned_count, local.scanned_count),
      assigned_count: Math.max(session.assigned_count, local.assigned_count),
      status: local.status ?? session.status,
    };
  });
}

function readProgressMap(): Record<string, AttendanceSessionProgress> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Record<string, AttendanceSessionProgress>;
  } catch {
    return {};
  }
}

function writeProgressMap(map: Record<string, AttendanceSessionProgress>) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
}
