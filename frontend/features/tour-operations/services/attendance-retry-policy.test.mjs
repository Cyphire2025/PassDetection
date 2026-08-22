import assert from "node:assert/strict";
import test from "node:test";
import {
  attendanceRetryState,
  classifyAttendanceCloseoutQueue,
  earliestAttendanceAttemptAt,
  isAttendanceAttemptEligible,
} from "./attendance-retry-policy.ts";

test("server Retry-After wins over local backoff and receives only positive jitter", () => {
  const now = Date.parse("2026-08-22T00:00:00.000Z");
  const state = attendanceRetryState({
    previousAttemptCount: 0,
    retryAfterMs: 30_000,
    nowMs: now,
    randomValue: 0.5,
  });
  assert.equal(state.attemptCount, 1);
  assert.equal(Date.parse(state.nextAttemptAt), now + 32_500);
  assert.equal(isAttendanceAttemptEligible(state.nextAttemptAt, state.nextAttemptAt, now + 30_000), false);
  assert.equal(isAttendanceAttemptEligible(state.nextAttemptAt, state.nextAttemptAt, now + 32_500), true);
});

test("closeout classifies a retry row as retryable rather than pending", () => {
  const counts = classifyAttendanceCloseoutQueue([
    {
      attemptCount: 2,
      deliveryState: "pending",
      groupId: "group-1",
      queuedAt: "2026-08-22T00:00:00.000Z",
      sessionId: "session-1",
    },
  ], "group-1", "session-1");
  assert.deepEqual(counts, {
    pending: 0,
    sending: 0,
    retryable: 1,
    oldestQueuedAt: "2026-08-22T00:00:00.000Z",
  });
});

test("closeout classifies an active delivery as sending rather than pending", () => {
  const counts = classifyAttendanceCloseoutQueue([
    {
      attemptCount: 0,
      deliveryState: "sending",
      groupId: "group-1",
      queuedAt: "2026-08-22T00:00:00.000Z",
      sessionId: "session-1",
    },
  ], "group-1", "session-1");
  assert.deepEqual(counts, {
    pending: 0,
    sending: 1,
    retryable: 0,
    oldestQueuedAt: "2026-08-22T00:00:00.000Z",
  });
});

test("closeout counts and oldest age are scoped to the canonical group session", () => {
  const counts = classifyAttendanceCloseoutQueue([
    {
      attemptCount: 0,
      deliveryState: "pending",
      groupId: "group-1",
      queuedAt: "2026-08-22T00:00:05.000Z",
      sessionId: "session-1",
    },
    {
      attemptCount: 0,
      deliveryState: "sending",
      groupId: "group-1",
      queuedAt: "2026-08-22T00:00:03.000Z",
      sessionId: "session-1",
    },
    {
      attemptCount: 3,
      deliveryState: "pending",
      groupId: "group-1",
      queuedAt: "2026-08-22T00:00:01.000Z",
      sessionId: "session-1",
    },
    {
      attemptCount: 0,
      deliveryState: "pending",
      groupId: "group-1",
      queuedAt: "2026-08-21T00:00:00.000Z",
      sessionId: "another-session",
    },
  ], "group-1", "session-1");
  assert.deepEqual(counts, {
    pending: 1,
    sending: 1,
    retryable: 1,
    oldestQueuedAt: "2026-08-22T00:00:01.000Z",
  });
});

test("local retry backoff grows and remains bounded", () => {
  const now = Date.parse("2026-08-22T00:00:00.000Z");
  const first = attendanceRetryState({ previousAttemptCount: 0, nowMs: now, randomValue: 0 });
  const fifth = attendanceRetryState({ previousAttemptCount: 4, nowMs: now, randomValue: 0 });
  const huge = attendanceRetryState({ previousAttemptCount: 100, nowMs: now, randomValue: 1 });
  assert.equal(Date.parse(first.nextAttemptAt) - now, 1_000);
  assert.equal(Date.parse(fifth.nextAttemptAt) - now, 16_000);
  assert.ok(Date.parse(huge.nextAttemptAt) - now <= 65_000);
});

test("earliest persisted attempt drives the exact queue wakeup", () => {
  assert.equal(
    earliestAttendanceAttemptAt([
      { queuedAt: "2026-08-22T00:00:00.000Z", nextAttemptAt: "2026-08-22T00:00:20.000Z" },
      { queuedAt: "2026-08-22T00:00:01.000Z", nextAttemptAt: "2026-08-22T00:00:10.000Z" },
    ]),
    "2026-08-22T00:00:10.000Z",
  );
});
