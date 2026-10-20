import type { Page } from "@playwright/test";

// A synthetic stream exercises the real Web Audio analyser and GPU renderer.
// The browser never opens the computer's physical microphone in these tests.
export async function syntheticMicrophone(page: Page, rightChannelOnly = false) {
  await page.addInitScript((rightOnly: boolean) => {
    const original = window.AudioContext;
    const contexts: AudioContext[] = [];
    const tracks: MediaStreamTrack[] = [];
    let amplitude: GainNode | null = null;
    let worklets = 0;
    const originalWorklet = window.AudioWorkletNode;
    window.AudioWorkletNode = class extends originalWorklet {
      constructor(context: BaseAudioContext, name: string, options?: AudioWorkletNodeOptions) {
        super(context, name, options);
        if (name === "global-connects-pcm") worklets++;
      }
    };
    Object.defineProperty(window, "__voiceTest", { value: {
      setVolume: (value: number) => { if (amplitude) amplitude.gain.value = value; },
      tracksStopped: () => tracks.length > 0 && tracks.every((track) => track.readyState === "ended"),
      workletsCreated: () => worklets,
    } });
    navigator.mediaDevices.getUserMedia = async () => {
      const context = new original();
      contexts.push(context);
      const oscillator = context.createOscillator();
      oscillator.frequency.value = 180;
      amplitude = context.createGain();
      amplitude.gain.value = 0;
      const destination = context.createMediaStreamDestination();
      oscillator.connect(amplitude);
      if (rightOnly) {
        const stereo = context.createChannelMerger(2);
        amplitude.connect(stereo, 0, 1); stereo.connect(destination);
      } else amplitude.connect(destination);
      oscillator.start();
      await context.resume();
      tracks.push(...destination.stream.getTracks());
      return destination.stream;
    };
    window.addEventListener("pagehide", () => { contexts.forEach((context) => void context.close()); });
  }, rightChannelOnly);
}
