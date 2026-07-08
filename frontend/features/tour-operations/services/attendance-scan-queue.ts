import { operationsApi, type AttendanceScanResponse } from "@/features/operations/api/operations.api";

export interface PendingAttendanceScan {
  id: string;
  sessionId: string;
  qrPayload: string;
  clientEventId: string;
  scannedAt: string;
  deviceId: string;
  queuedAt: string;
}

const DB_NAME = "passdetection-tour-ops";
const DB_VERSION = 1;
const STORE_NAME = "pending-attendance-scans";

export async function enqueueAttendanceScan(scan: Omit<PendingAttendanceScan, "id" | "queuedAt">) {
  const id = getStableScanQueueId(scan.sessionId, scan.qrPayload);
  const pendingScan: PendingAttendanceScan = {
    ...scan,
    id,
    queuedAt: new Date().toISOString(),
  };
  const db = await openDb();
  const transaction = db.transaction(STORE_NAME, "readwrite");
  const store = transaction.objectStore(STORE_NAME);
  const existing = await requestToPromise<PendingAttendanceScan | undefined>(store.get(id));
  if (!existing) {
    await requestToPromise(store.put(pendingScan));
  }
  db.close();
  return { pending: existing ?? pendingScan, duplicate: Boolean(existing) };
}

export async function countPendingAttendanceScans() {
  const db = await openDb();
  const count = await requestToPromise<number>(db.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME).count());
  db.close();
  return count;
}

export async function listPendingAttendanceScans() {
  const db = await openDb();
  const scans = await requestToPromise<PendingAttendanceScan[]>(
    db.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME).getAll(),
  );
  db.close();
  return scans.sort((a, b) => a.queuedAt.localeCompare(b.queuedAt));
}

export async function removePendingAttendanceScan(id: string) {
  const db = await openDb();
  await requestToPromise(db.transaction(STORE_NAME, "readwrite").objectStore(STORE_NAME).delete(id));
  db.close();
}

export async function syncPendingAttendanceScans() {
  if (!navigator.onLine) return { synced: 0, failed: 0 };

  const scans = await listPendingAttendanceScans();
  let synced = 0;
  let failed = 0;

  for (const scan of scans) {
    try {
      await operationsApi.scanMyAttendanceSession({
        sessionId: scan.sessionId,
        qrPayload: scan.qrPayload,
        clientEventId: scan.clientEventId,
        scannedAt: scan.scannedAt,
        deviceId: scan.deviceId,
        syncSource: "offline",
      });
      await removePendingAttendanceScan(scan.id);
      synced += 1;
    } catch {
      failed += 1;
    }
  }

  return { synced, failed };
}

export async function tryRecordAttendanceScan(scan: Omit<PendingAttendanceScan, "id" | "queuedAt">): Promise<
  | { mode: "online"; response: AttendanceScanResponse }
  | { mode: "queued"; pending: PendingAttendanceScan; duplicate: boolean }
> {
  if (!navigator.onLine) {
    const queued = await enqueueAttendanceScan(scan);
    return { mode: "queued", pending: queued.pending, duplicate: queued.duplicate };
  }

  try {
    const response = await operationsApi.scanMyAttendanceSession({
      sessionId: scan.sessionId,
      qrPayload: scan.qrPayload,
      clientEventId: scan.clientEventId,
      scannedAt: scan.scannedAt,
      deviceId: scan.deviceId,
      syncSource: "online",
    });
    return { mode: "online", response };
  } catch (error) {
    if (isLikelyNetworkFailure(error)) {
      const queued = await enqueueAttendanceScan(scan);
      return { mode: "queued", pending: queued.pending, duplicate: queued.duplicate };
    }
    throw error;
  }
}

function getStableScanQueueId(sessionId: string, qrPayload: string) {
  return `${sessionId}:${qrPayload}`;
}

function openDb() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function requestToPromise<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function isLikelyNetworkFailure(error: unknown) {
  if (!navigator.onLine) return true;
  if (!(error instanceof Error)) return false;
  return /network|fetch|timeout|offline|connection/i.test(error.message);
}
