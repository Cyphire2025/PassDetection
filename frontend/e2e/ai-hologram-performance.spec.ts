import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { workspace, captureHologram, sampleHologramCadence } from "./support/test-hologram-workspace";
import { hologramDiagnostics } from "./support/test-hologram-diagnostics";
import { testHologramSignal } from "./support/test-hologram-probe";
import { syntheticMicrophone } from "./support/ai-voice-fixtures";
import { expectFrozenHead, headMotionWindow } from "./support/test-hologram-motion";
import { observeRenderedHead, renderedHead } from "./support/test-hologram-coverage";
import { restingHeadProjection } from "./support/test-hologram-composition";

for (const mobile of [false, true]) test.describe(mobile ? "phone" : "desktop", () => {
  test.use({ viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 960 }, deviceScaleFactor: mobile ? 3 : 1 });
  test("cold scene load, smooth rendering and orientation", async ({ page }, info) => {
    await workspace(page, "female", false);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const session = await page.context().newCDPSession(page);
    await session.send("Network.enable");
    await session.send("Network.clearBrowserCache");
    if (mobile) {
      await session.send("Emulation.setCPUThrottlingRate", { rate: 4 });
      await session.send("Network.emulateNetworkConditions", { offline: false, latency: 40, downloadThroughput: 20_000_000 / 8, uploadThroughput: 5_000_000 / 8 });
    }
    await page.goto("/ai");
    const portrait = page.getByTestId("particle-face-test");
    await expect(portrait).toHaveAttribute("data-renderer", "webgl");
    const startup = await portrait.evaluate((element) => ({
      navigationToSceneMs: Number((element as HTMLElement).dataset.readyAt),
      mountToSceneMs: Number((element as HTMLElement).dataset.readyMs),
      sceneAssets: performance.getEntriesByType("resource").filter((entry) => /\/ai\/(human-head|test-landscape)\//.test(entry.name))
        .map((entry) => { const asset = entry as PerformanceResourceTiming; return { path: new URL(asset.name).pathname, bytes: asset.encodedBodySize, duration: asset.duration }; }),
    }));
    const cadence = await sampleHologramCadence(page, 2500);
    writeFileSync(info.outputPath("performance.json"), JSON.stringify({ mobile, ...startup, cadence }, null, 2));
    console.info(JSON.stringify({ mobile, sceneMs: startup.navigationToSceneMs, mountMs: startup.mountToSceneMs, fps: cadence.framesPerSecond, assetBytes: startup.sceneAssets.reduce((sum, asset) => sum + asset.bytes, 0) }));
    await info.attach("startup-and-cadence", { body: JSON.stringify({ mobile, cpuSlowdown: mobile ? 4 : 1, networkMbps: mobile ? 20 : null, ...startup, cadence }), contentType: "application/json" });
    await captureHologram(page, info.outputPath("scene.png"));
    expect(startup.sceneAssets.some((asset) => /fields-|head-v1\.bin/.test(asset.path))).toBe(false);
    expect(startup.sceneAssets.reduce((sum, asset) => sum + asset.bytes, 0)).toBeLessThan(1_800_000);
    expect(cadence.errors).toEqual([]); expect(cadence.webglError).toBe(0);
    // A development compilation is not a product startup measurement.
    if (process.env.HOLOGRAM_PRODUCTION === "1") expect(startup.navigationToSceneMs).toBeLessThan(2000);
    if (mobile) {
      await page.setViewportSize({ width: 844, height: 390 });
      await expect(page.getByRole("button", { name: "Start microphone", exact: true })).toBeInViewport();
      await expect(page.getByRole("textbox", { name: "Message Global Connects", exact: true })).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await captureHologram(page, info.outputPath("landscape.png"));
    }
    const diagnostics = await hologramDiagnostics(page);
    expect(diagnostics.consoleErrors).toEqual([]); expect(diagnostics.pageErrors).toEqual([]); expect(diagnostics.assetFailures).toEqual([]); expect(diagnostics.cspViolations).toEqual([]);
  });
});

test("voice holds rotation, retains gentle motion, and changes playback color", async ({ page }, info) => {
  test.setTimeout(120_000);
  await workspace(page); await syntheticMicrophone(page);
  // Keep the fixture playing until the real Stop control is exercised, even
  // when software GPU capture and actionability checks take several seconds.
  const rate = 16000, samples = rate * 120, wav = Buffer.alloc(44 + samples * 2);
  wav.write("RIFF"); wav.writeUInt32LE(wav.length - 8, 4); wav.write("WAVEfmt ", 8); wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22); wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28);
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write("data", 36); wav.writeUInt32LE(samples * 2, 40);
  for (let i = 0; i < samples; i++) wav.writeInt16LE(Math.round(Math.sin(i / rate * Math.PI * 360) * 14000), 44 + i * 2);
  await page.route("**/api/v1/ai-assistant/status", (route) => route.fulfill({ json: {
    configured: true, speech_configured: true, voice_configured: true, native_voice: false, avatar_appearance: "female",
    account_id: "test-portrait-admin", account_scope: "super_admin", access: "read_only",
  } }));
  await page.route("**/api/v1/ai-assistant/transcribe", (route) => route.fulfill({ json: { text: "Hello" } }));
  await page.route("**/api/v1/ai-assistant/chat", (route) => route.fulfill({ contentType: "text/event-stream", body: [
    { type: "text_delta", text: "Hello, how can I help?" }, { type: "done", request_id: route.request().postDataJSON().request_id },
  ].map((event) => `event: assistant\ndata: ${JSON.stringify(event)}\n\n`).join("") }));
  await page.route("**/api/v1/ai-assistant/speech", (route) => route.fulfill({ contentType: "audio/wav", body: wav }));
  await page.goto("/ai");
  await expect(page.getByTestId("particle-face-test")).toHaveAttribute("data-renderer", "webgl");
  await page.getByRole("button", { name: "Start microphone", exact: true }).click();
  await expect(page.getByRole("button", { name: "Finish voice message", exact: true })).toBeVisible();
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.ambientMotion?.[0]).toBeCloseTo(.28);
  expectFrozenHead(await headMotionWindow(page, 500));
  await page.evaluate(() => (window as unknown as { __voiceTest: { setVolume(v: number): void } }).__voiceTest.setVolume(.22));
  await page.getByRole("button", { name: "Finish voice message", exact: true }).click();
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.responseGlow?.[0]).toBeGreaterThan(.9);
  expectFrozenHead(await headMotionWindow(page, 500));
  await captureHologram(page, info.outputPath("ai-speaking.png"));
  await page.getByRole("button", { name: "Stop speaking", exact: true }).click();
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.responseGlow?.[0]).toBeLessThan(.05);
  expect((await testHologramSignal(page)).errors).toEqual([]);
});

test("ordinary pointer movement glows, retains anatomy, and returns particles home", async ({ page }, info) => {
  // Three synchronous GPU readbacks can be slow on CI's software renderer.
  // Keep the production startup budget separate from this diagnostic workload.
  test.setTimeout(120_000);
  await workspace(page); await syntheticMicrophone(page); await observeRenderedHead(page);
  await page.route("**/api/v1/ai-assistant/status", (route) => route.fulfill({ json: {
    configured: true, speech_configured: true, voice_configured: true, native_voice: false, avatar_appearance: "female",
    account_id: "test-portrait-admin", account_scope: "super_admin", access: "read_only",
  } }));
  await page.goto("/ai");
  await expect(page.getByTestId("particle-face-test")).toHaveAttribute("data-renderer", "webgl");
  await page.getByRole("button", { name: "Start microphone", exact: true }).click();
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.ambientMotion?.[0]).toBeCloseTo(.28);
  const viewport = page.viewportSize()!;
  const box = restingHeadProjection((await testHologramSignal(page)).headUniforms, viewport.width, viewport.height).box;
  const before = await renderedHead(page, box);
  const bounds = (await page.getByTestId("particle-face-test").boundingBox())!;
  await page.mouse.move(bounds.x + bounds.width * .4, bounds.y + bounds.height * .45);
  await page.mouse.move(bounds.x + bounds.width * .6, bounds.y + bounds.height * .45, { steps: 12 });
  expect((await testHologramSignal(page)).headUniforms["pointerEnergies[0]"].some((value, index) => index % 4 === 1 && value > .38)).toBe(true);
  const disturbed = await renderedHead(page, box);
  const retained = (mask: string) => {
    const initial = Buffer.from(before.mask, "base64"), current = Buffer.from(mask, "base64");
    let visible = 0, shared = 0;
    for (let i = 0; i < initial.length; i++) if (initial[i]) { visible++; if (current[i]) shared++; }
    return shared / visible;
  };
  expect(retained(disturbed.mask), "a stroke retains the recognizable face silhouette").toBeGreaterThan(.85);
  await page.mouse.move(2, 2); await page.waitForTimeout(750);
  expect(retained((await renderedHead(page, box)).mask), "particles return to the face after the stroke").toBeGreaterThan(.94);
  await captureHologram(page, info.outputPath("recovered-pointer-stroke.png"));
  expect((await testHologramSignal(page)).errors).toEqual([]);
});
