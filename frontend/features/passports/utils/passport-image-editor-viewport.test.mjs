import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";

// Production imports use bundler resolution; resolve this one dependency for Node's TS runner.
const hooks = registerHooks({
  resolve(specifier, context, nextResolve) {
    return nextResolve(
      specifier === "./passport-image-crop-geometry"
        ? "./passport-image-crop-geometry.ts"
        : specifier,
      context,
    );
  },
});
const { fitImagePreview } = await import("./passport-image-editor-viewport.ts");
hooks.deregister();

const base = {
  imageWidth: 4000,
  imageHeight: 3000,
  viewportWidth: 800,
  viewportHeight: 500,
  rotationDegrees: 0,
};

test("landscape images fit both viewport bounds without stretching", () => {
  const result = fitImagePreview(base);
  assert.equal(result.height, 500);
  assert.equal(result.width, 4000 / 6);
  assert.equal(result.fitScale, 1 / 6);
  assert.equal(result.zoom, 1);
});

test("portrait images remain fully visible inside a landscape viewport", () => {
  const result = fitImagePreview({ ...base, imageWidth: 3000, imageHeight: 4000 });
  assert.equal(result.height, 500);
  assert.equal(result.width, 375);
});

test("quarter rotation swaps the fitted aspect ratio", () => {
  const result = fitImagePreview({ ...base, rotationDegrees: 90 });
  assert.equal(result.height, 500);
  assert.equal(result.width, 375);
  assert.deepEqual(result, fitImagePreview({ ...base, rotationDegrees: -270 }));
});

test("fine rotations fit the expanded bounding box at every whole angle", () => {
  for (let rotationDegrees = 0; rotationDegrees < 360; rotationDegrees += 1) {
    const result = fitImagePreview({ ...base, rotationDegrees });
    assert.ok(result.width <= base.viewportWidth + 1e-10);
    assert.ok(result.height <= base.viewportHeight + 1e-10);
    assert.ok(result.scale > 0 && result.scale <= 1);
  }
});

test("small source images stay at native size instead of being enlarged", () => {
  const result = fitImagePreview({ ...base, imageWidth: 200, imageHeight: 100, zoom: 3 });
  assert.deepEqual(result, {
    width: 200, height: 100, fitScale: 1, scale: 1, zoom: 1,
  });
});

test("unmeasured, hidden, and malformed viewports have safe empty dimensions", () => {
  for (const key of ["imageWidth", "imageHeight", "viewportWidth", "viewportHeight"]) {
    for (const value of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      assert.deepEqual(fitImagePreview({ ...base, [key]: value }), {
        width: 0, height: 0, fitScale: 0, scale: 0, zoom: 1,
      });
    }
  }
});

test("a tiny phone viewport does not impose a minimum image size or overflow", () => {
  const result = fitImagePreview({ ...base, viewportWidth: 24, viewportHeight: 17 });
  assert.ok(result.width <= 24);
  assert.equal(result.height, 17);
  assert.ok(result.width > 0);
});

test("zoom enlarges the preview only and clamps the relative zoom to 1 through 3", () => {
  const fit = fitImagePreview(base);
  assert.deepEqual(fitImagePreview({ ...base, zoom: 0.2 }), fit);
  assert.deepEqual(fitImagePreview({ ...base, zoom: Number.NaN }), fit);
  assert.deepEqual(fitImagePreview({ ...base, zoom: Number.POSITIVE_INFINITY }), fit);
  const doubled = fitImagePreview({ ...base, zoom: 2 });
  assert.equal(doubled.width, fit.width * 2);
  assert.equal(doubled.height, fit.height * 2);
  assert.equal(doubled.fitScale, fit.fitScale);
  assert.equal(doubled.zoom, 2);
  assert.deepEqual(fitImagePreview({ ...base, zoom: 100 }), fitImagePreview({ ...base, zoom: 3 }));
});

test("zoom stops at native image size and reports the effective zoom", () => {
  const result = fitImagePreview({
    ...base, imageWidth: 1000, imageHeight: 500, zoom: 3,
  });
  assert.equal(result.width, 1000);
  assert.equal(result.height, 500);
  assert.equal(result.scale, 1);
  assert.equal(result.fitScale, 0.8);
  assert.equal(result.zoom, 1.25);
});

test("resizing affects only fitted dimensions and does not mutate inputs", () => {
  const input = Object.freeze({ ...base });
  const fitted = fitImagePreview(input);
  const smaller = fitImagePreview({ ...input, viewportHeight: 250 });
  assert.equal(smaller.width, fitted.width / 2);
  assert.equal(smaller.height, fitted.height / 2);
  assert.deepEqual(input, base);
});
