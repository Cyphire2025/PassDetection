import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useVoiceInput } from "./use-voice-input";

let amplitude = 0;
let nextFrame: FrameRequestCallback | undefined;
const track = { stop: vi.fn(), onended: null as (() => void) | null };
const stream = { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream;
const getUserMedia = vi.fn<() => Promise<MediaStream>>();
const close = vi.fn(async () => undefined);
const source = { connect: vi.fn(), disconnect: vi.fn() };
const analyser = {
  fftSize: 1024, disconnect: vi.fn(),
  getFloatTimeDomainData: (samples: Float32Array) => samples.fill(amplitude),
};

class TestAudioContext {
  state = "running";
  resume = async () => undefined;
  close = close;
  createAnalyser = () => analyser;
  createMediaStreamSource = () => source;
}

beforeEach(() => {
  amplitude = 0;
  nextFrame = undefined;
  track.onended = null;
  vi.clearAllMocks();
  vi.spyOn(performance, "now").mockReturnValue(0);
  vi.stubGlobal("AudioContext", TestAudioContext);
  vi.stubGlobal("isSecureContext", true);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, get: () => ({ getUserMedia }) });
  getUserMedia.mockResolvedValue(stream);
  vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => { nextFrame = callback; return 123; }));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("local voice input", () => {
  it("waits for a click, measures volume without speakers, and releases all resources on stop", async () => {
    const hook = renderHook(useVoiceInput);
    expect(getUserMedia).not.toHaveBeenCalled();
    amplitude = 0.12;
    await act(() => hook.result.current.start());
    expect(hook.result.current.status).toBe("listening");
    expect(hook.result.current.levelRef.current).toBeGreaterThan(0.1);
    expect(source.connect).toHaveBeenCalledExactlyOnceWith(analyser);
    act(() => hook.result.current.stop());
    expect(hook.result.current.status).toBe("idle");
    expect(hook.result.current.levelRef.current).toBe(0);
    expect(track.stop).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
    expect(source.disconnect).toHaveBeenCalledOnce();
    expect(cancelAnimationFrame).toHaveBeenCalledWith(123);
  });

  it("gates quiet background noise and responds when speech gets louder", async () => {
    const hook = renderHook(useVoiceInput);
    amplitude = 0.004;
    await act(() => hook.result.current.start());
    expect(hook.result.current.levelRef.current).toBe(0);
    amplitude = 0.15;
    act(() => nextFrame?.(16));
    expect(hook.result.current.levelRef.current).toBeGreaterThan(0.3);
    amplitude = 0;
    act(() => { for (let index = 0; index < 90; index += 1) nextFrame?.(index * 16); });
    expect(hook.result.current.levelRef.current).toBeLessThan(0.001);
  });

  it("keeps the same speech and silence envelope at 60fps, 2fps, and irregular frame intervals", async () => {
    const observations: Array<{ speaking: number; silent: number }> = [];
    const schedules = [Array.from({ length: 60 }, (_, index) => (index + 1) * 1000 / 60), [500, 1000], [70, 210, 930, 1000]];
    for (const frames of schedules) {
      amplitude = .15;
      const hook = renderHook(useVoiceInput);
      await act(() => hook.result.current.start());
      act(() => { for (const time of frames) nextFrame?.(time); });
      const speaking = hook.result.current.levelRef.current;
      amplitude = 0;
      act(() => { for (const time of frames) nextFrame?.(1000 + time); });
      observations.push({ speaking, silent: hook.result.current.levelRef.current });
      hook.unmount();
    }
    for (const observation of observations) {
      expect(observation.speaking).toBeGreaterThan(.99);
      expect(observation.silent).toBeLessThan(.002);
      expect(observation.speaking).toBeCloseTo(observations[0].speaking, 8);
      expect(observation.silent).toBeCloseTo(observations[0].silent, 8);
    }
  });

  it("clears stale microphone energy on the first frame after a long rendering stall", async () => {
    amplitude = .15;
    const hook = renderHook(useVoiceInput);
    await act(() => hook.result.current.start());
    act(() => nextFrame?.(100));
    expect(hook.result.current.levelRef.current).toBeGreaterThan(.9);
    amplitude = 0;
    act(() => nextFrame?.(10100));
    expect(hook.result.current.levelRef.current).toBeLessThan(.000001);
  });

  it("allows retry after permission denial", async () => {
    getUserMedia.mockRejectedValueOnce(new DOMException("Denied", "NotAllowedError"));
    const hook = renderHook(useVoiceInput);
    await act(() => hook.result.current.start());
    expect(hook.result.current.status).toBe("error");
    expect(hook.result.current.error).toMatch(/access is blocked/);
    expect(close).toHaveBeenCalledOnce();
    await act(() => hook.result.current.start());
    expect(hook.result.current.status).toBe("listening");
    expect(hook.result.current.error).toBeNull();
  });

  it("stops a permission result arriving after cancellation", async () => {
    let grant!: (stream: MediaStream) => void;
    getUserMedia.mockReturnValue(new Promise((resolve) => { grant = resolve; }));
    const hook = renderHook(useVoiceInput);
    let pending!: Promise<void>;
    act(() => { pending = hook.result.current.start(); });
    expect(hook.result.current.status).toBe("requesting");
    act(() => hook.result.current.stop());
    await act(async () => { grant(stream); await pending; });
    expect(track.stop).toHaveBeenCalledOnce();
    expect(hook.result.current.status).toBe("idle");
    expect(source.connect).not.toHaveBeenCalled();
  });

  it("releases the microphone on unmount and on hiding the page", async () => {
    const hook = renderHook(useVoiceInput);
    await act(() => hook.result.current.start());
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(track.stop).toHaveBeenCalledOnce();
    expect(hook.result.current.status).toBe("idle");
    await act(() => hook.result.current.start());
    hook.unmount();
    expect(track.stop).toHaveBeenCalledTimes(2);
    expect(close).toHaveBeenCalledTimes(2);
  });

  it("handles a disconnected microphone", async () => {
    const hook = renderHook(useVoiceInput);
    await act(() => hook.result.current.start());
    act(() => track.onended?.());
    expect(hook.result.current.status).toBe("error");
    expect(hook.result.current.error).toMatch(/disconnected/);
    expect(hook.result.current.levelRef.current).toBe(0);
    expect(close).toHaveBeenCalledOnce();
  });

  it("does not ask for a microphone on insecure origins", async () => {
    vi.stubGlobal("isSecureContext", false);
    const hook = renderHook(useVoiceInput);
    await act(() => hook.result.current.start());
    expect(hook.result.current.status).toBe("error");
    expect(hook.result.current.error).toMatch(/HTTPS/);
    expect(getUserMedia).not.toHaveBeenCalled();
  });
});
