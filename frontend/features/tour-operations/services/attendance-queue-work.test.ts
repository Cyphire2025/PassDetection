import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { PendingAttendanceScan } from "./attendance-queue-contracts";

const fixture = vi.hoisted(() => ({
  owner: "owner-a", now: Date.parse("2026-10-31T10:00:00Z"), reads: 0,
  rows: [] as PendingAttendanceScan[], remaining: [] as PendingAttendanceScan[],
  calls: [] as Array<{ kind: string; ids: string[]; reads: number }>,
  list: vi.fn(), batch: vi.fn(), single: vi.fn(),
}));
vi.mock("@/stores/auth.store", () => ({ useAuthStore: { getState: () => ({
  user: { id: fixture.owner }, sessionVersion: 1,
}) } }));
vi.mock("@/features/operations/api/operations.api", () => ({ operationsApi: {} }));
vi.mock("@/lib/api/client", () => ({ default: {} }));
vi.mock("./browser-offline-authorization", () => ({}));
vi.mock("./attendance-queue-storage", () => ({
  listPendingForOwner: fixture.list,
}));
vi.mock("./attendance-queue-outcomes", async (original) => ({
  ...await original<typeof import("./attendance-queue-outcomes")>(),
  syncPendingAttendanceScanBatch: fixture.batch,
  syncLegacyPendingAttendanceScan: fixture.single,
}));

function row(id: string, sessionId = "session-a"): PendingAttendanceScan {
  return { id, scanReference: `ref:${id}`, ownerUserId: "owner-a", groupId: "group-a",
    sessionId, qrPayload: `pdatt:${"a".repeat(43)}`, clientEventId: `event-${id.padStart(8, "0")}`,
    scannedAt: "2026-01-01T00:00:00Z", queuedAt: "2026-01-01T00:00:00Z",
    nextAttemptAt: "2026-01-01T00:00:00Z", attemptCount: 0,
    deliveryState: "pending", deviceId: "synthetic-runtime" };
}

function installRows(rows: PendingAttendanceScan[]) {
  fixture.rows = new Proxy(rows, { get(target, key, receiver) {
    if (typeof key === "string" && /^\d+$/.test(key)) fixture.reads++;
    return Reflect.get(target, key, receiver);
  } });
  fixture.remaining = [...rows];
  let listed = false;
  fixture.list.mockImplementation(async () => {
    if (listed) return fixture.remaining;
    listed = true;
    return fixture.rows;
  });
}

function successfulChunk(kind: string, scans: PendingAttendanceScan[]) {
  const ids = scans.map(scan => scan.id);
  fixture.calls.push({ kind, ids, reads: fixture.reads });
  fixture.remaining = fixture.remaining.filter(scan => !ids.includes(scan.id));
  return { synced: scans.length, discarded: 0, failed: 0, updates: [], stop: false };
}

beforeEach(() => {
  vi.resetModules(); vi.resetAllMocks();
  fixture.owner = "owner-a"; fixture.reads = 0; fixture.calls = [];
  fixture.now = Date.parse("2026-10-31T10:00:00Z");
  vi.spyOn(Date, "now").mockImplementation(() => fixture.now);
  Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
  Object.defineProperty(navigator, "locks", { value: undefined, configurable: true });
  fixture.batch.mockImplementation(async (scans: PendingAttendanceScan[]) => successfulChunk("batch", scans));
  fixture.single.mockImplementation(async (scan: PendingAttendanceScan) => successfulChunk("legacy", [scan]));
});
afterEach(() => vi.restoreAllMocks());

it("bounds current replay selection work for a representative5000-row single-session snapshot", async () => {
  installRows(Array.from({ length: 5000 }, (_, index) => row(String(index))));
  const { syncPendingAttendanceScans } = await import("./attendance-scan-queue");
  expect(await syncPendingAttendanceScans()).toMatchObject({ synced: 5000, failed: 0, nextAttemptAt: null });
  expect(fixture.calls).toHaveLength(100);
  expect(fixture.calls.every(call => call.ids.length === 50)).toBe(true);
  expect(fixture.calls.flatMap(call => call.ids)).toEqual(Array.from({ length: 5000 }, (_, index) => String(index)));
  console.info("attendance-selection-work", JSON.stringify({ rows: 5000,
    batches: fixture.calls.length, firstDispatchNumericReads: fixture.calls[0].reads,
    totalSnapshotNumericReads: fixture.reads }));
  expect(fixture.calls[0].reads).toBeLessThanOrEqual(60);
  expect(fixture.reads).toBeLessThanOrEqual(300000);
});

it("retains legacy/mixed-session order and reevaluates a later retry after an async batch", async () => {
  const legacy = { ...row("legacy"), clientEventId: "old" };
  const later = { ...row("later"), nextAttemptAt: new Date(fixture.now + 1000).toISOString() };
  installRows([row("first"), legacy, row("other", "session-b"), later, row("last")]);
  fixture.batch.mockImplementation(async (scans) => {
    const result = successfulChunk("batch", scans);
    fixture.now += 1000;
    return result;
  });
  const { syncPendingAttendanceScans } = await import("./attendance-scan-queue");
  expect(await syncPendingAttendanceScans()).toMatchObject({ synced: 5 });
  expect(fixture.calls.map(({ kind, ids }) => ({ kind, ids }))).toEqual([
    { kind: "batch", ids: ["first", "last"] }, { kind: "legacy", ids: ["legacy"] },
    { kind: "batch", ids: ["other"] }, { kind: "batch", ids: ["later"] },
  ]);
});

it("observes snapshot aliases whose identity and session change after a completed batch", async () => {
  const mutable = row("mutable");
  installRows([row("first"), row("other", "session-b"), mutable]);
  fixture.batch.mockImplementation(async (scans) => {
    const result = successfulChunk("batch", scans);
    if (fixture.calls.length === 1) { mutable.id = "changed"; mutable.sessionId = "session-b"; }
    return result;
  });
  const { syncPendingAttendanceScans } = await import("./attendance-scan-queue");
  await syncPendingAttendanceScans();
  expect(fixture.calls.map(call => call.ids)).toEqual([["first", "mutable"], ["other", "changed"]]);
});

it("keeps the original duplicate snapshot selection before the handled set is committed", async () => {
  const same = row("same"); installRows([row("first"), same, same]);
  const { syncPendingAttendanceScans } = await import("./attendance-scan-queue");
  await syncPendingAttendanceScans();
  expect(fixture.calls.map(call => call.ids)).toEqual([["first", "same", "same"]]);
});

it("stops after the first recoverable chunk outcome and preserves remaining scheduling", async () => {
  installRows(Array.from({ length: 120 }, (_, index) => row(String(index))));
  fixture.batch.mockImplementation(async (scans) => {
    fixture.calls.push({ kind: "batch", ids: scans.map((scan: PendingAttendanceScan) => scan.id), reads: fixture.reads });
    return { synced: 0, failed: scans.length, discarded: 0, updates: [], stop: true };
  });
  const { syncPendingAttendanceScans } = await import("./attendance-scan-queue");
  expect(await syncPendingAttendanceScans()).toMatchObject({ synced: 0, failed: 50 });
  expect(fixture.calls).toHaveLength(1);
  expect(fixture.remaining).toHaveLength(120);
});

it("does not select a replacement owner's continuation after its first async chunk", async () => {
  installRows(Array.from({ length: 120 }, (_, index) => row(String(index))));
  fixture.batch.mockImplementation(async (scans) => {
    const result = successfulChunk("batch", scans); fixture.owner = "owner-b"; return result;
  });
  const { syncPendingAttendanceScans } = await import("./attendance-scan-queue");
  expect(await syncPendingAttendanceScans()).toEqual({ synced: 0, failed: 0, discarded: 0, updates: [], nextAttemptAt: null });
  expect(fixture.calls).toHaveLength(1);
});
