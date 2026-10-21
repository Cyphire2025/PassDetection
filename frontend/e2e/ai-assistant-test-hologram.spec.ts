import { expect, test, type Page } from "@playwright/test";
import { assistantAuth } from "./support/assistant-auth";
import { observeTestHologram, testHologramSignal } from "./support/test-hologram-probe";

test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status === testInfo.expectedStatus) return;
  const diagnostics = await page.evaluate(() => {
    const target = window as unknown as { __portraitProbes?: Array<{ draws: number; vertices: number; errors: string[] }> };
    return target.__portraitProbes?.map(({ draws, vertices, errors }) => ({ draws, vertices, errors }));
  }).catch(() => null);
  await testInfo.attach("webgl-diagnostics", { body: JSON.stringify(diagnostics), contentType: "application/json" });
});

async function workspace(page: Page, appearance: "female" | "male" = "female") {
  await assistantAuth(page);
  await observeTestHologram(page);
  await page.route("**/api/v1/ai-assistant/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/availability")) return route.fulfill({ json: { enabled: true, allowed: true } });
    if (path.endsWith("/status")) return route.fulfill({ json: {
      configured: true, speech_configured: true, native_voice: true, voice_configured: true,
      provider: "openai", voice_provider: "openai", model: "gpt-realtime-2.1", avatar_appearance: appearance,
      account_id: "test-portrait-admin", account_scope: "super_admin", can_manage_settings: true,
      settings_revision: 1, access: "read_only",
    } });
    if (path.endsWith("/live")) return route.fulfill({ json: {
      observed_at: "2026-10-21T00:00:00Z", mcp: { connected: true, available_tools: 8, write_enabled: false },
    } });
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
}

async function chooseAppearance(page: Page, name: "Test" | "Human hologram" | "Sculpture") {
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  const panel = page.getByRole("dialog", { name: "Sculpture appearance", exact: true });
  await panel.getByRole("button", { name, exact: true }).click();
  await expect(panel.getByRole("button", { name, exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Escape");
}

async function headRotation(page: Page) {
  const uniforms = (await testHologramSignal(page)).headUniforms;
  const matrix = uniforms.modelMatrix ?? uniforms.modelViewMatrix;
  expect(matrix).toHaveLength(16);
  return [0, 1, 2, 4, 5, 6, 8, 9, 10].map((index) => matrix[index]);
}

const rotationDistance = (a: number[], b: number[]) => Math.hypot(...a.map((value, index) => value - b[index]));

test("Test mode renders a real particle face with pointer, drag, keyboard, reset, and clean mode switching", async ({ page }, testInfo) => {
  await workspace(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.setViewportSize({ width: 1440, height: 960 });
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/ai");
  await expect(page.getByTestId("human-hologram")).toBeVisible();
  await chooseAppearance(page, "Test");
  const portrait = page.getByTestId("particle-face-test");
  await expect(portrait).toHaveAttribute("data-renderer", "webgl");
  await expect(portrait).toHaveAttribute("data-appearance", "female");
  const canvas = portrait.getByRole("img", { name: "Female interactive 3D particle face", exact: true });
  await expect(canvas).toHaveAttribute("tabindex", "0");
  await expect(canvas).toHaveAccessibleDescription(/Drag to rotate.*Move to illuminate/);
  await expect.poll(async () => (await testHologramSignal(page)).points).toBeGreaterThan(1000);
  const initial = await testHologramSignal(page);
  const initialRotation = await headRotation(page);
  expect(initial.errors).toEqual([]);
  expect(initial.points).toBeGreaterThan(1000);
  expect(initial.points).toBeLessThanOrEqual(147456);
  expect(initial.draws).toBeGreaterThan(0);
  expect(initial.pressurePasses).toBeGreaterThan(0);
  expect(initial.simulationPasses).toBeGreaterThan(0);
  expect(initial.texturedPoints).toBeGreaterThan(0);
  expect(await canvas.evaluate((element) => {
    const target = element as HTMLCanvasElement;
    return (target.getContext("webgl2") ?? target.getContext("webgl"))?.getError();
  })).toBe(0);
  await canvas.focus();
  await canvas.press("ArrowRight");
  await expect.poll(async () => rotationDistance(await headRotation(page), initialRotation)).toBeGreaterThan(.05);
  await expect(canvas).toBeFocused();
  expect(await canvas.evaluate((element) => {
    const style = getComputedStyle(element); return style.outlineStyle !== "none" || style.boxShadow !== "none";
  })).toBe(true);
  await canvas.press("Home");
  await expect.poll(async () => rotationDistance(await headRotation(page), initialRotation)).toBeLessThan(.06);
  const bounds = (await canvas.boundingBox())!;
  const center = { x: bounds.x + bounds.width * .5, y: bounds.y + bounds.height * .5 };
  await page.mouse.move(center.x, center.y);
  let hoverStep = 0;
  await expect.poll(async () => {
    // Pointer wakes intentionally decay; keep moving while measuring hover.
    await page.mouse.move(center.x + (++hoverStep % 2 ? 12 : -12), center.y, { steps: 3 });
    return (await testHologramSignal(page)).headUniforms.cursor[2];
  }, { intervals: [50] }).toBeGreaterThan(.2);
  await page.mouse.down();
  await expect.poll(async () => (await testHologramSignal(page)).uniforms.cursor[2]).toBeGreaterThan(.75);
  await page.screenshot({ path: testInfo.outputPath("test-particle-face-pointer-glow.png") });
  await page.mouse.move(center.x + bounds.width * .2, center.y + bounds.height * .1, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => (await testHologramSignal(page)).maximumImpulse).toBeGreaterThan(.001);
  await expect.poll(async () => rotationDistance(await headRotation(page), initialRotation)).toBeGreaterThan(.15);
  await page.screenshot({ path: testInfo.outputPath("test-particle-face-rotated-desktop.png") });
  await page.mouse.move(3, 3);
  await expect.poll(async () => (await testHologramSignal(page)).uniforms.cursor[2]).toBeLessThan(.02);
  await portrait.getByRole("button", { name: "Reset 3D view", exact: true }).click();
  await expect.poll(async () => rotationDistance(await headRotation(page), initialRotation)).toBeLessThan(.06);
  await page.screenshot({ path: testInfo.outputPath("test-particle-face-front-desktop.png") });
  const beforeUnmount = await testHologramSignal(page);
  await chooseAppearance(page, "Human hologram");
  await expect(portrait).not.toBeAttached();
  await expect.poll(async () => (await testHologramSignal(page, beforeUnmount.id)).buffers).toBe(0);
  await expect.poll(async () => {
    const state = await testHologramSignal(page, beforeUnmount.id);
    return state.programs + state.textures + state.framebuffers + state.renderbuffers;
  }).toBe(0);
  const stopped = await testHologramSignal(page, beforeUnmount.id);
  await page.waitForTimeout(350); // Check the disposed renderer across multiple normal frame intervals.
  expect((await testHologramSignal(page, beforeUnmount.id)).draws).toBe(stopped.draws);
  await expect(page.getByRole("textbox", { name: "Message Global Connects" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Start microphone", exact: true })).toBeEnabled();
  expect(errors).toEqual([]);
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
  // Stop the GSAP entrance while it is active: the static face must be fully
  // visible instead of freezing at its partially transparent entrance value.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.opacity?.[0]).toBe(1);
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
  await canvas.focus(); await canvas.press("ArrowLeft");
  await expect.poll(async () => rotationDistance(await headRotation(page), stillRotation)).toBeGreaterThan(.05);
  await canvas.press("Home");
  await page.screenshot({ path: testInfo.outputPath("test-particle-face-male-mobile.png") });
  await page.getByRole("button", { name: "Switch to light mode", exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("test-particle-face-light-mobile.png") });
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  await page.getByRole("checkbox", { name: "Animate with voice and pointer" }).uncheck();
  await page.keyboard.press("Escape");
  await expect(portrait).toHaveAttribute("data-motion", "false");
  await page.setViewportSize({ width: 844, height: 390 });
  await expect(page.getByRole("textbox", { name: "Message Global Connects" })).toBeInViewport();
  await expect(page.getByRole("button", { name: "Start microphone", exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await testHologramSignal(page)).errors).toEqual([]);
});

test("Test portrait context loss and recovery keep the workspace usable", async ({ page }) => {
  await workspace(page);
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
