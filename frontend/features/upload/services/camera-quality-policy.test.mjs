import assert from "node:assert/strict";
import test from "node:test";
import {
  CAMERA_QUALITY_POLICY,
  isCameraMotionStable,
  updateRollingCameraReadiness,
} from "./camera-quality-policy.ts";

test("camera policy uses a 250 ms latest-three, two-pass live decision", () => {
  assert.equal(CAMERA_QUALITY_POLICY.liveAnalysisIntervalMs, 250);
  assert.equal(CAMERA_QUALITY_POLICY.liveDecisionWindow, 3);
  assert.equal(CAMERA_QUALITY_POLICY.livePassingSamples, 2);

  let state = { samples: [], ready: false };
  state = updateRollingCameraReadiness(state.samples, true, state.ready);
  assert.equal(state.ready, false);
  state = updateRollingCameraReadiness(state.samples, false, state.ready);
  assert.equal(state.ready, false);
  state = updateRollingCameraReadiness(state.samples, true, state.ready);
  assert.deepEqual(state.samples, [true, false, true]);
  assert.equal(state.ready, true);
});

test("readiness tolerates one miss but releases after two consecutive misses", () => {
  let state = { samples: [true, true, true], ready: true };
  state = updateRollingCameraReadiness(state.samples, false, state.ready);
  assert.equal(state.ready, true);
  state = updateRollingCameraReadiness(state.samples, false, state.ready);
  assert.equal(state.ready, false);
  state = updateRollingCameraReadiness(state.samples, true, state.ready);
  assert.equal(state.ready, false);
  state = updateRollingCameraReadiness(state.samples, true, state.ready);
  assert.equal(state.ready, true);
});

test("compact frame signatures reject motion but tolerate camera noise", () => {
  const stable = [90, 120, 160, 180];
  assert.equal(isCameraMotionStable(null, stable), false);
  assert.equal(isCameraMotionStable(stable, [94, 116, 166, 175]), true);
  assert.equal(isCameraMotionStable(stable, [40, 190, 70, 240]), false);
});

test("Vietnam output policy is exact 2:3 with an exclusive two MiB limit", () => {
  assert.equal(
    CAMERA_QUALITY_POLICY.visaOutputHeight
      / CAMERA_QUALITY_POLICY.visaOutputWidth,
    1.5,
  );
  assert.equal(CAMERA_QUALITY_POLICY.visaOutputWidth, 800);
  assert.equal(CAMERA_QUALITY_POLICY.visaOutputHeight, 1200);
  assert.equal(CAMERA_QUALITY_POLICY.maxVisaOutputBytes, 2 * 1024 * 1024);
});
