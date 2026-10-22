import { expect, test, type Page } from "@playwright/test";
import { syntheticMicrophone } from "./support/ai-voice-fixtures";
import { assistantAuth } from "./support/assistant-auth";
import { selectAssistantAppearance } from "./support/assistant-appearance";

async function selectSculpture(page: Page) {
  // The workspace now defaults to Test. These tests exercise
  // the retained sculpture mode through the same appearance choice as users.
  await selectAssistantAppearance(page, "Sculpture");
}

async function openSculpture(page: Page) {
  const response = await page.goto("/ai");
  await selectSculpture(page);
  return response;
}

test.beforeEach(async ({ page }) => {
  await assistantAuth(page);
  await page.route('**/api/v1/ai-assistant/status', (route) => route.fulfill({ json: { configured: false, speech_configured: false, model: 'gpt-6-luna', reasoning_effort: 'high', access: 'read_only', name: 'Synthetic administrator' } }));
  await page.route('**/api/v1/ai-assistant/live', (route) => route.fulfill({ json: { observed_at: new Date().toISOString(), mcp: { connected: false, available_tools: 0, write_enabled: false } } }));
});

test.use({ launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] } });


test("authorized workspace renders the enlarged horizontal sculpture on desktop and phone", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const response = await openSculpture(page);
  expect(response?.status()).toBe(200);
  expect(response?.headers()["permissions-policy"]).toContain("microphone=(self)");
  await expect(page.getByRole("main", { name: "Global Connects AI workspace" })).toBeVisible();
  await expect(page.getByText("Every journey,", { exact: false })).toHaveCount(0);
  await expect(page.getByTestId("voice-sculpture")).toHaveAttribute("data-renderer", "webgl");
  await expect(page.getByRole("button", { name: "Start microphone" })).toHaveAttribute("aria-pressed", "false");
  await page.screenshot({ path: testInfo.outputPath("ai-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeInViewport();
  await expect(page.getByTestId("voice-sculpture")).toHaveAttribute("data-renderer", "webgl");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("ai-mobile.png"), fullPage: true });
  expect(errors).toEqual([]);
});

test("local audio drives visible sculpture movement and stops with the microphone", async ({ page }, testInfo) => {
  test.setTimeout(120000);
  await syntheticMicrophone(page);
  const uploads: string[] = [];
  page.on("request", (request) => { if (request.method() === "POST") uploads.push(request.url()); });
  await openSculpture(page);
  await expect(page.getByTestId("voice-sculpture")).toHaveAttribute("data-renderer", "webgl");
  await page.getByRole("button", { name: "Start microphone" }).click();
  const stop = page.getByRole("button", { name: "Finish voice message" });
  await expect(stop).toBeVisible();
  const sculpture = page.getByTestId("voice-sculpture");
  const quiet = await sculpture.screenshot();
  await page.evaluate(() => (window as unknown as { __voiceTest: { setVolume: (value: number) => void } }).__voiceTest.setVolume(0.22));
  await expect.poll(() => page.getByTestId("assistant-voice-status").evaluate((element) => Number((element as HTMLElement).style.getPropertyValue("--voice-level")))).toBeGreaterThan(0.5);
  // Wait on the rendered control envelope, then allow the liquid simulation to flow.
  await page.waitForTimeout(900);
  const speaking = await sculpture.screenshot({ path: testInfo.outputPath("ai-speaking.png") });
  expect(quiet.equals(speaking)).toBe(false);
  await stop.click();
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __voiceTest: { tracksStopped: () => boolean } }).__voiceTest.tracksStopped())).toBe(true);
  expect(uploads).toEqual([]);
});

test("microphone denial is recoverable and keyboard escape releases input", async ({ page }) => {
  await syntheticMicrophone(page);
  await page.addInitScript(() => {
    const grant = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    let denied = false;
    navigator.mediaDevices.getUserMedia = (constraints) => {
      if (!denied) { denied = true; return Promise.reject(new DOMException("Denied", "NotAllowedError")); }
      return grant(constraints);
    };
  });
  await openSculpture(page);
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Microphone access is blocked" })).toBeVisible();
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("button", { name: "Finish voice message" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __voiceTest: { tracksStopped: () => boolean } }).__voiceTest.tracksStopped())).toBe(true);
});

test("unavailable WebGL still shows the sculpture and a working microphone", async ({ page }, testInfo) => {
  await syntheticMicrophone(page);
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string, ...args: unknown[]) {
      if (kind === "webgl2") return null;
      return Reflect.apply(original, this, [kind, ...args]);
    } as typeof original;
  });
  await openSculpture(page);
  await expect(page.getByTestId("voice-sculpture")).toHaveAttribute("data-renderer", "image");
  await expect(page.getByAltText("An interwoven horizontal sculpture of silver and sand-colored filaments")).toBeVisible();
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("button", { name: "Finish voice message" })).toBeVisible();
  await page.getByRole("button", { name: "Finish voice message" }).click();
  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await expect(page.getByTestId("voice-sculpture")).toHaveAttribute("data-matte", "ready");
  await expect(page.getByRole("main")).toHaveCSS("background-color", "rgb(0, 0, 0)");
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  const appearance=page.getByRole("dialog", { name: "Sculpture appearance", exact: true });
  await expect(appearance).toContainText("A still view remains available when animation is unavailable");
  await expect(appearance.getByRole("button", { name: "Sculpture", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(appearance.getByRole("button", { name: "Text", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Close sculpture appearance", exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("ai-dark-fallback.png") });
});

test("reduced motion preserves the sculpture without voice deformation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await syntheticMicrophone(page);
  await openSculpture(page);
  await expect(page.getByRole("main", { name: "Global Connects AI workspace" })).toBeVisible();
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("button", { name: "Finish voice message" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeVisible();
});

test("native browser microphone permission works on the AI route", async ({ page }) => {
  // Chromium's fake device exercises the actual browser permission and media APIs.
  // Unlike the other tests, getUserMedia is not replaced with a synthetic function.
  await openSculpture(page);
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("button", { name: "Finish voice message" })).toBeVisible();
  await expect(page.getByTestId("assistant-voice-status")).toContainText("Listening to you");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeVisible();
});

test("silent VRPS stays alive and dark appearance persists across reloads", async ({ page }, testInfo) => {
  await page.route("**/api/v1/ai-assistant/assets**", (route) => route.fulfill({ json: { items: [], next_cursor: null } }));
  await page.emulateMedia({ colorScheme: "light" });
  await openSculpture(page);
  const workspace = page.getByRole("main", { name: "Global Connects AI workspace" });
  await expect(workspace).toHaveAttribute("data-theme", "light");
  const sculpture = page.getByTestId("voice-sculpture");
  await expect(sculpture).toHaveAttribute("data-renderer", "webgl");
  const canvas = sculpture.locator("canvas").last();
  const still = await canvas.screenshot();
  await page.waitForTimeout(1800);
  expect(still.equals(await canvas.screenshot())).toBe(false);
  await expect(page.getByRole("button", { name: "Start microphone" })).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await expect(workspace).toHaveAttribute("data-theme", "dark");
  await expect(workspace).toHaveCSS("background-color", "rgb(0, 0, 0)");
  await expect(page.getByTestId("assistant-atmosphere").locator("i")).toHaveCount(54);
  await page.getByRole("button", { name: "Open library" }).click();
  await expect(page.getByRole("dialog", { name: "Your library" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("ai-dark-library.png") });
  await page.getByRole("button", { name: "Close panel", exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("ai-dark-desktop.png") });
  await page.reload();
  await expect(workspace).toHaveAttribute("data-theme", "dark");
  // Theme persists; appearance intentionally starts at Test in
  // a fresh workspace. Re-select the retained sculpture for its phone checks.
  await selectSculpture(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(sculpture).toHaveAttribute("data-renderer", "webgl");
  await expect(workspace).toHaveCSS("background-color", "rgb(0, 0, 0)");
  await expect(page.getByRole("button", { name: "Switch to light mode" })).toBeInViewport();
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath("ai-dark-mobile.png") });
});

test.describe("retina rendering", () => {
  test.use({ deviceScaleFactor: 2 });
  test("sculpture keeps native display density on desktop and phone", async ({ page }) => {
    await openSculpture(page);
    const sculpture = page.getByTestId("voice-sculpture");
    await expect(sculpture).toHaveAttribute("data-renderer", "webgl");
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await expect.poll(() => sculpture.locator("canvas").last().evaluate((element) => (element as HTMLCanvasElement).width / element.clientWidth)).toBeGreaterThanOrEqual(1.9);
    }
  });
});
