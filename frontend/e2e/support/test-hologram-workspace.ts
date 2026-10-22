import { writeFileSync } from "node:fs";
import { expect, type CDPSession, type Page } from "@playwright/test";
import { Matrix4 } from "three";
import { assistantAuth } from "./assistant-auth";
import { observeTestHologram, testHologramSignal } from "./test-hologram-probe";

export async function workspace(page: Page, appearance: "female" | "male" = "female") {
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

export async function chooseAppearance(page: Page, name: "Test" | "Human hologram" | "Sculpture") {
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  const panel = page.getByRole("dialog", { name: "Sculpture appearance", exact: true });
  await panel.getByRole("button", { name, exact: true }).click();
  await expect(panel.getByRole("button", { name, exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Escape");
  if (name === "Test") {
    await expect(page.getByRole("main", { name: "Global Connects AI workspace" })).toHaveAttribute("data-appearance", "test");
    const scene = await page.getByTestId("particle-face-test").locator("canvas").evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height,
        viewportWidth: innerWidth, viewportHeight: innerHeight, pointerEvents: getComputedStyle(element).pointerEvents };
    });
    expect(scene.x).toBeCloseTo(0); expect(scene.y).toBeCloseTo(0);
    expect(scene.width).toBeCloseTo(scene.viewportWidth); expect(scene.height).toBeCloseTo(scene.viewportHeight);
    expect(scene.pointerEvents).toBe("none");
  }
}

export async function headRotation(page: Page) {
  const state = await testHologramSignal(page);
  expect(state.headUniforms.modelViewMatrix).toHaveLength(16);
  expect(state.landscapeUniforms.viewMatrix).toHaveLength(16);
  return localHeadRotation(state.headUniforms.modelViewMatrix, state.landscapeUniforms.viewMatrix);
}

export function localHeadRotation(modelView: number[], cameraView: number[]) {
  // Both objects now share the actual terrain camera. Remove its view matrix
  // and the sculpture's camera-facing parent yaw before comparing face gestures.
  const camera = new Matrix4().fromArray(cameraView).invert();
  const world = camera.clone().multiply(new Matrix4().fromArray(modelView));
  const yaw = Math.atan2(camera.elements[12], camera.elements[14]);
  const local = new Matrix4().makeRotationY(-yaw).multiply(world).elements;
  return [0, 4, 8].flatMap((column) => {
    const length = Math.hypot(local[column], local[column + 1], local[column + 2]);
    expect(length).toBeGreaterThan(0);
    return [0, 1, 2].map((row) => local[column + row] / length);
  });
}

export async function landscapeCamera(page: Page) {
  const matrix = (await testHologramSignal(page)).landscapeUniforms.viewMatrix;
  expect(matrix).toHaveLength(16);
  return matrix;
}

export const rotationDistance = (a: number[], b: number[]) => Math.hypot(...a.map((value, index) => value - b[index]));

const sessions = new WeakMap<Page, Promise<CDPSession>>();
const browserSession = (page: Page) => {
  let session = sessions.get(page);
  if (!session) { session = page.context().newCDPSession(page); sessions.set(page, session); }
  return session;
};

/** Capture the current compositor image without waiting for fonts or extra frames. */
export async function captureHologram(page: Page, path: string) {
  const session = await browserSession(page), requestedAt = Date.now();
  const result = await session.send("Page.captureScreenshot", { format: "png", fromSurface: true, optimizeForSpeed: true });
  const completedAt = Date.now(), png = Buffer.from(result.data, "base64");
  writeFileSync(path, png);
  // This CDP method has no frame timestamp: these are capture bounds, not a
  // fabricated time at which the compositor presented the captured frame.
  return { png, requestedAt, completedAt };
}

/** Send real browser key events in order, without a focus/auto-wait per repeat. */
export async function pressHologramKeys(page: Page, key: string, count = 1) {
  const shifted = key.startsWith("Shift+"), name = shifted ? key.slice(6) : key;
  const codes: Record<string, number> = { Home: 36, ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ArrowDown: 40 };
  if (!codes[name]) throw new Error(`Unsupported portrait test key: ${key}`);
  await page.getByTestId("particle-face-test").locator("canvas").focus();
  const session = await browserSession(page), pending: Array<Promise<unknown>> = [];
  for (let index = 0; index < count; index++) {
    const event = { key: name, code: name, windowsVirtualKeyCode: codes[name], nativeVirtualKeyCode: codes[name], modifiers: shifted ? 8 : 0 };
    pending.push(session.send("Input.dispatchKeyEvent", { ...event, type: "keyDown" }));
    pending.push(session.send("Input.dispatchKeyEvent", { ...event, type: "keyUp" }));
  }
  await Promise.all(pending);
}

export async function sampleHologramCadence(page: Page, duration = 5000) {
  return page.evaluate((milliseconds) => new Promise<{
    gpu: Record<string, unknown>; points: number; elapsed: number; renderedFrames: number;
    framesPerSecond: number; intervals: number[]; errors: string[]; webglError: number;
  }>((resolve) => {
    const canvas = document.querySelector('[data-testid="particle-face-test"] canvas') as HTMLCanvasElement & {
      __portraitProbe: { frames: number; points: number; errors: string[] };
    };
    const gl = canvas.getContext("webgl2")!, debug = gl.getExtension("WEBGL_debug_renderer_info");
    const actual = (window as unknown as { __portraitActualGpu?: Record<string, unknown> }).__portraitActualGpu;
    const gpu = { renderer: gl.getParameter(gl.RENDERER), vendor: gl.getParameter(gl.VENDOR),
      unmaskedRenderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : actual?.unmaskedRenderer ?? null,
      unmaskedVendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : actual?.unmaskedVendor ?? null,
      hardwareConcurrency: navigator.hardwareConcurrency, devicePixelRatio, canvasWidth: canvas.width, canvasHeight: canvas.height };
    const started = performance.now(), first = canvas.__portraitProbe.frames, intervals: number[] = [];
    let last: number | undefined, frames = first, request = 0;
    const sample = (now: number) => {
      if (canvas.__portraitProbe.frames !== frames) {
        if (last !== undefined && now > last) intervals.push(now - last);
        last = now; frames = canvas.__portraitProbe.frames;
      }
      request = requestAnimationFrame(sample);
    };
    request = requestAnimationFrame(sample);
    setTimeout(() => {
      cancelAnimationFrame(request);
      const elapsed = performance.now() - started, renderedFrames = canvas.__portraitProbe.frames - first;
      resolve({ gpu, points: canvas.__portraitProbe.points, elapsed, renderedFrames, framesPerSecond: renderedFrames * 1000 / elapsed,
        intervals, errors: canvas.__portraitProbe.errors, webglError: gl.getError() });
    }, milliseconds);
  }), duration);
}
