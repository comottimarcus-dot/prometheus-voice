import unittest
from unittest.mock import patch
from prometheus_voice.action_timeline import ActionTimeline
class TimelineTests(unittest.TestCase):
    def test_bounded_expiring_and_no_payload(self):
        t=ActionTimeline();e={'trace':'a'*32,'source':'bridge','stage':'requested'}
        for _ in range(100):t.publish(e)
        self.assertEqual(len(t.snapshot()['events']),80)
        with self.assertRaises(ValueError):t.publish({**e,'text':'private'})
        with self.assertRaises(ValueError):t.publish({**e,'stage':'verified'})
        with patch('prometheus_voice.action_timeline.time.time',return_value=10**12):self.assertEqual(t.snapshot()['events'],[])
    def test_http_rejects_cross_origin_and_returns_observed_events(self):
        import json,threading,urllib.request,urllib.error
        from prometheus_voice.server import create_server
        server=create_server(None,port=0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            event={'trace':'a'*32,'source':'x6','stage':'image_received'}
            payload=json.dumps(event).encode()
            request=urllib.request.Request(base+'/api/action-events',data=payload,headers={'Origin':base,'Content-Type':'application/json'})
            with urllib.request.urlopen(request) as response:self.assertEqual(response.status,200)
            with urllib.request.urlopen(base+'/api/action-events') as response:
                rows=json.load(response)['events'];self.assertEqual(rows[0]['stage'],'image_received');self.assertEqual(len(rows),1)
            request=urllib.request.Request(base+'/api/action-events',data=payload,headers={'Origin':'http://example.com','Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
            self.assertEqual(error.exception.code,403);error.exception.close()
        finally:server.shutdown();server.server_close();thread.join()
