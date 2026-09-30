import json
import threading
import unittest
import urllib.request
import urllib.error
from prometheus_voice.server import create_server
class PreviewTests(unittest.TestCase):
    def test_read_clear_and_cross_site_protection(self):
        class Client:
            photo=b'\xff\xd8synthetic'
            def camera_preview(self,clear=False):
                if clear:self.photo=None
                return self.photo
        client=Client();server=create_server(None,port=0,x6_client=client)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urllib.request.urlopen(base+'/api/camera/preview') as r:
                self.assertEqual(r.read(),client.photo);self.assertEqual(r.headers['Cache-Control'],'no-store')
            req=urllib.request.Request(base+'/api/camera/preview',headers={'Origin':'http://example.com'})
            with self.assertRaises(urllib.error.HTTPError) as err: urllib.request.urlopen(req)
            self.assertEqual(err.exception.code,403);err.exception.close()
            req=urllib.request.Request(base+'/api/camera/preview/clear',data=b'{}',headers={'Origin':base,'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as r:self.assertEqual(r.status,200)
            with urllib.request.urlopen(base+'/api/camera/preview') as r:self.assertEqual(r.status,204)
        finally:server.shutdown();server.server_close();thread.join()
