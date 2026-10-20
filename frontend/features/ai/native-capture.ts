import { requireRunningAudio } from "./audio-readiness";
import { capturePcm } from "./native-audio";

type CaptureCallbacks = {
  send: (buffer: ArrayBuffer) => void;
  accepting: () => boolean;
  onReady: () => void;
  onError: (message: string) => void;
  onInput: (detected: boolean, hint: string) => void;
};

/** Capture immediately, retaining the first utterance while the provider connects. */
export function startNativeCapture(context: AudioContext, stream: MediaStream, callbacks: CaptureCallbacks) {
  let stopped = false, connected = false, announced = false, heard = false;
  let lastFrame: number | null = null;
  let release: (() => void) | undefined;
  let lastHint = "";
  const started = performance.now();
  const pending: ArrayBuffer[] = [];
  const tracks = stream.getAudioTracks();
  const stop = () => {
    if (stopped) return;
    stopped = true; clearInterval(pump); clearInterval(watch);
    context.removeEventListener("statechange", stateChanged);
    tracks.forEach((track) => { track.removeEventListener("mute", inputChanged); track.removeEventListener("unmute", inputChanged); });
    pending.length = 0; release?.();
  };
  const fail = (message: string) => { if (!stopped) { stop(); callbacks.onError(message); } };
  const inputChanged = () => {
    const hint = tracks.some((track) => track.muted)
      ? "Your microphone is muted. Check your laptop’s mute switch or input device."
      : !heard && performance.now() - started > 8000
        ? "No microphone sound yet. Check your laptop’s input device or mute switch." : "";
    if (hint !== lastHint) { lastHint = hint; callbacks.onInput(heard, hint); }
  };
  const stateChanged = () => {
    if (context.state !== "running") fail("Browser audio was interrupted. Tap the microphone again to reconnect.");
  };
  const announce = () => {
    if (connected && lastFrame !== null && !announced && !stopped) { announced = true; callbacks.onReady(); }
  };
  const flush = () => {
    if (stopped || !connected) return;
    if (!callbacks.accepting()) { pending.length = 0; return; }
    // Catch up without a large synchronous burst into the WebSocket buffer.
    try { for (let count = 0; count < 3 && pending.length; count++) callbacks.send(pending.shift()!); }
    catch (cause) { fail(cause instanceof Error ? cause.message : "Microphone audio could not be sent. Please reconnect."); }
  };
  const pump = setInterval(flush, 20);
  const watch = setInterval(() => {
    if (stopped) return;
    const now = performance.now();
    if (lastFrame === null && now - started > 6000) {
      fail("No microphone audio is reaching the voice connection. Check your input device, then reconnect.");
    } else if (lastFrame !== null && now - lastFrame > 2000) {
      fail("Microphone audio stopped reaching the voice connection. Check your input device, then reconnect.");
    } else inputChanged();
  }, 500);
  void (async () => {
    await requireRunningAudio(context);
    if (stopped) return;
    context.addEventListener("statechange", stateChanged);
    tracks.forEach((track) => { track.addEventListener("mute", inputChanged); track.addEventListener("unmute", inputChanged); });
    inputChanged();
    const dispose = await capturePcm(context, stream, (buffer) => {
      if (stopped) return;
      lastFrame = performance.now();
      if (!heard) {
        const samples = new Int16Array(buffer);
        let energy = 0;
        for (const sample of samples) energy += (sample / 32768) ** 2;
        if (samples.length && Math.sqrt(energy / samples.length) > .003) {
          heard = true; lastHint = ""; callbacks.onInput(true, "");
        }
      }
      announce();
      if (connected && !callbacks.accepting()) return;
      if (pending.length >= 250) { fail("The microphone connection is falling behind. Please reconnect."); return; }
      pending.push(buffer); flush();
    });
    if (stopped) dispose(); else release = dispose;
  })().catch((cause) => fail(cause instanceof Error ? cause.message : "Microphone audio could not start. Please reconnect."));
  return {
    connect() { connected = true; announce(); flush(); },
    stop,
  };
}
