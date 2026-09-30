import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {test} from 'node:test';
const source=(await readFile(new URL('../src/prometheus_voice/static/camera.js',import.meta.url),'utf8')).replace('export async function','async function');
function fixture(){
  const elements=new Map();let calls=0;
  const element=()=>({textContent:'',disabled:false,children:[],listeners:new Map(),replaceChildren(){this.children=[]},append(x){this.children.push(x)},addEventListener(t,f){this.listeners.set(t,f)},removeEventListener(t){this.listeners.delete(t)},click(){this.listeners.get('click')?.()}});
  const get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id)};
  const context={document:{getElementById:get,createElement:element},AbortSignal,setTimeout,clearTimeout,
    fetch:async()=>{calls++;return {ok:true,json:async()=>({status:'DETECTED',objects:[{label:'cup',count:1}]})}}};
  vm.runInNewContext(source,context);return {get,request:context.requestCamera,calls:()=>calls};
}
test('review requires a click before one capture request',async()=>{
  const f=fixture();const pending=f.request();assert.equal(f.calls(),0);
  f.get('camera-capture').click();const result=await pending;
  assert.equal(f.calls(),1);assert.equal(result.status,'READ');
});
test('cancelling review sends no capture',async()=>{
  const f=fixture();const pending=f.request();f.get('camera-cancel').click();
  await assert.rejects(pending);assert.equal(f.calls(),0);
});
