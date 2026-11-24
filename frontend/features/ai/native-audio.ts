import { audioDeadline } from "./audio-readiness";
export { NativePlayback } from "./native-playback";

/** Native voice uses raw PCM directly, without an intermediate transcription request. */
export function pcmBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text);
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
