import contextlib
import http.client
import io
import json
import threading
import unittest
from unittest.mock import Mock

from prometheus_voice.server import create_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.broker = Mock()
        self.broker.mint.return_value = "temporary-test-token"
        self.server = create_server(self.broker, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def request(self, path, headers=None, method="GET"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            body = response.read()
            if response.getheader("Content-Type", "").startswith("application/json"):
                body = json.loads(body)
            return response.status, dict(response.getheaders()), body
        finally:
            connection.close()

    def test_health_does_not_mint(self):
        status, _, body = self.request("/health")
        self.assertEqual((status, body), (200, {"status": "ok"}))
        self.broker.mint.assert_not_called()
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_token_is_not_cached_and_has_no_cors(self):
        status, headers, body = self.request("/api/voice-token")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"token": "temporary-test-token"})
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertFalse(any(name.lower().startswith("access-control-") for name in headers))
        self.broker.mint.assert_called_once_with(max_session_duration_seconds=150)

    def test_failure_does_not_leak_or_log(self):
        self.broker.mint.side_effect = RuntimeError("private-test-key")
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            status, headers, body = self.request("/api/voice-token")
        self.assertEqual(status, 502)
        self.assertEqual(body, {"error": "voice token unavailable"})
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(log.getvalue(), "")

    def test_rejects_cross_site_and_rebinding_before_mint(self):
        for headers in ({"Origin": "https://external.example"},
                        {"Host": "external.example"},
                        {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/api/voice-token", headers)[0], 403)
        self.broker.mint.assert_not_called()

    def test_unknown_paths_and_methods_do_not_mint(self):
        self.assertEqual(self.request("/unknown")[0], 404)
        self.assertEqual(self.request("/api/voice-token?secret=example")[0], 404)
        self.assertEqual(self.request("/api/voice-token", method="POST")[0], 403)
        self.broker.mint.assert_not_called()

    def test_rejects_public_binding(self):
        with self.assertRaises(ValueError):
            create_server(self.broker, host="0.0.0.0", port=0)

    def test_interface_assets_and_browser_restrictions(self):
        for path, mime in (("/", "text/html"), ("/app.css", "text/css"),
                           ("/app.js", "text/javascript"), ("/voice-session.js", "text/javascript"),
                           ("/voice-audio.js", "text/javascript"), ("/pcm-worklet.js", "text/javascript")):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith(mime))
                self.assertTrue(body)
                self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
                self.assertEqual(headers["Permissions-Policy"], "microphone=(self), camera=()")
        self.broker.mint.assert_not_called()

    def test_static_routes_cannot_read_arbitrary_files(self):
        for path in ("/.env", "/../.env", "/%2e%2e/.env", "/src/prometheus_voice/config.py",
                     "/static/../../.env", "/app.js?file=.env"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)
        self.broker.mint.assert_not_called()


if __name__ == "__main__":
    unittest.main()
