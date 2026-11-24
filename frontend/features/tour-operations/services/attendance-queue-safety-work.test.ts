import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { attendanceTestDatabase } from "../test-support/attendance-database";

vi.mock("@/stores/auth.store", () => ({ useAuthStore: { getState: () => ({
  user: { id: "owner-a" }, sessionVersion: 1,
}) } }));
vi.mock("@/lib/api/client", () => ({ default: {} }));
vi.mock("./browser-offline-crypto", () => ({
  unprotectBrowserJson: async (envelope: { ciphertext: ArrayBuffer }) => (
    JSON.parse(new TextDecoder().decode(envelope.ciphertext))
  ),
}));
vi.mock("./attendance-queue-privacy", () => ({
  createAttendanceScanReference: async ({ qrPayload }: { qrPayload: string }) => `ref:${qrPayload}`,
  attendanceQueueRowId: (reference: string) => `row:${reference}`,
  isAttendanceScanReference: () => true,
}));

const storeName = "pending-attendance-scans";
let storage: ReturnType<typeof attendanceTestDatabase>;

function seed(size: number) {
  for (let index = size - 1; index >= 0; index--) {
    const qrPayload = `pdatt:${String(index).padStart(43, "a")}`;
    const scanReference = `ref:${qrPayload}`;
    const queuedAt = new Date(Date.parse("2026-01-01T00:00:00Z") + index * 1000).toISOString();
    const ciphertext = new TextEncoder().encode(JSON.stringify({ qrPayload })).buffer;
    storage.rows(storeName).set(`row:${scanReference}`, {
      id: `row:${scanReference}`, scanReference, ownerUserId: "owner-a", groupId: "group-a",
      sessionId: "session-a", clientEventId: `event-${index}`, scannedAt: queuedAt,
      deviceId: "synthetic-runtime", queuedAt, nextAttemptAt: queuedAt,
      deliveryState: index % 3 === 0 ? "sending" : "pending",
      attemptCount: index % 3 === 1 ? 1 : 0, storageVersion: 5,
      protectedQrPayload: { algorithm: "AES-GCM", version: 1, keyId: "coordinator-offline-aes-gcm-v1",
        ciphertext, iv: new Uint8Array(12) },
    });
  }
}

beforeEach(() => {
  vi.resetModules(); storage = attendanceTestDatabase();
  vi.stubGlobal("indexedDB", { open() {
    const request = { result: storage.database, onsuccess: null as (() => void) | null };
    queueMicrotask(() => request.onsuccess?.()); return request;
  } });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("reuses the actual verified storage order instead of sorting5000timestamps a second time", async () => {
  seed(5000);
  const compare = vi.spyOn(String.prototype, "localeCompare");
  const { listPendingForOwner } = await import("./attendance-queue-storage");
  const ordered = await listPendingForOwner("owner-a");
  const storageComparisons = compare.mock.calls.length;
  expect(ordered[0].queuedAt).toBe("2026-01-01T00:00:00.000Z");
  expect(ordered.at(-1)?.queuedAt).toBe("2026-01-01T01:23:19.000Z");
  compare.mockClear();
  const { getBrowserAttendanceQueueSafetySnapshot } = await import("./attendance-scan-queue");
  const snapshot = await getBrowserAttendanceQueueSafetySnapshot();
  expect(snapshot).toMatchObject({ pending: 1666, sending: 1667, retryable: 1667,
    oldestQueuedAt: ordered[0].queuedAt, review: 0, discardAuditPending: 0 });
  console.info("attendance-oldest-work", JSON.stringify({ rows: 5000, storageComparisons,
    safetySnapshotComparisons: compare.mock.calls.length }));
  expect(compare.mock.calls.length).toBe(storageComparisons);
});

it("retains the empty queue safety outcome", async () => {
  const { getBrowserAttendanceQueueSafetySnapshot } = await import("./attendance-scan-queue");
  expect(await getBrowserAttendanceQueueSafetySnapshot()).toEqual({ ownerUserId: "owner-a",
    pending: 0, sending: 0, retryable: 0, review: 0, discardAuditPending: 0,
    oldestQueuedAt: null, nextAttemptAt: null });
});

it("keeps existing locale ordering of stored timestamp strings without normalization", async () => {
  seed(3);
  const last = [...storage.rows(storeName).values()][0];
  storage.rows(storeName).set(String(last.id), { ...last, queuedAt: "Not-an-ISO-timestamp" });
  const { listPendingForOwner } = await import("./attendance-queue-storage");
  const ordered = await listPendingForOwner("owner-a");
  const { getBrowserAttendanceQueueSafetySnapshot } = await import("./attendance-scan-queue");
  expect((await getBrowserAttendanceQueueSafetySnapshot()).oldestQueuedAt).toBe(ordered[0].queuedAt);
  expect(storage.rows(storeName).get(String(last.id))?.queuedAt).toBe("Not-an-ISO-timestamp");
});
