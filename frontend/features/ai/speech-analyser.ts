import type { RefObject } from "react";
import { neutralSpeechFrame, speechTargets, type SpeechFrame } from "./speech-frame";

const CHANNELS = ["energy", "jaw", "round", "wide", "closure", "fricative", "voiced"] as const;

/** One reusable FFT/window plus a fixed playback-clock history; no per-frame React updates. */
export class SpeechAnalyser {
  private wave: Float32Array<ArrayBuffer>;
  private spectrum: Float32Array<ArrayBuffer>;
  private target = neutralSpeechFrame();
  private filtered = neutralSpeechFrame();
  private neutral = neutralSpeechFrame();
  private history = Array.from({ length: 64 }, neutralSpeechFrame);
  private cursor = 0;
  private count = 0;
  private lastTime = -1;
  private lastSound = -1;
  constructor(private context: AudioContext, private analyser: AnalyserNode, private output: RefObject<SpeechFrame>) {
    analyser.fftSize = 1024; analyser.smoothingTimeConstant = .2;
    this.wave = new Float32Array(analyser.fftSize);
    this.spectrum = new Float32Array(analyser.frequencyBinCount);
  }
  sample() {
    if (this.context.state !== "running") { this.reset(); return; }
    const time = this.context.currentTime;
    if (time <= this.lastTime) return;
    this.analyser.getFloatTimeDomainData(this.wave); this.analyser.getFloatFrequencyData(this.spectrum);
    speechTargets(this.wave, this.spectrum, this.context.sampleRate, this.target);
    const elapsed = this.lastTime < 0 ? 1 / 60 : Math.min(.05, time - this.lastTime);
    this.lastTime = time;
    if (this.target.active) this.lastSound = time;
    for (const key of CHANNELS) {
      const response = key === "closure" ? .018 : this.target[key] > this.filtered[key] ? .025 : .055;
      this.filtered[key] += (this.target[key] - this.filtered[key]) * (1 - Math.exp(-elapsed / response));
    }
    this.filtered.time = time;
    this.filtered.active = this.filtered.energy > .01 && time - this.lastSound < .08;
    Object.assign(this.history[this.cursor], this.filtered);
    this.cursor = (this.cursor + 1) % this.history.length; this.count = Math.min(this.history.length, this.count + 1);
    const audibleTime = this.outputTime(time);
    let selected: SpeechFrame | undefined;
    for (let index = 0; index < this.count; index++) {
      const frame = this.history[index];
      if (frame.time <= audibleTime && (!selected || frame.time > selected.time)) selected = frame;
    }
    Object.assign(this.output.current, selected ?? this.neutral);
  }
  private outputTime(currentTime: number) {
    const timestamp = this.context.getOutputTimestamp?.();
    if (timestamp && Number.isFinite(timestamp.contextTime) && Number.isFinite(timestamp.performanceTime) && timestamp.performanceTime! > 0) {
      const estimate = timestamp.contextTime! + Math.max(0, performance.now() - timestamp.performanceTime!) / 1000;
      return Math.min(currentTime, estimate);
    }
    const latency = (this.context.outputLatency || 0) + (this.context.baseLatency || 0);
    return Math.max(0, currentTime - Math.min(.5, latency));
  }
  reset() {
    Object.assign(this.output.current, this.neutral); Object.assign(this.filtered, this.neutral);
    this.count = this.cursor = 0; this.lastTime = this.lastSound = -1;
  }
}
