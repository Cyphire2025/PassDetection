import { writeFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

import { workspace, chooseAppearance, captureHologram } from "./support/test-hologram-workspace";
import { hologramComposition } from "./support/test-hologram-composition";
import { testHologramSignal } from "./support/test-hologram-probe";
import { hologramDiagnostics } from "./support/test-hologram-diagnostics";
import { observeRenderedHead, renderedHead } from "./support/test-hologram-coverage";
import { headRegionMasks, renderedDensity, renderedPitContrast } from "./support/test-hologram-density";



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
