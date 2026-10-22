import { writeFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import sharp from "sharp";
import { hologramDiagnostics } from "./support/test-hologram-diagnostics";
import { testHologramHeadFrames, testHologramSignal } from "./support/test-hologram-probe";
import { chooseAppearance, workspace, captureHologram, sampleHologramCadence } from "./support/test-hologram-workspace";
import { restingHeadProjection } from "./support/test-hologram-composition";
import { expectAssembledVolume, expectInteriorPopulation, expectParticlesInsideBoundary, observeParticleDisplacement, particleDisplacement as displacement } from "./support/test-hologram-displacement";
import { expectSmoothIdleRotation } from "./support/test-hologram-motion";
type FlowWindow = Window & {
  __flowPointerEvents: Array<{ at: number; receivedAt: number; x: number; y: number; trusted: boolean }> };
type Box = { left: number; right: number; top: number; bottom: number };
const WIDTH = 1440, HEIGHT = 960;

/** Read actual enclosure positions and the SDF, without changing the simulation. */
async function observeDisplacement(page: Page) {
  await page.addInitScript(() => {
    const pointerEvents: FlowWindow["__flowPointerEvents"] = [];
    Object.defineProperty(window, "__flowPointerEvents", { value: pointerEvents });
    window.addEventListener("pointermove", (event) => {
      pointerEvents.push({ at: performance.timeOrigin + event.timeStamp, receivedAt: performance.timeOrigin + performance.now(),
        x: event.clientX, y: event.clientY, trusted: event.isTrusted });
      if (pointerEvents.length > 80) pointerEvents.shift();
    }, { passive: true, capture: true });
  });
  await observeParticleDisplacement(page);
}

async function luminance(png: Buffer) {
  const { data, info } = await sharp(png).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  expect([info.width, info.height, info.channels]).toEqual([WIDTH, HEIGHT, 3]);
  const values = new Float32Array(WIDTH * HEIGHT);
  for (let pixel = 0; pixel < values.length; pixel++) values[pixel] = data[pixel * 3] * .2126 + data[pixel * 3 + 1] * .7152 + data[pixel * 3 + 2] * .0722;
  return values;
}

function plumeGrowth(idle: Float32Array, current: Float32Array, face: Box, headerBottom: number) {
  const width = face.right - face.left, height = face.bottom - face.top;
  const region = { left: Math.max(0, Math.floor(face.left - width * .25)), right: Math.min(WIDTH, Math.ceil(face.right)),
    top: Math.max(Math.ceil(headerBottom + 4), Math.floor(face.top - height * .40)), bottom: Math.floor(face.top - 10) };
  let brightPixels = 0, energy = 0, highest = face.top;
  for (let y = region.top; y < region.bottom; y++) for (let x = region.left; x < region.right; x++) {
    const index = y * WIDTH + x, gain = current[index] - idle[index];
    // The faint cylindrical lattice cannot satisfy this near-white, high-gain threshold.
    // The ten-pixel gap also excludes resting grains and their local bloom fringe.
    if (current[index] >= 235 && gain >= 24) { brightPixels++; energy += gain; highest = Math.min(highest, y); }
  }
  return { brightPixels, energy, extension: face.top - highest, region };
}

test("records actual GPU render cadence without forcing hardware quality", async ({ page }, testInfo) => {
  test.setTimeout(60000);
  await workspace(page);
  await page.setViewportSize({ width: WIDTH, height: HEIGHT });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "no-preference" });
  await page.goto("/ai"); await chooseAppearance(page, "Test");
  await expect(page.getByTestId("particle-face-test")).toHaveAttribute("data-renderer", "webgl");
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.opacity[0]).toBe(1);
  const result = await sampleHologramCadence(page);
  writeFileSync(testInfo.outputPath("actual-gpu-render-profile.json"), JSON.stringify(result, null, 2));
  await testInfo.attach("actual-gpu-render-profile", { contentType: "application/json", body: JSON.stringify(result) });
  expect(result.renderedFrames).toBeGreaterThan(0);
  expect(result.errors).toEqual([]); expect(result.webglError).toBe(0);
  // Cadence is diagnostic, not a claim that a software GPU represents a user's hardware.
});

test("an upward pointer stroke produces a bright displaced plume beyond the resting head and then recovers", async ({ page }, testInfo) => {
  test.setTimeout(120000);
  await workspace(page); await observeDisplacement(page);
  await page.setViewportSize({ width: WIDTH, height: HEIGHT });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "no-preference" });
  await page.goto("/ai"); await chooseAppearance(page, "Test");
  const portrait = page.getByTestId("particle-face-test");
  await expect(portrait).toHaveAttribute("data-renderer", "webgl");
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.opacity[0]).toBe(1);
  await page.mouse.move(2, HEIGHT - 2);
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.cursor[2]).toBeLessThan(.01);
  const idleState = await testHologramSignal(page);
  const initialPose = (await testHologramHeadFrames(page)).at(-1)!;
  const { box, project } = restingHeadProjection(idleState.headUniforms, WIDTH, HEIGHT);
  const headBounds = [box];
  const headerBottom = await page.locator("header").evaluate((element) => element.getBoundingClientRect().bottom);
  const microphoneTop = (await page.getByRole("button", { name: "Start microphone", exact: true }).boundingBox())!.y;
  expect(box.top).toBeGreaterThan(headerBottom + 8); expect(box.bottom).toBeLessThan(microphoneTop - 4);
  const idleDisplacement = await displacement(page);
  const capture = await page.context().newCDPSession(page);
  const captures: Array<{ name: string; requestedAt: number; completedAt: number }> = [];
  const screenshot = async (name: string) => {
    const { png, requestedAt, completedAt } = await captureHologram(page, testInfo.outputPath(name));
    headBounds.push(restingHeadProjection((await testHologramSignal(page)).headUniforms, WIDTH, HEIGHT).box);
    captures.push({ name, requestedAt, completedAt }); return png;
  };
  const idle = await screenshot("flow-01-idle.png");
  const start = project(-.25, .55, .5), projectedEnd = project(-.38, 1.28, .5);
  const bounds = (await portrait.boundingBox())!;
  // The larger approved face approaches the header. Keep the trusted mouse
  // stroke inside its actual input frame rather than sending its endpoint into UI.
  const end = { x: projectedEnd.x, y: Math.max(projectedEnd.y, bounds.y + 4, headerBottom + 4) };
  expect(end.y).toBeGreaterThan(bounds.y); expect(start.y).toBeLessThan(bounds.y + bounds.height);
  await page.mouse.move(start.x, start.y);
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.cursor[2]).toBeGreaterThan(.65);
  // Schedule trusted browser mouse events against Node's real wall clock. Awaiting
  // a page round trip per point stretches a 220ms stroke into seconds on a busy GPU.
  // No button drag, camera rotation, fake RAF, or simulation clock is involved.
  const strokeStarted = Date.now(), eventTiming: Array<{ step: number; sent: number; acknowledged: number }> = [];
  await Promise.all(Array.from({ length: 10 }, async (_, index) => {
    await new Promise<void>((resolve) => setTimeout(resolve, (index + 1) * 22));
    const progress = (index + 1) / 10, sent = Date.now() - strokeStarted;
    await capture.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: start.x + (end.x - start.x) * progress,
      y: start.y + (end.y - start.y) * progress, buttons: 0, pointerType: "mouse" });
    eventTiming.push({ step: index + 1, sent, acknowledged: Date.now() - strokeStarted });
  }));
  const strokeFinished = Date.now();
  const burstField = displacement(page);
  const burst = await screenshot("flow-02-plume.png");
  const burstFinished = Date.now();
  const burstDisplacement = await burstField;
  const early = await screenshot("flow-03-early-decay.png");
  await page.mouse.move(2, HEIGHT - 2);
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.cursor[2]).toBeLessThan(.02);
  await page.waitForTimeout(2200);
  const recovered = await screenshot("flow-04-recovered.png");
  const recoveredDisplacement = await displacement(page);
  await capture.detach();
  const neutralLuma = await luminance(idle);
  // Idle rotation is intentional. Exclude every observed resting silhouette so
  // a changed rigid pose cannot masquerade as a displaced plume.
  const envelope = headBounds.reduce((all, item) => ({ left: Math.min(all.left, item.left), right: Math.max(all.right, item.right),
    top: Math.min(all.top, item.top), bottom: Math.max(all.bottom, item.bottom) }));
  const burstGrowth = plumeGrowth(neutralLuma, await luminance(burst), envelope, headerBottom);
  const earlyGrowth = plumeGrowth(neutralLuma, await luminance(early), envelope, headerBottom);
  const recovery = plumeGrowth(neutralLuma, await luminance(recovered), envelope, headerBottom);
  const peak = burstGrowth.energy >= earlyGrowth.energy ? burstGrowth : earlyGrowth;
  const final = await testHologramSignal(page), runtime = await hologramDiagnostics(page);
  const browserEvents = await page.evaluate(() => (window as unknown as FlowWindow).__flowPointerEvents);
  await testInfo.attach("plume-pixels-and-gpu-displacement", { contentType: "application/json", body: JSON.stringify({
    face: box, restingSilhouettes: headBounds, envelope, stroke: { start, end, startedAt: strokeStarted, eventTiming, browserEvents },
    timing: { strokeAcknowledgedMs: strokeFinished - strokeStarted, burstCompletedAfterStrokeMs: burstFinished - strokeFinished, captures },
    idleDisplacement, burstDisplacement, recoveredDisplacement, burstGrowth, earlyGrowth, recovery,
    simulationPasses: final.simulationPasses - idleState.simulationPasses, runtime,
  }, null, 2) });
  // Compositor capture can exceed 300ms on software GPUs. The image/GPU checks
  // below establish a real plume; capture bounds and trusted event times explain
  // which portion of the transient could be observed without faking its clock.
  expect(browserEvents.filter((event) => event.receivedAt >= strokeStarted).every((event) => event.trusted)).toBe(true);
  expect(final.maximumImpulse).toBeGreaterThan(.01);
  expect(burstDisplacement.shape.maximum, "pointer force extracts actual material beyond the SDF boundary").toBeGreaterThan(idleDisplacement.shape.maximum + .025);
  expect(burstDisplacement.shape.extracted, "extraction exceeds the moving-volume baseline").toBeGreaterThan(idleDisplacement.shape.extracted + 100);
  expect(peak.brightPixels, "a luminous particle plume must leave the original head, not only light the cage").toBeGreaterThan(40);
  expect(peak.extension).toBeGreaterThan(18);
  expect(recovery.energy).toBeLessThan(peak.energy * .65 + 120);
  expect(recoveredDisplacement.shape.extracted, "shape occupancy recovers without requiring particles to return to their seeds")
    .toBeLessThan(idleDisplacement.shape.extracted + (burstDisplacement.shape.extracted - idleDisplacement.shape.extracted) * .65);
  expectAssembledVolume(recoveredDisplacement);
  for (const sample of [idleDisplacement, burstDisplacement, recoveredDisplacement]) {
    expectParticlesInsideBoundary(sample); expectInteriorPopulation(sample);
  }
  expect(final.headNonPointDraws, "pointer movement cannot reveal a fixed solid head core").toBe(0);
  expectSmoothIdleRotation((await testHologramHeadFrames(page)).filter((frame) => frame.at >= initialPose.at));
  expect(final.headUniforms.articulation).toEqual([0, 0, 0, 0]);
  expect(final.errors).toEqual([]); expect(runtime.cspViolations).toEqual([]);
  expect(runtime.consoleErrors).toEqual([]); expect(runtime.pageErrors).toEqual([]); expect(runtime.assetFailures).toEqual([]);
  await chooseAppearance(page, "Human hologram");
  await expect.poll(async () => {
    const state = await testHologramSignal(page, final.id);
    return state.buffers + state.programs + state.textures + state.framebuffers + state.renderbuffers;
  }).toBe(0);
});
