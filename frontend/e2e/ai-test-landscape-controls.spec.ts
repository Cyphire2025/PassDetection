import { expect, test, type Page } from "@playwright/test";
import { hologramDiagnostics } from "./support/test-hologram-diagnostics";
import { testHologramSignal } from "./support/test-hologram-probe";
import { chooseAppearance, headRotation, landscapeCamera, rotationDistance, workspace } from "./support/test-hologram-workspace";

const orientation = (matrix: number[]) => [0, 1, 2, 4, 5, 6, 8, 9, 10].map((index) => matrix[index]);

test.afterEach(async ({ page }, testInfo) => {
  const runtime = await hologramDiagnostics(page);
  await testInfo.attach("landscape-control-diagnostics", { body: JSON.stringify(runtime), contentType: "application/json" });
  expect(runtime.cspViolations).toEqual([]);
  expect(runtime.consoleErrors).toEqual([]);
  expect(runtime.pageErrors).toEqual([]);
  expect(runtime.assetFailures).toEqual([]);
  if (process.env.TEST_HOLOGRAM_PRODUCTION_CSP === "1") {
    expect(runtime.documentCsp).toContain("script-src");
    expect(runtime.documentCsp).not.toContain("'unsafe-eval'");
  }
});

async function selectControl(page: Page, target: "face" | "landscape") {
  const portrait = page.getByTestId("particle-face-test");
  await portrait.getByRole("button", { name: `Rotate ${target}`, exact: true }).click();
  await expect(portrait).toHaveAttribute("data-control", target);
  await expect(portrait.getByRole("button", { name: `Rotate ${target}`, exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(portrait.getByRole("button", { name: `Rotate ${target === "face" ? "landscape" : "face"}`, exact: true })).toHaveAttribute("aria-pressed", "false");
}

async function dragMouse(page: Page, fraction: number) {
  const bounds = (await page.getByTestId("particle-face-test").boundingBox())!;
  const x = bounds.x + bounds.width * .4, y = bounds.y + bounds.height * .45;
  await page.mouse.move(x, y); await page.mouse.down();
  await page.mouse.move(x + bounds.width * fraction, y, { steps: 8 });
  await page.mouse.up(); await page.mouse.move(2, 2);
}

async function releaseScene(page: Page) {
  const before = await testHologramSignal(page);
  expect(before.errors).toEqual([]);
  expect(await page.getByTestId("particle-face-test").locator("canvas").evaluate((element) =>
    (element as HTMLCanvasElement).getContext("webgl2")?.getError())).toBe(0);
  await chooseAppearance(page, "Human hologram");
  await expect(page.getByTestId("particle-face-test")).not.toBeAttached();
  await expect.poll(async () => {
    const state = await testHologramSignal(page, before.id);
    return state.buffers + state.programs + state.textures + state.framebuffers + state.renderbuffers;
  }).toBe(0);
  const stopped = await testHologramSignal(page, before.id);
  await page.waitForTimeout(350);
  expect((await testHologramSignal(page, before.id)).draws).toBe(stopped.draws);
}

test("Face and Landscape controls rotate independently through a complete textured 360 degree view", async ({ page }, testInfo) => {
  test.setTimeout(150000);
  await workspace(page);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.goto("/ai"); await chooseAppearance(page, "Test");
  const portrait = page.getByTestId("particle-face-test"), canvas = portrait.locator("canvas");
  await expect(portrait).toHaveAttribute("data-renderer", "webgl");
  await expect(portrait).toHaveAttribute("data-control", "face");
  await expect(portrait.getByRole("button", { name: "Rotate face", exact: true })).toHaveAttribute("aria-pressed", "true");
  const face = await headRotation(page), camera = await landscapeCamera(page);

  await dragMouse(page, .16);
  await expect.poll(async () => rotationDistance(await headRotation(page), face)).toBeGreaterThan(.5);
  expect(rotationDistance(await landscapeCamera(page), camera)).toBeLessThan(.001);
  const turnedFace = await headRotation(page);
  await selectControl(page, "landscape"); await dragMouse(page, .14);
  await expect.poll(async () => rotationDistance(orientation(await landscapeCamera(page)), orientation(camera))).toBeGreaterThan(.4);
  expect(rotationDistance(await headRotation(page), turnedFace)).toBeLessThan(.001);
  expect((await testHologramSignal(page)).headUniforms.cursor[2]).toBe(0);
  const turnedCamera = await landscapeCamera(page);

  // Resetting the selected face must preserve the user's landscape viewpoint.
  await selectControl(page, "face");
  await portrait.getByRole("button", { name: "Reset 3D view", exact: true }).click();
  await expect.poll(async () => rotationDistance(await headRotation(page), face)).toBeLessThan(.001);
  expect(rotationDistance(await landscapeCamera(page), turnedCamera)).toBeLessThan(.001);
  await canvas.press("ArrowRight");
  await expect.poll(async () => rotationDistance(await headRotation(page), face)).toBeGreaterThan(.1);
  const preservedFace = await headRotation(page);
  await selectControl(page, "landscape"); await canvas.press("Home");
  await expect.poll(async () => rotationDistance(await landscapeCamera(page), camera)).toBeLessThan(.001);
  expect(rotationDistance(await headRotation(page), preservedFace)).toBeLessThan(.001);

  const views = [{ degrees: 0, matrix: await landscapeCamera(page), draws: (await testHologramSignal(page)).landscapeDraws }];
  await canvas.evaluate((element) => (element as HTMLCanvasElement).blur());
  await page.screenshot({ path: testInfo.outputPath("test-landscape-000-degrees.png") });
  for (const degrees of [90, 180, 270, 360]) {
    const before = await testHologramSignal(page);
    for (let step = 0; step < 6; step++) await canvas.press("ArrowRight");
    const expectedDistance = degrees === 180 ? Math.sqrt(8) : degrees === 360 ? 0 : 2;
    await expect.poll(async () => Math.abs(rotationDistance(orientation(await landscapeCamera(page)), orientation(camera)) - expectedDistance)).toBeLessThan(.005);
    await expect.poll(async () => (await testHologramSignal(page)).landscapeDraws).toBeGreaterThan(before.landscapeDraws);
    await expect.poll(async () => (await testHologramSignal(page)).mountainDraws).toBeGreaterThan(before.mountainDraws);
    const state = await testHologramSignal(page), matrix = await landscapeCamera(page);
    expect(rotationDistance(await headRotation(page), preservedFace)).toBeLessThan(.001);
    expect(state.errors).toEqual([]);
    views.push({ degrees, matrix, draws: state.landscapeDraws });
    await canvas.evaluate((element) => (element as HTMLCanvasElement).blur());
    await page.screenshot({ path: testInfo.outputPath(`test-landscape-${String(degrees).padStart(3, "0")}-degrees.png`) });
  }
  expect(rotationDistance(orientation(views[1].matrix), orientation(views[3].matrix))).toBeGreaterThan(2.8);
  expect(rotationDistance(views[4].matrix, camera)).toBeLessThan(.005);
  await testInfo.attach("actual-terrain-camera-full-turn", { body: JSON.stringify(views), contentType: "application/json" });
  await releaseScene(page);
});

test.describe("touch and reduced-motion controls", () => {
  test.use({ hasTouch: true, isMobile: true, viewport: { width: 390, height: 844 } });

  test("touch rotates the selected target while keyboard pitch limits and reset remain independent", async ({ page }, testInfo) => {
    test.setTimeout(90000);
    await workspace(page, "male");
    await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
    await page.goto("/ai"); await chooseAppearance(page, "Test");
    const portrait = page.getByTestId("particle-face-test"), canvas = portrait.locator("canvas");
    await expect(portrait).toHaveAttribute("data-renderer", "webgl");
    await expect(portrait.getByRole("button", { name: "Rotate face", exact: true })).toBeInViewport();
    await expect(portrait.getByRole("button", { name: "Rotate landscape", exact: true })).toBeInViewport();
    const face = await headRotation(page), camera = await landscapeCamera(page);
    const cdp = await page.context().newCDPSession(page);
    const swipe = async () => {
      const bounds = (await portrait.boundingBox())!;
      const x = bounds.x + bounds.width * .35, y = bounds.y + bounds.height * .45;
      const touch = (position: number) => [{ x: position, y, id: 1, radiusX: 8, radiusY: 8, force: 1 }];
      // Browser-generated touch/pointer events exercise capture and touch-action.
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: touch(x) });
      for (let step = 1; step <= 8; step++) await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: touch(x + bounds.width * .22 * step / 8) });
      await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    };
    await swipe();
    await expect.poll(async () => rotationDistance(await headRotation(page), face)).toBeGreaterThan(.5);
    expect(rotationDistance(await landscapeCamera(page), camera)).toBeLessThan(.001);
    const turnedFace = await headRotation(page);
    await portrait.getByRole("button", { name: "Rotate landscape", exact: true }).tap();
    await expect(portrait).toHaveAttribute("data-control", "landscape");
    await swipe();
    await expect.poll(async () => rotationDistance(orientation(await landscapeCamera(page)), orientation(camera))).toBeGreaterThan(.5);
    expect(rotationDistance(await headRotation(page), turnedFace)).toBeLessThan(.001);
    await canvas.press("Home");
    await expect.poll(async () => rotationDistance(await landscapeCamera(page), camera)).toBeLessThan(.001);
    for (let step = 0; step < 20; step++) await canvas.press("ArrowUp");
    const upper = await landscapeCamera(page);
    expect(rotationDistance(orientation(upper), orientation(camera))).toBeGreaterThan(.2);
    for (let step = 0; step < 6; step++) await canvas.press("ArrowUp");
    expect(rotationDistance(await landscapeCamera(page), upper)).toBeLessThan(.001);
    await canvas.press("ArrowDown");
    await expect.poll(async () => rotationDistance(orientation(await landscapeCamera(page)), orientation(upper))).toBeGreaterThan(.03);
    expect(rotationDistance(await headRotation(page), turnedFace)).toBeLessThan(.001);
    await portrait.getByRole("button", { name: "Reset 3D view", exact: true }).tap();
    await expect.poll(async () => rotationDistance(await landscapeCamera(page), camera)).toBeLessThan(.001);
    expect(rotationDistance(await headRotation(page), turnedFace)).toBeLessThan(.001);
    await cdp.detach();
    await page.screenshot({ path: testInfo.outputPath("test-landscape-touch-mobile.png") });
    await page.waitForTimeout(350);
    const still = await testHologramSignal(page);
    await page.waitForTimeout(350);
    expect((await testHologramSignal(page)).frames - still.frames).toBeLessThanOrEqual(2);
    expect((await testHologramSignal(page)).headUniforms.articulation).toEqual([0, 0, 0, 0]);
    expect(await page.evaluate(() => ({ scroll: scrollY, overflow: document.documentElement.scrollWidth > innerWidth }))).toEqual({ scroll: 0, overflow: false });
    await expect(page.getByRole("textbox", { name: "Message Global Connects" })).toBeInViewport();
    await releaseScene(page);
  });
});
