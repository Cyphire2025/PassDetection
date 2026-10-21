/** Audio-derived articulation weights, not provider-supplied phoneme timings. */
export type SpeechFrame = {
  time: number;
  active: boolean;
  energy: number;
  jaw: number;
  round: number;
  wide: number;
  closure: number;
  fricative: number;
  voiced: number;
};

export const neutralSpeechFrame = (): SpeechFrame => ({
  time: 0, active: false, energy: 0, jaw: 0, round: 0, wide: 0, closure: 1, fricative: 0, voiced: 0,
});

const unit = (value: number) => Math.max(0, Math.min(1, value));

/** Bounded acoustic estimates: vowel-band balance and frication distinguish equal-volume sounds. */
export function speechTargets(wave: Float32Array, spectrum: Float32Array, sampleRate: number, target: SpeechFrame): void {
  let energy = 0, crossings = 0;
  for (let index = 0; index < wave.length; index++) {
    energy += wave[index] ** 2;
    if (index && (wave[index] >= 0) !== (wave[index - 1] >= 0)) crossings++;
  }
  const rms = Math.sqrt(energy / Math.max(1, wave.length));
  target.energy = unit(rms * 6); target.active = rms > .003;
  if (!target.active) {
    target.jaw = target.round = target.wide = target.fricative = target.voiced = 0; target.closure = 1;
    return;
  }
  let low = 0, mid = 0, front = 0, hiss = 0;
  const spacing = sampleRate / (spectrum.length * 2);
  for (let bin = Math.ceil(200 / spacing); bin < spectrum.length && bin * spacing < 8000; bin++) {
    const power = Number.isFinite(spectrum[bin]) ? 10 ** (spectrum[bin] / 10) : 0;
    const frequency = bin * spacing;
    if (frequency < 900) low += power;
    else if (frequency < 2000) mid += power;
    else if (frequency < 3500) front += power;
    else hiss += power;
  }
  const total = low + mid + front + hiss || 1;
  low /= total; mid /= total; front /= total; hiss /= total;
  const gate = unit((rms - .002) * 70);
  const noise = unit((crossings / Math.max(1, wave.length) - .08) * 5);
  target.fricative = gate * unit(hiss * 2.2 + noise * .35);
  target.voiced = gate * (1 - target.fricative) * (1 - noise * .65);
  target.round = gate * unit(low * 1.2 - front * .8 - mid * .25) * (1 - target.fricative);
  target.wide = gate * unit(front * 1.6 + mid * .3 - low * .25) * (1 - target.round * .65);
  target.jaw = Math.sqrt(target.energy) * (.25 + mid * .65 + low * .2) * (1 - target.fricative * .55);
  target.closure = unit(1 - gate + target.fricative * .25);
}
