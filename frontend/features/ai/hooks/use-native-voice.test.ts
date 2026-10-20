import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useNativeVoice } from "./use-native-voice";

const mocks = vi.hoisted(() => ({ push: vi.fn(), clear: vi.fn(), dispose: vi.fn(), captureStop: vi.fn(), playbackError: (_message: string) => undefined as void }));
vi.mock("../native-audio", () => ({
  pcmBase64: vi.fn(),
  NativePlayback: class {
    analyser = { fftSize: 512, getFloatTimeDomainData: (samples: Float32Array) => samples.fill(0) };
    push = mocks.push; clear = mocks.clear; dispose = mocks.dispose;
    constructor(_context: AudioContext, _speaking: (active: boolean) => void, error: (message: string) => void) { mocks.playbackError = error; }
  },
}));
vi.mock("../native-capture", () => ({ startNativeCapture: (_context: AudioContext, _stream: MediaStream, callbacks: { onReady: () => void }) => ({ connect: callbacks.onReady, stop: mocks.captureStop }) }));

class Socket {
  static OPEN = 1; static CLOSING = 2;
  static latest: Socket;
  readyState = 1;
  onopen = null; onclose = null; onerror = null;
  onmessage: ((event: { data: string }) => void | Promise<void>) | null = null;
  send = vi.fn(); close = vi.fn(); addEventListener = vi.fn();
  constructor() { Socket.latest = this; }
}

beforeEach(() => {
  vi.clearAllMocks(); mocks.push.mockReset();
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("requestAnimationFrame", () => 1); vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.stubGlobal("AudioContext", class { state = "running"; resume = vi.fn().mockResolvedValue(undefined); close = vi.fn().mockResolvedValue(undefined); });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function start() {
  const events = vi.fn(), stopped = vi.fn();
  const hook = renderHook(() => useNativeVoice(events, stopped));
  act(() => hook.result.current.start({} as MediaStream, "conversation"));
  const send = async (event: object) => { await act(async () => { await Socket.latest.onmessage?.({ data: JSON.stringify(event) }); }); };
  await send({ type: "ready", conversation_id: "conversation", max_session_seconds: 600 });
  expect(hook.result.current.active).toBe(true);
  return { ...hook, events, stopped, send };
}

it("keeps capture and complete captions after an audio failure, and accepts same-turn replacement audio", async () => {
  const { result, events, stopped, send } = await start();
  mocks.push.mockImplementationOnce(() => { throw new Error("This reply exceeded the audio buffer limit. The full reply will continue in captions."); });
  const audio = { type: "audio", data: "AA==", sample_rate: 24000, turn_id: "turn" };
  await send(audio); await send(audio);
  expect(mocks.push).toHaveBeenCalledOnce();
  expect(result.current.error).toContain("full reply will continue in captions");
  await send({ type: "text_delta", text: "The complete final sentence.", turn_id: "turn" });
  const complete = { type: "turn_complete", turn_id: "turn", turn: { id: "turn", user: "Question", assistant: "The complete final sentence.", created_at: "2026-10-21T00:00:00Z" } };
  await send(complete);
  expect(events).toHaveBeenCalledWith(complete);
  expect(result.current.active).toBe(true); expect(stopped).not.toHaveBeenCalled();
  expect(Socket.latest.close).not.toHaveBeenCalled(); expect(mocks.captureStop).not.toHaveBeenCalled();
  await send({ type: "answer_reset", turn_id: "turn" });
  await send(audio);
  expect(mocks.push).toHaveBeenCalledTimes(2);
});

it("handles playback scheduler failures and new input without ending capture or inventing caption events", async () => {
  const { result, events, stopped, send } = await start();
  act(() => mocks.playbackError("Voice playback stopped. The full reply will continue in captions."));
  expect(result.current.error).toContain("captions");
  await send({ type: "input_started" });
  expect(mocks.clear).toHaveBeenCalledOnce(); expect(events).not.toHaveBeenCalled();
  expect(result.current.active).toBe(true); expect(stopped).not.toHaveBeenCalled();
  expect(Socket.latest.close).not.toHaveBeenCalled(); expect(mocks.captureStop).not.toHaveBeenCalled();
});
