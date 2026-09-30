import json
import unittest
import threading
from http.client import HTTPConnection
from prometheus_voice.server import create_server
from prometheus_voice.x6_client import X6CapabilityClient, X6Unavailable


class Socket:
    def __init__(self, change=lambda data: None):
        self.change = change
        self.sent = []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def send(self, raw): self.sent.append(json.loads(raw))
    def recv(self, timeout):
        assert timeout == 3
        data = {'type': 'x6_capabilities_result', 'request_id': self.sent[0]['request_id'],
                'status': 'ok', 'schema_version': 1, 'scope': 'runtime_capability_registry',
                'capabilities': [{'name': 'vision', 'registered_provider_count': 2, 'availability': 'unknown'}],
                'execution_authorized': False, 'health_checked': False}
        self.change(data)
        return json.dumps(data)


class X6ClientTests(unittest.TestCase):
    def test_real_websocket_exchange_against_isolated_fixture(self):
        from websockets.sync.server import serve
        from websockets.sync.client import connect
        def handler(ws):
            fixture = Socket()
            fixture.send(ws.recv(timeout=3))
            ws.send(fixture.recv(timeout=3))
        with serve(handler, '127.0.0.1', 0) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.socket.getsockname()[1]
            def fixture_connect(uri, **kwargs):
                return connect(f'ws://127.0.0.1:{port}', **kwargs)
            try:
                result = X6CapabilityClient(enabled=True, connect=fixture_connect).snapshot()
                self.assertEqual(result['capabilities'][0]['registered_provider_count'], 2)
            finally:
                server.shutdown()
                thread.join(3)

    def test_http_boundary_rejects_cross_site_before_query(self):
        class Client:
            calls = 0
            def snapshot(self):
                self.calls += 1
                return {'status': 'ok', 'capabilities': []}
        client = Client()
        with create_server(object(), port=0, x6_client=client) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for origin, expected in [('https://untrusted.example', 403),
                                         (f'http://127.0.0.1:{server.server_port}', 200)]:
                    connection = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                    connection.request('GET', '/api/x6/capabilities', headers={'Origin': origin})
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                    response.read()
                    connection.close()
                self.assertEqual(client.calls, 1)
            finally:
                server.shutdown()
                thread.join(3)

    def test_disabled_never_connects(self):
        def fail(*a, **kw): self.fail('Unexpected connection')
        with self.assertRaisesRegex(X6Unavailable, 'X6_NOT_ENABLED'):
            X6CapabilityClient(connect=fail).snapshot()

    def test_fixed_destination_read_only_request_and_sanitized_projection(self):
        socket = Socket(lambda d: d.update(private='secret'))
        def connect(uri, **kwargs):
            self.assertEqual(uri, 'ws://127.0.0.1:8765/capabilities')
            self.assertIsNone(kwargs['proxy'])
            self.assertEqual(kwargs['max_size'], 32768)
            return socket
        result = X6CapabilityClient(enabled=True, connect=connect).snapshot()
        self.assertEqual(socket.sent[0]['type'], 'x6_capabilities')
        self.assertEqual(set(socket.sent[0]), {'type', 'request_id'})
        self.assertEqual(result['capabilities'][0]['name'], 'vision')
        self.assertNotIn('private', result)

    def test_rejects_mismatches_and_false_availability(self):
        changes = [lambda d: d.update(request_id='wrong'), lambda d: d.update(execution_authorized=True),
                   lambda d: d.update(schema_version=True), lambda d: d.update(health_checked=True),
                   lambda d: d['capabilities'][0].update(availability='online'),
                   lambda d: d['capabilities'][0].update(registered_provider_count=True),
                   lambda d: d['capabilities'].append(d['capabilities'][0])]
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(X6Unavailable, 'X6_QUERY_UNAVAILABLE'):
                X6CapabilityClient(enabled=True, connect=lambda *a, **k: Socket(change)).snapshot()

    def test_errors_are_sanitized_and_lock_is_released(self):
        def fail(*a, **kw): raise RuntimeError('private-secret')
        client = X6CapabilityClient(enabled=True, connect=fail)
        for _ in range(2):
            with self.assertRaisesRegex(X6Unavailable, '^X6_QUERY_UNAVAILABLE$'):
                client.snapshot()

    def test_concurrent_query_does_not_connect(self):
        client = X6CapabilityClient(enabled=True)
        client._lock.acquire()
        try:
            with self.assertRaisesRegex(X6Unavailable, 'X6_QUERY_BUSY'): client.snapshot()
        finally: client._lock.release()
