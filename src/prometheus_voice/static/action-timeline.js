const panel=document.getElementById('action-timeline');
const status=document.getElementById('action-timeline-status');
const labels={requested:'Photo requested',awaiting_consent:'Awaiting spoken consent',consent_accepted:'Spoken consent accepted',consent_not_accepted:'Confirmation not accepted',consent_expired:'Confirmation expired',cancelled:'Request cancelled',dispatched:'Capture dispatched',image_received:'Validated image received',detection_returned:'Detection returned — predictions only',result_sent:'Result sent to voice agent',failed:'Action failed or blocked'};
let previous='';
async function refresh(){
 try{
  const response=await fetch('/api/action-events',{cache:'no-store',signal:AbortSignal.timeout(3000)});
  if(!response.ok)throw new Error();
  const data=await response.json();const serialized=JSON.stringify(data);
  if(serialized!==previous){
   const groups=new Map();
   for(const event of data.events){if(!labels[event.stage])continue;if(!groups.has(event.trace))groups.set(event.trace,[]);groups.get(event.trace).push(event);}
   const sections=[];
   for(const [trace,events] of [...groups].slice(-4).reverse()){
    const section=document.createElement('section');const title=document.createElement('h3');title.textContent=`Camera request ${trace.slice(0,8)}`;section.append(title);
    const list=document.createElement('ol');
    for(const event of events){const item=document.createElement('li');item.textContent=`${new Date(event.time*1000).toLocaleTimeString()} · ${labels[event.stage]} · ${event.source==='x6'?'X6':'Voice bridge'}`;list.append(item);}
    section.append(list);sections.push(section);
   }
   panel.replaceChildren(...sections);previous=serialized;
  }
  status.textContent=data.events.length?'Recent observed activity · expires after five minutes.':'Waiting for a new camera request.';
 }catch{status.textContent='Activity connection unavailable. Displayed events may be stale.';}
 finally{setTimeout(refresh,1000);}
}
refresh();
