import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  projectRejectedAttendanceScanForStorage,
} from "./rejected-attendance-scan-projection.ts";

const queue = readFileSync(
  new URL("./attendance-scan-queue.ts", import.meta.url),
  "utf8",
);
const offlineScanner = readFileSync(
  new URL("../../../public/offline-scanner.js", import.meta.url),
  "utf8",
);
const serviceWorker = readFileSync(
  new URL("../../../public/sw.js", import.meta.url),
  "utf8",
);

test("legacy rejected scans are projected to secret-free values and keys", () => {
  const qrPayload = `pdatt:${"a".repeat(43)}`;
  const projected = projectRejectedAttendanceScanForStorage({
    groupId: "group-1",
    sessionId: "session-1",
    clientEventId: "event-1",
    scannedAt: "2026-07-31T10:00:00.000Z",
    deviceId: "device-1",
    ownerUserId: "user-1",
    queuedAt: "2026-07-31T10:00:00.000Z",
    id: `user-1:group-1:session-1:${qrPayload}`,
    qrPayload,
    rejectedAt: "2026-07-31T10:01:00.000Z",
    errorCode: "ATTENDANCE_WRONG_GROUP",
  });

  assert.deepEqual(projected, {
    groupId: "group-1",
    sessionId: "session-1",
    clientEventId: "event-1",
    scannedAt: "2026-07-31T10:00:00.000Z",
    deviceId: "device-1",
    ownerUserId: "user-1",
    queuedAt: "2026-07-31T10:00:00.000Z",
    id: "user-1:group-1:session-1:event-1",
    rejectedAt: "2026-07-31T10:01:00.000Z",
    errorCode: "ATTENDANCE_WRONG_GROUP",
  });
  assert.equal(JSON.stringify(projected).includes(qrPayload), false);
  assert.equal(projected && "qrPayload" in projected, false);
});

test("both queue openers run the v4 rejected-record migration", () => {
  for (const source of [queue, offlineScanner]) {
    assert.match(source, /const DB_VERSION = 4/);
    assert.match(source, /event\.oldVersion < 4/);
    assert.match(
      source,
      /PENDING_STORE_NAME\)[\s\S]*?event\.oldVersion < 2[\s\S]*?deleteObjectStore\(PENDING_STORE_NAME\)/,
    );
    assert.match(source, /migrateRejectedAttendanceScans\(rejectedStore\)/);
    assert.match(source, /store\.put\(migrated\)/);
    assert.match(source, /store\.delete\(cursor\.primaryKey\)/);
  }
  assert.match(serviceWorker, /passdetection-public-static-v9/);
});
