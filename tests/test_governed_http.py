import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from prometheus_voice.evidence import EvidenceLedger
from prometheus_voice.server import create_server
from prometheus_voice.workflow import GovernedWorkflow


class GovernedHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.broker = Mock()
        self.ledger = EvidenceLedger(Path(self.temp.name) / 'http.jsonl')
        self.server = create_server(self.broker, port=0, workflow=GovernedWorkflow(self.ledger))
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown(); self.thread.join(); self.server.server_close(); self.temp.cleanup()

    def post(self, path, payload, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        base = {'Origin': f'http://127.0.0.1:{self.server.server_port}', 'Content-Type': 'application/json'}
        if headers: base.update(headers)
        try:
            connection.request('POST', path, body=json.dumps(payload), headers=base)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_full_http_flow_without_voice_or_network_provider(self):
        status, data = self.post('/api/governed/plan', {'operation': 'math.calculate', 'parameters': {'operator': 'add', 'a': 19, 'b': 23}})
        self.assertEqual(status, 200)
        status, result = self.post('/api/governed/execute', {'plan_id': data['plan_id']})
        self.assertEqual(status, 200)
        self.assertEqual(result['value'], 42)
        self.assertEqual(result['evidence']['status'], 'VERIFIED')
        self.assertTrue(self.post('/api/governed/execute', {'plan_id': data['plan_id']})[1]['replayed'])
        self.broker.mint.assert_not_called()

    def test_cross_origin_and_invalid_content_type_are_rejected(self):
        for headers, expected in [({'Origin': 'https://evil.example'}, 403),
                                  ({'Origin': ''}, 403),
                                  ({'Sec-Fetch-Site': 'cross-site'}, 403),
                                  ({'Content-Type': 'text/plain'}, 415),
                                  ({'Content-Length': '9000'}, 413)]:
            with self.subTest(headers=headers):
                self.assertEqual(self.post('/api/governed/plan', {}, headers)[0], expected)
        self.assertFalse(self.ledger.path.exists())

    def test_malformed_and_nonexistent_requests_fail_closed(self):
        self.assertEqual(self.post('/api/governed/execute', {'plan_id': 'unknown'})[0], 404)
        self.assertEqual(self.post('/api/governed/plan', {'approved': True})[0], 400)
        self.assertEqual(self.post('/not-a-route', {})[0], 404)
