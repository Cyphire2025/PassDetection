import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  remapVideoCropToSource,
} from "./camera-capture.ts";

test("maps a video crop into the centred still-image sensor window", () => {
  const crop = remapVideoCropToSource(
    { left: 480, top: 270, width: 960, height: 540 },
    1920,
    1080,
    4000,
    3000,
  );

  assert.deepEqual(crop, {
    left: 1000,
    top: 937.5,
    width: 2000,
    height: 1125,
  });
});

test("keeps same-aspect video crops proportional", () => {
  const crop = remapVideoCropToSource(
    { left: 100, top: 50, width: 300, height: 200 },
    500,
    300,
    2000,
    1200,
  );

  assert.deepEqual(crop, {
    left: 400,
    top: 200,
    width: 1200,
    height: 800,
  });
});

test("capture helper feature-detects ImageCapture and preserves video fallback", () => {
  const source = readFileSync(
    new URL("./camera-capture.ts", import.meta.url),
    "utf8",
  );

  assert.match(source, /typeof ImageCapture !== "function"/);
  assert.match(source, /\? await imageCapture\.takePhoto\(settings\)/);
  assert.match(source, /blob = await imageCapture\.takePhoto\(\)/);
  assert.match(source, /return fallback/);
});
