import assert from "node:assert/strict";
import test from "node:test";
import {
  attendanceQueueRowId,
  createAttendanceScanReference,
  createRejectedAttendanceScan,
  sanitizeLegacyRejectedAttendanceScan,
} from "./attendance-queue-privacy.ts";

const rawQr = "pdatt:abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNO12";

test("queue row IDs use a deterministic SHA-256 reference and never the raw QR", async () => {
  const input = {
    ownerUserId: "owner-1",
    groupId: "group-1",
    sessionId: "session-1",
    qrPayload: rawQr,
  };
  const first = await createAttendanceScanReference(input);
  const second = await createAttendanceScanReference(input);
  const id = attendanceQueueRowId(first);
  assert.equal(first, second);
  assert.match(first, /^sha256:[0-9a-f]{64}$/);
  assert.doesNotMatch(id, new RegExp(rawQr.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
});

test("terminal rejection records retain safe operator context but no retry bearer", async () => {
  const scanReference = await createAttendanceScanReference({
    ownerUserId: "owner-1",
    groupId: "group-1",
    sessionId: "session-1",
    qrPayload: rawQr,
  });
  const rejected = createRejectedAttendanceScan({
    scanReference,
    ownerUserId: "owner-1",
    groupId: "group-1",
    sessionId: "session-1",
    clientEventId: "event-1",
    scannedAt: "2026-08-22T00:00:00.000Z",
    deviceId: "device-1",
    queuedAt: "2026-08-22T00:00:00.000Z",
  }, "ATTENDANCE_INVALID");
  assert.equal("qrPayload" in rejected, false);
  assert.doesNotMatch(JSON.stringify(rejected), new RegExp(rawQr));
  assert.equal(rejected.clientEventId, "event-1");
  assert.equal(rejected.errorCode, "ATTENDANCE_INVALID");
});

test("legacy rejected rows are re-keyed and scrubbed without losing review metadata", async () => {
  const migrated = await sanitizeLegacyRejectedAttendanceScan({
    id: `owner-1:group-1:session-1:${rawQr}`,
    ownerUserId: "owner-1",
    groupId: "group-1",
    sessionId: "session-1",
    qrPayload: rawQr,
    clientEventId: "event-legacy",
    scannedAt: "2026-08-22T00:00:00.000Z",
    deviceId: "device-1",
    queuedAt: "2026-08-22T00:00:00.000Z",
    rejectedAt: "2026-08-22T00:01:00.000Z",
    errorCode: "HTTP_422",
  });
  assert.ok(migrated);
  assert.equal("qrPayload" in migrated, false);
  assert.doesNotMatch(JSON.stringify(migrated), new RegExp(rawQr));
  assert.equal(migrated.clientEventId, "event-legacy");
  assert.equal(migrated.errorCode, "HTTP_422");
});
