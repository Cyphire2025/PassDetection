import { copyFileSync, writeFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import sharp from "sharp";
import { workspace, chooseAppearance, captureHologram, headRotation, rotationDistance } from "./support/test-hologram-workspace";
import { hologramComposition } from "./support/test-hologram-composition";
import { testHologramSignal } from "./support/test-hologram-probe";
import { hologramDiagnostics } from "./support/test-hologram-diagnostics";
import { observeRenderedHead, renderedHead } from "./support/test-hologram-coverage";
import { headRegionMasks, renderedDensity, renderedPitContrast } from "./support/test-hologram-density";
import { observeParticleDisplacement, particleDisplacement, expectAssembledVolume, expectParticlesInsideBoundary, type ParticleDisplacement } from "./support/test-hologram-displacement";
import { volumeTransport } from "./support/test-hologram-transport";

test.use({ video: "on" });

async function hardwareBudget(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "hardwareConcurrency", { get: () => 8 });
    const prototype = WebGL2RenderingContext.prototype, get = prototype.getExtension;
    prototype.getExtension = function (this: WebGL2RenderingContext, name: string) {
      const result = Reflect.apply(get, this, [name]);
      if (name === "WEBGL_debug_renderer_info") {
        if (result) Object.defineProperty(window, "__portraitActualGpu", { configurable: true, value: {
          unmaskedRenderer: this.getParameter(result.UNMASKED_RENDERER_WEBGL), unmaskedVendor: this.getParameter(result.UNMASKED_VENDOR_WEBGL),
        } });
        return null;
      }
      return result;
    } as typeof get;
  });
}

type FlowFrame = { field: ParticleDisplacement; image: string; pose: number[]; capture: { requestedAt: number; completedAt: number; sampleAt: number } };

test("idle volume transports persistent particle identities through a dense assembled head", async ({ page }, info) => {
  test.setTimeout(120000);
  await workspace(page); await observeParticleDisplacement(page); await hardwareBudget(page);
  await page.setViewportSize({ width: 1681, height: 936 }); await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.goto("/ai"); await chooseAppearance(page, "Test");
  await expect(page.getByTestId("particle-face-test")).toHaveAttribute("data-renderer", "webgl");
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.opacity[0], { timeout: 30000 }).toBe(1);
  const composition = await hologramComposition(page), portrait = composition.ui.portrait;
  // Hold only the target volume's pose through a real stationary drag far from
  // the head. Flow runs on the real clock; the measured wake must remain quiet.
  await page.mouse.move(portrait.left + 12, (portrait.top + portrait.bottom) / 2); await page.mouse.down();
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const frames: FlowFrame[] = [], started = Date.now(), timeOrigin = await page.evaluate(() => performance.timeOrigin);
  try {
    while (Date.now() - started < 65000) {
      const field = await particleDisplacement(page), image = info.outputPath(`volume-phase-${String(frames.length).padStart(2, "0")}.png`);
      const captured = await captureHologram(page, image);
      frames.push({ field, image, pose: await headRotation(page), capture: { requestedAt: captured.requestedAt, completedAt: captured.completedAt, sampleAt: timeOrigin + field.at } });
      if (frames.length >= 12 && field.time - frames[0].field.time > 10) break;
    }
  } finally { await page.mouse.up(); }
  const transport = volumeTransport(frames.map((frame) => frame.field)), evidence = { transport, frames };
  writeFileSync(info.outputPath("volume-transport.json"), JSON.stringify(evidence));
  await info.attach("actual-volume-identity-transport", { body: JSON.stringify(evidence), contentType: "application/json" });
  expect(frames.length).toBeGreaterThan(10); expect(transport.seconds).toBeGreaterThan(8);
  for (const frame of frames) {
    expect(frame.field.wakeMaximum, "idle flow is not a hidden pointer interaction").toBeLessThan(.01);
    expect(rotationDistance(frame.pose, frames[0].pose), "target volume pose stays fixed during transport measurement").toBeLessThan(.001);
    expectParticlesInsideBoundary(frame.field); expectAssembledVolume(frame.field);
  }
  expect(transport.all.count).toBeGreaterThan(1000);
  expect(transport.deep.count, "current negative SDF identifies genuine deep material").toBeGreaterThan(100);
  for (const [name, population] of Object.entries({ all: transport.all, deep: transport.deep })) {
    expect(population.medianNet, `${name} identities visibly change location rather than oscillate about seeds`).toBeGreaterThan(.15);
    expect(population.transported, `${name} material crosses several spatial cells`).toBeGreaterThan(population.count * .2);
    // Net/path efficiency necessarily falls as material circulates within a
    // bounded volume. Net travel and independent spatial-cell crossings above
    // establish transport without incorrectly requiring a straight trajectory.
  }
  expect(transport.front.count).toBeGreaterThan(100);
  expect(transport.front.visibleTransport, "front-facing material travels by a visibly resolvable distance").toBeGreaterThan(transport.front.count * .3);
  expect(transport.maximumDensityChange, "Eulerian head density remains assembled while identities move").toBeLessThan(.35);
  for (const [label, index] of [["initial", 0], ["flowing", Math.floor(frames.length / 2)], ["transported", frames.length - 1]] as const) {
    copyFileSync(frames[index].image, info.outputPath(`volume-${label}.png`));
  }
  // Actual compositor pixels must change within the face as well as GPU state.
  // This ROI stays inside the held target volume, excluding sky/cage/fog edges.
  const head = composition.head, region = { left: Math.round(head.left + (head.right - head.left) * .3),
    top: Math.round(head.top + (head.bottom - head.top) * .3), width: Math.round((head.right - head.left) * .4), height: Math.round((head.bottom - head.top) * .4) };
  const first = await sharp(frames[0].image).extract(region).removeAlpha().greyscale().raw().toBuffer();
  const last = await sharp(frames.at(-1)!.image).extract(region).removeAlpha().greyscale().raw().toBuffer();
  const imageChange = first.reduce((sum, value, index) => sum + Math.abs(value - last[index]), 0) / first.length;
  await info.attach("actual-held-volume-image-change", { body: JSON.stringify({ region, meanAbsoluteLuminanceChange: imageChange }), contentType: "application/json" });
  expect(imageChange, "persistent material transport must be visible in the real composed image").toBeGreaterThan(3);
});

test.afterEach(async ({ page }, info) => {
  const diagnostics = await hologramDiagnostics(page);
  await info.attach("idle-renderer-diagnostics", { body: JSON.stringify(diagnostics), contentType: "application/json" });
  expect(diagnostics.pageErrors).toEqual([]); expect(diagnostics.cspViolations).toEqual([]);
  expect(diagnostics.assetFailures).toEqual([]);
  const state = await testHologramSignal(page);
  expect(state.errors).toEqual([]); expect(state.headNonPointDraws).toBe(0);
});

for (const viewport of [{ width: 1681, height: 936 }, { width: 390, height: 844 }]) {
  test(`dense particle-only sculpture retains visible shell coverage at ${viewport.width}px`, async ({ page }, info) => {
    test.setTimeout(60000);
    await workspace(page); await observeRenderedHead(page); await page.setViewportSize(viewport);
    await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
    if (viewport.width > 1000) await hardwareBudget(page);
    await page.goto("/ai"); await chooseAppearance(page, "Test");
    await expect(page.getByTestId("particle-face-test")).toHaveAttribute("data-renderer", "webgl");
    await expect.poll(async () => (await testHologramSignal(page)).headUniforms.opacity[0], { timeout: 30000 }).toBe(1);
    const composition = await hologramComposition(page), state = await testHologramSignal(page), box = composition.head;
    const pending = renderedHead(page, { left: box.left - 20, right: box.right + 20, top: box.top - 20, bottom: box.bottom + 20 });
    // A real Home interaction requests a frame even when reduced motion has
    // correctly put the renderer to sleep. No fake animation clock is used.
    await page.getByTestId("particle-face-test").locator("canvas").focus(); await page.keyboard.press("Home");
    const coverage = await pending, shot = await captureHologram(page, info.outputPath("dense-shell.png"));
    const masks = headRegionMasks(coverage, state.headUniforms, viewport);
    const density = renderedDensity(coverage, masks), pits = await renderedPitContrast(shot.png, coverage, masks);
    const evidence = { viewport, points: state.points, composition, density, pits, headNonPointDraws: state.headNonPointDraws };
    writeFileSync(info.outputPath("dense-shell.json"), JSON.stringify(evidence, null, 2));
    await info.attach("actual-shell-density", { body: JSON.stringify(evidence), contentType: "application/json" });
    // Coverage is only a lower bound. Dark-pit contrast and the untouched image
    // are retained because a filled interior can still look visibly pitted.
    for (const region of Object.values(density)) {
      expect(region.pixels).toBeGreaterThan(100); expect(region.coverage).toBeGreaterThan(.975);
      expect(region.largestGapDiameterCss).toBeLessThan((box.right - box.left) * .025);
    }
    // The reviewed adult SDF appearance has stronger anatomical grain shading
    // than the previous rest-spring material. The user accepted these actual
    // desktop/phone images; keep each region within one luminance level of its
    // measured contrast, while preserving the independent coverage/gap checks.
    const acceptedContrast = viewport.width < 1000
      ? { forehead: 12.704, cheeks: 11.315, scalp: 12.418 }
      : { forehead: 15.448, cheeks: 13.942, scalp: 11.800 };
    for (const [name, region] of Object.entries(pits)) {
      const limit = acceptedContrast[name as keyof typeof acceptedContrast] + 1;
      expect(region.negativeContrastRms, `${name} does not regain large dark grain recesses`).toBeLessThan(limit);
    }
  });
}
