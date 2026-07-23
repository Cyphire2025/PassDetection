import { operationsApi, type AttendanceScanResponse } from "@/features/operations/api/operations.api";
import { useAuthStore } from "@/stores/auth.store";
import { writeAttendanceSessionProgress } from "./attendance-session-progress";
import {
  isPermanentAttendanceScanError,
  type AttendanceSyncUpdate,
} from "./attendance-sync-policy";

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

export interface RejectedAttendanceScan extends PendingAttendanceScan {
  rejectedAt: string;
  errorCode: string;
}

export interface AttendanceScanSyncResult {
  synced: number;
  failed: number;
  discarded: number;
  updates: AttendanceScanSyncUpdate[];
}

export type AttendanceScanSyncUpdate = AttendanceSyncUpdate;

const DB_NAME = "passdetection-tour-ops";
const DB_VERSION = 3;
const PENDING_STORE_NAME = "pending-attendance-scans";
const REJECTED_STORE_NAME = "rejected-attendance-scans";
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
  const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
  const store = transaction.objectStore(PENDING_STORE_NAME);
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
  const store = db.transaction(PENDING_STORE_NAME, "readonly").objectStore(PENDING_STORE_NAME);
  const count = await requestToPromise<number>(store.index(OWNER_INDEX).count(ownerUserId));
  db.close();
  return count;
}

export async function listPendingAttendanceScans() {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return [];
  const db = await openDb();
  const store = db.transaction(PENDING_STORE_NAME, "readonly").objectStore(PENDING_STORE_NAME);
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
  const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
  const store = transaction.objectStore(PENDING_STORE_NAME);
  const existing = await requestToPromise<PendingAttendanceScan | undefined>(store.get(id));
  if (existing?.ownerUserId === ownerUserId) {
    await requestToPromise(store.delete(id));
  }
  db.close();
}

export async function countRejectedAttendanceScans(sessionId: string | null) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId || !sessionId) return 0;
  const db = await openDb();
  const store = db.transaction(REJECTED_STORE_NAME, "readonly").objectStore(REJECTED_STORE_NAME);
  const scans = await requestToPromise<RejectedAttendanceScan[]>(
    store.index(OWNER_INDEX).getAll(ownerUserId),
  );
  db.close();
  return scans.filter((scan) => scan.sessionId === sessionId).length;
}

export async function acknowledgeRejectedAttendanceScans(sessionId: string | null) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId || !sessionId) return 0;
  const db = await openDb();
  const transaction = db.transaction(REJECTED_STORE_NAME, "readwrite");
  const store = transaction.objectStore(REJECTED_STORE_NAME);
  const scans = await requestToPromise<RejectedAttendanceScan[]>(
    store.index(OWNER_INDEX).getAll(ownerUserId),
  );
  const matchingScans = scans.filter((scan) => scan.sessionId === sessionId);
  await Promise.all(matchingScans.map((scan) => requestToPromise(store.delete(scan.id))));
  db.close();
  return matchingScans.length;
}

export async function syncPendingAttendanceScans() {
  if (!navigator.onLine) return { synced: 0, failed: 0, discarded: 0, updates: [] };

  const ownerUserId = getCurrentUserId();
  if (!ownerUserId) return { synced: 0, failed: 0, discarded: 0, updates: [] };
  const scans = await listPendingAttendanceScans();
  let synced = 0;
  let failed = 0;
  let discarded = 0;
  const updates: AttendanceScanSyncUpdate[] = [];

  for (const scan of scans) {
    if (getCurrentUserId() !== ownerUserId || scan.ownerUserId !== ownerUserId) break;
    try {
      const response = await operationsApi.scanMyAttendanceSession({
        sessionId: scan.sessionId,
        qrPayload: scan.qrPayload,
        clientEventId: scan.clientEventId,
        scannedAt: scan.scannedAt,
        deviceId: scan.deviceId,
        syncSource: "offline",
      });
      writeAttendanceSessionProgress(scan.sessionId, {
        scanned_count: response.scanned_count,
        assigned_count: response.assigned_count,
      });
      updates.push({
        sessionId: scan.sessionId,
        status: response.status,
        message: response.message,
        scannedCount: response.scanned_count,
        assignedCount: response.assigned_count,
      });
      await removePendingAttendanceScan(scan.id);
      synced += 1;
    } catch (error) {
      if (isPermanentAttendanceScanError(getErrorCode(error))) {
        await quarantineRejectedAttendanceScan(scan, getErrorCode(error));
        discarded += 1;
      } else {
        failed += 1;
      }
    }
  }

  return { synced, failed, discarded, updates };
}

async function quarantineRejectedAttendanceScan(scan: PendingAttendanceScan, errorCode: string) {
  const ownerUserId = getCurrentUserId();
  if (!ownerUserId || scan.ownerUserId !== ownerUserId) return;
  const db = await openDb();
  const transaction = db.transaction([PENDING_STORE_NAME, REJECTED_STORE_NAME], "readwrite");
  const pendingStore = transaction.objectStore(PENDING_STORE_NAME);
  const rejectedStore = transaction.objectStore(REJECTED_STORE_NAME);
  const rejectedScan: RejectedAttendanceScan = {
    ...scan,
    rejectedAt: new Date().toISOString(),
    errorCode,
  };
  await requestToPromise(rejectedStore.put(rejectedScan));
  await requestToPromise(pendingStore.delete(scan.id));
  db.close();
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
      if (db.objectStoreNames.contains(PENDING_STORE_NAME) && event.oldVersion < 2) {
        db.deleteObjectStore(PENDING_STORE_NAME);
      }
      if (!db.objectStoreNames.contains(PENDING_STORE_NAME)) {
        const store = db.createObjectStore(PENDING_STORE_NAME, { keyPath: "id" });
        store.createIndex(OWNER_INDEX, "ownerUserId", { unique: false });
      }
      if (!db.objectStoreNames.contains(REJECTED_STORE_NAME)) {
        const store = db.createObjectStore(REJECTED_STORE_NAME, { keyPath: "id" });
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
  const code = getErrorCode(error);
  const message = getErrorMessage(error);
  return code === "NETWORK_ERROR"
    || code === "REQUEST_TIMEOUT"
    || /network|fetch|timeout|offline|connection/i.test(message);
}

function getErrorCode(error: unknown) {
  if (typeof error !== "object" || error === null || !("code" in error)) return "";
  return String(error.code);
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  if (typeof error !== "object" || error === null || !("message" in error)) return "";
  return String(error.message);
}

function getCurrentUserId() {
  return useAuthStore.getState().user?.id ?? null;
}

function requireCurrentUserId() {
  const userId = getCurrentUserId();
  if (!userId) throw new Error("An authenticated coordinator session is required.");
  return userId;
}
