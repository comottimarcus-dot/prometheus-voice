import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const source = (await readFile(new URL('../src/prometheus_voice/static/news.js', import.meta.url), 'utf8')).replace('export async function', 'async function');
function fixture(fetch) {
  const elements = new Map();
  const create = () => ({ textContent: '', children: [], disabled: false,
    replaceChildren() { this.children = []; }, append(e) { this.children.push(e); }, addEventListener() {} });
  const get = id => { if (!elements.has(id)) elements.set(id, create()); return elements.get(id); };
  const context = { document: { getElementById: get, createElement: create }, fetch, AbortSignal };
  vm.runInNewContext(source, context);
  return { read: context.readShadowBroker, get };
}
test('news is rendered as text with source links and a bounded spoken projection', async () => {
  const f = fixture(async () => ({ ok: true, json: async () => ({ source_updated_at: 'date', stories: [
    { title: '<script>not executable</script>', source: 'Publisher', published: 'date', link: 'https://example.test/' },
  ] }) }));
  const value = await f.read();
  assert.equal(value.status, 'READ'); assert.equal(value.content_is_untrusted, true);
  assert.equal(value.independently_verified, false); assert.equal(value.stories[0].link, undefined);
  assert.match(f.get('news-results').children[0].textContent, /<script>/);
  assert.equal(f.get('news-results').children[0].children[0].rel, 'noopener noreferrer');
});
test('unavailable news clears previous stories and fails the voice tool', async () => {
  const f = fixture(async () => ({ ok: false, json: async () => ({ error: 'private' }) }));
  f.get('news-results').children.push({});
  await assert.rejects(f.read(), /Information unavailable/);
  assert.equal(f.get('news-results').children.length, 0);
  assert.equal(f.get('news-refresh').disabled, false);
});
