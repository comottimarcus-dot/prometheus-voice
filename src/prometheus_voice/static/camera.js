const review=document.getElementById('camera-review');
const capture=document.getElementById('camera-capture');
const cancel=document.getElementById('camera-cancel');
const status=document.getElementById('camera-status');
const results=document.getElementById('camera-results');
let busy=false;
export async function requestCamera({signal}={}) {
  if(busy || signal?.aborted) throw new Error('Camera unavailable');
  busy=true; review.disabled=true; results.replaceChildren();
  capture.disabled=false; cancel.disabled=false;
  status.textContent='Review: one photo from the connected Zhengchen will be sent through X6 to your Z800 for object detection. Click Capture photo within 25 seconds.';
  status.scrollIntoView?.({block:'center',behavior:'smooth'});
  try {
    await new Promise((resolve,reject)=>{
      const cleanup=()=>{clearTimeout(timer);capture.removeEventListener('click',yes);cancel.removeEventListener('click',no);signal?.removeEventListener('abort',no);};
      const yes=()=>{cleanup();resolve();};const no=()=>{cleanup();reject(new Error('Cancelled'));};
      const timer=setTimeout(no,25000);
      capture.addEventListener('click',yes);cancel.addEventListener('click',no);signal?.addEventListener('abort',no,{once:true});
    });
    if(signal?.aborted)throw new Error('Cancelled');
    capture.disabled=true;cancel.disabled=true;
    status.textContent='Capture requested. Keep the camera connected. Do not repeat the request.';
    const response=await fetch('/api/camera/capture',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',cache:'no-store',redirect:'error',
      signal:signal?AbortSignal.any([signal,AbortSignal.timeout(55000)]):AbortSignal.timeout(55000)});
    const data=await response.json();if(!response.ok || data.status!=='DETECTED')throw new Error('Unavailable');
    const summary=data.objects.length ? data.objects.map(x=>`${x.count} ${x.label}`).join(', ') : 'No objects met the detector threshold. This does not prove the scene is empty.';
    const line=document.createElement('p');line.textContent=summary;results.append(line);
    status.textContent='Object detection returned. Model predictions; not independently verified. No face recognition was used.';
    return {status:'READ',objects:data.objects,spoken_summary:summary,independently_verified:false};
  }catch{
    status.textContent='No confirmed detection result. The request may have been cancelled or failed. Do not assume a photo was not taken or retry automatically.';
    throw new Error('No confirmed camera result');
  }finally{busy=false;review.disabled=false;capture.disabled=true;cancel.disabled=true;}
}
review.addEventListener('click',()=>requestCamera().catch(()=>{}));
