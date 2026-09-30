import unittest
from unittest.mock import patch
from prometheus_voice.device_transcript import DeviceTranscript
class TranscriptTests(unittest.TestCase):
    def test_bound_expiry_and_session_reset(self):
        store=DeviceTranscript()
        with patch('prometheus_voice.device_transcript.time.monotonic',return_value=100):
            for _ in range(45): store.publish({'session':'a'*32,'role':'user','text':'hello'})
            self.assertEqual(len(store.snapshot()['rows']),40)
            store.publish({'session':'b'*32,'role':'agent','text':'Hi'})
            self.assertEqual(len(store.snapshot()['rows']),1)
        with patch('prometheus_voice.device_transcript.time.monotonic',return_value=281):
            self.assertEqual(store.snapshot()['rows'],[])
    def test_invalid_payload_is_not_stored(self):
        store=DeviceTranscript()
        for event in ({}, {'session':'a'*32,'role':'tool','text':'secret'}, {'session':'a'*32,'role':'user','text':'x'*4001}):
            with self.assertRaises(ValueError): store.publish(event)
        self.assertEqual(store.snapshot()['rows'],[])
    def test_http_delivery_and_cross_origin_rejection(self):
        import threading, json, urllib.request, urllib.error
        from prometheus_voice.server import create_server
        server=create_server(None,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url='http://127.0.0.1:'+str(server.server_port)
        try:
            payload=json.dumps({'session':'a'*32,'role':'user','text':'synthetic hello'}).encode()
            req=urllib.request.Request(url+'/api/device/transcript',data=payload,headers={'Content-Type':'application/json','Origin':url})
            with urllib.request.urlopen(req) as response: self.assertEqual(response.status,200)
            with urllib.request.urlopen(url+'/api/device/transcript') as response:
                self.assertEqual(json.load(response)['rows'][0]['text'],'synthetic hello')
            req=urllib.request.Request(url+'/api/device/transcript',data=payload,headers={'Content-Type':'application/json','Origin':'http://example.com'})
            with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(req)
            self.assertEqual(error.exception.code,403)
        finally:
            server.shutdown();server.server_close();thread.join()
