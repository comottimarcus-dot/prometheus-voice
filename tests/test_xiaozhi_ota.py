import json
import unittest
from dataclasses import replace
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from prometheus_voice.config import load_settings
from prometheus_voice.xiaozhi_ota import create_server


class XiaoZhiOtaTests(unittest.TestCase):
    def test_response_targets_isolated_bridge(self):
        with TemporaryDirectory() as directory:
            env = Path(directory) / '.env'
            env.write_text('ASSEMBLYAI_API_KEY=test\nPROMETHEUS_XIAOZHI_TOKEN=synthetic-device-token\nPROMETHEUS_XIAOZHI_PUBLIC_HOST=192.0.2.1\n', encoding='utf-8')
            env.chmod(0o600)
            settings = load_settings(env)
            self.assertEqual(settings.ota_port, 8001)
            server = create_server(replace(settings, ota_host='127.0.0.1', ota_port=0))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            try:
                connection.request('POST', '/', body=b'{}', headers={'Content-Type': 'application/json'})
                response = connection.getresponse()
                payload = json.loads(response.read())
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                self.assertEqual(payload['websocket'], {
                    'url': 'ws://192.0.2.1:8766',
                    'token': 'synthetic-device-token',
                    'version': 2,
                })
                self.assertNotIn('assemblyai_api_key', payload)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
