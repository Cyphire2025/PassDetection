import { afterEach, expect, it, vi } from "vitest";
import { SpeechAnalyser } from "./speech-analyser";
import { neutralSpeechFrame } from "./speech-frame";

afterEach(() => vi.restoreAllMocks());

function setup() {
  vi.spyOn(performance, "now").mockReturnValue(1000);
  const clock = { currentTime: 0, audible: -.1, state: "running", bin: 8, amplitude: .08 };
  const analyser = {
    fftSize: 0, smoothingTimeConstant: 0, frequencyBinCount: 512,
    getFloatTimeDomainData: vi.fn((samples: Float32Array) => samples.fill(clock.amplitude)),
    getFloatFrequencyData: (samples: Float32Array) => { samples.fill(-Infinity); samples[clock.bin] = -15; },
  };
  const context = { get currentTime() { return clock.currentTime; }, get state() { return clock.state; }, sampleRate: 48000,
    getOutputTimestamp: () => ({ contextTime: clock.audible, performanceTime: 1000 }) } as AudioContext;
  const ref = { current: neutralSpeechFrame() };
  const speech = new SpeechAnalyser(context, analyser as unknown as AnalyserNode, ref);
  const sample = (time: number, audible = time - .1) => { clock.currentTime = time; clock.audible = audible; speech.sample(); };
  return { clock, analyser, ref, speech, sample };
}

it("selects articulation by audible output time rather than the newest decoded audio", () => {
  const { clock, sample, ref } = setup();
  const stableFrame = ref.current;
  sample(0); sample(.04); sample(.08);
  expect(ref.current.active).toBe(false); expect(ref.current.jaw).toBe(0);
  for (let index = 3; index <= 7; index++) sample(index * .04);
  expect(ref.current.active).toBe(true); expect(ref.current.round).toBeGreaterThan(.9);
  clock.bin = 52;
  sample(.32, .20); sample(.36, .24);
  expect(ref.current.round).toBeGreaterThan(.9); expect(ref.current.wide).toBe(0);
  sample(.40); sample(.44); sample(.48);
  expect(ref.current.wide).toBeGreaterThan(.8); expect(ref.current.round).toBeLessThan(.4);
  expect(ref.current).toBe(stableFrame);
});

it("does not advance smoothing on a stopped playback clock and neutralizes pause and cancellation", () => {
  const { clock, sample, speech, ref, analyser } = setup();
  sample(1, 1);
  const jaw = ref.current.jaw;
  speech.sample(); speech.sample();
  expect(ref.current.jaw).toBe(jaw); expect(analyser.getFloatTimeDomainData).toHaveBeenCalledOnce();
  clock.state = "suspended"; speech.sample();
  expect(ref.current).toEqual(neutralSpeechFrame());
  clock.state = "running"; sample(2, 2);
  expect(ref.current.active).toBe(true);
  speech.reset(); expect(ref.current).toEqual(neutralSpeechFrame());
  sample(3, 2.8);
  expect(ref.current).toEqual(neutralSpeechFrame()); // Old history cannot leak into a replacement reply.
});

it("settles the mouth between syllables while retaining a fixed output object across a long stream", () => {
  const { clock, sample, ref } = setup();
  const stableFrame = ref.current;
  for (let index = 0; index < 600; index++) sample(index / 60);
  expect(ref.current.active).toBe(true);
  clock.amplitude = 0;
  for (let index = 600; index < 630; index++) sample(index / 60);
  expect(ref.current.active).toBe(false); expect(ref.current.jaw).toBeLessThan(.001);
  expect(ref.current.closure).toBeGreaterThan(.999); expect(ref.current).toBe(stableFrame);
});
