import assert from "node:assert/strict";
import test from "node:test";
import {
  getEmptyPassportAutoCaptureProgress,
  getPassportAutoCaptureProgress,
  PASSPORT_AUTO_CAPTURE_STABLE_MS,
} from "./passport-auto-capture.ts";

test("requires five continuous seconds before auto capture", () => {
  const start = 1_000;

  assert.equal(getPassportAutoCaptureProgress(start, start).secondsRemaining, 5);
  assert.equal(getPassportAutoCaptureProgress(start, start + 4_999).isComplete, false);
  assert.equal(getPassportAutoCaptureProgress(start, start + 5_000).isComplete, true);
  assert.equal(PASSPORT_AUTO_CAPTURE_STABLE_MS, 5_000);
});

test("reports smooth bounded progress through the stability window", () => {
  const halfway = getPassportAutoCaptureProgress(2_000, 4_500);

  assert.equal(halfway.progress, 0.5);
  assert.equal(halfway.elapsedMs, 2_500);
  assert.equal(halfway.remainingMs, 2_500);
  assert.equal(halfway.secondsRemaining, 3);
});

test("clamps early and late timestamps safely", () => {
  assert.deepEqual(getPassportAutoCaptureProgress(5_000, 4_000), {
    progress: 0,
    elapsedMs: 0,
    remainingMs: 5_000,
    secondsRemaining: 5,
    isComplete: false,
  });
  assert.deepEqual(getPassportAutoCaptureProgress(5_000, 20_000), {
    progress: 1,
    elapsedMs: 5_000,
    remainingMs: 0,
    secondsRemaining: 0,
    isComplete: true,
  });
});

test("returns a reusable reset state", () => {
  assert.deepEqual(getEmptyPassportAutoCaptureProgress(), {
    progress: 0,
    elapsedMs: 0,
    remainingMs: 5_000,
    secondsRemaining: 5,
    isComplete: false,
  });
});
