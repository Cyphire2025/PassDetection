import { expect, test } from "@playwright/test";
import { workspace, headRotation, rotationDistance } from "./support/test-hologram-workspace";
import { testHologramSignal } from "./support/test-hologram-probe";
import { hologramDiagnostics } from "./support/test-hologram-diagnostics";

// Portable real-render checks. CDP input/readback benchmarks remain Chromium-only.
for (const appearance of ["female", "male"] as const) {
  test(`${appearance} scene loads, rotates, and fits both orientations`, async ({ page }, info) => {
    await workspace(page, appearance);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/ai");
    const portrait = page.getByTestId("particle-face-test"), canvas = portrait.locator("canvas");
    await expect(portrait).toHaveAttribute("data-renderer", "webgl");
    await expect(portrait).toHaveAttribute("data-appearance", appearance);
    const initial = await headRotation(page);
    await canvas.focus(); await page.keyboard.press("ArrowRight");
    await expect.poll(async () => rotationDistance(await headRotation(page), initial)).toBeGreaterThan(.1);
    await page.keyboard.press("Home");
    await expect.poll(async () => rotationDistance(await headRotation(page), initial)).toBeLessThan(.001);
    for (const size of [{ width: 390, height: 844 }, { width: 844, height: 390 }]) {
      await page.setViewportSize(size);
      await expect(page.getByRole("button", { name: "Start microphone", exact: true })).toBeInViewport();
      await expect(page.getByRole("textbox", { name: "Message Global Connects", exact: true })).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    const signal = await testHologramSignal(page), diagnostics = await hologramDiagnostics(page);
    expect(signal.points).toBeGreaterThan(17000); expect(signal.headNonPointDraws).toBe(0); expect(signal.errors).toEqual([]);
    expect(diagnostics.pageErrors).toEqual([]); expect(diagnostics.assetFailures).toEqual([]); expect(diagnostics.cspViolations).toEqual([]);
    // WebKit logs this unsupported Chromium viewport hint at error level.
    expect(diagnostics.consoleErrors?.filter((message) => message !== 'Viewport argument key "interactive-widget" not recognized and ignored.')).toEqual([]);
    await info.attach("application-diagnostics", { body: JSON.stringify(diagnostics), contentType: "application/json" });
    // WebKit's Playwright screenshot helper injects an unnonced `body {}` style
    // to synchronize animations. Validate the application's CSP before capture.
    await page.screenshot({ path: info.outputPath(`${appearance}-landscape.png`), caret: "initial" });
  });
}
