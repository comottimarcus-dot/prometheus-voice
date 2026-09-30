"""Best-effort bounded telemetry; fixed events only, no transcript or payload."""
import json
import queue
import threading
import urllib.request
EVENTS=frozenset(('requested','awaiting_consent','consent_accepted','consent_not_accepted','consent_expired','cancelled','dispatched','image_received','detection_returned','result_sent','failed'))
_queue=queue.Queue(maxsize=100)
def emit(trace,source,stage):
    if stage not in EVENTS or source not in ('bridge','x6'):return
    try:_queue.put_nowait({'trace':trace,'source':source,'stage':stage})
    except queue.Full:pass

def _work():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while True:
        data=_queue.get()
        try:
            request=urllib.request.Request('http://127.0.0.1:8780/api/action-events',data=json.dumps(data).encode(),headers={'Origin':'http://127.0.0.1:8780','Content-Type':'application/json'})
            with opener.open(request,timeout=.5) as response:response.read(256)
        except Exception:pass
threading.Thread(target=_work,daemon=True).start()
