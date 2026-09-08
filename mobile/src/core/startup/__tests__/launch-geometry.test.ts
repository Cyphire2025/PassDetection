import { fitLaunchLogo, launchDockGeometry, type LaunchRect } from '../launch-geometry';

// These are measured content bounds of the source asset. The fit contract is
// about visible artwork, independent of the white margins in its 16:9 frame.
const ink = { left: 553 / 3840, top: 605 / 2160, width: 2734 / 3840, height: 950 / 2160 };

test.each([
  [142, 48],
  [260, 80],
  [100, 100],
])('centers all visible logo artwork inside a %i by %i destination without distortion', (width, height) => {
  const frame = fitLaunchLogo(width, height);
  const visibleWidth = frame.width * ink.width;
  const visibleHeight = frame.height * ink.height;
  expect(frame.width / frame.height).toBeCloseTo(16 / 9, 12);
  expect(frame.left + frame.width * ink.left).toBeCloseTo((width - visibleWidth) / 2, 10);
  expect(frame.top + frame.height * ink.top).toBeCloseTo((height - visibleHeight) / 2, 10);
  expect(visibleWidth).toBeLessThanOrEqual(width + 1e-10);
  expect(visibleHeight).toBeLessThanOrEqual(height + 1e-10);
  expect(Math.min(Math.abs(visibleWidth - width), Math.abs(visibleHeight - height))).toBeLessThan(1e-10);
});

test.each([
  [{ x: 0, y: 0, width: 390, height: 844 }, { x: 124, y: 108, width: 142, height: 48 }],
  [{ x: 12, y: 34, width: 430, height: 896 }, { x: 156, y: 158, width: 142, height: 48 }],
  [{ x: 28, y: 24, width: 1024, height: 1366 }, { x: 469, y: 156, width: 142, height: 48 }],
])('lands visible artwork exactly on its measured destination for root %j', (root, target) => {
  const dock = launchDockGeometry(root, target);
  expect(dock).not.toBeNull();
  const originalFrameWidth = Math.min(root.width, 720);
  const finalWidth = originalFrameWidth * dock!.scale;
  const finalHeight = finalWidth * 9 / 16;
  const finalLeft = root.x + root.width / 2 + dock!.translateX - finalWidth / 2;
  const finalTop = root.y + root.height / 2 + dock!.translateY - finalHeight / 2;
  const finalInkWidth = finalWidth * ink.width;
  const finalInkHeight = finalHeight * ink.height;
  expect(finalLeft + finalWidth * ink.left).toBeCloseTo(target.x + (target.width - finalInkWidth) / 2, 10);
  expect(finalTop + finalHeight * ink.top).toBeCloseTo(target.y + (target.height - finalInkHeight) / 2, 10);
  expect(finalInkWidth).toBeLessThanOrEqual(target.width + 1e-10);
  expect(finalInkHeight).toBeLessThanOrEqual(target.height + 1e-10);
  expect(dock!.scale).toBeLessThan(1);
});

const root: LaunchRect = { x: 0, y: 0, width: 390, height: 844 };
test.each([
  null,
  { x: -10, y: 100, width: 142, height: 48 },
  { x: 300, y: 100, width: 142, height: 48 },
  { x: 100, y: -10, width: 142, height: 48 },
  { x: 100, y: 820, width: 142, height: 48 },
  { x: 100, y: 100, width: 0, height: 48 },
  { x: 100, y: 100, width: 142, height: -1 },
  { x: Number.NaN, y: 100, width: 142, height: 48 },
  { x: 100, y: 100, width: Number.POSITIVE_INFINITY, height: 48 },
])('rejects an unusable destination %j instead of animating outside the app', (target) => {
  expect(launchDockGeometry(root, target)).toBeNull();
});

test.each([
  { ...root, width: 0 },
  { ...root, height: -1 },
  { ...root, x: Number.NaN },
])('rejects a root that has no usable screen geometry %j', (invalidRoot) => {
  expect(launchDockGeometry(invalidRoot, { x: 100, y: 100, width: 142, height: 48 })).toBeNull();
});
