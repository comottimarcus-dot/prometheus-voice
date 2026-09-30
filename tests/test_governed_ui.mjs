import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const source = (await readFile(new URL('../src/prometheus_voice/static/governed.js', import.meta.url), 'utf8')).replace('export function requestVoiceCalculation', 'function requestVoiceCalculation');

function fixture(responses) {
  class Element {
    value = ''; disabled = false; textContent = ''; children = []; handlers = {};
    addEventListener(name, callback) { this.handlers[name] = callback; }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children = items; }
    querySelectorAll() { return []; }
  }
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  get('operand-a').value = '19'; get('operand-b').value = '23'; get('operator').value = 'add';
  const requests = [], timers = new Map(); let next = 0;
  const context = {
    document: { getElementById: get, createElement: () => new Element(), createTextNode: text => text },
    Date, AbortSignal,
    setTimeout: fn => { const id = ++next; timers.set(id, fn); return id; },
    clearTimeout: id => timers.delete(id),
    fetch: async (path, options) => {
      requests.push({ path, payload: JSON.parse(options.body) });
      const result = responses.shift();
      if (result instanceof Error) throw result;
      return { ok: true, json: async () => result };
    },
  };
  vm.runInNewContext(source, context);
  return { get, requests, timers, requestVoice: context.requestVoiceCalculation, async click(id, event = 'click') {
    await get(id).handlers[event]({ preventDefault() {} });
    await new Promise(resolve => setImmediate(resolve));
  } };
}

function proposal(decision = 'ALLOW') {
  return { plan_id: 'server-plan', can_execute: decision === 'ALLOW', plan: {
    expires_at: new Date(Date.now() + 30000).toISOString(), objective: 'Bounded calculation',
    status: decision === 'ALLOW' ? 'PROPOSED' : decision === 'CONFIRM' ? 'AWAITING_CONFIRMATION' : 'BLOCKED',
    selection: { policy: { decision, risk: 'low', explanation: 'Policy explanation' },
      proposed_executor_id: 'local-calculator', assessments: [] },
    steps: decision === 'DENY' ? [] : [{ mode: 'REAL', success_criteria: ['FINITE_NUMERIC_RESULT'] }],
  } };
}

test('review then execute sends only the server-issued plan ID', async () => {
  const f = fixture([proposal(), { status: 'EXECUTED', value: 42, reason_code: 'CALCULATION_COMPLETED',
    executor: 'local-calculator', trace_id: 'trace', evidence: { status: 'VERIFIED', sequence: 1, head_hash: 'head' } }]);
  await f.click('governed-form', 'submit');
  assert.equal(f.get('execute-plan').disabled, false);
  assert.equal(f.requests[0].payload.parameters.a, 19);
  await f.click('execute-plan');
  assert.deepEqual(f.requests[1].payload, { plan_id: 'server-plan' });
  assert.equal(f.get('execute-plan').disabled, true);
  assert.match(f.get('governed-message').textContent, /chain verified/);
});

test('confirmation and denial previews do not enable execution', async () => {
  for (const [id, decision] of [['preview-confirm', 'CONFIRM'], ['preview-deny', 'DENY']]) {
    const f = fixture([proposal(decision)]); await f.click(id);
    assert.equal(f.get('execute-plan').disabled, true);
    assert.equal(f.requests.length, 1);
  }
});

test('editing inputs invalidates the prior plan', async () => {
  const f = fixture([proposal()]); await f.click('governed-form', 'submit');
  await f.click('governed-form', 'input');
  assert.equal(f.get('execute-plan').disabled, true);
  await f.click('execute-plan'); assert.equal(f.requests.length, 1);
});

test('plan expiration disables execution', async () => {
  const f = fixture([proposal()]); await f.click('governed-form', 'submit');
  [...f.timers.values()][0]();
  assert.equal(f.get('execute-plan').disabled, true);
});

test('ambiguous response permits retrieval using the same plan only', async () => {
  const f = fixture([proposal(), new Error('offline'), { status: 'EXECUTED', value: 42,
    evidence: { status: 'FAILED' }, trace_id: 'trace', executor: 'local-calculator' }]);
  await f.click('governed-form', 'submit'); await f.click('execute-plan');
  assert.equal(f.get('execute-plan').disabled, false);
  await f.click('execute-plan');
  assert.deepEqual(f.requests[1].payload, f.requests[2].payload);
  assert.match(f.get('governed-message').textContent, /evidence could not be verified/);
});

test('voice proposal does not call server until human review and execution', async () => {
  const f = fixture([proposal(), { status: 'EXECUTED', value: 42, evidence: { status: 'VERIFIED', sequence: 1, head_hash: 'h' }, executor: 'local-calculator', mode: 'REAL' }]);
  const controller = new AbortController();
  const pending = f.requestVoice({ operator: 'add', a: 19, b: 23 }, { signal: controller.signal });
  assert.equal(f.requests.length, 0); assert.equal(f.get('operand-a').value, '19');
  await f.click('governed-form', 'submit'); assert.equal(f.requests.length, 1);
  await f.click('execute-plan'); const result = await pending;
  assert.equal(result.value, 42); assert.equal(result.evidence, 'VERIFIED');
  assert.equal(result.operands.a, 19);
});

test('voice cancellation removes execution permission and avoids any request', async () => {
  const f = fixture([]); const controller = new AbortController();
  const pending = f.requestVoice({ operator: 'add', a: 19, b: 23 }, { signal: controller.signal });
  const rejected = assert.rejects(pending); controller.abort(); await rejected;
  assert.equal(f.requests.length, 0); assert.equal(f.get('execute-plan').disabled, true);
});

test('review timeout reports no execution rather than a failed calculation', async () => {
  const f = fixture([]); const controller = new AbortController();
  const pending = f.requestVoice({ operator: 'add', a: 19, b: 23 }, { signal: controller.signal });
  [...f.timers.values()][0]();
  const result = await pending;
  assert.equal(result.status, 'NOT_EXECUTED'); assert.equal(result.reason_code, 'REVIEW_EXPIRED');
  assert.equal(f.requests.length, 0);
});
