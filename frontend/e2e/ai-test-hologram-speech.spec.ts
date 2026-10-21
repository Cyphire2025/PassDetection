import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";
import { assistantAuth } from "./support/assistant-auth";
import { syntheticMicrophone } from "./support/ai-voice-fixtures";
import { observeTestHologram, testHologramSignal } from "./support/test-hologram-probe";
import { hologramDiagnostics } from "./support/test-hologram-diagnostics";

test.afterEach(async ({ page }, testInfo) => {
  const diagnostics = await hologramDiagnostics(page);
  await testInfo.attach("landscape-runtime-diagnostics", { body: JSON.stringify(diagnostics), contentType: "application/json" });
  expect(diagnostics.cspViolations).toEqual([]);
  expect(diagnostics.pageErrors).toEqual([]);
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.assetFailures).toEqual([]);
  if (process.env.TEST_HOLOGRAM_PRODUCTION_CSP === "1") {
    expect(diagnostics.documentCsp).toContain("script-src");
    expect(diagnostics.documentCsp).not.toContain("'unsafe-eval'");
  }
});

type SpeechProbe = { started: number; playing: number; stopped: number; played: number };
type SpeechWindow = Window & { __hologramSpeech: () => SpeechProbe };
type SpeechSample = { mouth: number[]; closure: number; playback: SpeechProbe };
const TONE_SECONDS = 3.6;

async function workspace(page: Page) {
  await assistantAuth(page); await syntheticMicrophone(page); await observeTestHologram(page);
  await page.route("**/api/v1/ai-assistant/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/availability")) return route.fulfill({ json: { enabled: true, allowed: true } });
    if (path.endsWith("/status")) return route.fulfill({ json: {
      configured: true, speech_configured: true, native_voice: true, voice_configured: true,
      provider: "openai", voice_provider: "openai", model: "gpt-realtime-2.1", avatar_appearance: "female",
      account_id: "speech-portrait-admin", account_scope: "super_admin", can_manage_settings: true,
      settings_revision: 1, access: "read_only",
    } });
    if (path.endsWith("/live")) return route.fulfill({ json: {
      observed_at: new Date().toISOString(), mcp: { connected: true, available_tools: 8, write_enabled: false },
    } });
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
  // Observe uniforms and actual AudioBufferSource playback without replacing
  // AudioContext, analyser data, RAF, source scheduling, or the speech monitor.
  await page.addInitScript(() => {
    const entries: Array<{ source: AudioBufferSourceNode; at: number; seconds: number; ended: boolean; stopped: boolean }> = [];
    const start = AudioBufferSourceNode.prototype.start;
    AudioBufferSourceNode.prototype.start = function (...args: Parameters<AudioBufferSourceNode["start"]>) {
      if (this.buffer?.sampleRate === 24000) {
        const entry = { source: this, at: args[0] || this.context.currentTime, seconds: this.buffer.duration, ended: false, stopped: false };
        entries.push(entry); this.addEventListener("ended", () => { entry.ended = true; }, { once: true });
      }
      return start.apply(this, args);
    };
    const stop = AudioBufferSourceNode.prototype.stop;
    AudioBufferSourceNode.prototype.stop = function (...args: Parameters<AudioBufferSourceNode["stop"]>) {
      const entry = entries.find((item) => item.source === this);
      if (entry && !entry.ended) entry.stopped = true;
      return stop.apply(this, args);
    };
    Object.defineProperty(window, "__hologramSpeech", { value: () => ({ started: entries.length,
      playing: entries.filter((entry) => !entry.stopped && !entry.ended && entry.source.context.currentTime >= entry.at).length,
      stopped: entries.filter((entry) => entry.stopped).length,
      played: entries.filter((entry) => entry.ended && !entry.stopped).reduce((total, entry) => total + entry.seconds, 0),
    }) });
  });
}

function pcm(frequency: number, seconds = TONE_SECONDS) {
  const buffer = Buffer.alloc(Math.round(24000 * seconds) * 2);
  for (let sample = 0; sample < buffer.length / 2; sample++) {
    buffer.writeInt16LE(Math.round(Math.sin(sample * 2 * Math.PI * frequency / 24000) * 7000), sample * 2);
  }
  return buffer.toString("base64");
}

const playback = (page: Page) => page.evaluate(() => (window as unknown as SpeechWindow).__hologramSpeech());
const articulation = async (page: Page) => (await testHologramSignal(page)).headUniforms.articulation;
const closure = async (page: Page) => (await testHologramSignal(page)).headUniforms.closure[0];

async function speakingMouth(page: Page, channel: number, minimum: number) {
  let observed: SpeechSample | undefined;
  await expect.poll(async () => {
    // Capture the submitted mouth and actual AudioContext playback together;
    // another round trip can land after a short utterance on a software GPU.
    observed = await page.evaluate(() => {
      const canvas = document.querySelector('[data-testid="particle-face-test"] canvas') as HTMLCanvasElement & {
        __portraitProbe: { headUniforms: { articulation: number[]; closure: number[] } };
      };
      const uniforms = canvas.__portraitProbe.headUniforms;
      return { mouth: uniforms.articulation, closure: uniforms.closure[0], playback: (window as unknown as SpeechWindow).__hologramSpeech() };
    });
    return observed.playback.playing > 0 ? observed.mouth[channel] : 0;
  }, { intervals: [80] }).toBeGreaterThan(minimum);
  return observed!;
}

test("Test mouth follows audible spectral changes and silence, not early captions, and clears on interruption", async ({ page }, testInfo) => {
  test.setTimeout(90000);
  await workspace(page); await page.emulateMedia({ colorScheme: "dark" });
  await page.setViewportSize({ width: 1440, height: 960 });
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  const closes: Array<number | undefined> = [];
  let wire: WebSocketRoute | undefined, capturePackets = 0;
  await page.routeWebSocket("**/api/v1/ai-assistant/voice", (socket) => {
    wire = socket; socket.onClose((code) => { closes.push(code); });
    socket.onMessage((raw) => {
      const message = JSON.parse(String(raw));
      if (message.type === "start") socket.send(JSON.stringify({ type: "ready", conversation_id: message.conversation_id, max_session_seconds: 600 }));
      if (message.type === "audio") capturePackets++;
    });
  });
  await page.goto("/ai");
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  await page.getByRole("dialog", { name: "Sculpture appearance", exact: true }).getByRole("button", { name: "Test", exact: true }).click();
  await page.keyboard.press("Escape");
  const portrait = page.getByTestId("particle-face-test");
  await expect(portrait).toHaveAttribute("data-renderer", "webgl");
  await page.getByRole("button", { name: "Start microphone", exact: true }).click();
  await expect.poll(() => capturePackets).toBeGreaterThan(1);
  const send = (event: object) => { expect(wire).toBeDefined(); wire!.send(JSON.stringify(event)); };
  const audio = (frequency: number, seconds = TONE_SECONDS) => send({ type: "audio", data: pcm(frequency, seconds), sample_rate: 24000, turn_id: "articulation" });
  const neutral = async () => {
    await expect.poll(async () => Math.max(...await articulation(page)), { intervals: [100] }).toBeLessThan(.01);
    await expect.poll(() => closure(page), { intervals: [100] }).toBeLessThan(.01);
  };
  const caption = "This caption arrives before the spoken audio, so it must not animate the lips.";
  send({ type: "input_transcript", text: "Demonstrate your speaking mouth.", turn_id: "articulation" });
  send({ type: "text_delta", text: caption, turn_id: "articulation" });
  await page.waitForTimeout(450); // Multiple rendered frames after text, with no output PCM.
  await neutral(); expect((await playback(page)).started).toBe(0);

  audio(500);
  const rounded = (await speakingMouth(page, 1, .7)).mouth;
  expect(rounded[0]).toBeGreaterThan(.2); expect(rounded[2]).toBeLessThan(.2);
  await page.screenshot({ path: testInfo.outputPath("test-mouth-rounded-actual-audio.png") });
  await expect.poll(async () => (await playback(page)).played).toBeCloseTo(TONE_SECONDS, 3);
  audio(0, .8); await neutral(); // Actual queued silent PCM must close the mouth.
  await expect.poll(async () => (await playback(page)).played).toBeCloseTo(TONE_SECONDS + .8, 3);

  audio(2700);
  const wide = (await speakingMouth(page, 2, .6)).mouth;
  expect(wide[1]).toBeLessThan(.2); expect(wide[2]).toBeGreaterThan(rounded[2] + .5);
  await expect.poll(async () => (await playback(page)).played).toBeCloseTo(TONE_SECONDS * 2 + .8, 3); await neutral();

  audio(1200);
  await speakingMouth(page, 0, .5);
  await page.screenshot({ path: testInfo.outputPath("test-mouth-open-actual-audio.png") });
  await expect.poll(async () => (await playback(page)).played).toBeCloseTo(TONE_SECONDS * 3 + .8, 3); await neutral();
  audio(6000);
  expect((await speakingMouth(page, 3, .7)).closure).toBeGreaterThan(.06);
  await expect.poll(async () => (await playback(page)).played).toBeCloseTo(TONE_SECONDS * 4 + .8, 3); await neutral();

  // A complete provider response may still have a long bounded PCM backlog.
  // Barge-in must clear its mouth and audio without disconnecting capture.
  for (let index = 0; index < 45; index++) audio(500, 1);
  send({ type: "turn_complete", turn_id: "articulation", turn: { id: "articulation", user: "Demonstrate your speaking mouth.", assistant: caption,
    created_at: new Date().toISOString(), voice: true, sources: [], images: [] } });
  await expect.poll(async () => (await articulation(page))[1], { intervals: [80] }).toBeGreaterThan(.7);
  const beforeInterruption = capturePackets;
  send({ type: "input_started" }); await neutral();
  await expect.poll(async () => (await playback(page)).playing).toBe(0);
  expect((await playback(page)).stopped).toBeGreaterThan(0);
  await expect.poll(() => capturePackets).toBeGreaterThan(beforeInterruption + 3);
  const cancelled = (await playback(page)).started;
  await page.waitForTimeout(1200); await neutral();
  expect((await playback(page)).started).toBe(cancelled);
  await page.getByRole("button", { name: "Show conversation", exact: true }).click();
  await expect(page.getByText(caption, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "End voice conversation", exact: true })).toBeVisible();
  expect(closes).toEqual([]); expect(errors).toEqual([]);
  expect((await testHologramSignal(page)).errors).toEqual([]);
});
