/* Native 16 kHz AudioContext is preferred. Fractional box integration handles
   browsers that ignore the requested rate; it is not a telephony-grade codec. */
class StrivePCM extends AudioWorkletProcessor {
  constructor() { super(); this.output = new Int16Array(16000); this.pos = 0;
    this.ratio = sampleRate / 16000; this.need = this.ratio; this.sum = 0; }
  process(inputs) {
    const channels = inputs[0]; if (!channels?.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      let value = 0; for (const channel of channels) value += channel[i] / channels.length;
      let remaining = 1;
      while (remaining > 1e-8) {
        const taken = Math.min(remaining, this.need); this.sum += value * taken;
        remaining -= taken; this.need -= taken;
        if (this.need < 1e-8) {
          const x = Math.max(-1, Math.min(1, this.sum / this.ratio));
          this.output[this.pos++] = Math.round(x < 0 ? x * 32768 : x * 32767);
          this.need = this.ratio; this.sum = 0;
          if (this.pos === 16000) {this.port.postMessage(this.output.buffer, [this.output.buffer]); this.output = new Int16Array(16000); this.pos = 0;}
        }
      }
    }
    return true;
  }
}
registerProcessor('strive-pcm', StrivePCM);
