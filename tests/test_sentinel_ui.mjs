import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const source = (await readFile(new URL('../src/prometheus_voice/static/sentinel.js', import.meta.url), 'utf8')).replaceAll('export async function', 'async function');
function fixture(data, ok=true) {
  const elements = new Map();
  const create = () => ({textContent:'', children:[], disabled:false, replaceChildren(){this.children=[];}, append(x){this.children.push(x);}, addEventListener(){}});
  const get = id => {if(!elements.has(id))elements.set(id,create());return elements.get(id);};
  const context = {document:{getElementById:get,createElement:create},AbortSignal,fetch:async()=>({ok,json:async()=>data})};
  vm.runInNewContext(source,context);return {...context,get};
}
test('waiting with zero echoes explicitly requires a second distinct sample', async()=>{
  const f=fixture({cells:25,echoes:0,max_precipitation_mm:0,motion:'waiting',bearing_deg:null});
  const result=await f.readSentinel();
  assert.match(result.spoken_summary,/waiting for a second distinct weather sample/);
  assert.doesNotMatch(result.spoken_summary,/no motion/);
});
test('air count states nautical miles and the display cap', async()=>{
  const f=fixture({targets:40,limit_reached:true,fetch_age_seconds:2});
  const result=await f.readSentinelAir();
  assert.match(result.spoken_summary,/25 nautical miles/);
  assert.match(result.spoken_summary,/limit of 40/);
});
test('air failure clears stale results rather than reporting zero',async()=>{
  const f=fixture({},false);f.get('sentinel-results').children.push({});
  await assert.rejects(f.readSentinelAir(),/unavailable/);
  assert.equal(f.get('sentinel-results').children.length,0);
});
