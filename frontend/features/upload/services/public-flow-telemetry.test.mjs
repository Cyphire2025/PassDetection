import assert from "node:assert/strict";
import test from "node:test";
import {
  advanceStableReason,
  createStableReasonState,
  enqueueTelemetry,
  isPublicFlowTelemetryPayload,
  parseTelemetryQueue,
  passportScannerRejectionReason,
  visaPhotoRejectionReason,
} from "./public-flow-telemetry.ts";

test("emits a rejection only after it remains stable for at least one second", () => {
  let state = createStableReasonState();

  let result = advanceStableReason(state, "no_face", 100);
  state = result.state;
  assert.equal(result.emittedReason, null);

  result = advanceStableReason(state, "no_face", 1_099);
  state = result.state;
  assert.equal(result.emittedReason, null);

  result = advanceStableReason(state, "no_face", 1_100);
  state = result.state;
  assert.equal(result.emittedReason, "no_face");

  result = advanceStableReason(state, "no_face", 2_500);
  assert.equal(result.emittedReason, null);
});

test("changing or clearing a candidate restarts the stability window", () => {
  let state = createStableReasonState();
  state = advanceStableReason(state, "too_dark", 0).state;
  state = advanceStableReason(state, "too_bright", 700).state;

  let result = advanceStableReason(state, "too_bright", 1_699);
  state = result.state;
  assert.equal(result.emittedReason, null);

  state = advanceStableReason(state, null, 1_700).state;
  state = advanceStableReason(state, "too_bright", 1_800).state;
  result = advanceStableReason(state, "too_bright", 2_800);
  assert.equal(result.emittedReason, "too_bright");
});

test("visa mapping follows visible guidance precedence", () => {
  const base = {
    cameraUnavailable: false,
    qualityModelUnavailable: false,
    faceStatus: "ready",
    backgroundStatus: "white",
    clarityStatus: "good",
  };

  assert.equal(visaPhotoRejectionReason({
    ...base,
    cameraUnavailable: true,
    faceStatus: "no_face",
  }), "camera_unavailable");
  assert.equal(visaPhotoRejectionReason({
    ...base,
    faceStatus: "multiple",
  }), "multiple_faces");
  assert.equal(visaPhotoRejectionReason({
    ...base,
    clarityStatus: "too_dark",
  }), "too_dark");
  assert.equal(visaPhotoRejectionReason({
    ...base,
    clarityStatus: "blurry",
    backgroundStatus: "not_plain",
  }), "blurry");
  assert.equal(visaPhotoRejectionReason({
    ...base,
    backgroundStatus: "not_white",
  }), "background_not_light_neutral");
});

test("passport mapping follows frame, glare, lighting, then blur precedence", () => {
  const base = {
    failureReason: null,
    frameStatus: "ready",
    passportDetected: true,
    glareStatus: "clear",
    lightingStatus: "good",
    blurStatus: "sharp",
  };

  assert.equal(passportScannerRejectionReason({
    ...base,
    passportDetected: false,
    frameStatus: "sideways",
  }), "sideways");
  assert.equal(passportScannerRejectionReason({
    ...base,
    glareStatus: "glare",
    lightingStatus: "too_dark",
  }), "glare");
  assert.equal(passportScannerRejectionReason({
    ...base,
    lightingStatus: "too_bright",
    blurStatus: "blurry",
  }), "too_bright");
  assert.equal(passportScannerRejectionReason({
    ...base,
    failureReason: "crop_validation_failed",
  }), "crop_validation_failed");
});

test("queue parser rejects arbitrary, mismatched, or identifying fields", () => {
  const valid = {
    event: "public_flow",
    reason: "connectivity_lost",
  };
  assert.equal(isPublicFlowTelemetryPayload(valid), true);
  assert.equal(isPublicFlowTelemetryPayload({
    ...valid,
    name: "Traveller Name",
  }), false);
  assert.equal(isPublicFlowTelemetryPayload({
    event: "public_flow",
    reason: "free_text_reason",
  }), false);
  assert.equal(isPublicFlowTelemetryPayload({
    event: "visa_photo_rejection",
    reason: "connectivity_lost",
  }), false);

  assert.deepEqual(parseTelemetryQueue(JSON.stringify([
    valid,
    { ...valid, phone: "9999999999" },
    { event: "public_flow", reason: "free_text_reason" },
  ])), [valid]);
});

test("offline queue is bounded to the newest fixed-enum events", () => {
  let queue = [];
  for (let index = 0; index < 40; index += 1) {
    queue = enqueueTelemetry(queue, {
      event: "public_flow",
      reason: index % 2 === 0
        ? "connectivity_lost"
        : "connectivity_restored",
    });
  }

  assert.equal(queue.length, 32);
  assert.equal(queue[0].reason, "connectivity_lost");
  assert.equal(queue.at(-1).reason, "connectivity_restored");
});
