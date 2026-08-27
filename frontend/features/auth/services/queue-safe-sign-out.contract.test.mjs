import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), "utf8");

const authStore = read("../../../stores/auth.store.ts");
const sessionState = read("./session-state.ts");
const guard = read("../components/queue-safe-sign-out-guard.tsx");
const queue = read("../../tour-operations/services/attendance-scan-queue.ts");
const privacy = read("../../tour-operations/services/attendance-queue-privacy.ts");
const activity = read("../../tour-operations/components/coordinator-group-activity-page.tsx");
const apiClient = read("../../../lib/api/client.ts");

test("voluntary logout is owner-locked and blocked by default", () => {
  assert.match(authStore, /queueDisposition = "block"/);
  assert.match(authStore, /reason !== "logout"/);
  assert.match(authStore, /runAttendanceQueueLogoutBoundary/);
  assert.match(queue, /withOwnerQueueLock\(ownerUserId/);
  assert.match(queue, /hasUnsafeBrowserAttendanceQueue\(snapshot\)/);
  assert.match(authStore, /requestQueueSafeSignOutReview\(boundary\.snapshot\)/);
});

test("logout recovery offers sync first and requires two destructive confirmations", () => {
  assert.match(guard, /Sync then sign out/);
  assert.match(guard, /discard-warning/);
  assert.match(guard, /Continue to final confirmation/);
  assert.match(guard, /discard-final/);
  assert.match(guard, /Permanently discard and sign out/);
  assert.match(guard, /queueDisposition: "discard"/);
});

test("auth loss and account change preserve the owner-scoped queue", () => {
  assert.doesNotMatch(sessionState, /deleteDatabase|TOUR_OPERATIONS_DB/);
  assert.match(sessionState, /owner-scoped attendance queue is deliberately excluded/);
  assert.match(queue, /store\.index\(OWNER_INDEX\)\.getAll\(ownerUserId\)/);
  assert.match(queue, /ownerUserId !== ownerUserId/);
  assert.match(authStore, /current\.user\?\.id !== expectedUserId/);
});

test("terminal records and keys cannot retain the raw QR bearer", () => {
  assert.match(queue, /interface RejectedAttendanceScan \{/);
  const rejectedInterface = queue.slice(
    queue.indexOf("export interface RejectedAttendanceScan"),
    queue.indexOf("interface StoredPendingAttendanceScan"),
  );
  assert.doesNotMatch(rejectedInterface, /qrPayload/);
  assert.match(privacy, /id: `attendance-rejected:\$\{scan\.scanReference\}`/);
  assert.match(queue, /sanitizeLegacyRejectedAttendanceScan/);
  assert.doesNotMatch(privacy, /\.\.\.scan/);
});

test("429 and 503 API errors carry only a bounded Retry-After delay", () => {
  assert.match(apiClient, /responseStatus === 429 \|\| responseStatus === 503/);
  assert.match(apiClient, /parseRetryAfterMs/);
  assert.match(queue, /retryAfterMs: getRetryAfterMs/);
  assert.match(queue, /nextAttemptAt/);
});

test("closeout copy describes the account checkpoint and never claims device-fleet proof", () => {
  assert.match(activity, /coordinator-account closeout checkpoint/);
  assert.doesNotMatch(activity, /fleet closeout checkpoint/i);
});
