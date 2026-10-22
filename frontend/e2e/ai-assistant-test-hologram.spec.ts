import { expect, test, type Page } from "@playwright/test";
import { testHologramHeadFrames, testHologramSignal } from "./support/test-hologram-probe";
import { expectNoRotationJump, expectRenderedHome } from "./support/test-hologram-motion";
import { workspace, chooseAppearance, headRotation, landscapeCamera, rotationDistance, captureHologram, pressHologramKeys, sampleHologramCadence } from "./support/test-hologram-workspace";
import { hologramDiagnostics } from "./support/test-hologram-diagnostics";
import { boundsHeight, boundsWidth, expectCompositionFits, hologramComposition } from "./support/test-hologram-composition";
import { expectInteriorPopulation, observeParticleDisplacement, particleDisplacement } from "./support/test-hologram-displacement";

const expectedParticleBudget = (page: Page) => page.getByTestId("particle-face-test").locator("canvas").evaluate((element) => {
  const canvas = element as HTMLCanvasElement, gl = canvas.getContext("webgl2")!;
  const debug = gl.getExtension("WEBGL_debug_renderer_info");
  const software = debug && /swiftshader|llvmpipe|software/i.test(String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)));
  return software ? 30976 : canvas.clientWidth < 640 || navigator.hardwareConcurrency <= 4 ? 43264 : 78400;
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

test("Test is the default scene with pointer, drag, keyboard, reset, and clean mode switching", async ({ page }, testInfo) => {
  test.setTimeout(120000);
  await workspace(page);
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 960 });
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/ai");
  await expect(page.getByRole("main", { name: "Global Connects AI workspace" })).toHaveAttribute("data-appearance", "test");
  await expect(page.getByTestId("particle-face-test")).toHaveAttribute("data-renderer", "webgl");
  await expect(page.getByTestId("human-hologram")).toHaveCount(0);
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.opacity[0]).toBe(1);
  await captureHologram(page, testInfo.outputPath("test-particle-face-default-before-interaction.png"));
  await chooseAppearance(page, "Test");
  const portrait = page.getByTestId("particle-face-test");
  await expect(portrait).toHaveAttribute("data-renderer", "webgl");
  await expect(portrait).toHaveAttribute("data-appearance", "female");
  const canvas = portrait.getByRole("img", { name: "Female interactive 3D particle face", exact: true });
  await expect(canvas).toHaveAttribute("tabindex", "0");
  await expect(canvas).toHaveAccessibleDescription(/Move to stir the snow.*Drag to rotate the face.*Shift-drag.*Home or double-click/);
  await expect(portrait.getByRole("button")).toHaveCount(0);
  await expect.poll(async () => (await testHologramSignal(page)).points).toBeGreaterThan(1000);
  const initialRotation = await headRotation(page);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect.poll(async () => (await testHologramSignal(page)).simulationPasses).toBeGreaterThan(0);
  const initial = await testHologramSignal(page);
  expect(initial.errors).toEqual([]);
  expect(initial.points).toBeGreaterThan(1000);
  expect(initial.points).toBe(await expectedParticleBudget(page));
  expect(initial.draws).toBeGreaterThan(0);
  expect(initial.pressurePasses).toBeGreaterThan(0);
  expect(initial.simulationPasses).toBeGreaterThan(0);
  expect(initial.texturedPoints).toBeGreaterThan(0);
  expect(initial.landscapeDraws).toBeGreaterThan(0);
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.opacity[0]).toBe(1);
  const composition = await hologramComposition(page);
  expectCompositionFits(composition);
  await testInfo.attach("enlarged-desktop-projected-composition", { body: JSON.stringify(composition), contentType: "application/json" });
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
  await pressHologramKeys(page, "ArrowRight");
  await expect.poll(async () => rotationDistance(await headRotation(page), initialRotation)).toBeGreaterThan(.05);
  await expect(canvas).toBeFocused();
  expect(await canvas.evaluate((element) => {
    const style = getComputedStyle(element); return style.outlineStyle !== "none" || style.boxShadow !== "none";
  })).toBe(true);
  await pressHologramKeys(page, "Home");
  const initialReset = await expectRenderedHome(page, initialRotation);
  await testInfo.attach("initial-home-reset-poses", { body: JSON.stringify(initialReset), contentType: "application/json" });
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
  await page.keyboard.down("Shift");
  const beforeLandscapeHover = (await testHologramSignal(page)).frames;
  await page.mouse.move(center.x, center.y, { steps: 3 });
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.cursor[2]).toBeLessThan(.02);
  expect((await testHologramSignal(page)).frames).toBeGreaterThan(beforeLandscapeHover);
  expect((await testHologramSignal(page)).headUniforms.motion[0]).toBe(1);
  const camera = await landscapeCamera(page);
  const orientation = (matrix: number[]) => [0, 1, 2, 4, 5, 6, 8, 9, 10].map((index) => matrix[index]);
  const finalDistance = Math.sqrt(8) * Math.sin(Math.PI / 24);
  const beforeLandscapeTurn = (await testHologramHeadFrames(page)).at(-1)!;
  await pressHologramKeys(page, "Shift+ArrowRight");
  // The small atmospheric drift remains live while the explicit 15-degree turn eases.
  await expect.poll(async () => Math.abs(rotationDistance(orientation(await landscapeCamera(page)), orientation(camera)) - finalDistance)).toBeLessThan(.012);
  // A single keyboard step must submit intermediate real camera matrices, not
  // merely jump to the final view while CSS claims to animate it.
  expect((await testHologramSignal(page)).landscapeCameras.some((matrix) => {
    const distance = rotationDistance(orientation(matrix), orientation(camera));
    return distance > .005 && distance < finalDistance - .02;
  })).toBe(true);
  expectNoRotationJump((await testHologramHeadFrames(page)).filter((frame) => frame.at >= beforeLandscapeTurn.at));
  await pressHologramKeys(page, "Home");
  await expect.poll(async () => rotationDistance(orientation(await landscapeCamera(page)), orientation(camera))).toBeLessThan(.012);
  await page.keyboard.up("Shift");
  await page.mouse.move(center.x, center.y, { steps: 3 });
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.cursor[2]).toBeGreaterThan(.2);
  await page.mouse.down();
  await expect.poll(async () => (await testHologramSignal(page)).uniforms.cursor[2]).toBeGreaterThan(.75);
  await captureHologram(page, testInfo.outputPath("test-particle-face-pointer-glow.png"));
  await page.mouse.move(center.x + bounds.width * .2, center.y + bounds.height * .1, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => (await testHologramSignal(page)).maximumImpulse).toBeGreaterThan(.001);
  await expect.poll(async () => rotationDistance(await headRotation(page), initialRotation)).toBeGreaterThan(.15);
  await captureHologram(page, testInfo.outputPath("test-particle-face-rotated-desktop.png"));
  await page.mouse.move(3, 3);
  await expect.poll(async () => (await testHologramSignal(page)).uniforms.cursor[2]).toBeLessThan(.02);
  await portrait.dblclick();
  await expect.poll(async () => rotationDistance(await headRotation(page), initialRotation)).toBeLessThan(.06);
  await captureHologram(page, testInfo.outputPath("test-particle-face-front-desktop.png"));
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

test("high-quality Test portrait renders 78400 particles with all SMAA passes and releases GPU resources", async ({ page }, testInfo) => {
  test.setTimeout(90000);
  await workspace(page); await observeParticleDisplacement(page);
  // Match the approved mockup aspect ratio for composition measurements.
  await page.setViewportSize({ width: 1681, height: 936 });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.addInitScript(() => {
    // Exercise the high-quality branch on CI's real software GPU. Only the
    // capability classification changes; shader compilation and draws stay real.
    Object.defineProperty(navigator, "hardwareConcurrency", { get: () => 8 });
    const prototype = WebGL2RenderingContext.prototype;
    const getExtension = prototype.getExtension;
    prototype.getExtension = function (this: WebGL2RenderingContext, name: string) {
      const result = Reflect.apply(getExtension, this, [name]);
      if (name === "WEBGL_debug_renderer_info") {
        if (result) Object.defineProperty(window, "__portraitActualGpu", { configurable: true, value: {
          unmaskedRenderer: this.getParameter(result.UNMASKED_RENDERER_WEBGL), unmaskedVendor: this.getParameter(result.UNMASKED_VENDOR_WEBGL),
        } });
        return null;
      }
      return result;
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
  await expect.poll(async () => (await testHologramSignal(page)).points).toBe(78400);
  const homeRotation = await headRotation(page);
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.opacity[0], { timeout: 30000 }).toBe(1);
  const passes = await page.evaluate(() => (window as unknown as { __smaaPasses: Record<string, number> }).__smaaPasses);
  expect(passes.edges).toBeGreaterThan(0); expect(passes.weights).toBeGreaterThan(0); expect(passes.blend).toBeGreaterThan(0);
  expect(await portrait.locator("canvas").evaluate((element) => (element as HTMLCanvasElement).getContext("webgl2")?.getError())).toBe(0);
  const rendered = await testHologramSignal(page);
  expect(rendered.errors).toEqual([]); expect(rendered.texturedPoints).toBeGreaterThan(0);
  expect(rendered.headNonPointDraws).toBe(0);
  expect(rendered.landscapeDraws).toBeGreaterThan(0);
  const composition = await hologramComposition(page);
  expectCompositionFits(composition);
  expect(Math.hypot(...rendered.headUniforms.modelViewMatrix.slice(0, 3))).toBeCloseTo(4 * .95, 4);
  expect(boundsHeight(composition.head) / composition.ui.height).toBeGreaterThan(.48);
  expect(boundsHeight(composition.head) / composition.ui.height).toBeLessThan(.56);
  expect(boundsWidth(composition.disk) / composition.ui.width).toBeGreaterThan(.32);
  expect(boundsWidth(composition.disk) / composition.ui.width).toBeLessThan(.35);
  expect(boundsHeight(composition.cage) / composition.ui.height).toBeGreaterThan(.55);
  expect(boundsHeight(composition.cage) / composition.ui.height).toBeLessThan(.66);
  await testInfo.attach("approved-mockup-projected-composition", { body: JSON.stringify(composition), contentType: "application/json" });
  // Keep structural observations static on CPU-only CI. The following cadence,
  // state readback, Home and drag checks still exercise the real animated scene.
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const volume = await particleDisplacement(page);
  expectInteriorPopulation(volume);
  await testInfo.attach("actual-high-quality-volume-population", { body: JSON.stringify(volume), contentType: "application/json" });
  await testInfo.attach("forced-quality-actual-gpu-profile", {
    body: JSON.stringify(await sampleHologramCadence(page, 1500)), contentType: "application/json",
  });
  await pressHologramKeys(page, "Home");
  const reset = await expectRenderedHome(page, homeRotation);
  await testInfo.attach("actual-home-reset-poses", { body: JSON.stringify(reset), contentType: "application/json" });
  await portrait.locator("canvas").evaluate((element) => (element as HTMLCanvasElement).blur());
  await captureHologram(page, testInfo.outputPath("test-particle-face-high-quality-three.png"));
  const canvas = portrait.locator("canvas"), front = await headRotation(page);
  await canvas.focus();
  await pressHologramKeys(page, "ArrowRight", 10);
  await expect.poll(async () => rotationDistance(await headRotation(page), front)).toBeGreaterThan(1.8);
  await canvas.evaluate((element) => (element as HTMLCanvasElement).blur());
  await captureHologram(page, testInfo.outputPath("test-particle-face-high-quality-rotated-three.png"));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await pressHologramKeys(page, "Home");
  await expect.poll(async () => rotationDistance(await headRotation(page), homeRotation)).toBeLessThan(.04);
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.motion[0]).toBe(0);
  await canvas.evaluate((element) => (element as HTMLCanvasElement).blur());
  await captureHologram(page, testInfo.outputPath("test-particle-face-high-quality-static-three.png"));
  const beforeWide = (await testHologramSignal(page)).draws;
  await page.setViewportSize({ width: 1920, height: 1080 });
  await expect.poll(async () => portrait.locator("canvas").evaluate((element) => element.getBoundingClientRect().width)).toBe(1920);
  await expect.poll(async () => (await testHologramSignal(page)).draws).toBeGreaterThan(beforeWide);
  await captureHologram(page, testInfo.outputPath("test-particle-face-original-wide-1920.png"));
  await chooseAppearance(page, "Human hologram"); await expect(portrait).not.toBeAttached();
  await expect.poll(async () => {
    const state = await testHologramSignal(page, rendered.id);
    return state.buffers + state.programs + state.textures + state.framebuffers + state.renderbuffers;
  }).toBe(0);
  expect(errors).toEqual([]);
});
