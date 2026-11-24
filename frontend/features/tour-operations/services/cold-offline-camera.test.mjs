import assert from "node:assert/strict";
import test from "node:test";
import { startup, settled, waitUntil, SECOND_SESSION } from "../test-support/cold-offline.test-fixture.mjs";

async function cameraFixture() {
  const context = await startup({ extraSession: true });
  await context.entered; context.release(); await settled(context);
  const calls = [];
  let releases = 0;
  Object.defineProperty(context.window, "isSecureContext", { value: true });
  Object.defineProperty(context.window.navigator, "mediaDevices", { value: { getUserMedia() {} } });
  context.window.ZXingBrowser = {
    BrowserCodeReader: { releaseAllStreams() { releases++; } },
    BrowserQRCodeReader: class {
      decodeFromConstraints(constraints, _preview, callback) {
        const pending = Promise.withResolvers();
        calls.push({ ...pending, constraints, callback });
        return pending.promise;
      }
    },
  };
  return { ...context, calls, releases: () => releases,
    start: context.window.document.getElementById("start-camera"),
    preview: context.window.document.getElementById("camera-preview") };
}

test("standalone camera startup is single-flight and preserves existing capture bounds", async () => {
  const context = await cameraFixture();
  try {
    context.start.click(); context.start.click();
    assert.equal(context.calls.length, 1);
    assert.equal(context.start.disabled, true);
    assert.equal(context.calls[0].constraints.audio, false);
    assert.equal(context.calls[0].constraints.video.width.max, 1280);
    assert.equal(context.calls[0].constraints.video.height.max, 720);
    assert.equal(context.calls[0].constraints.video.frameRate.max, 30);
    context.calls[0].resolve({ stop() {} });
    await waitUntil(() => context.window.document.getElementById("scan-feedback").textContent.startsWith("Camera ready"));
  } finally { context.window.dispatchEvent(new context.window.Event("pagehide")); context.close(); }
});

test("pagehide stops an active stream and releases late startup controls before retry", async () => {
  const context = await cameraFixture();
  try {
    context.start.click();
    let stoppedTracks = 0, stoppedControls = 0;
    context.preview.srcObject = { getTracks: () => [{ stop() { stoppedTracks++; } }] };
    context.window.dispatchEvent(new context.window.Event("pagehide"));
    assert.equal(stoppedTracks, 1);
    assert.equal(context.preview.srcObject, null);
    context.calls[0].resolve({ stop() { stoppedControls++; } });
    await waitUntil(() => !context.start.disabled);
    assert.equal(stoppedControls, 1);
    assert.ok(context.releases() >= 2);
    assert.doesNotMatch(context.window.document.getElementById("scan-feedback").textContent, /Camera ready/);
    context.start.click();
    assert.equal(context.calls.length, 2);
    context.calls[1].resolve({ stop() {} });
  } finally { context.window.dispatchEvent(new context.window.Event("pagehide")); context.close(); }
});

test("changing the selected activity stops active capture and keeps restart available", async () => {
  const context = await cameraFixture();
  try {
    let stops = 0;
    context.start.click(); context.calls[0].resolve({ stop() { stops++; } });
    await waitUntil(() => context.window.document.getElementById("scan-feedback").textContent.startsWith("Camera ready"));
    const select = context.window.document.getElementById("session-select");
    select.value = SECOND_SESSION; select.dispatchEvent(new context.window.Event("change"));
    assert.equal(stops, 1);
    assert.equal(context.start.disabled, false);
    assert.equal(context.window.document.getElementById("selected-activity").textContent, "Synthetic second activity");
    context.start.click(); assert.equal(context.calls.length, 2);
    context.calls[1].resolve({ stop() {} });
  } finally { context.window.dispatchEvent(new context.window.Event("pagehide")); context.close(); }
});
