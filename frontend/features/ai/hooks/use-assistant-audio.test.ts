import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { neutralSpeechFrame } from "../speech-frame";
import { useAssistantAudio } from "./use-assistant-audio";

const mocks = vi.hoisted(() => ({ speak: vi.fn(), start: vi.fn(), stop: vi.fn(), getStream: vi.fn(), clearError: vi.fn() }));
vi.mock("../api", () => ({ assistantApi: { speak: mocks.speak }, assistantMessage: (_cause: unknown, fallback: string) => fallback }));
vi.mock("./use-voice-input", () => ({ useVoiceInput: () => ({ status: "idle", error: null, levelRef: { current: 0 }, start: mocks.start, stop: mocks.stop, getStream: mocks.getStream, clearError: mocks.clearError }) }));

class PlaybackContext {
  static latest: PlaybackContext;
  state = "running"; currentTime = 0; sampleRate = 48000; destination = {}; playing = false;
  resume = vi.fn().mockResolvedValue(undefined); close = vi.fn().mockResolvedValue(undefined);
  decodeAudioData = vi.fn().mockResolvedValue({ duration: 1 });
  source = { buffer: null, connect: vi.fn(), disconnect: vi.fn(), onended: null as (() => void) | null,
    start: () => { this.playing = true; }, stop: vi.fn(() => { this.playing = false; }) };
  constructor() { PlaybackContext.latest = this; }
  createBufferSource() { return this.source; }
  createAnalyser() {
    return { fftSize: 512, frequencyBinCount: 512, smoothingTimeConstant: 0, connect: vi.fn(), disconnect: vi.fn(),
      getFloatTimeDomainData: (samples: Float32Array) => samples.fill(this.playing ? .08 : 0),
      getFloatFrequencyData: (samples: Float32Array) => { samples.fill(-Infinity); samples[8] = -15; } };
  }
}

let frame: FrameRequestCallback | null = null;
beforeEach(() => {
  vi.clearAllMocks(); mocks.speak.mockReset(); frame = null;
  vi.stubGlobal("AudioContext", PlaybackContext);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frame = callback; return 1; });
  vi.stubGlobal("cancelAnimationFrame", () => { frame = null; });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each(["cancel", "complete"])("read-aloud follows audible playback through delayed loading and %s", async (ending) => {
  let deliver!: (blob: Blob) => void;
  mocks.speak.mockReturnValue(new Promise<Blob>((resolve) => { deliver = resolve; }));
  const { result } = renderHook(() => useAssistantAudio(vi.fn()));
  const stableFrame = result.current.speechFrame.current;
  let finished!: Promise<void>;
  act(() => { finished = result.current.speak("This text is available before its spoken audio."); });
  expect(result.current.preparing).toBe(true);
  expect(result.current.speechFrame.current).toEqual(neutralSpeechFrame());
  expect(frame).toBeNull(); // Text arrival and TTS loading do not articulate the mouth.
  await act(async () => { deliver({ arrayBuffer: async () => new ArrayBuffer(2) } as Blob); });
  expect(result.current.speaking).toBe(true);
  const context = PlaybackContext.latest;
  act(() => { context.currentTime = .05; frame?.(50); });
  expect(result.current.speechFrame.current.active).toBe(true);
  expect(result.current.speechFrame.current.round).toBeGreaterThan(.8);
  expect(result.current.speechFrame.current.jaw).toBeGreaterThan(.2);
  expect(result.current.speechFrame.current).toBe(stableFrame);
  await act(async () => {
    if (ending === "cancel") result.current.stopPlayback();
    else { context.playing = false; context.source.onended?.(); }
    await finished;
  });
  expect(result.current.speechFrame.current).toEqual(neutralSpeechFrame());
  expect(result.current.playbackLevel.current).toBe(0); expect(result.current.speaking).toBe(false);
  expect(frame).toBeNull(); expect(result.current.error).toBeFalsy();
});
