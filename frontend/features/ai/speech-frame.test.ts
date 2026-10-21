import { expect, it } from "vitest";
import { neutralSpeechFrame, speechTargets } from "./speech-frame";

function sound(bins: number[]) {
  const wave = new Float32Array(1024), spectrum = new Float32Array(512).fill(-Infinity);
  const amplitude = .08 * Math.sqrt(2 / bins.length);
  for (const bin of bins) {
    spectrum[bin] = 20 * Math.log10(amplitude);
    for (let index = 0; index < wave.length; index++) wave[index] += amplitude * Math.sin(2 * Math.PI * bin * index / wave.length);
  }
  const frame = neutralSpeechFrame(); speechTargets(wave, spectrum, 48000, frame);
  return frame;
}

it("distinguishes rounded, wide and open vowel-band sounds at the same audible energy", () => {
  const rounded = sound([8, 16]), wide = sound([8, 52]), open = sound([24, 32]);
  expect(rounded.energy).toBeCloseTo(wide.energy, 5); expect(wide.energy).toBeCloseTo(open.energy, 5);
  expect(rounded.round).toBeGreaterThan(wide.round + .3);
  expect(wide.wide).toBeGreaterThan(rounded.wide + .3);
  expect(open.jaw).toBeGreaterThan(rounded.jaw + .15);
});

it("uses high-frequency energy and crossings for consonant shaping instead of opening on every sound", () => {
  const vowel = sound([8, 16]), frication = sound([92, 115, 139]);
  expect(vowel.energy).toBeCloseTo(frication.energy, 5);
  expect(frication.fricative).toBeGreaterThan(.8);
  expect(frication.voiced).toBeLessThan(vowel.voiced);
  expect(frication.jaw).toBeLessThan(vowel.jaw);
  expect(frication.closure).toBeGreaterThan(vowel.closure);
});

it("closes on actual silence even when the FFT still contains a previous vowel", () => {
  const frame = neutralSpeechFrame();
  const spectrum = new Float32Array(512).fill(-Infinity); spectrum[8] = -10;
  speechTargets(new Float32Array(1024), spectrum, 48000, frame);
  expect(frame).toEqual(neutralSpeechFrame());
});
