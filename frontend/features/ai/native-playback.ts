const RATE = 24000;
const PAGE_SAMPLES = 6000;
// PCM16 only: about 11.6 minutes, aligned with the server's minimum session budget.
const MAX_QUEUED_BYTES = 32 * 1024 * 1024;
const MAX_SOURCES = 8;
const LOOKAHEAD_SECONDS = 1;

type Page = { samples: Int16Array; length: number; offset: number };

/** Fixed-size pages also bound metadata when a provider sends tiny audio packets. */
class PcmQueue {
  private pages: Page[] = [];
  samples = 0;
  append(encoded: string) {
    if (encoded.length > 300000) throw new Error("The voice audio packet is too large.");
    const raw = atob(encoded);
    if (!raw.length || raw.length % 2) throw new Error("The voice audio packet is invalid.");
    if (this.samples * 2 + raw.length > MAX_QUEUED_BYTES) {
      throw new Error("This reply exceeded the audio buffer limit. The full reply will continue in captions.");
    }
    for (let offset = 0; offset < raw.length;) {
      let page = this.pages.at(-1);
      if (!page || page.length === PAGE_SAMPLES) {
        page = { samples: new Int16Array(PAGE_SAMPLES), length: 0, offset: 0 }; this.pages.push(page);
      }
      const count = Math.min(PAGE_SAMPLES - page.length, (raw.length - offset) / 2);
      for (let index = 0; index < count; index++, offset += 2) {
        page.samples[page.length++] = raw.charCodeAt(offset) | raw.charCodeAt(offset + 1) << 8;
      }
      this.samples += count;
    }
  }
  take(limit: number) {
    const page = this.pages[0];
    const end = Math.min(page.length, page.offset + limit);
    const samples = page.samples.subarray(page.offset, end);
    this.samples -= samples.length; page.offset = end;
    if (end === page.length) this.pages.shift();
    return samples;
  }
  clear() { this.pages = []; this.samples = 0; }
}

/** Generation may run much faster than speech; only the short playback window is decoded. */
export class NativePlayback {
  readonly analyser: AnalyserNode;
  private gain: GainNode;
  private queue = new PcmQueue();
  private sources = new Set<AudioBufferSourceNode>();
  private audibleSources = new Set<AudioBufferSourceNode>();
  private scheduledAt = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private disposed = false;
  private broken = false;
  private speaking = false;
  private pausedAt: number | null = null;
  private pauseNotified = false;
  constructor(private context: AudioContext, private onSpeaking: (active: boolean) => void, private onError: (message: string) => void = () => undefined) {
    this.analyser = context.createAnalyser(); this.analyser.fftSize = 512;
    this.gain = context.createGain(); this.gain.connect(this.analyser); this.analyser.connect(context.destination);
  }
  push(encoded: string, rate: number) {
    if (this.disposed || this.broken) throw new Error("Voice playback is unavailable. The reply will continue in captions.");
    if (rate !== RATE) throw new Error("The voice audio format is unsupported.");
    this.queue.append(encoded);
    if (this.timer === null) this.timer = setInterval(() => this.pump(), 50);
    this.pump();
  }
  private pump() {
    if (this.disposed || this.broken) return;
    try {
      if (this.context.state === "closed") throw new Error("Audio context closed");
      if (this.context.state !== "running") {
        this.pausedAt ??= performance.now(); this.announce(false);
        if (!this.pauseNotified && performance.now() - this.pausedAt >= 3000) {
          this.pauseNotified = true;
          this.onError("Browser audio is paused. Speech will resume when audio is available; captions will continue.");
        }
        return;
      }
      this.pausedAt = null; this.pauseNotified = false;
      const now = this.context.currentTime;
      while (this.queue.samples && this.sources.size < MAX_SOURCES) {
        this.scheduledAt = Math.max(now + .025, this.scheduledAt);
        const count = Math.min(PAGE_SAMPLES, Math.floor((now + LOOKAHEAD_SECONDS - this.scheduledAt) * RATE));
        if (count < 1) break;
        const pcm = this.queue.take(count);
        const buffer = this.context.createBuffer(1, pcm.length, RATE);
        const samples = buffer.getChannelData(0);
        let energy = 0;
        for (let index = 0; index < pcm.length; index++) { samples[index] = pcm[index] / 32768; energy += samples[index] ** 2; }
        const source = this.context.createBufferSource(); source.buffer = buffer; source.connect(this.gain);
        source.onended = () => { source.disconnect(); this.sources.delete(source); this.audibleSources.delete(source); this.pump(); };
        this.sources.add(source); source.start(this.scheduledAt); this.scheduledAt += buffer.duration;
        if (Math.sqrt(energy / samples.length) > .003) this.audibleSources.add(source);
        this.gain.gain.cancelScheduledValues(now); this.gain.gain.setTargetAtTime(1, now, .008);
      }
      this.announce(this.audibleSources.size > 0);
      if (!this.queue.samples && !this.sources.size) this.stopTimer();
    } catch {
      this.broken = true; this.clear();
      this.onError("Voice playback stopped. The full reply will continue in captions.");
    }
  }
  private announce(active: boolean) { if (this.speaking !== active) { this.speaking = active; this.onSpeaking(active); } }
  private stopTimer() { if (this.timer !== null) { clearInterval(this.timer); this.timer = null; } }
  clear() {
    this.stopTimer(); this.queue.clear();
    this.gain.gain.setTargetAtTime(0, this.context.currentTime, .006);
    for (const source of this.sources) { source.onended = () => source.disconnect(); try { source.stop(this.context.currentTime + .025); } catch { source.disconnect(); } }
    this.sources.clear(); this.audibleSources.clear(); this.scheduledAt = 0; this.pausedAt = null; this.pauseNotified = false; this.announce(false);
  }
  dispose() { this.disposed = true; this.clear(); this.analyser.disconnect(); this.gain.disconnect(); }
}
