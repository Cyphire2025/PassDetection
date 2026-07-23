import type { AttendanceSession } from "@/features/operations/api/operations.api";
import { useAuthStore } from "@/stores/auth.store";

interface AttendanceSessionProgress {
  scanned_count: number;
  assigned_count: number;
  status?: string;
  updated_at: string;
}

const STORAGE_KEY_PREFIX = "passdetection-attendance-session-progress";

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
      scanned_count: local.scanned_count,
      assigned_count: local.assigned_count,
      status: local.status ?? session.status,
    };
  });
}

export function reconcileAttendanceSessionProgress(sessions: AttendanceSession[]) {
  const map = readProgressMap();
  let changed = false;
  for (const session of sessions) {
    if (!(session.id in map)) continue;
    delete map[session.id];
    changed = true;
  }
  if (changed) writeProgressMap(map);
}

function readProgressMap(): Record<string, AttendanceSessionProgress> {
  if (typeof window === "undefined") return {};
  const storageKey = getCurrentUserStorageKey();
  if (!storageKey) return {};
  try {
    return JSON.parse(window.localStorage.getItem(storageKey) ?? "{}") as Record<string, AttendanceSessionProgress>;
  } catch {
    return {};
  }
}

function writeProgressMap(map: Record<string, AttendanceSessionProgress>) {
  const storageKey = getCurrentUserStorageKey();
  if (!storageKey) return;
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(map));
  } catch {
    // Progress is an optimization; server state remains authoritative.
  }
}

function getCurrentUserStorageKey() {
  const userId = useAuthStore.getState().user?.id;
  return userId ? `${STORAGE_KEY_PREFIX}:user:${userId}` : null;
}
