import { audioDeadline } from "./audio-readiness";

/** Native voice uses raw PCM directly, without an intermediate transcription request. */
export function pcmBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text);
}

export function decodePcm(encoded: string): Float32Array<ArrayBuffer> {
  if (encoded.length > 300000) throw new Error("The voice audio packet is too large.");
  const raw = atob(encoded);
  if (!raw.length || raw.length % 2) throw new Error("The voice audio packet is invalid.");
  const bytes = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index++) bytes[index] = raw.charCodeAt(index);
  const view = new DataView(bytes.buffer);
  const samples = new Float32Array(raw.length / 2);
  for (let index = 0; index < samples.length; index++) samples[index] = view.getInt16(index * 2, true) / 32768;
  return samples;
}

export async function capturePcm(context: AudioContext, stream: MediaStream, send: (buffer: ArrayBuffer) => void): Promise<() => void> {
  const source = context.createMediaStreamSource(stream);
  const silent = context.createGain(); silent.gain.value = 0; silent.connect(context.destination);
  let worklet: AudioWorkletNode | null = null;
  try {
    await audioDeadline(context.audioWorklet.addModule("/ai/voice-capture.worklet.js"), 1500, "Microphone processor did not load.");
    const node = new AudioWorkletNode(context, "global-connects-pcm", {
      numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
      channelCount: 1, channelCountMode: "explicit",
    });
    worklet = node;
    node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => send(event.data);
    source.connect(node); node.connect(silent);
    return () => { node.port.onmessage = null; node.port.close(); source.disconnect(); node.disconnect(); silent.disconnect(); };
  } catch {
    if (worklet) { worklet.port.onmessage = null; worklet.port.close(); worklet.disconnect(); source.disconnect(); }
    // Older WebKit and restricted worklet environments retain a bounded PCM fallback.
    try {
    const node = context.createScriptProcessor(4096, 1, 1);
    let phase = 0, sum = 0, count = 0, position = 0;
    let packet = new Int16Array(1600);
    node.onaudioprocess = (event) => {
      for (const sample of event.inputBuffer.getChannelData(0)) {
        sum += sample; count++; phase += 16000;
        if (phase >= context.sampleRate) {
          phase -= context.sampleRate;
          const value = Math.max(-1, Math.min(1, sum / count));
          packet[position++] = Math.round(value * (value < 0 ? 32768 : 32767));
          sum = 0; count = 0;
          if (position === packet.length) { send(packet.buffer); packet = new Int16Array(1600); position = 0; }
        }
      }
    };
    source.connect(node); node.connect(silent);
    return () => { node.onaudioprocess = null; source.disconnect(); node.disconnect(); silent.disconnect(); };
    } catch (cause) { source.disconnect(); silent.disconnect(); throw cause; }
  }
}

export class NativePlayback {
  readonly analyser: AnalyserNode;
  private gain: GainNode;
  private sources = new Set<AudioBufferSourceNode>();
  private audibleSources = new Set<AudioBufferSourceNode>();
  private scheduledAt = 0;
  constructor(private context: AudioContext, private onSpeaking: (active: boolean) => void) {
    this.analyser = context.createAnalyser(); this.analyser.fftSize = 512;
    this.gain = context.createGain(); this.analyser.connect(this.gain); this.gain.connect(context.destination);
  }
  push(encoded: string, rate: number) {
    if (rate !== 24000) throw new Error("The voice audio format is unsupported.");
    const samples = decodePcm(encoded);
    // Duplex providers can stream near-silence between spoken replies.
    let energy = 0; for (const sample of samples) energy += sample * sample;
    const audible = Math.sqrt(energy / samples.length) > .003;
    if (this.scheduledAt - this.context.currentTime > 20) throw new Error("Voice playback is falling behind. Please reconnect.");
    const buffer = this.context.createBuffer(1, samples.length, rate); buffer.copyToChannel(samples, 0);
    const source = this.context.createBufferSource(); source.buffer = buffer; source.connect(this.analyser);
    this.gain.gain.cancelScheduledValues(this.context.currentTime);
    this.gain.gain.setTargetAtTime(1, this.context.currentTime, .008);
    this.scheduledAt = Math.max(this.context.currentTime + .025, this.scheduledAt);
    source.start(this.scheduledAt); this.scheduledAt += buffer.duration; this.sources.add(source);
    if (audible) { this.audibleSources.add(source); if (this.audibleSources.size === 1) this.onSpeaking(true); }
    source.onended = () => {
      source.disconnect(); this.sources.delete(source);
      if (this.audibleSources.delete(source) && !this.audibleSources.size) this.onSpeaking(false);
    };
  }
  clear() {
    this.gain.gain.setTargetAtTime(0, this.context.currentTime, .006);
    for (const source of this.sources) { source.onended = () => source.disconnect(); try { source.stop(this.context.currentTime + .025); } catch { source.disconnect(); } }
    this.sources.clear(); this.audibleSources.clear(); this.scheduledAt = 0; this.onSpeaking(false);
  }
  dispose() { this.clear(); this.analyser.disconnect(); this.gain.disconnect(); }
}
