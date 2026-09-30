from __future__ import annotations

import json
import unittest
import traceback
import urllib.error
from unittest.mock import patch

from prometheus_voice.token_broker import (
    AssemblyAIVoiceTokenBroker,
    TokenBrokerError,
)


class FakeResponse:
    status = 200

    def __init__(self, body=None):
        self.body = body if body is not None else json.dumps({"token": "temporary-test-token"}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, limit):
        return self.body[:limit]


class TokenBrokerTests(unittest.TestCase):
    @patch("prometheus_voice.token_broker.urllib.request.urlopen")
    def test_mints_temporary_token_without_exposing_key(self, urlopen):
        urlopen.return_value = FakeResponse()

        broker = AssemblyAIVoiceTokenBroker(api_key="private-test-key")
        token = broker.mint(
            expires_in_seconds=60,
            max_session_duration_seconds=900,
        )

        self.assertEqual(token, "temporary-test-token")

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer private-test-key",
        )
        self.assertNotIn("private-test-key", request.full_url)

    def test_rejects_invalid_token_expiry(self):
        broker = AssemblyAIVoiceTokenBroker(api_key="private-test-key")

        with self.assertRaises(TokenBrokerError):
            broker.mint(expires_in_seconds=0)

        with self.assertRaises(TokenBrokerError):
            broker.mint(expires_in_seconds=601)

    def test_rejects_invalid_session_duration(self):
        broker = AssemblyAIVoiceTokenBroker(api_key="private-test-key")

        with self.assertRaises(TokenBrokerError):
            broker.mint(max_session_duration_seconds=59)

        with self.assertRaises(TokenBrokerError):
            broker.mint(max_session_duration_seconds=10801)

    def test_repr_does_not_expose_api_key(self):
        broker = AssemblyAIVoiceTokenBroker(api_key="private-test-key")
        self.assertNotIn("private-test-key", repr(broker))

    @patch("prometheus_voice.token_broker.urllib.request.urlopen")
    def test_rejects_invalid_payloads(self, urlopen):
        payloads = [b'[]', b'null', b'42', b'"text"', b'{}',
                    b'{"token":null}', b'{"token":123}', b'{"token":" "}',
                    b'{broken', b'\xff', b'x' * 65537]
        for body in payloads:
            with self.subTest(body_type=type(body).__name__, length=len(body)):
                urlopen.return_value = FakeResponse(body)
                with self.assertRaises(TokenBrokerError):
                    AssemblyAIVoiceTokenBroker("synthetic-key").mint()

    @patch("prometheus_voice.token_broker.urllib.request.urlopen")
    def test_upstream_errors_have_sanitized_tracebacks(self, urlopen):
        marker = "SYNTHETIC-SENSITIVE-CONTENT"
        for error in [urllib.error.HTTPError("https://example.invalid", 401, marker, {}, None),
                      urllib.error.URLError(marker), TimeoutError(marker),
                      ConnectionResetError(marker)]:
            with self.subTest(error_type=type(error).__name__):
                urlopen.side_effect = error
                try:
                    AssemblyAIVoiceTokenBroker("synthetic-key").mint()
                except TokenBrokerError:
                    self.assertNotIn(marker, traceback.format_exc())
                else:
                    self.fail("Expected sanitized broker error")

    @patch("prometheus_voice.token_broker.urllib.request.urlopen")
    def test_non_integer_limits_fail_before_network(self, urlopen):
        for name in ("expires_in_seconds", "max_session_duration_seconds"):
            for value in (True, None, "60", 60.5):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(TokenBrokerError):
                        AssemblyAIVoiceTokenBroker("synthetic-key").mint(**{name: value})
        urlopen.assert_not_called()

    @patch("prometheus_voice.token_broker.urllib.request.urlopen")
    def test_read_timeout_is_sanitized(self, urlopen):
        from unittest.mock import Mock
        response = FakeResponse()
        response.read = Mock(side_effect=TimeoutError("SYNTHETIC-SENSITIVE-CONTENT"))
        urlopen.return_value = response
        try:
            AssemblyAIVoiceTokenBroker("synthetic-key").mint()
        except TokenBrokerError:
            self.assertNotIn("SYNTHETIC-SENSITIVE-CONTENT", traceback.format_exc())
        else:
            self.fail("Expected read timeout")


if __name__ == "__main__":
    unittest.main()
