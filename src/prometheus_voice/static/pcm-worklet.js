// Convert the device rate to 24 kHz using weighted sample averaging.
// A 480-sample frame is 20 ms, encoded explicitly as little-endian PCM16.
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 24000;
    this.weight = 0;
    this.sum = 0;
    this.offset = 0;
    this.buffer = new ArrayBuffer(960);
    this.view = new DataView(this.buffer);
  }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (const value of input) {
      let remaining = 1;
      while (remaining > 1e-9) {
        const part = Math.min(remaining, this.ratio - this.weight);
        this.sum += value * part;
        this.weight += part;
        remaining -= part;
        if (this.weight >= this.ratio - 1e-9) {
          const sample = Math.max(-1, Math.min(1, this.sum / this.ratio));
          this.view.setInt16(this.offset * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
          this.offset++;
          this.sum = this.weight = 0;
          if (this.offset === 480) {
            this.port.postMessage(this.buffer, [this.buffer]);
            this.buffer = new ArrayBuffer(960);
            this.view = new DataView(this.buffer);
            this.offset = 0;
          }
        }
      }
    }
    return true; // Output remains silent; the microphone is never monitored locally.
  }
}
registerProcessor("pcm-capture", PCMProcessor);
