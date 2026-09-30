from datetime import UTC, datetime, timedelta
import unittest
from prometheus_voice.x6_client import validate_sentinel, X6CapabilityClient


def payload():
    return dict(type='x6_sentinel_result', request_id='q', status='ok', schema_version=1,
                node='sentinel-nm0', source='open-meteo', source_updated_at=datetime.now(UTC).isoformat(),
                source_age_seconds=0, cells=25, echoes=0, max_precipitation_mm=0,
                motion='waiting', bearing_deg=None, execution_authorized=False,
                node_identity_verified=False, source_transport_verified=False)


class SentinelClientTests(unittest.TestCase):
    def test_projects_public_fields(self):
        result = validate_sentinel({**payload(), 'private': 'secret'}, 'q')
        self.assertNotIn('private', result)
        self.assertEqual(result['motion'], 'waiting')

    def test_invalid_or_stale_snapshots_fail(self):
        for changes in ({'request_id': 'bad'}, {'node': 'other'}, {'cells': 24}, {'echoes': True},
                        {'source_age_seconds': 1201}, {'node_identity_verified': True},
                        {'motion': 'moving'}, {'max_precipitation_mm': float('nan')},
                        {'source_updated_at': (datetime.now(UTC)-timedelta(hours=1)).isoformat()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_sentinel({**payload(), **changes}, 'q')

    def test_fixed_read_only_query(self):
        import json
        class Socket:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def send(self, raw): self.query = json.loads(raw)
            def recv(self, timeout):
                assert timeout == 3 and self.query['type'] == 'x6_sentinel'
                assert set(self.query) == {'type', 'request_id'}
                return json.dumps({**payload(), 'request_id': self.query['request_id']})
        def connect(url, **kwargs):
            self.assertEqual(url, 'ws://127.0.0.1:8765/sentinel')
            return Socket()
        self.assertEqual(X6CapabilityClient(enabled=True, connect=connect).sentinel()['cells'], 25)
