/* Raw mono PCM at 16 kHz. No recording or network code runs in the worklet. */
class GlobalConnectsPcm extends AudioWorkletProcessor {
  constructor() {
    super();
    this.phase = 0; this.sum = 0; this.count = 0;
    this.packet = new Int16Array(1600); this.position = 0;
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    for (let index = 0; index < channel.length; index++) {
      this.sum += channel[index]; this.count++; this.phase += 16000;
      if (this.phase >= sampleRate) {
        this.phase -= sampleRate;
        const value = Math.min(1, Math.max(-1, this.sum / this.count));
        this.packet[this.position++] = Math.round(value * (value < 0 ? 32768 : 32767));
        this.sum = 0; this.count = 0;
        if (this.position === this.packet.length) {
          this.port.postMessage(this.packet.buffer, [this.packet.buffer]);
          this.packet = new Int16Array(1600); this.position = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("global-connects-pcm", GlobalConnectsPcm);
