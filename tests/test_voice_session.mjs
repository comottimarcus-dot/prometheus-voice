import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

// Import the browser module without requiring package.json or an npm install.
const source = await readFile(new URL('../src/prometheus_voice/static/voice-session.js', import.meta.url), 'utf8');
const { VoiceSession, TranscriptLog } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

function fixture(mint, onEvent = () => {}, runTool = null, readCapabilities = null, readInformation = null, readSentinel = null, readSentinelAir = null) {
  const sockets = [], states = [], timers = new Map();
  let tick = 0, minted = 0;
  const clock = {
    setTimeout(fn, ms) { const id = ++tick; timers.set(id, { fn, ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  const client = new VoiceSession({
    mintToken: mint || (async () => `temporary-${++minted}`),
    onState: state => states.push(state), clock, onEvent, runTool, readCapabilities, readInformation, readSentinel, readSentinelAir,
    socketFactory(url) {
      const socket = {
        url, readyState: 0, sent: [], closed: false,
        send(data) { this.sent.push(JSON.parse(data)); },
        close() { this.closed = true; this.readyState = 3; },
        open() { this.readyState = 1; this.onopen?.(); },
        event(payload) { this.onmessage?.({ data: JSON.stringify(payload) }); },
      };
      sockets.push(socket); return socket;
    },
  });
  return { client, sockets, states, timers,
    expire(ms) {
      const entry = [...timers].find(([, timer]) => timer.ms === ms);
      assert.ok(entry, `Expected ${ms}ms deadline`);
      timers.delete(entry[0]); entry[1].fn();
    },
  };
}

async function ready(f) {
  await f.client.start(); f.sockets.at(-1).open();
  f.sockets.at(-1).event({ type: 'session.ready', session_id: 'ignored' });
}

test('Sentinel AIR routes only to aircraft reader', async () => {
  const f = fixture(null, () => {}, null, null, null,
    () => assert.fail('Unexpected weather read'), async () => ({status:'READ',targets:7}));
  await ready(f);const ws=f.sockets[0];
  ws.event({type:'tool.call',name:'sentinel_air',call_id:'air1',arguments:{}});
  await new Promise(resolve=>setImmediate(resolve));ws.event({type:'reply.done'});
  const response=ws.sent.find(m=>m.type==='tool.result');
  assert.equal(response.is_error,false);assert.equal(JSON.parse(response.result).targets,7);f.client.stop();
});

test('Sentinel routes one read and preserves waiting without claiming execution', async () => {
  let calls = 0;
  const f = fixture(null, () => {}, () => assert.fail('Unexpected action'), null, null,
    async () => { calls++; return { status: 'READ', motion: 'waiting', echoes: 0 }; });
  await ready(f); const ws = f.sockets[0];
  assert.ok(ws.sent[0].session.tools.some(t => t.name === 'sentinel_weather'));
  const call = { type: 'tool.call', name: 'sentinel_weather', call_id: 'sentinel1', arguments: {} };
  ws.event(call); ws.event(call); await new Promise(resolve => setImmediate(resolve));
  assert.equal(ws.sent.filter(m => m.type === 'tool.result').length, 0);
  ws.event({ type: 'reply.done' });
  assert.equal(calls, 1);
  const response = ws.sent.find(m => m.type === 'tool.result');
  assert.equal(response.is_error, false);
  assert.equal(JSON.parse(response.result).motion, 'waiting'); f.client.stop();
});

test('Sentinel failure is sanitized and never falls back to a different reader', async () => {
  const f = fixture(null, () => {}, null, () => assert.fail('Unexpected registry'),
    () => assert.fail('Unexpected news'), async () => { throw new Error('private-sentinel'); });
  await ready(f); const ws = f.sockets[0];
  ws.event({ type: 'tool.call', name: 'sentinel_weather', call_id: 's', arguments: {} });
  await new Promise(resolve => setImmediate(resolve)); ws.event({ type: 'reply.done' });
  const response = ws.sent.find(m => m.type === 'tool.result');
  assert.equal(response.is_error, true);
  assert.ok(!response.result.includes('private-sentinel')); f.client.stop();
});

test('ShadowBroker reader is isolated from calculation and returns sourced data once', async () => {
  let calls = 0;
  const f = fixture(null, () => {}, () => assert.fail('Unexpected calculation'), null,
    async () => { calls++; return { status: 'READ', stories: [{ title: 'Report', source: 'Publisher', published: 'date' }] }; });
  await ready(f); const ws = f.sockets[0];
  const call = { type: 'tool.call', name: 'shadowbroker_briefing', call_id: 'news1', arguments: {} };
  ws.event(call); ws.event(call);
  await new Promise(resolve => setImmediate(resolve));
  ws.event({ type: 'reply.done' });
  assert.equal(calls, 1);
  const response = ws.sent.find(m => m.type === 'tool.result');
  assert.equal(response.is_error, false);
  assert.equal(JSON.parse(response.result).stories[0].source, 'Publisher');
});

test('ShadowBroker rejects supplied URLs and sanitizes unavailable-provider errors', async () => {
  let calls = 0;
  const reader = async () => { calls++; throw new Error('private-token'); };
  const invalid = fixture(null, () => {}, null, null, reader); await ready(invalid);
  invalid.sockets[0].event({ type: 'tool.call', name: 'shadowbroker_briefing', call_id: 'bad', arguments: { url: 'https://example.test' } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 0);
  const f = fixture(null, () => {}, null, null, reader); await ready(f);
  const ws = f.sockets[0]; ws.event({ type: 'tool.call', name: 'shadowbroker_briefing', call_id: 'news', arguments: {} });
  await new Promise(resolve => setImmediate(resolve)); ws.event({ type: 'reply.done' });
  const response = ws.sent.find(m => m.type === 'tool.result');
  assert.equal(response.is_error, true); assert.ok(!response.result.includes('private-token'));
});

test('X6 query returns a read outcome after reply completion and ignores duplicates', async () => {
  let calls = 0;
  const f = fixture(null, () => {}, null, async () => { calls++; return { status: 'READ', capability_count: 14, availability: 'unknown' }; });
  await ready(f); const ws = f.sockets[0];
  assert.equal(ws.sent[0].session.tools[0].name, 'x6_capabilities');
  const call = { type: 'tool.call', name: 'x6_capabilities', call_id: 'query1', arguments: {} };
  ws.event(call); ws.event(call);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 1);
  assert.equal(ws.sent.filter(m => m.type === 'tool.result').length, 0);
  ws.event({ type: 'reply.done' });
  const result = ws.sent.find(m => m.type === 'tool.result');
  assert.equal(result.is_error, false);
  assert.equal(JSON.parse(result.result).status, 'READ');
});

test('X6 query rejects model-supplied commands before invoking the reader', async () => {
  let calls = 0;
  const f = fixture(null, () => {}, null, async () => { calls++; });
  await ready(f);
  f.sockets[0].event({ type: 'tool.call', name: 'x6_capabilities', call_id: 'q', arguments: { command: 'execute' } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 0); assert.equal(f.client.state, 'ending');
});

test('stop cancels X6 query and suppresses late registry results', async () => {
  let finish, signal;
  const f = fixture(null, () => {}, null, options => { signal = options.signal; return new Promise(resolve => { finish = resolve; }); });
  await ready(f); const ws = f.sockets[0];
  ws.event({ type: 'tool.call', name: 'x6_capabilities', call_id: 'q', arguments: {} });
  await new Promise(resolve => setImmediate(resolve));
  f.client.stop(); assert.equal(signal.aborted, true);
  finish({ status: 'READ' });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ws.sent.some(m => m.type === 'tool.result'), false);
});

test('configure before ready, end once, wait for server acknowledgement', async () => {
  const f = fixture(); await f.client.start(); const ws = f.sockets[0];
  assert.equal(f.client.state, 'connecting'); ws.open();
  assert.equal(ws.sent[0].type, 'session.update');
  assert.deepEqual(ws.sent[0].session.input.language_codes, ['en']);
  assert.deepEqual(ws.sent[0].session.tools, []);
  assert.equal(f.client.state, 'connecting');
  ws.event({ type: 'session.ready' });
  assert.equal(f.client.state, 'ready');
  f.client.stop(); f.client.stop();
  assert.equal(f.client.state, 'ending'); assert.equal(ws.closed, false);
  assert.deepEqual(ws.sent.slice(1), [{ type: 'session.end' }]);
  ws.event({ type: 'session.ended' });
  assert.equal(f.client.state, 'ended'); assert.equal(f.client.endConfirmed, true);
  assert.equal(ws.closed, true); assert.equal(f.timers.size, 0);
});

test('cancel while minting prevents a late token from opening a socket', async () => {
  let resolveToken, signal;
  const f = fixture(args => { signal = args.signal; return new Promise(resolve => { resolveToken = resolve; }); });
  const pending = f.client.start(); f.client.stop(); resolveToken('late-credential');
  assert.equal(await pending, false); assert.equal(signal.aborted, true);
  assert.equal(f.sockets.length, 0); assert.equal(f.client.state, 'cancelled');
});

test('cancel during socket handshake ignores a late open', async () => {
  const f = fixture(); await f.client.start(); const ws = f.sockets[0];
  const lateOpen = ws.onopen; f.client.stop(); lateOpen();
  assert.equal(ws.closed, true); assert.equal(ws.sent.length, 0);
  assert.equal(f.client.endConfirmed, false);
});

test('duplicate start is ignored and restart obtains a fresh token', async () => {
  const f = fixture(); await ready(f);
  assert.equal(await f.client.start(), false);
  f.client.stop(); f.sockets[0].event({ type: 'session.ended' });
  await f.client.start();
  assert.equal(f.sockets.length, 2);
  assert.notEqual(f.sockets[0].url, f.sockets[1].url);
  f.client.stop();
});

test('disconnect is not reported as confirmed teardown and does not reconnect', async () => {
  const f = fixture(); await ready(f); f.sockets[0].onclose();
  assert.equal(f.client.state, 'error'); assert.equal(f.client.endConfirmed, false);
  assert.equal(f.sockets.length, 1); assert.equal(f.timers.size, 0);
});

test('stop timeout reports unconfirmed teardown', async () => {
  const f = fixture(); await ready(f); f.client.stop(); f.expire(3000);
  assert.equal(f.client.state, 'error'); assert.equal(f.client.endConfirmed, false);
  assert.equal(f.sockets[0].closed, true);
});

test('connection timeout closes an open socket through session.end', async () => {
  const f = fixture(); await f.client.start(); f.sockets[0].open(); f.expire(25000);
  assert.equal(f.sockets[0].sent.at(-1).type, 'session.end');
  f.sockets[0].event({ type: 'session.ended' });
  assert.equal(f.client.state, 'error'); assert.equal(f.client.endConfirmed, true);
});

test('first-session time limit sends session.end', async () => {
  const f = fixture(); await ready(f); f.expire(120000);
  assert.equal(f.client.state, 'ending');
  assert.equal(f.sockets[0].sent.at(-1).type, 'session.end');
});

test('untrusted server errors are not exposed to state observers', async () => {
  const f = fixture(); await ready(f);
  f.sockets[0].event({ type: 'session.error', message: 'SECRET-CONTENT' });
  assert.equal(f.client.state, 'ending');
  assert.equal(JSON.stringify(f.states).includes('SECRET-CONTENT'), false);
  f.sockets[0].event({ type: 'session.ended' });
  assert.equal(f.client.state, 'error');
});

test('malformed JSON and unexpected tool calls fail closed', async () => {
  for (const payload of ['{', JSON.stringify({ type: 'tool.call', name: 'execute' })]) {
    const f = fixture(); await ready(f); f.sockets[0].onmessage({ data: payload });
    assert.equal(f.client.state, 'ending');
    assert.equal(f.sockets[0].sent.at(-1).type, 'session.end');
  }
});

test('token failure exposes only a fixed lifecycle state', async () => {
  const f = fixture(async () => { throw new Error('SECRET-CONTENT'); });
  assert.equal(await f.client.start(), false);
  assert.equal(f.client.state, 'error'); assert.equal(f.sockets.length, 0);
  assert.equal(JSON.stringify(f.states).includes('SECRET-CONTENT'), false);
});

test('audio and transcripts never enter lifecycle state notifications', async () => {
  const f = fixture(); await ready(f);
  for (const type of ['reply.audio', 'transcript.user', 'transcript.agent']) {
    f.sockets[0].event({ type, text: 'PRIVATE-CONTENT', data: 'PRIVATE-CONTENT' });
  }
  assert.equal(JSON.stringify(f.states).includes('PRIVATE-CONTENT'), false);
  assert.equal(f.sockets[0].sent.length, 1);
  f.client.stop();
});

for (const mode of ['manual', 'automatic']) {
  test(`${mode} stop drains final text without restarting audio or extending timeout`, async () => {
    const events = []; const f = fixture(undefined, event => events.push(event));
    await ready(f); const ws = f.sockets[0];
    if (mode === 'manual') f.client.stop(); else f.expire(120000);
    const deadlines = [...f.timers.keys()];
    ws.event({ type: 'transcript.agent', reply_id: 'last', text: 'Final answer.' });
    ws.event({ type: 'transcript.user', item_id: 'last-user', text: 'Final question.' });
    ws.event({ type: 'reply.started' });
    ws.event({ type: 'reply.audio', data: 'AAA=' });
    assert.deepEqual(events.map(event => event.type), ['transcript', 'transcript']);
    assert.equal(events[0].text, 'Final answer.');
    assert.equal(f.client.sendAudio('AAA='), false);
    assert.equal(f.client.state, 'ending');
    assert.deepEqual([...f.timers.keys()], deadlines);
    assert.deepEqual(ws.sent.at(-1), { type: 'session.end' });
    ws.event({ type: 'session.ended' });
    assert.equal(f.client.endConfirmed, true);
  });
}

test('late text callbacks after teardown or timeout are ignored', async () => {
  for (const timeout of [true, false]) {
    const events = []; const f = fixture(undefined, event => events.push(event));
    await ready(f); const ws = f.sockets[0]; const lateMessage = ws.onmessage;
    f.client.stop();
    if (timeout) f.expire(3000); else ws.event({ type: 'session.ended' });
    lateMessage({ data: JSON.stringify({ type: 'transcript.agent', text: 'Stale text' }) });
    assert.equal(events.length, 0);
    assert.equal(f.client.endConfirmed, !timeout);
  }
});

test('microphone frames are sent only while ready', async () => {
  const f = fixture();
  assert.equal(f.client.sendAudio('AAA='), false);
  await f.client.start(); f.sockets[0].open();
  assert.equal(f.client.sendAudio('AAA='), false);
  f.sockets[0].event({ type: 'session.ready' });
  assert.equal(f.client.sendAudio('AAA='), true);
  assert.deepEqual(f.sockets[0].sent.at(-1), { type: 'input.audio', audio: 'AAA=' });
  f.client.stop();
  assert.equal(f.client.sendAudio('AAA='), false);
});

test('socket congestion ends the session instead of accumulating microphone audio', async () => {
  const f = fixture(); await ready(f);
  f.sockets[0].bufferedAmount = 128001;
  assert.equal(f.client.sendAudio('AAA='), false);
  assert.equal(f.client.state, 'ending');
  assert.equal(f.sockets[0].sent.at(-1).type, 'session.end');
});

test('only confirmed interruptions flush playback; stale audio waits for a new reply', async () => {
  const events = []; const f = fixture(undefined, event => events.push(event));
  await ready(f); const socket = f.sockets[0];
  socket.event({ type: 'input.speech.started' });
  assert.equal(events.length, 0);
  socket.event({ type: 'reply.done', status: 'interrupted' });
  socket.event({ type: 'reply.audio', data: 'AAA=' });
  assert.deepEqual(events, [{ type: 'interrupt' }]);
  socket.event({ type: 'reply.started', reply_id: 'new' });
  socket.event({ type: 'reply.audio', data: 'AAA=' });
  assert.equal(events.at(-1).type, 'audio'); f.client.stop();
});

test('transcript updates preserve response identity and interruption', async () => {
  const events = []; const f = fixture(undefined, event => events.push(event));
  await ready(f);
  f.sockets[0].event({ type: 'transcript.agent', reply_id: 'r1', text: 'Hello', interrupted: true });
  assert.equal(events[0].id, 'r1'); assert.equal(events[0].interrupted, true);
  f.client.stop();
});

test('one reply stays one row and interrupted text is not restored to full greeting', () => {
  const log = new TranscriptLog();
  log.update({ id: 'r1', role: 'Prometheus', text: 'Hello. What would you like to accomplish?', interrupted: false });
  log.update({ id: 'r1', role: 'Prometheus', text: 'Hello. What would', interrupted: true });
  log.update({ id: 'u1', role: 'You', text: 'Can you explain yourself?' });
  const rows = log.update({ id: 'r1', role: 'Prometheus', text: 'Hello. What would you like to accomplish?', interrupted: false });
  assert.equal(rows.length, 2); assert.equal(rows[0].text, 'Hello. What would');
  assert.equal(rows[0].interrupted, true);
});

test('a genuine repeated greeting with a different reply ID stays visible', () => {
  const log = new TranscriptLog();
  log.update({ id: 'r1', role: 'Prometheus', text: 'Hello' });
  assert.equal(log.update({ id: 'r2', role: 'Prometheus', text: 'Hello' }).length, 2);
  log.clear();
  assert.equal(log.update({ id: 'r1', role: 'Prometheus', text: 'Hello' }).length, 1);
});

const toolCall = { type: 'tool.call', name: 'governed_calculation', call_id: 'call-1',
  arguments: { operator: 'add', a: 19, b: 23 } };
const flush = () => new Promise(resolve => setImmediate(resolve));

test('review begins immediately but tool result waits for reply.done', async () => {
  let count = 0;
  const f = fixture(undefined, undefined, async () => { count++; return { status: 'EXECUTED', value: 42, evidence: 'VERIFIED' }; });
  await ready(f); const ws = f.sockets[0];
  assert.equal(ws.sent[0].session.tools[0].name, 'governed_calculation');
  ws.event(toolCall); await flush(); assert.equal(count, 1);
  assert.equal(ws.sent.filter(e => e.type === 'tool.result').length, 0);
  ws.event({ type: 'reply.done', status: 'completed' }); await flush();
  const replies = ws.sent.filter(e => e.type === 'tool.result');
  assert.equal(count, 1); assert.equal(replies.length, 1);
  assert.equal(JSON.parse(replies[0].result).value, 42);
  assert.equal(replies[0].is_error, false);
  ws.event(toolCall); await flush(); assert.equal(count, 1); f.client.stop();
});

test('tool results wait while a new user turn is in flight', async () => {
  let resolve;
  const f = fixture(undefined, undefined, () => new Promise(r => { resolve = r; }));
  await ready(f); const ws = f.sockets[0];
  ws.event(toolCall); ws.event({ type: 'reply.done', status: 'completed' }); await flush();
  ws.event({ type: 'input.speech.started' }); resolve({ status: 'EXECUTED', value: 42 }); await flush();
  assert.equal(ws.sent.filter(e => e.type === 'tool.result').length, 0);
  ws.event({ type: 'reply.done', status: 'completed' });
  assert.equal(ws.sent.filter(e => e.type === 'tool.result').length, 1); f.client.stop();
});

test('stop aborts pending review and suppresses late tool results', async () => {
  let resolve, signal;
  const f = fixture(undefined, undefined, (_, options) => {
    signal = options.signal; return new Promise(r => { resolve = r; });
  });
  await ready(f); const ws = f.sockets[0];
  ws.event(toolCall); ws.event({ type: 'reply.done', status: 'completed' }); await flush();
  f.client.stop(); assert.equal(signal.aborted, true);
  resolve({ status: 'EXECUTED', value: 42 }); await flush();
  assert.equal(ws.sent.filter(e => e.type === 'tool.result').length, 0);
});

test('interrupted transition cancels queued tool without invoking the handler', async () => {
  let count = 0; const f = fixture(undefined, undefined, async () => { count++; });
  await ready(f); f.sockets[0].event(toolCall);
  f.sockets[0].event({ type: 'reply.done', status: 'interrupted' }); await flush();
  assert.equal(count, 0); f.client.stop();
});

test('malformed tool arguments fail closed before invoking the handler', async () => {
  for (const args of [{ operator: 'eval', a: 1, b: 2 }, { operator: 'add', a: '19', b: 23 },
                      { operator: 'add', a: 19, b: 23, approved: true }]) {
    let count = 0; const f = fixture(undefined, undefined, async () => { count++; });
    await ready(f); f.sockets[0].event({ ...toolCall, arguments: args }); await flush();
    assert.equal(count, 0); assert.equal(f.client.state, 'ending');
  }
});

test('handler failures produce a fixed error without private exception details', async () => {
  const f = fixture(undefined, undefined, async () => { throw new Error('SYNTHETIC-PRIVATE'); });
  await ready(f); const ws = f.sockets[0];
  ws.event(toolCall); ws.event({ type: 'reply.done', status: 'completed' }); await flush();
  const result = ws.sent.find(e => e.type === 'tool.result');
  assert.equal(result.is_error, true); assert.equal(result.result.includes('SYNTHETIC-PRIVATE'), false);
  f.client.stop();
});
