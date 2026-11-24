import assert from "node:assert/strict";
import test from "node:test";
import { drawPassportGuideFrame } from "./passport-camera-guide.ts";

const originalMediaElement = globalThis.HTMLMediaElement;
globalThis.HTMLMediaElement = { HAVE_CURRENT_DATA: 2 };
test.after(() => { globalThis.HTMLMediaElement = originalMediaElement; });

function fixture(readyState = 2) {
  const calls = [];
  const video = {
    readyState, videoWidth: 200, videoHeight: 100,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 100 }),
  };
  const canvas = { width: 0, height: 0, getContext: () => ({ drawImage: (...args) => calls.push(args) }) };
  return { video, canvas, calls };
}

test("samples the full source when no guide is mounted", () => {
  const { video, canvas, calls } = fixture();
  assert.equal(drawPassportGuideFrame(video, canvas, null, 320, 200), true);
  assert.deepEqual(calls[0], [video, 0, 0, 200, 100, 0, 0, 320, 200]);
});

test("preserves object-cover offsets and ten-percent guide context", () => {
  const { video, canvas, calls } = fixture();
  const guide = { getBoundingClientRect: () => ({ left: 10, top: 20, width: 80, height: 60 }) };
  assert.equal(drawPassportGuideFrame(video, canvas, guide, 320, 200), true);
  assert.deepEqual(calls[0], [video, 52, 14, 96, 72, 0, 0, 320, 200]);
});

test("keeps an oversized guide inside actual source bounds", () => {
  const { video, canvas, calls } = fixture();
  const guide = { getBoundingClientRect: () => ({ left: -100, top: -100, width: 400, height: 400 }) };
  assert.equal(drawPassportGuideFrame(video, canvas, guide, 320, 200), true);
  assert.deepEqual(calls[0], [video, 0, 0, 200, 100, 0, 0, 320, 200]);
});

test("does not sample an unavailable camera or invalid destination", () => {
  const { video, canvas, calls } = fixture(1);
  assert.equal(drawPassportGuideFrame(video, canvas, null, 320, 200), false);
  video.readyState = 2;
  assert.equal(drawPassportGuideFrame(video, canvas, null, 0, 200), false);
  assert.equal(calls.length, 0);
});

test("handles a missing canvas context without requesting a frame", () => {
  const { video, canvas, calls } = fixture();
  canvas.getContext = () => null;
  assert.equal(drawPassportGuideFrame(video, canvas, null, 320, 200), false);
  assert.equal(calls.length, 0);
});
