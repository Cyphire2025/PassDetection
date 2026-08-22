import assert from "node:assert/strict";
import test from "node:test";

import {
  CANONICAL_ATTENDANCE_LOAD,
  validateAttendanceCountReconciliation,
  validateAttendanceLoadEntries,
} from "./mobile-attendance-load-contract.mjs";

const uuid = (value) => `00000000-0000-4000-8000-${String(value).padStart(12, "0")}`;
const qr = (suffix) => `pdatt:${String(suffix).padStart(43, "A")}`;
const entry = (coordinator, actionCount = 2, duplicateCount = 1) => ({
  access_token: `synthetic-token-${String(coordinator).padEnd(40, "x")}`,
  trip_id: uuid(9000),
  session_id: uuid(8000),
  actions: Array.from({ length: actionCount }, (_, index) => ({
    client_event_id: uuid(coordinator * 100 + index),
    duplicate_client_event_id: index < duplicateCount
      ? uuid(100000 + coordinator * 100 + index)
      : null,
    signed_qr: qr(coordinator * 100 + index),
  })),
});

test("locks the release gate to 25 coordinators, 800 fresh scans, and 100 duplicates", () => {
  assert.deepEqual(CANONICAL_ATTENDANCE_LOAD, {
    coordinatorCount: 25,
    duplicatesPerCoordinator: 4,
    scansPerCoordinator: 32,
  });
  assert.equal(
    CANONICAL_ATTENDANCE_LOAD.coordinatorCount
      * CANONICAL_ATTENDANCE_LOAD.scansPerCoordinator,
    800,
  );
  assert.equal(
    CANONICAL_ATTENDANCE_LOAD.coordinatorCount
      * CANONICAL_ATTENDANCE_LOAD.duplicatesPerCoordinator,
    100,
  );
  assert.equal(Object.isFrozen(CANONICAL_ATTENDANCE_LOAD), true);
});

test("accepts unique fresh and deliberate-duplicate actions with an immutable projection", () => {
  const result = validateAttendanceLoadEntries([entry(1), entry(2)], 2, 2, 1);
  assert.equal(result.length, 2);
  assert.equal(result[0].actions.length, 2);
  assert.deepEqual(Object.keys(result[0]).sort(), [
    "accessToken",
    "actions",
    "sessionId",
    "tripId",
  ]);
  assert.equal(Object.isFrozen(result[0].actions), true);
  assert.match(result[0].actions[0].duplicateClientEventId, /^[0-9a-f-]+$/);
  assert.equal(result[0].actions[1].duplicateClientEventId, null);
});

test("requires exact empty-before and 800-after authoritative count reconciliation", () => {
  const sessionId = uuid(8000);
  const response = (scannedCount) => ({
    session: {
      id: sessionId,
      name: "Synthetic release gate",
      status: "active",
      scanned_count: scannedCount,
      assigned_count: 800,
      started_at: "2026-08-22T00:00:00Z",
      completed_at: null,
    },
    missing: [],
    next_cursor: null,
  });
  assert.deepEqual(validateAttendanceCountReconciliation(response(0), sessionId, 800, 0), {
    assignedCount: 800,
    scannedCount: 0,
    status: "active",
  });
  assert.equal(
    validateAttendanceCountReconciliation(response(800), sessionId, 800, 800).scannedCount,
    800,
  );
  assert.throws(
    () => validateAttendanceCountReconciliation(response(799), sessionId, 800, 800),
    /did not match/,
  );
  assert.throws(
    () => validateAttendanceCountReconciliation(
      { ...response(800), unexpected: "data" },
      sessionId,
      800,
      800,
    ),
    /response contract/,
  );
});

test("rejects duplicate sessions and actions without echoing bearer values", () => {
  const reusedSession = entry(1);
  let sessionError;
  try {
    validateAttendanceLoadEntries(
      [reusedSession, { ...entry(2), access_token: reusedSession.access_token }],
      2,
      2,
      1,
    );
  } catch (error) {
    sessionError = error;
  }
  assert.ok(sessionError instanceof Error);
  assert.equal(sessionError.message.includes(reusedSession.access_token), false);

  const duplicateQr = entry(2);
  duplicateQr.actions[0].signed_qr = reusedSession.actions[0].signed_qr;
  let actionError;
  try {
    validateAttendanceLoadEntries([reusedSession, duplicateQr], 2, 2, 1);
  } catch (error) {
    actionError = error;
  }
  assert.ok(actionError instanceof Error);
  assert.equal(actionError.message.includes(reusedSession.actions[0].signed_qr), false);
});

test("rejects reused duplicate IDs and an incomplete deliberate-duplicate fixture", () => {
  const first = entry(1);
  const reusedId = entry(2);
  reusedId.actions[0].duplicate_client_event_id = first.actions[0].client_event_id;
  assert.throws(
    () => validateAttendanceLoadEntries([first, reusedId], 2, 2, 1),
    /duplicate synthetic event identifier/,
  );

  const missingDuplicate = entry(1);
  missingDuplicate.actions[0].duplicate_client_event_id = null;
  assert.throws(
    () => validateAttendanceLoadEntries([missingDuplicate], 1, 2, 1),
    /action 0 is invalid/,
  );
});

test("fails closed on insufficient or malformed fixtures", () => {
  assert.throws(
    () => validateAttendanceLoadEntries([entry(1)], 2, 2, 1),
    /exact coordinator count/,
  );
  assert.throws(
    () => validateAttendanceLoadEntries([entry(1, 1)], 1, 2, 1),
    /entry 0 is invalid/,
  );
  assert.throws(
    () => validateAttendanceLoadEntries(
      [{ ...entry(1), session_id: "not-a-uuid" }],
      1,
      2,
      1,
    ),
    /entry 0 is invalid/,
  );
  assert.throws(
    () => validateAttendanceLoadEntries([entry(1)], 1, 2, 3),
    /deliberate duplicate count is invalid/,
  );
});
