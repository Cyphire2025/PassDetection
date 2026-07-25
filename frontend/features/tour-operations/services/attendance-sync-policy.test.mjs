import assert from "node:assert/strict";
import test from "node:test";
import {
  getAttendanceCompletionBlocker,
  getAuthoritativeAttendanceCount,
  getLatestSessionSyncUpdate,
  isPermanentAttendanceScanError,
  isRecoverableAttendanceScanError,
  isSuccessfulAttendanceReplayStatus,
  reconcileLiveAttendanceCount,
  selectVisibleAttendanceSessions,
} from "./attendance-sync-policy.ts";

const update = (status, scannedCount) => ({
  sessionId: "session-1",
  status,
  message: status,
  scannedCount,
  assignedCount: 12,
});

test("counted scans use the backend's authoritative count", () => {
  assert.equal(getAuthoritativeAttendanceCount(update("counted", 8)), 8);
});

test("invalid and duplicate scans cannot inflate an offline count", () => {
  const previouslyCounted = 7;
  assert.equal(getAuthoritativeAttendanceCount(update("invalid", previouslyCounted)), 7);
  assert.equal(getAuthoritativeAttendanceCount(update("duplicate", previouslyCounted)), 7);
});

test("live polling advances other coordinators without regressing a local scan", () => {
  assert.equal(reconcileLiveAttendanceCount(12, 11), 12);
  assert.equal(reconcileLiveAttendanceCount(12, 13), 13);
  assert.equal(reconcileLiveAttendanceCount(null, 13), null);
});

test("the latest response for the active session wins deterministically", () => {
  const updates = [
    update("counted", 8),
    { ...update("counted", 2), sessionId: "another-session" },
    update("duplicate", 8),
  ];
  assert.deepEqual(getLatestSessionSyncUpdate(updates, "session-1"), update("duplicate", 8));
});

test("offline, pending, failed, and rejected queues block completion", () => {
  assert.equal(
    getAttendanceCompletionBlocker({ isOnline: false, pending: 0, failed: 0, rejected: 0 }),
    "offline",
  );
  assert.equal(
    getAttendanceCompletionBlocker({ isOnline: true, pending: 1, failed: 0, rejected: 0 }),
    "pending",
  );
  assert.equal(
    getAttendanceCompletionBlocker({ isOnline: true, pending: 0, failed: 1, rejected: 0 }),
    "failed",
  );
  assert.equal(
    getAttendanceCompletionBlocker({ isOnline: true, pending: 0, failed: 0, rejected: 1 }),
    "rejected",
  );
});

test("a retry can complete only after the rejected queue is explicitly acknowledged", () => {
  const beforeAcknowledgement = getAttendanceCompletionBlocker({
    isOnline: true,
    pending: 0,
    failed: 0,
    rejected: 1,
  });
  const afterAcknowledgement = getAttendanceCompletionBlocker({
    isOnline: true,
    pending: 0,
    failed: 0,
    rejected: 0,
  });
  assert.equal(beforeAcknowledgement, "rejected");
  assert.equal(afterAcknowledgement, null);
});

test("permanent validation failures are quarantined but recoverable auth failures are retried", () => {
  assert.equal(isPermanentAttendanceScanError("HTTP_400"), true);
  assert.equal(isPermanentAttendanceScanError("HTTP_422"), true);
  assert.equal(isPermanentAttendanceScanError("HTTP_403"), false);
  assert.equal(isPermanentAttendanceScanError("HTTP_500"), false);
});

test("temporary HTTP and VPS failures are safe to queue for replay", () => {
  for (const code of ["HTTP_408", "HTTP_425", "HTTP_429", "HTTP_500", "HTTP_502", "HTTP_503", "HTTP_599"]) {
    assert.equal(isRecoverableAttendanceScanError(code), true, code);
  }
  for (const code of ["HTTP_400", "HTTP_401", "HTTP_403", "HTTP_404", "HTTP_409", "HTTP_422"]) {
    assert.equal(isRecoverableAttendanceScanError(code), false, code);
  }
});

test("offline replay clears only counted or already-counted scans", () => {
  assert.equal(isSuccessfulAttendanceReplayStatus("counted"), true);
  assert.equal(isSuccessfulAttendanceReplayStatus("duplicate"), true);
  assert.equal(isSuccessfulAttendanceReplayStatus("invalid"), false);
  assert.equal(isSuccessfulAttendanceReplayStatus("future_non_counting_status"), false);
});

test("fresh server sessions immediately override stale local progress after reload", () => {
  const serverSessions = [{ id: "session-1", scanned_count: 5 }];
  const cachedSessions = [{ id: "session-1", scanned_count: 9 }];
  let mergeCalls = 0;

  const visible = selectVisibleAttendanceSessions(
    true,
    serverSessions,
    cachedSessions,
    (sessions) => {
      mergeCalls += 1;
      return sessions;
    },
  );

  assert.equal(visible[0].scanned_count, 5);
  assert.equal(mergeCalls, 0);
});
