import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const source = (await readFile(new URL('../src/prometheus_voice/static/x6.js', import.meta.url), 'utf8')).replace('export async function', 'async function');
function fixture(fetch) {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, { textContent: '', disabled: false, children: [],
      replaceChildren() { this.children = []; }, append(e) { this.children.push(e); }, addEventListener() {} });
    return elements.get(id);
  };
  const context = { document: { getElementById: get, createElement: () => ({ textContent: '' }) }, fetch, AbortSignal, Date };
  vm.runInNewContext(source, context);
  return { read: context.readX6Capabilities, get };
}
test('spoken registry summary uses fresh backend counts and marks truncated names', async () => {
  let calls = 0;
  const f = fixture(async path => {
    calls++; assert.equal(path, '/api/x6/capabilities');
    return { ok: true, json: async () => ({ capabilities: Array.from({ length: 40 }, (_, i) => ({ name: `cap_${i}`, registered_provider_count: 2 })) }) };
  });
  const result = await f.read(); await f.read();
  assert.equal(calls, 2); assert.equal(result.status, 'READ');
  assert.equal(result.capability_count, 40); assert.equal(result.registered_provider_count, 80);
  assert.equal(result.capability_names.length, 32); assert.equal(result.names_truncated, true);
  assert.equal(result.health_checked, false); assert.equal(result.execution_authorized, false);
});
test('registry failure clears stale UI and cannot become a successful tool result', async () => {
  const f = fixture(async () => { throw new Error('private-sentinel'); });
  f.get('x6-results').children.push({});
  await assert.rejects(f.read(), /^Error: Query unavailable$/);
  assert.equal(f.get('x6-results').children.length, 0);
  assert.equal(f.get('x6-refresh').disabled, false);
});
test('already cancelled voice query makes no backend request', async () => {
  const f = fixture(() => assert.fail('Unexpected request'));
  const controller = new AbortController(); controller.abort();
  await assert.rejects(f.read({ signal: controller.signal }));
});
