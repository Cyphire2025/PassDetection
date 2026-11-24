import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { attendanceTestDatabase } from "../test-support/attendance-database";

const transport = vi.hoisted(() => ({
  authentication: { user: { id: "owner-a" }, sessionVersion: 1 },
  batch: vi.fn(), single: vi.fn(), post: vi.fn(), progress: vi.fn(),
}));
vi.mock("@/stores/auth.store", () => ({ useAuthStore: { getState: () => transport.authentication } }));
vi.mock("@/features/operations/api/operations.api", () => ({ operationsApi: {
  scanMyAttendanceSessionBatch: transport.batch, scanMyAttendanceSession: transport.single,
} }));
vi.mock("@/lib/api/client", () => ({ default: { post: transport.post } }));
vi.mock("./attendance-session-progress", () => ({ writeAttendanceSessionProgress: transport.progress }));
vi.mock("./browser-offline-authorization", () => ({ getBrowserAttendanceRuntimeHint: vi.fn() }));
// Exercise actual queue/privacy/database modules through an IndexedDB API fixture.
// This transport fixture cannot establish browser crash durability or real crypto.
vi.mock("./browser-offline-crypto", () => ({
  unprotectBrowserJson: async () => ({ qrPayload: `pdatt:${"a".repeat(43)}` }),
  protectBrowserJson: vi.fn(),
}));

const pendingStore = "pending-attendance-scans";
const discardStore = "attendance-discard-tombstones";
const old = "2026-01-01T10:00:00.000Z";

describe("attendance persisted sending ownership", () => {
  let storage: ReturnType<typeof attendanceTestDatabase>;
  let lockRequests: string[];

  beforeEach(() => {
    vi.resetModules(); vi.clearAllMocks();
    transport.authentication = { user: { id: "owner-a" }, sessionVersion: 1 };
    storage = attendanceTestDatabase(); lockRequests = [];
    const lanes = new Map<string, Promise<void>>();
    vi.stubGlobal("crypto", webcrypto);
    vi.stubGlobal("indexedDB", { open: vi.fn(() => {
      const request = { result: storage.database, onsuccess: null as (() => void) | null };
      queueMicrotask(() => request.onsuccess?.());
      return request;
    }) });
    Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
    Object.defineProperty(navigator, "locks", { value: { request: vi.fn(async (
      name: string, _options: unknown, operation: () => Promise<unknown>,
    ) => {
      lockRequests.push(name);
      const previous = lanes.get(name) ?? Promise.resolve();
      let release!: () => void;
      const completion = new Promise<void>((resolve) => { release = resolve; });
      lanes.set(name, completion);
      await previous;
      try { return await operation(); }
      finally { release(); if (lanes.get(name) === completion) lanes.delete(name); }
    }) }, configurable: true });
  });
  afterEach(() => { vi.unstubAllGlobals(); Reflect.deleteProperty(navigator, "locks"); });

  async function seedSending(ownerUserId = "owner-a", event = "event-0001") {
    const { createAttendanceScanReference, attendanceQueueRowId } = await import("./attendance-queue-privacy");
    const scanReference = await createAttendanceScanReference({
      ownerUserId, groupId: "group-a", sessionId: "session-a", qrPayload: `pdatt:${"a".repeat(43)}`,
    });
    const row = {
      id: attendanceQueueRowId(scanReference), scanReference, ownerUserId,
      groupId: "group-a", sessionId: "session-a", clientEventId: event,
      scannedAt: old, deviceId: "device-a", queuedAt: old, nextAttemptAt: old,
      attemptCount: 2, deliveryState: "sending", deliveryStartedAt: old, storageVersion: 5,
      protectedQrPayload: { version: 1, algorithm: "AES-GCM", keyId: "coordinator-offline-aes-gcm-v1", ciphertext: new ArrayBuffer(16), iv: new Uint8Array(12) },
    };
    storage.rows(pendingStore).set(row.id, row);
    return row;
  }

  it("reconciles an interrupted protected-v5 claim only inside the next exclusive drain", async () => {
    const row = await seedSending(); const other = await seedSending("owner-b");
    transport.batch.mockImplementation(async ({ batchId, scans }) => ({ batch_id: batchId,
      items: scans.map((scan: { clientEventId: string }) => ({ client_event_id: scan.clientEventId,
        outcome: "duplicate", retryable: false, error_code: null, scan: { status: "duplicate", message: "Already counted", scanned_count: 1, assigned_count: 2 } })) }));
    const queue = await import("./attendance-scan-queue");
    expect(await queue.getNextPendingAttendanceAttemptAt()).toBeNull();
    await expect(queue.syncPendingAttendanceScans()).resolves.toMatchObject({ synced: 1, failed: 0 });
    expect(transport.batch).toHaveBeenCalledOnce();
    expect(transport.batch.mock.calls[0][0]).toMatchObject({ expectedOwnerUserId: "owner-a",
      scans: [{ clientEventId: row.clientEventId, scannedAt: row.scannedAt }] });
    expect(lockRequests.some((name) => name.includes("attendance-drain:owner-a"))).toBe(true);
    expect(storage.rows(pendingStore).has(row.id)).toBe(false);
    expect(storage.rows(pendingStore).get(other.id)).toEqual(other);
  });

  it.each([undefined, {}])("retains unknown sending outcomes without a usable lock manager: %j", async (locks) => {
    const row = await seedSending();
    Reflect.deleteProperty(navigator, "locks");
    if (locks) Object.defineProperty(navigator, "locks", { value: locks, configurable: true });
    const queue = await import("./attendance-scan-queue");
    await expect(queue.syncPendingAttendanceScans()).resolves.toMatchObject({ synced: 0 });
    expect(transport.batch).not.toHaveBeenCalled();
    expect(storage.rows(pendingStore).get(row.id)).toEqual(row);
  });

  it("does not release a live claim while another document holds the drain lock", async () => {
    const row = await seedSending();
    storage.rows(pendingStore).set(row.id, { ...row, deliveryState: "pending", deliveryStartedAt: undefined });
    let finish!: (value: unknown) => void;
    transport.batch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const firstDocument = await import("./attendance-scan-queue");
    const first = firstDocument.syncPendingAttendanceScans();
    await vi.waitFor(() => expect(transport.batch).toHaveBeenCalledOnce());
    vi.resetModules();
    const nextDocument = await import("./attendance-scan-queue");
    const next = nextDocument.syncPendingAttendanceScans();
    await vi.waitFor(() => expect(lockRequests.filter((name) => name.includes("attendance-drain:owner-a"))).toHaveLength(2));
    expect(transport.batch).toHaveBeenCalledOnce();
    expect(storage.rows(pendingStore).get(row.id)).toMatchObject({ deliveryState: "sending" });
    finish({ batch_id: transport.batch.mock.calls[0][0].batchId, items: [{
      client_event_id: row.clientEventId, outcome: "counted", retryable: false, error_code: null,
      scan: { status: "counted", message: "Counted", scanned_count: 1, assigned_count: 2 },
    }] });
    await expect(first).resolves.toMatchObject({ synced: 1 });
    await expect(next).resolves.toMatchObject({ synced: 0 });
    expect(transport.batch).toHaveBeenCalledOnce();
  });

  it("retains protected data and retries after authorization denies a recovered delivery", async () => {
    const row = await seedSending();
    transport.batch.mockRejectedValueOnce({ code: "HTTP_401" });
    const queue = await import("./attendance-scan-queue");
    await expect(queue.syncPendingAttendanceScans()).resolves.toMatchObject({ synced: 0, failed: 1 });
    expect(storage.rows(pendingStore).get(row.id)).toMatchObject({
      scanReference: row.scanReference, clientEventId: row.clientEventId, scannedAt: row.scannedAt,
      protectedQrPayload: row.protectedQrPayload, deliveryState: "pending", attemptCount: 3,
    });
    expect(transport.progress).not.toHaveBeenCalled();
  });

  it("preserves the permitted retry time of an interrupted delivery", async () => {
    const row = await seedSending();
    const nextAttemptAt = new Date(Date.now() + 60_000).toISOString();
    storage.rows(pendingStore).set(row.id, { ...row, nextAttemptAt });
    const queue = await import("./attendance-scan-queue");
    await expect(queue.syncPendingAttendanceScans()).resolves.toMatchObject({ synced: 0, nextAttemptAt });
    expect(transport.batch).not.toHaveBeenCalled();
    expect(storage.rows(pendingStore).get(row.id)).toMatchObject({ deliveryState: "pending", nextAttemptAt, attemptCount: 2 });
  });

  it("does not rewrite an interrupted row that fails protected identity validation", async () => {
    const row = await seedSending();
    const invalid = { ...row, scanReference: `sha256:${"0".repeat(64)}` };
    storage.rows(pendingStore).set(row.id, invalid);
    const queue = await import("./attendance-scan-queue");
    await expect(queue.syncPendingAttendanceScans()).rejects.toThrow("identity check");
    expect(transport.batch).not.toHaveBeenCalled();
    expect(storage.rows(pendingStore).get(row.id)).toEqual(invalid);
  });

  it("reconciles an interrupted discard with its original event identity under the owner lock", async () => {
    const row = { id: "discard-row", discardEventId: "f3cfd7e1-23aa-43f4-bafc-2ca43cc8b733",
      ownerUserId: "owner-a", groupId: "group-a", sessionId: "session-a", capturedAt: old,
      discardedAt: old, reasonCategory: "operator_discard", scanReference: `sha256:${"a".repeat(64)}`,
      syncState: "sending", attemptCount: 1, nextAttemptAt: old, lastAttemptAt: old };
    storage.rows(discardStore).set(row.id, row);
    transport.post.mockResolvedValue({ data: { items: [{ discard_event_id: row.discardEventId, status: "already_applied", reason_code: null }] } });
    const queue = await import("./attendance-scan-queue");
    await expect(queue.syncAttendanceDiscardTombstones()).resolves.toMatchObject({ synchronized: 1, pending: 0 });
    expect(transport.post.mock.calls[0][1].items).toEqual([expect.objectContaining({ discard_event_id: row.discardEventId })]);
    expect(JSON.stringify(transport.post.mock.calls[0][1])).not.toMatch(/qrPayload|qr_payload|passenger/);
    expect(storage.rows(discardStore).get(row.id)).toMatchObject({ syncState: "synchronized" });
  });

  it("retains an interrupted discard when cross-tab exclusion is unavailable", async () => {
    const row = { id: "unknown-discard", ownerUserId: "owner-a", syncState: "sending", discardedAt: old, nextAttemptAt: old };
    storage.rows(discardStore).set(row.id, row);
    Reflect.deleteProperty(navigator, "locks");
    const queue = await import("./attendance-scan-queue");
    await expect(queue.syncAttendanceDiscardTombstones()).resolves.toMatchObject({ synchronized: 0, pending: 1 });
    expect(transport.post).not.toHaveBeenCalled();
    expect(storage.rows(discardStore).get(row.id)).toEqual(row);
  });

  it("preserves direct capacity constructor and public constant identities", async () => {
    const queue = await import("./attendance-scan-queue");
    const contracts = await import("./attendance-queue-contracts");
    expect(queue.AttendanceQueueCapacityError).toBe(contracts.AttendanceQueueCapacityError);
    expect(new queue.AttendanceQueueCapacityError()).toMatchObject({ name: "AttendanceQueueCapacityError", code: "ATTENDANCE_QUEUE_CAPACITY_REACHED" });
    expect(queue.MAX_PENDING_ATTENDANCE_SCANS_PER_OWNER).toBe(5_000);
  });

  it("preserves owner-attributed unscoped legacy rows during explicitly confirmed sign-out", async () => {
    const row = await seedSending();
    storage.rows(pendingStore).delete(row.id);
    const { createRejectedAttendanceScan } = await import("./attendance-queue-privacy");
    const rejected = createRejectedAttendanceScan({ ...row, groupId: undefined }, "HTTP_400", old);
    storage.rows("rejected-attendance-scans").set(rejected.id, { ...rejected, storageVersion: 5 });
    // Explicit discard currently allows sign-out while retaining an unscoped
    // terminal record; it cannot invent a group for privacy-safe audit evidence.
    const allowed = vi.fn().mockResolvedValue("signed-out");
    const queue = await import("./attendance-scan-queue");
    await expect(queue.runAttendanceQueueLogoutBoundary("owner-a", "discard", allowed)).resolves.toMatchObject({ allowed: true, value: "signed-out" });
    expect(allowed).toHaveBeenCalledOnce();
    expect(storage.rows("rejected-attendance-scans").has(rejected.id)).toBe(true);
  });
});
