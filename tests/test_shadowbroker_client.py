from datetime import UTC, datetime, timedelta
import unittest
from prometheus_voice.x6_client import validate_information, X6CapabilityClient


def payload():
    return {'type': 'x6_information_result', 'request_id': 'q', 'status': 'ok',
            'schema_version': 1, 'provenance': 'shadowbroker', 'execution_authorized': False,
            'source_age_seconds': 0, 'source_updated_at': datetime.now(UTC).isoformat(),
            'stories': [{'title': 'Headline', 'source': 'Publisher', 'published': '2026-09-25', 'link': 'https://example.test/story'}]}


class ShadowBrokerClientTests(unittest.TestCase):
    def test_projection_strips_private_fields_and_preserves_source(self):
        data = payload(); data['secret'] = 'private'
        result = validate_information(data, 'q')
        self.assertNotIn('secret', result)
        self.assertEqual(result['stories'][0]['source'], 'Publisher')

    def test_empty_stories_are_valid(self):
        data = payload(); data['stories'] = []
        self.assertEqual(validate_information(data, 'q')['stories'], [])

    def test_wrong_identity_freshness_and_oversized_results_fail(self):
        for changes in ({'request_id': 'other'}, {'schema_version': True}, {'execution_authorized': True},
                        {'source_age_seconds': 901}, {'source_updated_at': (datetime.now(UTC)-timedelta(hours=1)).isoformat()},
                        {'stories': payload()['stories'] * 4}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_information({**payload(), **changes}, 'q')

    def test_links_cannot_execute_script(self):
        data = payload(); data['stories'][0]['link'] = 'javascript:alert(1)'
        self.assertEqual(validate_information(data, 'q')['stories'][0]['link'], '')

    def test_news_uses_only_fixed_information_query(self):
        import json
        class Socket:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def send(self, raw): self.query = json.loads(raw)
            def recv(self, timeout):
                assert timeout == 10
                assert self.query['type'] == 'x6_information'
                assert set(self.query) == {'type', 'request_id'}
                return json.dumps({**payload(), 'request_id': self.query['request_id']})
        def connect(url, **kwargs):
            self.assertEqual(url, 'ws://127.0.0.1:8765/information')
            self.assertIsNone(kwargs['proxy'])
            return Socket()
        self.assertEqual(X6CapabilityClient(enabled=True, connect=connect).information()['status'], 'ok')
