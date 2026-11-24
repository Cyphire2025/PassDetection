import { afterEach, expect, it, vi } from "vitest";
import { pcmBase64 } from "./native-audio";
import { NativePlayback } from "./native-playback";

afterEach(() => { vi.useRealTimers(); });

function audioClock() {
  vi.useFakeTimers(); vi.setSystemTime(0);
  let state = "running", anchor = 0, held = 0;
  const now = () => held + (state === "running" ? (Date.now() - anchor) / 1000 : 0);
  const active = new Set<Source>();
  const played: Float32Array[] = [];
  const started: { at: number; duration: number }[] = [];
  const sources: Source[] = [];
  let peakSources = 0;
  const startFailure = { enabled: false };
  class Source {
    buffer!: AudioBuffer;
    onended: (() => void) | null = null;
    disconnect = vi.fn(); connect = vi.fn();
    private timer: ReturnType<typeof setTimeout> | null = null;
    start(at: number) {
      if (startFailure.enabled) throw new Error("Synthetic browser scheduling failure");
      active.add(this); peakSources = Math.max(peakSources, active.size);
      started.push({ at, duration: this.buffer.duration });
      const finish = () => {
        const remaining = at + this.buffer.duration - now();
        if (remaining > .000001) { this.timer = setTimeout(finish, Math.max(1, remaining * 1000)); return; }
        played.push(this.buffer.getChannelData(0)); active.delete(this); this.onended?.();
      };
      this.timer = setTimeout(finish, Math.max(0, (at + this.buffer.duration - now()) * 1000));
    }
    stop = vi.fn(() => { if (this.timer !== null) clearTimeout(this.timer); active.delete(this); this.onended?.(); });
  }
  const gain = { gain: { cancelScheduledValues: vi.fn(), setTargetAtTime: vi.fn() }, connect: vi.fn(), disconnect: vi.fn() };
  const analyser = { fftSize: 0, connect: vi.fn(), disconnect: vi.fn() };
  const context = {
    get currentTime() { return now(); }, get state() { return state; }, destination: {},
    createGain: () => gain, createAnalyser: () => analyser,
    createBuffer: (_channels: number, length: number, rate: number) => {
      const data = new Float32Array(length);
      return { duration: length / rate, getChannelData: () => data };
    },
    createBufferSource: () => { const source = new Source(); sources.push(source); return source; },
  } as unknown as AudioContext;
  return { context, played, started, sources, startFailure, peakSources: () => peakSources,
    setState(next: string) { held = now(); anchor = Date.now(); state = next; } };
}

const packet = (length: number, amplitude: number) => pcmBase64(new Int16Array(length).fill(amplitude).buffer);

it("plays a two-minute burst in exact PCM order with a short decoded window and bounded source count", async () => {
  const clock = audioClock(), speaking = vi.fn(), errors = vi.fn();
  const playback = new NativePlayback(clock.context, speaking, errors);
  for (let second = 0; second < 120; second++) playback.push(packet(24000, second % 2 ? -12000 - second : 12000 + second), 24000);
  expect(clock.started.length).toBeLessThanOrEqual(8);
  expect(clock.started.reduce((sum, source) => sum + source.duration, 0)).toBeLessThanOrEqual(1);
  await vi.advanceTimersByTimeAsync(121000);
  let position = 0, exact = true;
  for (const samples of clock.played) for (const sample of samples) {
    const second = Math.floor(position++ / 24000);
    if (sample !== (second % 2 ? -12000 - second : 12000 + second) / 32768) exact = false;
  }
  expect(position).toBe(120 * 24000); expect(exact).toBe(true);
  expect(clock.peakSources()).toBeLessThanOrEqual(8);
  expect(clock.started.every((source) => source.duration <= .25)).toBe(true);
  expect(errors).not.toHaveBeenCalled(); expect(speaking).toHaveBeenLastCalledWith(false);
  expect(vi.getTimerCount()).toBe(0); playback.dispose();
});

it("coalesces tiny packets while bounding sources and retaining every sample", async () => {
  const clock = audioClock(), playback = new NativePlayback(clock.context, vi.fn());
  const tiny = packet(1, -32768);
  for (let index = 0; index < 12000; index++) playback.push(tiny, 24000);
  expect(clock.started.length).toBeLessThanOrEqual(8);
  await vi.advanceTimersByTimeAsync(1000);
  expect(clock.played.reduce((sum, samples) => sum + samples.length, 0)).toBe(12000);
  expect(clock.played.every((samples) => samples.every((sample) => sample === -1))).toBe(true);
  expect(clock.peakSources()).toBeLessThanOrEqual(8); playback.dispose();
});

it("clears scheduled and pending audio on interruption and cannot replay an old FIFO", async () => {
  const clock = audioClock(), playback = new NativePlayback(clock.context, vi.fn());
  for (let second = 0; second < 60; second++) playback.push(packet(24000, 1000), 24000);
  await vi.advanceTimersByTimeAsync(500);
  playback.clear();
  const priorSamples = clock.played.reduce((sum, samples) => sum + samples.length, 0);
  const priorSources = clock.started.length;
  await vi.advanceTimersByTimeAsync(61000);
  expect(clock.started).toHaveLength(priorSources);
  expect(clock.played.reduce((sum, samples) => sum + samples.length, 0)).toBe(priorSamples);
  playback.push(packet(2400, -1000), 24000);
  await vi.advanceTimersByTimeAsync(500);
  expect(clock.played.at(-1)?.every((sample) => sample === -1000 / 32768)).toBe(true);
  expect(clock.played.reduce((sum, samples) => sum + samples.length, 0)).toBe(priorSamples + 2400);
  playback.dispose(); expect(vi.getTimerCount()).toBe(0);
});

it("retains paused PCM, reports prolonged suspension once, then resumes without losing audio", async () => {
  const clock = audioClock(), errors = vi.fn(), playback = new NativePlayback(clock.context, vi.fn(), errors);
  clock.setState("suspended"); playback.push(packet(24000, 1200), 24000);
  await vi.advanceTimersByTimeAsync(5000);
  expect(clock.started).toHaveLength(0); expect(errors).toHaveBeenCalledOnce();
  expect(errors).toHaveBeenCalledWith(expect.stringContaining("Browser audio is paused"));
  clock.setState("running"); await vi.advanceTimersByTimeAsync(1500);
  expect(clock.played.reduce((sum, samples) => sum + samples.length, 0)).toBe(24000);
  playback.dispose();
});

it.each(["closed", "start-failure"])("reports %s as a playback-only failure and releases scheduled nodes", async (failure) => {
  const clock = audioClock(), errors = vi.fn(), playback = new NativePlayback(clock.context, vi.fn(), errors);
  if (failure === "closed") clock.setState("closed"); else clock.startFailure.enabled = true;
  playback.push(packet(24000, 1200), 24000);
  expect(errors).toHaveBeenCalledExactlyOnceWith("Voice playback stopped. The full reply will continue in captions.");
  expect(clock.sources.every((source) => source.disconnect.mock.calls.length > 0)).toBe(true);
  expect(vi.getTimerCount()).toBe(0); playback.dispose();
});

it("enforces a compact PCM memory cap without discarding previously accepted speech", async () => {
  const clock = audioClock(), playback = new NativePlayback(clock.context, vi.fn());
  clock.setState("suspended");
  const chunk = packet(96000, 1200);
  let accepted = 0;
  while (accepted + 192000 <= 32 * 1024 * 1024) { playback.push(chunk, 24000); accepted += 192000; }
  expect(() => playback.push(chunk, 24000)).toThrow("full reply will continue in captions");
  clock.setState("running"); await vi.advanceTimersByTimeAsync(1200);
  expect(clock.played.reduce((sum, samples) => sum + samples.length, 0)).toBeGreaterThan(24000);
  playback.clear(); expect(vi.getTimerCount()).toBe(0); playback.dispose();
});
