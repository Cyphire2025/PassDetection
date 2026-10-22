import { expect, test, type Page, type TestInfo, type WebSocketRoute } from "@playwright/test";
import { assistantAuth } from "./support/assistant-auth";
import { syntheticMicrophone } from "./support/ai-voice-fixtures";
import { observeTestHologram, testHologramSignal } from "./support/test-hologram-probe";
import { hologramDiagnostics } from "./support/test-hologram-diagnostics";
import { captureHologram, chooseAppearance } from "./support/test-hologram-workspace";
import { expectCoherentInteriorMotion, expectCoherentSurfaceMotion, expectParticlesInsideBoundary, expectWholeFaceDeformation, observeParticleDisplacement, particleDisplacement } from "./support/test-hologram-displacement";
import { expectFrozenHead, expectSmoothIdleRotation, headMotionWindow } from "./support/test-hologram-motion";

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
type SpeechWindow = Window & { __hologramSpeech: () => SpeechProbe; __voiceTest: { setVolume: (value: number) => void } };
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

async function speakingControlsFit(page: Page, testInfo: TestInfo, name: string) {
  const voice = page.getByTestId("assistant-voice-status");
  await expect(voice.getByRole("status")).toHaveText("Speaking with you");
  await expect(voice.getByRole("button", { name: "Stop speaking", exact: true })).toBeVisible();
  const layout = await page.evaluate(() => {
    const voice = document.querySelector('[data-testid="assistant-voice-status"]')!;
    const microphone = voice.querySelector('button[aria-label="End voice conversation"]')!;
    const stop = Array.from(voice.querySelectorAll("button")).find((button) => button.textContent?.includes("Stop speaking"))!;
    const box = (element: Element) => {
      const rect = element.getBoundingClientRect();
      return { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom };
    };
    const stopBox = box(stop);
    return { width: innerWidth, height: innerHeight,
      boxes: { microphone: box(microphone), label: box(voice.querySelector('[role="status"]')!), stop: stopBox,
        composer: box(document.querySelector('textarea[aria-label="Message Global Connects"]')!.parentElement!) },
      stopReceivesPointer: stop.contains(document.elementFromPoint((stopBox.left + stopBox.right) / 2, (stopBox.top + stopBox.bottom) / 2)),
      playback: (window as unknown as SpeechWindow).__hologramSpeech(),
    };
  });
  await testInfo.attach(`speaking-controls-${name}`, { body: JSON.stringify(layout), contentType: "application/json" });
  expect(layout.playback.playing).toBeGreaterThan(0);
  expect(layout.stopReceivesPointer).toBe(true);
  const boxes = Object.entries(layout.boxes);
  for (let index = 0; index < boxes.length; index++) {
    const [name, box] = boxes[index];
    expect(box.right - box.left, `${name} has visible width`).toBeGreaterThan(0);
    expect(box.bottom - box.top, `${name} has visible height`).toBeGreaterThan(0);
    expect(box.left, `${name} fits the left edge`).toBeGreaterThanOrEqual(0);
    expect(box.right, `${name} fits the right edge`).toBeLessThanOrEqual(layout.width);
    expect(box.top, `${name} fits the top edge`).toBeGreaterThanOrEqual(0);
    expect(box.bottom, `${name} fits the bottom edge`).toBeLessThanOrEqual(layout.height);
    for (const [otherName, other] of boxes.slice(index + 1)) {
      const gap = Math.max(other.left - box.right, box.left - other.right, other.top - box.bottom, box.top - other.bottom);
      expect(gap, `${name} stays separate from ${otherName}`).toBeGreaterThan(0);
    }
  }
  await captureHologram(page, testInfo.outputPath(`test-speaking-controls-${name}.png`));
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
    await expect.poll(async () => {
      const uniforms = (await testHologramSignal(page)).headUniforms;
      return Math.max(...uniforms.articulation, uniforms.closure[0]);
    }, { intervals: [100] }).toBeLessThan(.01);
  };
  // Listening should energize the sculpture without inventing speech articulation.
  // This uses real capture/analyser samples, before any output PCM is delivered.
  await page.evaluate(() => (window as unknown as SpeechWindow).__voiceTest.setVolume(.25));
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.speechEnergy[0]).toBeGreaterThan(.08);
  await neutral(); expect((await playback(page)).started).toBe(0);
  const listening = await testHologramSignal(page);
  await testInfo.attach("listening-particles-with-neutral-mouth", {
    body: JSON.stringify({ energy: listening.headUniforms.speechEnergy, articulation: listening.headUniforms.articulation, closure: listening.headUniforms.closure }),
    contentType: "application/json",
  });
  await captureHologram(page, testInfo.outputPath("test-particles-listening-neutral-mouth.png"));
  await page.evaluate(() => (window as unknown as SpeechWindow).__voiceTest.setVolume(0));
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.speechEnergy[0]).toBeLessThan(.02);
  const caption = "This caption arrives before the spoken audio, so it must not animate the lips.";
  send({ type: "input_transcript", text: "Demonstrate your speaking mouth.", turn_id: "articulation" });
  send({ type: "text_delta", text: caption, turn_id: "articulation" });
  await page.waitForTimeout(450); // Multiple rendered frames after text, with no output PCM.
  await neutral(); expect((await playback(page)).started).toBe(0);

  audio(500);
  const rounded = (await speakingMouth(page, 1, .7)).mouth;
  expect(rounded[0]).toBeGreaterThan(.2); expect(rounded[2]).toBeLessThan(.2);
  await captureHologram(page, testInfo.outputPath("test-mouth-rounded-actual-audio.png"));
  await expect.poll(async () => (await playback(page)).played).toBeCloseTo(TONE_SECONDS, 3);
  audio(0, .8); await neutral(); // Actual queued silent PCM must close the mouth.
  await expect.poll(async () => (await playback(page)).played).toBeCloseTo(TONE_SECONDS + .8, 3);

  audio(2700);
  const wide = (await speakingMouth(page, 2, .6)).mouth;
  expect(wide[1]).toBeLessThan(.2); expect(wide[2]).toBeGreaterThan(rounded[2] + .5);
  await expect.poll(async () => (await playback(page)).played).toBeCloseTo(TONE_SECONDS * 2 + .8, 3); await neutral();

  audio(1200);
  await speakingMouth(page, 0, .5);
  await captureHologram(page, testInfo.outputPath("test-mouth-open-actual-audio.png"));
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
  await speakingControlsFit(page, testInfo, "desktop");
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

test("Test speaking controls fit phone portrait and landscape, and Stop speaking stops real playback", async ({ page }, testInfo) => {
  test.setTimeout(90000);
  await workspace(page); await page.emulateMedia({ colorScheme: "dark" });
  let wire: WebSocketRoute | undefined, capturePackets = 0;
  await page.routeWebSocket("**/api/v1/ai-assistant/voice", (socket) => {
    wire = socket;
    socket.onMessage((raw) => {
      const message = JSON.parse(String(raw));
      if (message.type === "start") socket.send(JSON.stringify({ type: "ready", conversation_id: message.conversation_id, max_session_seconds: 600 }));
      if (message.type === "audio") capturePackets++;
    });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/ai"); await chooseAppearance(page, "Test");
  await expect(page.getByTestId("particle-face-test")).toHaveAttribute("data-renderer", "webgl");
  for (const viewport of [{ name: "phone-portrait", width: 390, height: 844 }, { name: "phone-landscape", width: 844, height: 390 }]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const previousPackets = capturePackets;
    await page.getByRole("button", { name: "Start microphone", exact: true }).click();
    await expect.poll(() => capturePackets).toBeGreaterThan(previousPackets + 1);
    expect(wire).toBeDefined();
    for (let index = 0; index < 12; index++) {
      wire!.send(JSON.stringify({ type: "audio", data: pcm(500, 1), sample_rate: 24000, turn_id: viewport.name }));
    }
    await speakingMouth(page, 1, .7);
    await speakingControlsFit(page, testInfo, viewport.name);
    const stoppedBefore = (await playback(page)).stopped;
    await page.getByRole("button", { name: "Stop speaking", exact: true }).click();
    await expect.poll(async () => (await playback(page)).playing).toBe(0);
    expect((await playback(page)).stopped).toBeGreaterThan(stoppedBefore);
    await expect(page.getByRole("button", { name: "Stop speaking", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Start microphone", exact: true })).toBeVisible();
  }
  expect((await testHologramSignal(page)).errors).toEqual([]);
});

test("idle rotation pauses for microphone and audible speech while particles keep deforming, then resumes smoothly", async ({ page }, testInfo) => {
  test.setTimeout(120000);
  await workspace(page); await observeParticleDisplacement(page);
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1681, height: 936 });
  let wire: WebSocketRoute | undefined, capturePackets = 0;
  await page.routeWebSocket("**/api/v1/ai-assistant/voice", (socket) => {
    wire = socket;
    socket.onMessage((raw) => {
      const message = JSON.parse(String(raw));
      if (message.type === "start") socket.send(JSON.stringify({ type: "ready", conversation_id: message.conversation_id, max_session_seconds: 600 }));
      if (message.type === "audio") capturePackets++;
    });
  });
  await page.goto("/ai"); await chooseAppearance(page, "Test");
  await expect(page.getByTestId("particle-face-test")).toHaveAttribute("data-renderer", "webgl");
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.opacity[0]).toBe(1);
  await page.mouse.move(2, 934);
  const idleBefore = await particleDisplacement(page), idle = await headMotionWindow(page, 1800), idleAfter = await particleDisplacement(page);
  await testInfo.attach("actual-idle-surface-coherence", { contentType: "application/json", body: JSON.stringify({ idleBefore, idleAfter }) });
  expectSmoothIdleRotation(idle);
  expectWholeFaceDeformation(idleAfter); expectParticlesInsideBoundary(idleAfter);
  expectCoherentSurfaceMotion(idleAfter);
  expectCoherentInteriorMotion(idleAfter);
  expect((await testHologramSignal(page)).headNonPointDraws).toBe(0);
  await page.getByRole("button", { name: "Start microphone", exact: true }).click();
  await expect.poll(() => capturePackets).toBeGreaterThan(1);
  // An open, silent microphone must not disable idle rotation.
  const silentMic = await headMotionWindow(page, 1800);
  expectSmoothIdleRotation(silentMic);
  await page.evaluate(() => (window as unknown as SpeechWindow).__voiceTest.setVolume(.25));
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.speechEnergy[0]).toBeGreaterThan(.08);
  const micBefore = await particleDisplacement(page), micFrames = await headMotionWindow(page), micAfter = await particleDisplacement(page);
  expectFrozenHead(micFrames);
  expect(micFrames.every((frame) => Math.max(...frame.articulation) < .01)).toBe(true);
  expect(micAfter.signature).not.toBe(micBefore.signature);
  expect(micAfter.changed).toBeGreaterThan(100); expect(micAfter.deltaRms).toBeGreaterThan(.00001);
  expectWholeFaceDeformation(micAfter);
  expectCoherentInteriorMotion(micAfter);
  await captureHologram(page, testInfo.outputPath("test-rotation-paused-by-microphone.png"));
  await page.evaluate(() => (window as unknown as SpeechWindow).__voiceTest.setVolume(0));
  await expect.poll(async () => (await testHologramSignal(page)).headUniforms.speechEnergy[0]).toBeLessThan(.02);
  const afterMic = await headMotionWindow(page, 2300);
  expectSmoothIdleRotation(afterMic);

  expect(wire).toBeDefined();
  for (let index = 0; index < 12; index++) wire!.send(JSON.stringify({ type: "audio", data: pcm(500, 1), sample_rate: 24000, turn_id: "rotation-pause" }));
  await speakingMouth(page, 1, .7);
  const outputBefore = await particleDisplacement(page), outputFrames = await headMotionWindow(page), outputAfter = await particleDisplacement(page);
  expectFrozenHead(outputFrames);
  expect(outputFrames.every((frame) => frame.articulation[1] > .6)).toBe(true);
  expect((await playback(page)).playing).toBeGreaterThan(0);
  expect(outputAfter.signature).not.toBe(outputBefore.signature);
  expect(outputAfter.changed).toBeGreaterThan(100); expect(outputAfter.deltaRms).toBeGreaterThan(.00001);
  expectWholeFaceDeformation(outputAfter);
  expectCoherentInteriorMotion(outputAfter);
  for (const sample of [micBefore, micAfter, outputBefore, outputAfter]) expectParticlesInsideBoundary(sample);
  await captureHologram(page, testInfo.outputPath("test-rotation-paused-by-audible-speech.png"));
  wire!.send(JSON.stringify({ type: "input_started" }));
  await expect.poll(async () => (await playback(page)).playing).toBe(0);
  const afterOutput = await headMotionWindow(page, 2300);
  expectSmoothIdleRotation(afterOutput);
  const beforePackets = capturePackets;
  await expect.poll(() => capturePackets).toBeGreaterThan(beforePackets + 2);
  await testInfo.attach("actual-rotation-and-deformation-during-speech", { contentType: "application/json", body: JSON.stringify({
    idle, idleBefore, idleAfter, silentMic, micFrames, micBefore, micAfter, afterMic, outputFrames, outputBefore, outputAfter, afterOutput,
  }) });
  await page.getByRole("button", { name: "End voice conversation", exact: true }).click();
  expect((await testHologramSignal(page)).errors).toEqual([]);
  expect((await testHologramSignal(page)).headNonPointDraws).toBe(0);
});
