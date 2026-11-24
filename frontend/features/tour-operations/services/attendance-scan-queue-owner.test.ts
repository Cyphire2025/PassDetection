import { beforeEach, describe, expect, it, vi } from "vitest";
import { attendanceTestDatabase } from "../test-support/attendance-database";

const boundary = vi.hoisted(() => ({
  authentication: { user: { id: "owner-a" }, sessionVersion: 1 },
  open: vi.fn(),
  decrypt: vi.fn(),
  runtimeHint: vi.fn(),
  scan: vi.fn(),
  batch: vi.fn(),
  publish: vi.fn(),
  post: vi.fn(),
  progress: vi.fn(),
}));
vi.mock("@/stores/auth.store", () => ({ useAuthStore: { getState: () => boundary.authentication } }));
vi.mock("@/features/operations/api/operations.api", () => ({ operationsApi: {
  scanMyAttendanceSession: boundary.scan, scanMyAttendanceSessionBatch: boundary.batch,
  publishMyAttendanceCloseoutCheckpoint: boundary.publish,
} }));
vi.mock("@/lib/api/client", () => ({ default: { post: boundary.post } }));
vi.mock("./attendance-session-progress", () => ({ writeAttendanceSessionProgress: boundary.progress }));
vi.mock("./browser-offline-authorization", () => ({
  getBrowserAttendanceRuntimeHint: boundary.runtimeHint, authorizeBrowserOfflineScan: vi.fn(),
}));
vi.mock("./browser-offline-database", async (importOriginal) => ({
  ...await importOriginal<typeof import("./browser-offline-database")>(), openBrowserOfflineDatabase: boundary.open,
}));
vi.mock("./browser-offline-crypto", () => ({
  unprotectBrowserJson: boundary.decrypt, protectBrowserJson: vi.fn(),
}));
vi.mock("./attendance-queue-privacy", () => ({
  attendanceQueueRowId: (reference: string) => `row:${reference}`,
  createAttendanceScanReference: async ({ ownerUserId }: { ownerUserId: string }) => `ref:${ownerUserId}`,
  isAttendanceScanReference: () => true,
  createRejectedAttendanceScan: vi.fn(), sanitizeLegacyRejectedAttendanceScan: vi.fn(),
}));

const pendingStore = "pending-attendance-scans";
const discardedStore = "attendance-discard-tombstones";
const qr = `pdatt:${"a".repeat(43)}`;
const now = "2026-01-01T10:00:00.000Z";
const input = { groupId: "group-a", sessionId: "session-a", qrPayload: qr, clientEventId: "event-0001", scannedAt: now, deviceId: "device-a" };
const accepted = { status: "counted", message: "Counted", scanned_count: 1, assigned_count: 2 };

function pendingRow(owner: string, clientEventId = "event-0001") {
  return {
    ...input, qrPayload: undefined, ownerUserId: owner, id: `row:ref:${owner}`, scanReference: `ref:${owner}`,
    clientEventId, queuedAt: now, nextAttemptAt: now, attemptCount: 0, deliveryState: "pending", storageVersion: 5,
    protectedQrPayload: {
      version: 1, algorithm: "AES-GCM", keyId: "coordinator-offline-aes-gcm-v1", ciphertext: new ArrayBuffer(16), iv: new Uint8Array(12),
    },
  };
}

describe("attendance queue owner changes at asynchronous boundaries", () => {
  let storage: ReturnType<typeof attendanceTestDatabase>;
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    storage = attendanceTestDatabase();
    boundary.authentication.user = { id: "owner-a" };
    boundary.open.mockResolvedValue(storage.database);
    boundary.decrypt.mockResolvedValue({ qrPayload: qr });
    boundary.runtimeHint.mockResolvedValue("runtime-a");
    boundary.scan.mockResolvedValue(accepted);
    boundary.publish.mockResolvedValue({ reported_at: now });
    Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
  });

  it("blocks online delivery if the account changes while the runtime hint is loading", async () => {
    boundary.runtimeHint.mockImplementation(async () => {
      boundary.authentication.user = { id: "owner-b" };
      return "runtime-a";
    });
    const queue = await import("./attendance-scan-queue");
    await expect(queue.tryRecordAttendanceScan(input)).rejects.toThrow("owner changed");
    expect(boundary.scan).not.toHaveBeenCalled();
    expect(boundary.open).not.toHaveBeenCalled();
  });

  it("passes the captured owner through a stable online delivery", async () => {
    const queue = await import("./attendance-scan-queue");
    await expect(queue.tryRecordAttendanceScan(input)).resolves.toEqual({ mode: "online", response: accepted });
    expect(boundary.scan).toHaveBeenCalledWith(expect.objectContaining({ expectedOwnerUserId: "owner-a", syncSource: "online" }));
  });

  it.each(["event-0001", "old"])("retains and releases the %s claim if the account changes during claimed-row decryption", async (clientEventId) => {
    storage.rows(pendingStore).set("row:ref:owner-a", pendingRow("owner-a", clientEventId));
    storage.rows(pendingStore).set("row:ref:owner-b", pendingRow("owner-b"));
    boundary.decrypt.mockImplementation(async () => {
      if (storage.rows(pendingStore).get("row:ref:owner-a")?.deliveryState === "sending") {
        boundary.authentication.user = { id: "owner-b" };
      }
      return { qrPayload: qr };
    });
    const queue = await import("./attendance-scan-queue");
    await expect(queue.syncPendingAttendanceScans()).resolves.toEqual({ synced: 0, failed: 0, discarded: 0, updates: [], nextAttemptAt: null });
    expect(boundary.scan).not.toHaveBeenCalled();
    expect(boundary.batch).not.toHaveBeenCalled();
    expect(boundary.progress).not.toHaveBeenCalled();
    expect(storage.rows(pendingStore).get("row:ref:owner-a")).toMatchObject({ ownerUserId: "owner-a", deliveryState: "pending", attemptCount: 1, deliveryStartedAt: undefined });
    expect(storage.rows(pendingStore).get("row:ref:owner-b")).toMatchObject({ ownerUserId: "owner-b", deliveryState: "pending", attemptCount: 0 });
    expect(storage.rows("rejected-attendance-scans").size).toBe(0);
  });

  it("retains privacy-safe discard evidence if the account changes while its delivery claim is committed", async () => {
    storage.rows(discardedStore).set("discard-a", {
      id: "discard-a", ownerUserId: "owner-a", groupId: "group-a", sessionId: "session-a", discardEventId: "discard-event-a",
      capturedAt: now, discardedAt: now, nextAttemptAt: now, attemptCount: 0, syncState: "pending", reasonCategory: "duplicate_local_evidence", scanReference: "ref:owner-a",
    });
    storage.onWrite((store, row) => {
      if (store === discardedStore && row.syncState === "sending") boundary.authentication.user = { id: "owner-b" };
    });
    const queue = await import("./attendance-scan-queue");
    await expect(queue.syncAttendanceDiscardTombstones()).rejects.toThrow("owner changed");
    expect(boundary.post).not.toHaveBeenCalled();
    expect(storage.rows(discardedStore).get("discard-a")).toMatchObject({ ownerUserId: "owner-a", syncState: "pending", attemptCount: 1 });
  });

  it.each(["event-0001", "old"])("suppresses a successful %s response received after an account switch and leaves the original row retryable", async (clientEventId) => {
    storage.rows(pendingStore).set("row:ref:owner-a", pendingRow("owner-a", clientEventId));
    const changeOwner = async () => {
      boundary.authentication.user = { id: "owner-b" };
      return accepted;
    };
    boundary.scan.mockImplementation(changeOwner);
    boundary.batch.mockImplementation(async (request) => {
      await changeOwner();
      return { batch_id: request.batchId, items: [{ client_event_id: clientEventId, outcome: "counted", retryable: false, scan: accepted, error_code: null }] };
    });
    const queue = await import("./attendance-scan-queue");
    const result = await queue.syncPendingAttendanceScans();
    expect(result.updates).toEqual([]);
    expect(boundary.progress).not.toHaveBeenCalled();
    expect(storage.rows(pendingStore).get("row:ref:owner-a")).toMatchObject({ ownerUserId: "owner-a", deliveryState: "pending", attemptCount: 1 });
  });

  it("does not return private pending rows if the owner changes while they are decrypted", async () => {
    storage.rows(pendingStore).set("row:ref:owner-a", pendingRow("owner-a"));
    boundary.decrypt.mockImplementation(async () => {
      boundary.authentication.user = { id: "owner-b" };
      return { qrPayload: qr };
    });
    const queue = await import("./attendance-scan-queue");
    await expect(queue.listPendingAttendanceScans()).rejects.toThrow("owner changed");
    expect(storage.rows(pendingStore).has("row:ref:owner-a")).toBe(true);
  });

  it.each(["event-0001", "old"])("keeps %s retryable when the server detects a cookie actor mismatch before the tab notices it", async (clientEventId) => {
    storage.rows(pendingStore).set("row:ref:owner-a", pendingRow("owner-a", clientEventId));
    const mismatch = { code: "AUTH_REQUEST_OWNER_CHANGED", status: 409, message: "The signed-in account changed." };
    boundary.scan.mockRejectedValue(mismatch);
    boundary.batch.mockRejectedValue(mismatch);
    const queue = await import("./attendance-scan-queue");
    await expect(queue.syncPendingAttendanceScans()).resolves.toMatchObject({ synced: 0, failed: 1, discarded: 0, updates: [] });
    expect(storage.rows(pendingStore).get("row:ref:owner-a")).toMatchObject({ ownerUserId: "owner-a", deliveryState: "pending", attemptCount: 1 });
    expect(storage.rows("rejected-attendance-scans").size).toBe(0);
  });

  it("reconciles a stable owner batch and retains another account's row", async () => {
    storage.rows(pendingStore).set("row:ref:owner-a", pendingRow("owner-a"));
    storage.rows(pendingStore).set("row:ref:owner-b", pendingRow("owner-b"));
    boundary.batch.mockImplementation(async (request) => ({
      batch_id: request.batchId,
      items: [{ client_event_id: "event-0001", outcome: "counted", retryable: false, scan: accepted, error_code: null }],
    }));
    const queue = await import("./attendance-scan-queue");
    await expect(queue.syncPendingAttendanceScans()).resolves.toMatchObject({ synced: 1, discarded: 0, failed: 0 });
    expect(boundary.batch).toHaveBeenCalledWith(expect.objectContaining({ expectedOwnerUserId: "owner-a" }));
    expect(storage.rows(pendingStore).has("row:ref:owner-a")).toBe(false);
    expect(storage.rows(pendingStore).has("row:ref:owner-b")).toBe(true);
    expect(boundary.progress).toHaveBeenCalledWith("group-a", "session-a", { scanned_count: 1, assigned_count: 2 });
  });

  it("binds count-only checkpoint delivery to the owner whose queue was collected", async () => {
    const checkpoint = await import("./attendance-closeout-checkpoint");
    await checkpoint.publishBrowserAttendanceCloseoutCheckpoint("group-a", "session-a");
    expect(boundary.publish).toHaveBeenCalledWith(expect.objectContaining({
      expectedOwnerUserId: "owner-a", groupId: "group-a", sessionId: "session-a",
      checkpoint: expect.objectContaining({ pending_count: 0, runtime_id: "runtime-a" }),
    }));
  });

  it("does not publish checkpoint counts if the account changes while the runtime hint loads", async () => {
    boundary.runtimeHint.mockImplementation(async () => {
      boundary.authentication.user = { id: "owner-b" };
      return "runtime-a";
    });
    const checkpoint = await import("./attendance-closeout-checkpoint");
    await expect(checkpoint.publishBrowserAttendanceCloseoutCheckpoint("group-a", "session-a"))
      .rejects.toThrow("account changed");
    expect(boundary.publish).not.toHaveBeenCalled();
  });
});
