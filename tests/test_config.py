import unittest
from prometheus_voice.config import Settings


class SettingsTests(unittest.TestCase):
    def test_repr_hides_credential(self):
        settings = Settings("synthetic-test-credential")
        self.assertNotIn("synthetic-test-credential", repr(settings))

    def test_container_repr_hides_credential(self):
        settings = Settings("synthetic-test-credential")
        self.assertNotIn("synthetic-test-credential", repr({"settings": settings}))

    def test_credential_and_defaults_remain_available(self):
        settings = Settings("synthetic-test-credential")
        self.assertEqual(settings.assemblyai_api_key, "synthetic-test-credential")
        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.port, 8780)
