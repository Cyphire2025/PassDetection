import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { startNativeCapture } from "./native-capture";
import { capturePcm } from "./native-audio";

vi.mock("./native-audio", () => ({ capturePcm: vi.fn() }));

class Audio extends EventTarget {
  state = "running";
  resume = vi.fn(async () => { this.state = "running"; });
}
class Track extends EventTarget { muted = false; }
let audio: Audio, track: Track, stream: MediaStream;
let frame: (buffer: ArrayBuffer) => void;
let release: () => void;
const pcm = (amplitude = 0) => new Int16Array(1600).fill(amplitude).buffer;
const callbacks = () => ({
  send: vi.fn(), accepting: vi.fn(() => true), onReady: vi.fn(),
  onError: vi.fn(), onInput: vi.fn(),
});
const starts: ReturnType<typeof startNativeCapture>[] = [];
function start(events = callbacks()) {
  const capture = startNativeCapture(audio as unknown as AudioContext, stream, events);
  starts.push(capture); return { capture, events };
}

beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks(); audio = new Audio(); track = new Track(); release = vi.fn();
  stream = { getAudioTracks: () => [track] } as unknown as MediaStream;
  vi.mocked(capturePcm).mockImplementation(async (_context, _stream, send) => { frame = send; return release; });
});
afterEach(() => { starts.splice(0).forEach((capture) => capture.stop()); vi.restoreAllMocks(); vi.useRealTimers(); });

describe("native microphone readiness", () => {
  it("retains speech spoken while connecting and requires both a frame and provider readiness", async () => {
    const { capture, events } = start();
    await vi.advanceTimersByTimeAsync(1);
    const first = pcm(1200), second = pcm(2400);
    frame(first); frame(second);
    expect(events.send).not.toHaveBeenCalled();
    expect(events.onReady).not.toHaveBeenCalled();
    expect(events.onInput).toHaveBeenCalledWith(true, "");
    capture.connect();
    expect(events.send.mock.calls.map(([buffer]) => buffer)).toEqual([first, second]);
    expect(events.onReady).toHaveBeenCalledOnce();
  });

  it("does not report listening just because the server sent ready", async () => {
    const { capture, events } = start(); capture.connect();
    await vi.advanceTimersByTimeAsync(1);
    expect(events.onReady).not.toHaveBeenCalled();
    frame(pcm());
    expect(events.onReady).toHaveBeenCalledOnce();
    expect(events.onInput).not.toHaveBeenCalledWith(true, "");
  });

  it("flushes five seconds of setup audio in order within the server's authorized-session rate window", async () => {
    const events = callbacks(), sent: ArrayBuffer[] = [];
    const authorizedAt = performance.now();
    let bytes = 0;
    events.send.mockImplementation((buffer: ArrayBuffer) => {
      bytes += buffer.byteLength; sent.push(buffer);
      expect(bytes).toBeLessThanOrEqual(64000 + (performance.now() - authorizedAt) * 40);
    });
    const { capture } = start(events);
    await vi.advanceTimersByTimeAsync(1);
    const expected = Array.from({ length: 50 }, (_, index) => pcm(500 + index));
    for (const buffer of expected) { frame(buffer); await vi.advanceTimersByTimeAsync(100); }
    expect(events.send).not.toHaveBeenCalled();
    capture.connect();
    expect(events.send.mock.calls.length).toBeLessThanOrEqual(3);
    for (let index = 0; index < 20; index++) {
      const buffer = pcm(1500 + index); expected.push(buffer); frame(buffer);
      await vi.advanceTimersByTimeAsync(100);
    }
    expect(sent).toEqual(expected);
    expect(events.onError).not.toHaveBeenCalled();
  });

  it("reports a blocked context instead of silently running a nonfunctional capture", async () => {
    audio.state = "suspended";
    audio.resume.mockImplementation(() => new Promise(() => undefined));
    const { events } = start();
    await vi.advanceTimersByTimeAsync(3001);
    expect(events.onError).toHaveBeenCalledWith(expect.stringContaining("Browser audio is paused"));
    expect(events.onReady).not.toHaveBeenCalled();
    expect(capturePcm).not.toHaveBeenCalled();
  });

  it("reports missing first frames and a stalled capture", async () => {
    const first = start(); first.capture.connect();
    await vi.advanceTimersByTimeAsync(6500);
    expect(first.events.onError).toHaveBeenCalledWith(expect.stringContaining("No microphone audio is reaching"));
    expect(release).toHaveBeenCalledOnce();
    const second = start(); second.capture.connect();
    await vi.advanceTimersByTimeAsync(1); frame(pcm(1200));
    await vi.advanceTimersByTimeAsync(2500);
    expect(second.events.onError).toHaveBeenCalledWith(expect.stringContaining("Microphone audio stopped"));
  });

  it("keeps ordinary silence connected, explains no sound, and clears the hint on real input", async () => {
    const { capture, events } = start(); capture.connect();
    await vi.advanceTimersByTimeAsync(1);
    for (let index = 0; index < 90; index++) { frame(pcm()); await vi.advanceTimersByTimeAsync(100); }
    expect(events.onError).not.toHaveBeenCalled();
    expect(events.onInput).toHaveBeenCalledWith(false, expect.stringContaining("No microphone sound yet"));
    frame(pcm(1500));
    expect(events.onInput).toHaveBeenLastCalledWith(true, "");
    track.muted = true; track.dispatchEvent(new Event("mute"));
    expect(events.onInput).toHaveBeenLastCalledWith(true, expect.stringContaining("microphone is muted"));
    track.muted = false; track.dispatchEvent(new Event("unmute"));
    expect(events.onInput).toHaveBeenLastCalledWith(true, "");
    expect(events.onError).not.toHaveBeenCalled();
  });

  it("stops after interruption and disposes a capture that resolves after cancellation", async () => {
    const { events } = start();
    await vi.advanceTimersByTimeAsync(1);
    audio.state = "suspended"; audio.dispatchEvent(new Event("statechange"));
    expect(events.onError).toHaveBeenCalledWith(expect.stringContaining("Browser audio was interrupted"));
    expect(release).toHaveBeenCalledOnce();
    audio.state = "running";
    let resolve!: (release: () => void) => void;
    vi.mocked(capturePcm).mockImplementation(() => new Promise((done) => { resolve = done; }));
    const next = start();
    await vi.advanceTimersByTimeAsync(1);
    next.capture.stop(); const lateRelease = vi.fn(); resolve(lateRelease);
    await vi.advanceTimersByTimeAsync(1);
    expect(lateRelease).toHaveBeenCalledOnce();
    expect(next.events.onReady).not.toHaveBeenCalled();
  });
});
