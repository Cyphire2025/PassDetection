import { operationsApi, type AttendanceScanResponse } from "@/features/operations/api/operations.api";
import { useAuthStore } from "@/stores/auth.store";

export interface AttendanceScanInput {
  sessionId: string;
  qrPayload: string;
  clientEventId: string;
  scannedAt: string;
  deviceId: string;
}

export interface PendingAttendanceScan extends AttendanceScanInput {
  id: string;
  ownerUserId: string;
  queuedAt: string;
}

const DB_NAME = "passdetection-tour-ops";
const DB_VERSION = 2;
const STORE_NAME = "pending-attendance-scans";
const OWNER_INDEX = "owner-user-id";

export async function enqueueAttendanceScan(scan: AttendanceScanInput) {
  const ownerUserId = requireCurrentUserId();
  const id = getStableScanQueueId(ownerUserId, scan.sessionId, scan.qrPayload);
  const pendingScan: PendingAttendanceScan = {
    ...scan,
    id,
    ownerUserId,
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
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return 0;
  const db = await openDb();
  const store = db.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME);
  const count = await requestToPromise<number>(store.index(OWNER_INDEX).count(ownerUserId));
  db.close();
  return count;
}

export async function listPendingAttendanceScans() {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return [];
  const db = await openDb();
  const store = db.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME);
  const scans = await requestToPromise<PendingAttendanceScan[]>(
    store.index(OWNER_INDEX).getAll(ownerUserId),
  );
  db.close();
  return scans.sort((a, b) => a.queuedAt.localeCompare(b.queuedAt));
}

export async function removePendingAttendanceScan(id: string) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return;
  const db = await openDb();
  const transaction = db.transaction(STORE_NAME, "readwrite");
  const store = transaction.objectStore(STORE_NAME);
  const existing = await requestToPromise<PendingAttendanceScan | undefined>(store.get(id));
  if (existing?.ownerUserId === ownerUserId) {
    await requestToPromise(store.delete(id));
  }
  db.close();
}

export async function syncPendingAttendanceScans() {
  if (!navigator.onLine) return { synced: 0, failed: 0 };

  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return { synced: 0, failed: 0 };
  const scans = await listPendingAttendanceScans();
  let synced = 0;
  let failed = 0;

  for (const scan of scans) {
    if (getCurrentUserId() !== ownerUserId || scan.ownerUserId !== ownerUserId) break;
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

export async function tryRecordAttendanceScan(scan: AttendanceScanInput): Promise<
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

function getStableScanQueueId(ownerUserId: string, sessionId: string, qrPayload: string) {
  return `${ownerUserId}:${sessionId}:${qrPayload}`;
}

function openDb() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => {
      const db = request.result;
      // Version 1 records were not user-scoped. Remove that legacy store
      // rather than risk syncing one coordinator's queue under another login.
      if (db.objectStoreNames.contains(STORE_NAME) && event.oldVersion < 2) {
        db.deleteObjectStore(STORE_NAME);
      }
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: "id" });
        store.createIndex(OWNER_INDEX, "ownerUserId", { unique: false });
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

function getCurrentUserId() {
  return useAuthStore.getState().user?.id ?? null;
}

function requireCurrentUserId() {
  const userId = getCurrentUserId();
  if (!userId) throw new Error("An authenticated coordinator session is required.");
  return userId;
}
