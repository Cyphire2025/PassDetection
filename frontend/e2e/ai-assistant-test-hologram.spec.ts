import { expect, test, type Page } from "@playwright/test";
import { testHologramSignal } from "./support/test-hologram-probe";

import { workspace, chooseAppearance, headRotation, rotationDistance, captureHologram, pressHologramKeys } from "./support/test-hologram-workspace";
import { hologramDiagnostics } from "./support/test-hologram-diagnostics";
import { expectCompositionFits, hologramComposition } from "./support/test-hologram-composition";


const expectedParticleBudget = (page: Page) => page.getByTestId("particle-face-test").locator("canvas").evaluate((element) => {
  const canvas = element as HTMLCanvasElement, gl = canvas.getContext("webgl2")!;
  const debug = gl.getExtension("WEBGL_debug_renderer_info");
  const software = debug && /swiftshader|llvmpipe|software/i.test(String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)));
  return software ? 25600 : canvas.clientWidth < 640 || navigator.hardwareConcurrency <= 4 ? 30976 : 43264;
});

test.afterEach(async ({ page }, testInfo) => {
  const runtime = await hologramDiagnostics(page);
  await testInfo.attach("landscape-runtime-diagnostics", { body: JSON.stringify(runtime), contentType: "application/json" });
  const diagnostics = await page.evaluate(() => {
    const target = window as unknown as { __portraitProbes?: Array<{
      draws: number; frames: number; frameTime: number; firstFrameTime: number; vertices: number; headNonPointDraws: number; errors: string[];
    }> };
    return target.__portraitProbes?.map(({ draws, frames, frameTime, firstFrameTime, vertices, headNonPointDraws, errors }) =>
      ({ draws, frames, observedSeconds: (frameTime - firstFrameTime) / 1000, vertices, headNonPointDraws, errors }));
  }).catch(() => null);
  await testInfo.attach("webgl-diagnostics", { body: JSON.stringify(diagnostics), contentType: "application/json" });
  for (const context of diagnostics ?? []) expect(context.headNonPointDraws, "head renders only particles, with no solid core or authored wire").toBe(0);
  expect(runtime.cspViolations).toEqual([]);
  expect(runtime.pageErrors).toEqual([]);
  expect(runtime.assetFailures).toEqual([]);
  if (process.env.TEST_HOLOGRAM_PRODUCTION_CSP === "1") {
    expect(runtime.documentCsp).toContain("script-src");
    expect(runtime.documentCsp).not.toContain("'unsafe-eval'");
  }
  const expectedFallback = testInfo.title.includes("when WebGL is unavailable");
  expect(runtime.consoleErrors?.filter((message) => !(expectedFallback && /THREE.WebGLRenderer: Error creating WebGL context/.test(message)))).toEqual([]);
});

test("male Test portrait finishes its entrance when reduced motion is enabled and fits mobile controls", async ({ page }, testInfo) => {
  await workspace(page, "male");
  await page.emulateMedia({ reducedMotion: "no-preference", colorScheme: "dark" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/ai");
  await chooseAppearance(page, "Test");
  const portrait = page.getByTestId("particle-face-test");
  await expect(portrait).toHaveAttribute("data-renderer", "webgl");
  await expect(portrait).toHaveAttribute("data-appearance", "male");
  expect((await testHologramSignal(page)).points).toBe(await expectedParticleBudget(page));
  await expect(portrait.getByRole("button")).toHaveCount(0);
  // Stop the GSAP entrance while it is active: the static face must be fully
  // visible instead of freezing at its partially transparent entrance value.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.opacity?.[0]).toBe(1);
  const mobileComposition = await hologramComposition(page);
  expectCompositionFits(mobileComposition);
  await testInfo.attach("enlarged-mobile-projected-composition", { body: JSON.stringify(mobileComposition), contentType: "application/json" });
  const canvas = portrait.getByRole("img", { name: "Male interactive 3D particle face", exact: true });
  await page.mouse.move(2, 2);
  await page.waitForTimeout(350); // Let initial resize/intersection observers settle before counting idle work.
  const still = await testHologramSignal(page);
  const stillRotation = await headRotation(page);
  await page.waitForTimeout(350);
  // One rendered frame can contain fluid, depth, bloom and composite GPU passes.
  expect((await testHologramSignal(page)).frames - still.frames).toBeLessThanOrEqual(2);
  expect((await testHologramSignal(page)).headUniforms.articulation).toEqual([0, 0, 0, 0]);
  const sizing = await canvas.evaluate((element) => {
    const target = element as HTMLCanvasElement;
    return { ratio: target.width / target.clientWidth, overflow: document.documentElement.scrollWidth > innerWidth };
  });
  expect(sizing.ratio).toBeLessThanOrEqual(1.76);
  expect(sizing.overflow).toBe(false);
  await canvas.focus(); await pressHologramKeys(page, "ArrowLeft");
  await expect.poll(async () => rotationDistance(await headRotation(page), stillRotation)).toBeGreaterThan(.05);
  await pressHologramKeys(page, "Home");
  await captureHologram(page, testInfo.outputPath("test-particle-face-male-mobile.png"));
  await page.getByRole("button", { name: "Switch to light mode", exact: true }).click();
  await captureHologram(page, testInfo.outputPath("test-particle-face-light-mobile.png"));
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  await page.getByRole("checkbox", { name: "Animate with voice and pointer" }).uncheck();
  await page.keyboard.press("Escape");
  await expect(portrait).toHaveAttribute("data-motion", "false");
  await page.setViewportSize({ width: 844, height: 390 });
  await expect(page.getByRole("textbox", { name: "Message Global Connects" })).toBeInViewport();
  await expect(page.getByRole("button", { name: "Start microphone", exact: true })).toBeInViewport();
  await expect.poll(async () => (await hologramComposition(page)).ui.width).toBe(844);
  const landscapeComposition = await hologramComposition(page);
  expectCompositionFits(landscapeComposition);
  await testInfo.attach("enlarged-landscape-mobile-composition", { body: JSON.stringify(landscapeComposition), contentType: "application/json" });
  await captureHologram(page, testInfo.outputPath("test-particle-face-light-landscape-mobile.png"));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await testHologramSignal(page)).errors).toEqual([]);
});

test("Test portrait context loss and recovery keep the workspace usable", async ({ page }) => {
  await workspace(page);
  // Context restoration must perform real GPU work; a continuously animated
  // scene is unnecessary while exercising loss, fallback and reinitialization.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/ai");
  await chooseAppearance(page, "Test");
  const portrait = page.getByTestId("particle-face-test");
  await expect(portrait).toHaveAttribute("data-renderer", "webgl");
  await portrait.locator("canvas").evaluate((element) => {
    const canvas = element as HTMLCanvasElement & { __restoreTestContext?: () => void };
    const extension = (canvas.getContext("webgl2") ?? canvas.getContext("webgl"))?.getExtension("WEBGL_lose_context");
    if (!extension) throw new Error("The browser does not expose WebGL context loss testing");
    canvas.__restoreTestContext = () => extension.restoreContext();
    extension.loseContext();
  });
  await expect(portrait).toHaveAttribute("data-renderer", "fallback");
  await expect(portrait).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message Global Connects" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Start microphone", exact: true })).toBeEnabled();
  await portrait.locator("canvas").evaluate((element) => (element as HTMLCanvasElement & { __restoreTestContext?: () => void }).__restoreTestContext?.());
  await expect(portrait).toHaveAttribute("data-renderer", "webgl");
  expect((await testHologramSignal(page)).errors).toEqual([]);
});

test("Test mode has a usable fallback when WebGL is unavailable", async ({ page }) => {
  await workspace(page);
  await page.addInitScript(() => {
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...args: unknown[]) {
      if (/webgl/.test(type)) return null;
      return getContext.apply(this, [type, ...args] as Parameters<typeof getContext>);
    } as typeof getContext;
  });
  await page.goto("/ai");
  await chooseAppearance(page, "Test");
  const portrait = page.getByTestId("particle-face-test");
  await expect(portrait).toHaveAttribute("data-renderer", "fallback");
  await expect(portrait).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message Global Connects" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Start microphone", exact: true })).toBeEnabled();
});
