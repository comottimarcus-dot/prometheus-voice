import re
import threading
import time
from collections import deque
STAGES=frozenset(('requested','awaiting_consent','consent_accepted','consent_not_accepted','consent_expired','cancelled','dispatched','image_received','detection_returned','result_sent','failed'))
class ActionTimeline:
    def __init__(self):self.lock=threading.Lock();self.rows=deque(maxlen=80);self.sequence=0
    def publish(self,event):
        if (not isinstance(event,dict) or set(event)!={'trace','source','stage'} or not isinstance(event['trace'],str) or not re.fullmatch('[a-f0-9]{32}',event['trace']) or event['source'] not in ('bridge','x6') or event['stage'] not in STAGES):raise ValueError('Invalid event')
        with self.lock:
            self.sequence+=1
            self.rows.append({**event,'id':self.sequence,'time':time.time()})
    def snapshot(self):
        with self.lock:
            cutoff=time.time()-300
            while self.rows and self.rows[0]['time']<cutoff:self.rows.popleft()
            return {'events':list(self.rows)}
