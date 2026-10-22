import { expect, type Page } from "@playwright/test";
import { type HologramHeadFrame, testHologramHeadFrames, testHologramLastHomeAt } from "./test-hologram-probe";
import { localHeadRotation, rotationDistance } from "./test-hologram-workspace";

export const headFrameRotation = (frame: HologramHeadFrame) => localHeadRotation(frame.modelView, frame.cameraView);
export const headAngle = (a: HologramHeadFrame, b: HologramHeadFrame) =>
  2 * Math.asin(Math.min(1, rotationDistance(headFrameRotation(a), headFrameRotation(b)) / Math.sqrt(8)));

/** The transform describes the target volume, not a rigid particle cloud.
 * Real elapsed frames prevent a paused transform passing by pausing rendering. */
export async function headMotionWindow(page: Page, milliseconds = 1400) {
  const start = (await testHologramHeadFrames(page)).at(-1)!;
  expect(start).toBeDefined();
  await expect.poll(async () => (await testHologramHeadFrames(page)).at(-1)!.at - start.at,
    { intervals: [100] }).toBeGreaterThanOrEqual(milliseconds);
  const frames = (await testHologramHeadFrames(page)).filter((frame) => frame.at >= start.at);
  expect(frames.length).toBeGreaterThan(2);
  return frames;
}

export function expectSmoothIdleRotation(frames: HologramHeadFrame[]) {
  const first = frames[0], last = frames.at(-1)!;
  expect(headAngle(first, last), "idle target-volume rotation must advance").toBeGreaterThan(.03);
  expectNoRotationJump(frames);
}

export function expectNoRotationJump(frames: HologramHeadFrame[]) {
  expect(frames.length).toBeGreaterThan(1);
  for (let index = 1; index < frames.length; index++) {
    const elapsed = (frames[index].at - frames[index - 1].at) / 1000;
    // The actual idle speed is .22rad/s. Allow small matrix precision error,
    // never an instantaneous jump when the speech hold releases.
    expect(headAngle(frames[index - 1], frames[index])).toBeLessThanOrEqual(elapsed * .23 + .003);
  }
}

export function expectFrozenHead(frames: HologramHeadFrame[]) {
  for (const frame of frames.slice(1)) expect(headAngle(frames[0], frame)).toBeLessThan(.0001);
}

/** Check the actual reset transition, including poses between slow round trips. */
export async function expectRenderedHome(page: Page, home: number[]) {
  const keyAt = await testHologramLastHomeAt(page);
  expect(keyAt, "a real Home key event reached the canvas").toBeGreaterThan(0);
  await expect.poll(async () => {
    const frames = (await testHologramHeadFrames(page)).filter((frame) => frame.at > keyAt);
    return Math.min(...frames.map((frame) => rotationDistance(headFrameRotation(frame), home)));
  }).toBeLessThan(.04);
  return { keyAt, frames: (await testHologramHeadFrames(page)).filter((frame) => frame.at > keyAt) };
}
