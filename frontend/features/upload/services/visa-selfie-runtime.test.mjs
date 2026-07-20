import assert from "node:assert/strict";
import test from "node:test";
import {
  INITIAL_VISA_READINESS,
  SerializedVisaInferenceQueue,
  VISA_CAMERA_SAFE_RETRY_MESSAGE,
  VisaDetectorInferenceError,
  isMediaPipeRuntimeFailure,
  updateVisaReadinessHysteresis,
  waitForVisaInferenceDrain,
} from "./visa-selfie-runtime.ts";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test("Visa inference queue never overlaps detector operations and drain waits", async () => {
  const first = deferred();
  const second = deferred();
  let active = 0;
  let maximumActive = 0;
  const starts = [];
  const queue = new SerializedVisaInferenceQueue();

  const run = (label, gate) => queue.run(async () => {
    starts.push(label);
    active += 1;
    maximumActive = Math.max(maximumActive, active);
    await gate.promise;
    active -= 1;
    return label;
  });

  const firstResult = run("live", first);
  const secondResult = run("final", second);
  await Promise.resolve();
  assert.deepEqual(starts, ["live"]);
  assert.equal(queue.busy, true);

  first.resolve();
  assert.equal(await firstResult, "live");
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(starts, ["live", "final"]);

  let drained = false;
  const drain = queue.drain().then(() => {
    drained = true;
  });
  await Promise.resolve();
  assert.equal(drained, false);

  second.resolve();
  assert.equal(await secondResult, "final");
  await drain;
  assert.equal(maximumActive, 1);
  assert.equal(queue.busy, false);
});

test("Visa inference queue continues safely after a rejected detector operation", async () => {
  const queue = new SerializedVisaInferenceQueue();
  await assert.rejects(
    queue.run(async () => {
      throw new Error("detector failed");
    }),
    /detector failed/,
  );
  assert.equal(await queue.run(async () => "recovered"), "recovered");
});

test("bounded drain releases camera lifecycle without unlocking a stalled queue", async () => {
  const stalled = deferred();
  const queue = new SerializedVisaInferenceQueue();
  void queue.run(() => stalled.promise);
  await Promise.resolve();

  assert.equal(await waitForVisaInferenceDrain(queue, 5), false);
  assert.equal(queue.busy, true);

  stalled.resolve();
  assert.equal(await waitForVisaInferenceDrain(queue, 50), true);
  assert.equal(queue.busy, false);
});

test("Visa readiness keeps two-of-three promotion and releases after sustained misses", () => {
  let state = { ...INITIAL_VISA_READINESS };
  state = updateVisaReadinessHysteresis(state, true);
  assert.equal(state.ready, false);
  state = updateVisaReadinessHysteresis(state, false);
  assert.equal(state.ready, false);
  state = updateVisaReadinessHysteresis(state, true);
  assert.equal(state.ready, true);

  for (let index = 0; index < 3; index += 1) {
    state = updateVisaReadinessHysteresis(state, false);
    assert.equal(state.ready, true);
  }
  state = updateVisaReadinessHysteresis(state, false);
  assert.equal(state.ready, false);
});

test("Visa readiness does not promote with fewer than two passes in three", () => {
  let state = { ...INITIAL_VISA_READINESS };
  state = updateVisaReadinessHysteresis(state, true);
  state = updateVisaReadinessHysteresis(state, false);
  state = updateVisaReadinessHysteresis(state, false);
  assert.equal(state.ready, false);
  state = updateVisaReadinessHysteresis(state, true);
  assert.equal(state.ready, false);
});

test("MediaPipe WASM errors are recognized and never exposed to clients", () => {
  const raw = new Error(
    "Out of bounds memory access (evaluating 'invoker(fn, thisWired, arg0Wired)')",
  );
  assert.equal(isMediaPipeRuntimeFailure(raw), true);
  const safe = new VisaDetectorInferenceError(raw);
  assert.equal(safe.runtimeFailure, true);
  assert.equal(safe.resetDetector, true);
  assert.equal(safe.message, VISA_CAMERA_SAFE_RETRY_MESSAGE);
  assert.doesNotMatch(safe.message, /invoker|out of bounds|wasm/i);
});
