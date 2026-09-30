import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import vm from 'node:vm';
const base = new URL('../src/prometheus_voice/static/', import.meta.url);
const workletSource = await readFile(new URL('pcm-worklet.js', base), 'utf8');
const audioSource = await readFile(new URL('voice-audio.js', base), 'utf8');
const { VoiceAudio } = await import(`data:text/javascript;base64,${Buffer.from(audioSource).toString('base64')}`);

for (const rate of [24000, 44100, 48000, 96000]) {
  test(`capture produces exactly 24 kHz PCM16 from ${rate} Hz`, () => {
    const frames = []; let Processor;
    vm.runInNewContext(workletSource, {
      sampleRate: rate, ArrayBuffer, DataView,
      AudioWorkletProcessor: class { port = { postMessage: value => frames.push(value) }; },
      registerProcessor: (_, value) => { Processor = value; },
    });
    const processor = new Processor();
    for (let i = 0; i < rate; i += 128) {
      processor.process([[new Float32Array(Math.min(128, rate - i)).fill(-1)]]);
    }
    assert.equal(frames.length, 50);
    for (const frame of frames) {
      assert.equal(frame.byteLength, 960);
      assert.equal(new DataView(frame).getInt16(0, true), -32768);
    }
  });
}

function fixture(media) {
  const contexts = [], tracks = [{ stopped: false, stop() { this.stopped = true; } }];
  class Context {
    state = 'running'; currentTime = 0; destination = {}; sources = [];
    audioWorklet = { addModule: async () => {} };
    constructor() { contexts.push(this); }
    async resume() {}
    async close() { this.state = 'closed'; }
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createBuffer(_, count, rate) {
      const data = new Float32Array(count);
      return { duration: count / rate, getChannelData: () => data };
    }
    createBufferSource() {
      const source = { connect() {}, disconnect() {}, start() {}, stop() { this.stopped = true; } };
      this.sources.push(source); return source;
    }
  }
  class Worklet { port = {}; connect() {} disconnect() {} }
  const audio = new VoiceAudio({ onFrame() {}, onFailure() {}, Context, Worklet,
    media: media || { getUserMedia: async () => ({ getTracks: () => tracks }) } });
  return { audio, contexts, tracks };
}

test('stop releases tracks, playback and audio context', async () => {
  const f = fixture(); await f.audio.start(); f.audio.play(btoa('\x00\x80\xff\x7f'));
  assert.equal(f.contexts[0].sources[0].buffer.getChannelData()[0], -1);
  f.audio.stop();
  assert.equal(f.tracks[0].stopped, true);
  assert.equal(f.contexts[0].state, 'closed');
  assert.equal(f.contexts[0].sources[0].stopped, true);
});

test('late microphone permission after stop immediately releases tracks', async () => {
  let resolve, reached;
  const waiting = new Promise(r => { reached = r; });
  const f = fixture({ getUserMedia: () => { reached(); return new Promise(r => { resolve = r; }); } });
  const pending = f.audio.start(); await waiting; f.audio.stop();
  resolve({ getTracks: () => f.tracks });
  assert.equal(await pending, false); assert.equal(f.tracks[0].stopped, true);
});

test('permission denial closes the audio context', async () => {
  const f = fixture({ getUserMedia: async () => { throw new Error('private detail'); } });
  await assert.rejects(f.audio.start(), { message: 'Microphone unavailable' });
  assert.equal(f.contexts[0].state, 'closed');
});

test('interruption cancels already scheduled playback', async () => {
  const f = fixture(); await f.audio.start(); f.audio.play(btoa('\x00\x00'));
  f.audio.interrupt();
  assert.equal(f.contexts[0].sources[0].stopped, true);
  assert.equal(f.audio.sources.size, 0); f.audio.stop();
});

test('malformed playback fails closed', async () => {
  const f = fixture(); await f.audio.start();
  assert.throws(() => f.audio.play(btoa('x')));
  assert.throws(() => f.audio.play('%%%'));
  f.audio.stop();
});
