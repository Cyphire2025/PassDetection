import { expect, test } from "@playwright/test";
import { testHologramSignal } from "./support/test-hologram-probe";
import { workspace, chooseAppearance, headRotation, landscapeCamera, rotationDistance } from "./support/test-hologram-workspace";
import { hologramDiagnostics } from "./support/test-hologram-diagnostics";

test.afterEach(async ({ page }, testInfo) => {
  const runtime = await hologramDiagnostics(page);
  await testInfo.attach("landscape-runtime-diagnostics", { body: JSON.stringify(runtime), contentType: "application/json" });
  const diagnostics = await page.evaluate(() => {
    const target = window as unknown as { __portraitProbes?: Array<{
      draws: number; frames: number; frameTime: number; firstFrameTime: number; vertices: number; errors: string[];
    }> };
    return target.__portraitProbes?.map(({ draws, frames, frameTime, firstFrameTime, vertices, errors }) =>
      ({ draws, frames, observedSeconds: (frameTime - firstFrameTime) / 1000, vertices, errors }));
  }).catch(() => null);
  await testInfo.attach("webgl-diagnostics", { body: JSON.stringify(diagnostics), contentType: "application/json" });
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

test("Test mode renders a real particle face with pointer, drag, keyboard, reset, and clean mode switching", async ({ page }, testInfo) => {
  test.setTimeout(120000);
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
  expect(initial.landscapeDraws).toBeGreaterThan(0);
  expect((await hologramDiagnostics(page)).assets).toEqual(expect.arrayContaining([
    "/ai/test-landscape/mountain.bin", "/ai/test-landscape/ground.bin", "/ai/test-landscape/patch.bin",
    "/ai/test-landscape/grade-rgba16f.bin", "/ai/test-landscape/mountain-color.webp",
    "/ai/test-landscape/ground-color.webp", "/ai/test-landscape/wind.webp",
  ]));
  expect((await hologramDiagnostics(page)).assets?.filter((path) => /\.(ktx2|wasm|drc)$/.test(path))).toEqual([]);
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
  // The scene fills the viewport; only the portrait frame handles pointer input.
  const bounds = (await portrait.boundingBox())!;
  const center = { x: bounds.x + bounds.width * .5, y: bounds.y + bounds.height * .5 };
  await page.mouse.move(center.x, center.y);
  let hoverStep = 0;
  await expect.poll(async () => {
    // Hover must remain responsive while the pointer moves across the face.
    await page.mouse.move(center.x + (++hoverStep % 2 ? 12 : -12), center.y, { steps: 3 });
    return (await testHologramSignal(page)).headUniforms.cursor[2];
  }, { intervals: [50] }).toBeGreaterThan(.2);
  await portrait.getByRole("button", { name: "Rotate landscape", exact: true }).click();
  await expect(portrait).toHaveAttribute("data-control", "landscape");
  const beforeLandscapeHover = (await testHologramSignal(page)).frames;
  await page.mouse.move(center.x, center.y, { steps: 3 });
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.cursor[2]).toBeLessThan(.02);
  expect((await testHologramSignal(page)).frames).toBeGreaterThan(beforeLandscapeHover);
  expect((await testHologramSignal(page)).headUniforms.motion[0]).toBe(1);
  const camera = await landscapeCamera(page);
  const orientation = (matrix: number[]) => [0, 1, 2, 4, 5, 6, 8, 9, 10].map((index) => matrix[index]);
  const finalDistance = Math.sqrt(8) * Math.sin(Math.PI / 24);
  await canvas.press("ArrowRight");
  await expect.poll(async () => Math.abs(rotationDistance(orientation(await landscapeCamera(page)), orientation(camera)) - finalDistance)).toBeLessThan(.005);
  // A single keyboard step must submit intermediate real camera matrices, not
  // merely jump to the final view while CSS claims to animate it.
  expect((await testHologramSignal(page)).landscapeCameras.some((matrix) => {
    const distance = rotationDistance(orientation(matrix), orientation(camera));
    return distance > .005 && distance < finalDistance - .02;
  })).toBe(true);
  expect(rotationDistance(await headRotation(page), initialRotation)).toBeLessThan(.06);
  await canvas.press("Home");
  await expect.poll(async () => rotationDistance(await landscapeCamera(page), camera)).toBeLessThan(.03);
  await portrait.getByRole("button", { name: "Rotate face", exact: true }).click();
  await page.mouse.move(center.x, center.y, { steps: 3 });
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.cursor[2]).toBeGreaterThan(.2);
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

test("high-quality Test portrait renders 147456 particles with all SMAA passes and releases GPU resources", async ({ page }, testInfo) => {
  test.setTimeout(90000);
  await workspace(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => {
    // Exercise the high-quality branch on CI's real software GPU. Only the
    // capability classification changes; shader compilation and draws stay real.
    Object.defineProperty(navigator, "hardwareConcurrency", { get: () => 8 });
    const prototype = WebGL2RenderingContext.prototype;
    const getExtension = prototype.getExtension;
    prototype.getExtension = function (this: WebGL2RenderingContext, name: string) {
      return name === "WEBGL_debug_renderer_info" ? null : Reflect.apply(getExtension, this, [name]);
    } as typeof getExtension;
    const counts = { edges: 0, weights: 0, blend: 0 };
    Object.defineProperty(window, "__smaaPasses", { value: counts });
    type Pass = keyof typeof counts;
    const shaders = new WeakMap<WebGLShader, Pass>(), programs = new WeakMap<WebGLProgram, Set<Pass>>();
    const active = new WeakMap<WebGL2RenderingContext, WebGLProgram | null>();
    const shaderSource = prototype.shaderSource;
    prototype.shaderSource = function (shader, source) {
      if (source.includes("SMAAColorEdgeDetection")) shaders.set(shader, "edges");
      else if (source.includes("SMAABlendingWeightCalculation")) shaders.set(shader, "weights");
      else if (source.includes("SMAANeighborhoodBlending")) shaders.set(shader, "blend");
      return shaderSource.call(this, shader, source);
    };
    const attachShader = prototype.attachShader;
    prototype.attachShader = function (program, shader) {
      const pass = shaders.get(shader);
      if (pass) { const names = programs.get(program) ?? new Set<Pass>(); names.add(pass); programs.set(program, names); }
      return attachShader.call(this, program, shader);
    };
    const useProgram = prototype.useProgram;
    prototype.useProgram = function (program) { active.set(this, program); return useProgram.call(this, program); };
    const draw = (context: WebGL2RenderingContext) => {
      const program = active.get(context); if (program) programs.get(program)?.forEach((pass) => { counts[pass]++; });
    };
    const drawArrays = prototype.drawArrays, drawElements = prototype.drawElements;
    prototype.drawArrays = function (mode, first, count) { draw(this); return drawArrays.call(this, mode, first, count); };
    prototype.drawElements = function (mode, count, type, offset) { draw(this); return drawElements.call(this, mode, count, type, offset); };
  });
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/ai"); await chooseAppearance(page, "Test");
  const portrait = page.getByTestId("particle-face-test");
  await expect(portrait).toHaveAttribute("data-renderer", "webgl");
  await expect.poll(async () => (await testHologramSignal(page)).points).toBe(147456);
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.opacity[0], { timeout: 30000 }).toBe(1);
  const passes = await page.evaluate(() => (window as unknown as { __smaaPasses: Record<string, number> }).__smaaPasses);
  expect(passes.edges).toBeGreaterThan(0); expect(passes.weights).toBeGreaterThan(0); expect(passes.blend).toBeGreaterThan(0);
  expect(await portrait.locator("canvas").evaluate((element) => (element as HTMLCanvasElement).getContext("webgl2")?.getError())).toBe(0);
  const rendered = await testHologramSignal(page);
  expect(rendered.errors).toEqual([]); expect(rendered.texturedPoints).toBeGreaterThan(0);
  expect(rendered.landscapeDraws).toBeGreaterThan(0);
  await page.screenshot({ path: testInfo.outputPath("test-particle-face-high-quality-three.png") });
  const canvas = portrait.locator("canvas"), front = await headRotation(page);
  await canvas.focus();
  for (let step = 0; step < 10; step++) await canvas.press("ArrowRight");
  await expect.poll(async () => rotationDistance(await headRotation(page), front)).toBeGreaterThan(1.8);
  await canvas.evaluate((element) => (element as HTMLCanvasElement).blur());
  await page.screenshot({ path: testInfo.outputPath("test-particle-face-high-quality-rotated-three.png") });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await canvas.press("Home");
  await expect.poll(async () => rotationDistance(await headRotation(page), front)).toBeLessThan(.04);
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.motion[0]).toBe(0);
  await canvas.evaluate((element) => (element as HTMLCanvasElement).blur());
  await page.screenshot({ path: testInfo.outputPath("test-particle-face-high-quality-static-three.png") });
  const beforeWide = (await testHologramSignal(page)).draws;
  await page.setViewportSize({ width: 1920, height: 1080 });
  await expect.poll(async () => portrait.locator("canvas").evaluate((element) => element.getBoundingClientRect().width)).toBe(1920);
  await expect.poll(async () => (await testHologramSignal(page)).draws).toBeGreaterThan(beforeWide);
  await page.screenshot({ path: testInfo.outputPath("test-particle-face-original-wide-1920.png") });
  await chooseAppearance(page, "Human hologram"); await expect(portrait).not.toBeAttached();
  await expect.poll(async () => {
    const state = await testHologramSignal(page, rendered.id);
    return state.buffers + state.programs + state.textures + state.framebuffers + state.renderbuffers;
  }).toBe(0);
  expect(errors).toEqual([]);
});
