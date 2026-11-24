import { afterEach, expect, it, vi } from "vitest";
import { capturePcm, NativePlayback, pcmBase64 } from "./native-audio";

afterEach(() => { vi.useRealTimers(); });

it("falls back after a stalled worklet load and still resamples audible input into PCM", async () => {
  vi.useFakeTimers();
  const source = { connect: vi.fn(), disconnect: vi.fn() };
  const gain = { gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() };
  const processor = { onaudioprocess: null as ((event: AudioProcessingEvent) => void) | null, connect: vi.fn(), disconnect: vi.fn() };
  const context = {
    sampleRate: 48000, destination: {},
    createMediaStreamSource: () => source, createGain: () => gain,
    audioWorklet: { addModule: () => new Promise<void>(() => undefined) },
    createScriptProcessor: () => processor,
  } as unknown as AudioContext;
  const send = vi.fn();
  const pending = capturePcm(context, {} as MediaStream, send);
  await vi.advanceTimersByTimeAsync(1501);
  const release = await pending;
  expect(gain.gain.value).toBe(0);
  const samples = new Float32Array(4800).fill(.25);
  processor.onaudioprocess!({ inputBuffer: { getChannelData: () => samples } } as unknown as AudioProcessingEvent);
  expect(send).toHaveBeenCalledOnce();
  const output = new Int16Array(send.mock.calls[0][0]);
  expect(output).toHaveLength(1600);
  expect(output.every((sample) => sample === 8192)).toBe(true);
  release();
  expect(processor.onaudioprocess).toBeNull();
  expect(source.disconnect).toHaveBeenCalledOnce();
  expect(processor.disconnect).toHaveBeenCalledOnce();
  expect(gain.disconnect).toHaveBeenCalledOnce();
});

it("schedules continuous quiet output without hiding listening behind a false speaking state", () => {
  const sources: Array<{
    buffer: AudioBuffer | null; connect: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn>;
    start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn>; onended: (() => void) | null;
  }> = [];
  const gain = { gain: { cancelScheduledValues: vi.fn(), setTargetAtTime: vi.fn() }, connect: vi.fn(), disconnect: vi.fn() };
  const analyser = { fftSize: 0, connect: vi.fn(), disconnect: vi.fn() };
  const context = {
    currentTime: 0, state: "running", destination: {}, createGain: () => gain, createAnalyser: () => analyser,
    createBuffer: (_channels: number, length: number, rate: number) => ({ duration: length / rate, getChannelData: () => new Float32Array(length) }),
    createBufferSource: () => {
      const source = { buffer: null, connect: vi.fn(), disconnect: vi.fn(), start: vi.fn(), stop: vi.fn(), onended: null };
      sources.push(source); return source;
    },
  } as unknown as AudioContext;
  const speaking = vi.fn(), playback = new NativePlayback(context, speaking);
  const packet = (amplitude: number) => pcmBase64(new Int16Array(2400).fill(amplitude).buffer);
  for (let index = 0; index < 3; index++) playback.push(packet(45), 24000);
  expect(speaking).not.toHaveBeenCalled();
  expect(sources).toHaveLength(3);
  sources.forEach((source, index) => expect(source.start.mock.calls[0][0]).toBeCloseTo(.025 + index * .1));

  playback.push(packet(1200), 24000);
  playback.push(packet(45), 24000);
  expect(speaking.mock.calls).toEqual([[true]]);
  sources[0].onended!();
  expect(speaking.mock.calls).toEqual([[true]]);
  sources[3].onended!();
  expect(speaking.mock.calls).toEqual([[true], [false]]);
  expect(sources[4].stop).not.toHaveBeenCalled(); // Trailing quiet audio is still scheduled normally.
  playback.push(packet(2400), 24000);
  playback.clear();
  expect(speaking.mock.calls).toEqual([[true], [false], [true], [false]]);
  sources[5].onended!();
  expect(speaking.mock.calls).toEqual([[true], [false], [true], [false]]);
  playback.dispose();
});
