import { expect, test } from "@playwright/test";
import { syntheticMicrophone } from "./support/ai-voice-fixtures";
import { assistantAuth } from "./support/assistant-auth";

test.beforeEach(async ({ page }) => {
  await assistantAuth(page);
  await page.route('**/api/v1/ai-assistant/status', (route) => route.fulfill({ json: { configured: false, speech_configured: false, model: 'gpt-6-luna', reasoning_effort: 'high', access: 'read_only', name: 'Synthetic administrator' } }));
  await page.route('**/api/v1/ai-assistant/live', (route) => route.fulfill({ json: { observed_at: new Date().toISOString(), agencies: [] } }));
});

test.use({ launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] } });


test("authorized workspace renders the enlarged horizontal sculpture on desktop and phone", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const response = await page.goto("/ai");
  expect(response?.status()).toBe(200);
  expect(response?.headers()["permissions-policy"]).toContain("microphone=(self)");
  await expect(page.getByRole("heading", { name: "Every journey, a little clearer." })).toBeVisible();
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
  await page.goto("/ai");
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
  await page.goto("/ai");
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Microphone access is blocked" })).toBeVisible();
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("button", { name: "Finish voice message" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __voiceTest: { tracksStopped: () => boolean } }).__voiceTest.tracksStopped())).toBe(true);
});

test("unavailable WebGL still shows the sculpture and a working microphone", async ({ page }) => {
  await syntheticMicrophone(page);
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string, ...args: unknown[]) {
      if (kind === "webgl2") return null;
      return Reflect.apply(original, this, [kind, ...args]);
    } as typeof original;
  });
  await page.goto("/ai");
  await expect(page.getByTestId("voice-sculpture")).toHaveAttribute("data-renderer", "image");
  await expect(page.getByAltText("An interwoven horizontal sculpture of silver and sand-colored filaments")).toBeVisible();
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("button", { name: "Finish voice message" })).toBeVisible();
  await page.getByRole("button", { name: "Finish voice message" }).click();
});

test("reduced motion preserves the sculpture without voice deformation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await syntheticMicrophone(page);
  await page.goto("/ai");
  await expect(page.getByRole("heading", { name: "Every journey, a little clearer." })).toBeVisible();
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("button", { name: "Finish voice message" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeVisible();
});

test("native browser microphone permission works on the AI route", async ({ page }) => {
  // Chromium's fake device exercises the actual browser permission and media APIs.
  // Unlike the other tests, getUserMedia is not replaced with a synthetic function.
  await page.goto("/ai");
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("button", { name: "Finish voice message" })).toBeVisible();
  await expect(page.getByTestId("assistant-voice-status")).toContainText("Listening to you");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeVisible();
});
