import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";
import { assistantAuth } from "./support/assistant-auth";
import { syntheticMicrophone } from "./support/ai-voice-fixtures";

type PlaybackSnapshot = { started: number; active: number; stopped: number; playedSeconds: number };
type VoiceProbe = {
  __longVoicePlayback: () => PlaybackSnapshot;
  __voiceTest: { tracksStopped: () => boolean };
};

async function workspace(page: Page) {
  await assistantAuth(page);
  await syntheticMicrophone(page);
  await page.route("**/api/v1/ai-assistant/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/availability")) return route.fulfill({ json: { enabled: true, allowed: true } });
    if (path.endsWith("/status")) return route.fulfill({ json: {
      configured: true, speech_configured: true, native_voice: true, voice_configured: true,
      provider: "openai", voice_provider: "openai", model: "gpt-realtime-2.1", avatar_appearance: "female",
      account_id: "long-voice-admin", account_scope: "super_admin", can_manage_settings: true,
      settings_revision: 1, access: "read_only",
    } });
    if (path.endsWith("/live")) return route.fulfill({ json: {
      observed_at: new Date().toISOString(), mcp: { connected: true, available_tools: 8, write_enabled: false },
    } });
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
  // Observe actual browser sources and ended events. AudioContext time, source
  // playback, capture and the application's scheduler all run without mocks.
  await page.addInitScript(() => {
    const entries = new Map<AudioBufferSourceNode, { ended: boolean; stopped: boolean; seconds: number }>();
    const originalStart = AudioBufferSourceNode.prototype.start;
    const originalStop = AudioBufferSourceNode.prototype.stop;
    AudioBufferSourceNode.prototype.start = function (...args: Parameters<AudioBufferSourceNode["start"]>) {
      if (this.buffer?.sampleRate === 24000) {
        const entry = { ended: false, stopped: false, seconds: this.buffer.duration };
        entries.set(this, entry);
        this.addEventListener("ended", () => { entry.ended = true; }, { once: true });
      }
      return originalStart.apply(this, args);
    };
    AudioBufferSourceNode.prototype.stop = function (...args: Parameters<AudioBufferSourceNode["stop"]>) {
      const entry = entries.get(this);
      if (entry && !entry.ended) entry.stopped = true;
      return originalStop.apply(this, args);
    };
    Object.defineProperty(window, "__longVoicePlayback", { value: () => {
      const values = [...entries.values()];
      return {
        started: values.length, active: values.filter((entry) => !entry.ended).length,
        stopped: values.filter((entry) => entry.stopped).length,
        playedSeconds: values.filter((entry) => entry.ended && !entry.stopped).reduce((total, entry) => total + entry.seconds, 0),
      };
    } });
  });
}

function audioSecond() {
  const pcm = Buffer.alloc(24000 * 2);
  for (let sample = 0; sample < 24000; sample++) {
    pcm.writeInt16LE(Math.round(Math.sin(sample * 2 * Math.PI * 180 / 24000) * 9000), sample * 2);
  }
  return pcm.toString("base64");
}

const playback = (page: Page) => page.evaluate(() => (window as unknown as VoiceProbe).__longVoicePlayback());

test("a long burst finishes speaking without losing captions or the microphone, and interruption cancels queued audio", async ({ page }) => {
  test.setTimeout(90000);
  await workspace(page);
  let wire: WebSocketRoute | undefined;
  let packets = 0;
  const closes: Array<number | undefined> = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.routeWebSocket("**/api/v1/ai-assistant/voice", (socket) => {
    wire = socket;
    socket.onClose((code) => { closes.push(code); });
    socket.onMessage((raw) => {
      const message = JSON.parse(String(raw));
      if (message.type === "start") socket.send(JSON.stringify({ type: "ready", conversation_id: message.conversation_id, max_session_seconds: 600 }));
      if (message.type === "audio") packets++;
    });
  });
  await page.goto("/ai");
  const main = page.getByRole("main", { name: "Global Connects AI workspace" });
  await page.getByRole("button", { name: "Start microphone", exact: true }).click();
  await expect.poll(() => packets).toBeGreaterThan(1);
  const send = (event: object) => { expect(wire).toBeDefined(); wire!.send(JSON.stringify(event)); };
  const pcm = audioSecond();
  const sendAudio = (turn: string, seconds: number) => {
    for (let index = 0; index < seconds; index++) send({ type: "audio", data: pcm, sample_rate: 24000, turn_id: turn });
  };
  const finishTurn = (id: string, user: string, assistant: string) => send({ type: "turn_complete", turn_id: id,
    turn: { id, user, assistant, created_at: new Date().toISOString(), voice: true, sources: [], images: [] } });

  const answer = "This complete answer includes every part of the long spoken response, including its final sentence.";
  send({ type: "input_transcript", text: "Give me the full detailed answer.", turn_id: "long-reply" });
  send({ type: "text_delta", text: answer.slice(0, 45), turn_id: "long-reply" });
  // A provider may generate forty-five seconds of PCM well ahead of playback.
  // The old twenty-second scheduled-ahead guard disconnected during this burst.
  sendAudio("long-reply", 45);
  send({ type: "text_delta", text: answer.slice(45), turn_id: "long-reply" });
  finishTurn("long-reply", "Give me the full detailed answer.", answer);
  await page.getByRole("button", { name: "Show conversation", exact: true }).click();
  await expect(page.getByText(answer, { exact: true })).toBeVisible();
  await expect(main).toHaveAttribute("data-phase", "speaking");
  await expect(main.getByRole("alert")).not.toBeAttached();
  const captureAtReply = packets;
  await expect.poll(() => packets).toBeGreaterThan(captureAtReply + 5);
  await expect.poll(async () => Math.round((await playback(page)).playedSeconds * 1000), { timeout: 60000, intervals: [250, 1000] }).toBe(45000);
  expect(await playback(page)).toMatchObject({ active: 0, stopped: 0 });
  expect((await playback(page)).playedSeconds).toBeCloseTo(45, 5);
  await expect(main).toHaveAttribute("data-phase", "listening");
  await expect(page.getByRole("button", { name: "End voice conversation", exact: true })).toBeVisible();
  expect(closes).toEqual([]);
  expect(await page.evaluate(() => (window as unknown as VoiceProbe).__voiceTest.tracksStopped())).toBe(false);
  expect(packets).toBeGreaterThan(captureAtReply + 100);

  for (const generationComplete of [true, false]) {
    const turn = generationComplete ? "completed-queued-reply" : "interrupted-reply";
    const caption = generationComplete ? "The provider finished, but this reply is still playing." : "This reply is still being generated.";
    send({ type: "input_transcript", text: "Start another long answer.", turn_id: turn });
    sendAudio(turn, 45);
    send({ type: "text_delta", text: caption, turn_id: turn });
    if (generationComplete) finishTurn(turn, "Start another long answer.", caption);
    await expect(page.getByText(caption, { exact: true })).toBeVisible();
    await expect(main).toHaveAttribute("data-phase", "speaking");
    await expect.poll(async () => (await playback(page)).active).toBeGreaterThan(0);
    const articles = await main.getByRole("article").count();
    // Speech can begin after response.done while the browser still has audio.
    // That transport event must cancel audio without inventing a history turn.
    send(generationComplete ? { type: "input_started" } : { type: "interrupted", turn_id: turn });
    await expect.poll(async () => (await playback(page)).active).toBe(0);
    await expect(main).toHaveAttribute("data-phase", "listening");
    const cancelled = await playback(page);
    expect(cancelled.stopped).toBeGreaterThan(0);
    // Wait past a scheduling horizon: discarded audio must never resume itself.
    await page.waitForTimeout(1200);
    expect((await playback(page)).started).toBe(cancelled.started);
    await expect(main.getByRole("article")).toHaveCount(articles);
    expect(closes).toEqual([]);
  }
  const afterInterruption = await playback(page);

  const resumed = "I heard the interruption and can continue.";
  send({ type: "input_transcript", text: "Continue now.", turn_id: "resumed-reply" });
  sendAudio("resumed-reply", 2);
  send({ type: "text_delta", text: resumed, turn_id: "resumed-reply" });
  finishTurn("resumed-reply", "Continue now.", resumed);
  await expect(page.getByText(resumed, { exact: true })).toBeVisible();
  await expect.poll(async () => Math.round(((await playback(page)).playedSeconds - afterInterruption.playedSeconds) * 1000)).toBe(2000);
  await expect(main).toHaveAttribute("data-phase", "listening");
  await expect(main.getByRole("alert")).not.toBeAttached();
  expect(closes).toEqual([]);
  expect(errors).toEqual([]);
  await page.getByRole("button", { name: "End voice conversation", exact: true }).click();
  await expect(page.getByRole("button", { name: "Start microphone", exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as VoiceProbe).__voiceTest.tracksStopped())).toBe(true);
});
