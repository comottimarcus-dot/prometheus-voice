const img=document.getElementById('camera-preview');
const status=document.getElementById('camera-preview-status');
const clear=document.getElementById('camera-preview-clear');
let url=null, pixels=null, generation=0, clearing=false;
function hide(){img.hidden=true;img.removeAttribute('src');if(url)URL.revokeObjectURL(url);url=null;pixels=null;}
async function refresh(){
  const current=generation;
  try{
    if(clearing)return;
    const response=await fetch('/api/camera/preview',{cache:'no-store',signal:AbortSignal.timeout(5000)});
    if(current!==generation)return;
    if(response.status===204){hide();status.textContent='No recent photo. Photos expire after three minutes.';return;}
    if(!response.ok)throw new Error();
    const blob=await response.blob();
    if(current!==generation)return;
    const bytes=new Uint8Array(await blob.arrayBuffer());
    if(current!==generation)return;
    const unchanged=pixels && pixels.length===bytes.length && pixels.every((value,index)=>value===bytes[index]);
    if(!unchanged){
      const previous=url;
      url=URL.createObjectURL(blob);pixels=bytes;
      img.src=url;img.hidden=false;
      if(previous)URL.revokeObjectURL(previous);
    }
    status.textContent='Last authorized photo · temporary preview. Detector predictions may be incorrect.';
  }catch{if(current===generation){hide();status.textContent='Photo preview unavailable.';}}
  finally{setTimeout(refresh,2000);}
}
clear.addEventListener('click',async()=>{
  generation++;clearing=true;clear.disabled=true;hide();
  try{
    const response=await fetch('/api/camera/preview/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(5000)});
    if(!response.ok)throw new Error();
    status.textContent='Photo cleared.';
  }catch{status.textContent='Could not confirm removal from the server. The photo still expires automatically.';}
  finally{clearing=false;clear.disabled=false;}
});
refresh();
