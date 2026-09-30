import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const source=fs.readFileSync(new URL('../src/prometheus_voice/static/camera-preview.js',import.meta.url),'utf8');
test('same photo remains visible without replacing its URL; changed photo replaces once; clear removes it',async()=>{
 const timers=[];let data=[1,2,3],created=0,srcWrites=0;const revoked=[];
 const elements={};for(const id of ['camera-preview','camera-preview-status','camera-preview-clear'])elements[id]={hidden:true,addEventListener(type,fn){this.click=fn},removeAttribute(){}};
 Object.defineProperty(elements['camera-preview'],'src',{set(){srcWrites++}});
 const context=vm.createContext({document:{getElementById:id=>elements[id]},Uint8Array,AbortSignal:{timeout(){}},URL:{createObjectURL(){return `blob:${++created}`},revokeObjectURL(url){revoked.push(url)}},setTimeout(fn){timers.push(fn)},fetch:async()=>({ok:true,status:200,blob:async()=>({arrayBuffer:async()=>new Uint8Array(data).buffer})})});
 vm.runInContext(source,context);await new Promise(resolve=>setImmediate(resolve));
 assert.equal(srcWrites,1);assert.equal(elements['camera-preview'].hidden,false);
 await timers.shift()();assert.equal(srcWrites,1);assert.deepEqual(revoked,[]);
 data=[4,5,6];await timers.shift()();assert.equal(srcWrites,2);assert.equal(elements['camera-preview'].hidden,false);assert.deepEqual(revoked,['blob:1']);
 await elements['camera-preview-clear'].click();assert.equal(elements['camera-preview'].hidden,true);assert.deepEqual(revoked,['blob:1','blob:2']);
});
