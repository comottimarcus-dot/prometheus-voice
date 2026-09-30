export class VoiceAudio {
  constructor({ onFrame, onFailure, media = navigator.mediaDevices,
    Context = globalThis.AudioContext, Worklet = globalThis.AudioWorkletNode }) {
    Object.assign(this, { onFrame, onFailure, media, Context, Worklet });
    this.generation = 0;
    this.sources = new Set();
    this.context = null;
    this.stream = null;
  }

  async start() {
    this.stop();
    const generation = this.generation;
    try {
      const context = new this.Context();
      this.context = context;
      await context.resume();
      if (generation !== this.generation) return false;
      await context.audioWorklet.addModule('/pcm-worklet.js');
      if (generation !== this.generation) return false;
      const stream = await this.media.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      if (generation !== this.generation) {
        stream.getTracks().forEach(track => track.stop());
        return false;
      }
      this.stream = stream;
      stream.getTracks().forEach(track => {
        track.onended = () => { this.stop(); this.onFailure(); };
      });
      this.input = context.createMediaStreamSource(stream);
      this.worklet = new this.Worklet(context, 'pcm-capture', {
        channelCount: 1, channelCountMode: 'explicit', outputChannelCount: [1],
      });
      this.worklet.port.onmessage = ({ data }) => {
        if (generation !== this.generation) return;
        try {
          const bytes = new Uint8Array(data);
          this.onFrame(btoa(String.fromCharCode(...bytes)));
        } catch { this.stop(); this.onFailure(); }
      };
      this.worklet.onprocessorerror = () => { this.stop(); this.onFailure(); };
      this.input.connect(this.worklet);
      this.worklet.connect(context.destination);
      this.playAt = context.currentTime;
      return true;
    } catch {
      if (generation === this.generation) this.stop();
      throw new Error('Microphone unavailable');
    }
  }

  play(encoded) {
    const context = this.context;
    if (!context || context.state === 'closed') return;
    const raw = atob(encoded);
    if (!raw.length || raw.length % 2 || raw.length > 384000) throw new Error('Invalid audio');
    const buffer = context.createBuffer(1, raw.length / 2, 24000);
    const samples = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) {
      const value = raw.charCodeAt(i * 2) | (raw.charCodeAt(i * 2 + 1) << 8);
      samples[i] = (value >= 32768 ? value - 65536 : value) / 32768;
    }
    const start = Math.max(this.playAt, context.currentTime);
    if (start + buffer.duration - context.currentTime > 15) throw new Error('Playback limit');
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    this.sources.add(source);
    source.onended = () => { source.disconnect(); this.sources.delete(source); };
    source.start(start);
    this.playAt = start + buffer.duration;
  }

  interrupt() {
    for (const source of this.sources) {
      source.onended = null;
      try { source.stop(); source.disconnect(); } catch { /* Already ended. */ }
    }
    this.sources.clear();
    this.playAt = this.context?.currentTime || 0;
  }

  stop() {
    this.generation++;
    if (this.stream) {
      this.stream.getTracks().forEach(track => { track.onended = null; track.stop(); });
      this.stream = null;
    }
    if (this.worklet) {
      this.worklet.port.onmessage = null;
      this.worklet.onprocessorerror = null;
      this.worklet.disconnect();
      this.worklet = null;
    }
    this.input?.disconnect(); this.input = null;
    this.interrupt();
    if (this.context) {
      this.context.close().catch(() => {});
      this.context = null;
    }
  }
}
