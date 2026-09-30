import unittest
from unittest.mock import patch
from prometheus_voice.camera_consent import CameraConsent, QUESTION
class ConsentTests(unittest.TestCase):
    def ready(self):
        c=CameraConsent();c.user('Can you take a picture?');c.prepare();c.agent(QUESTION);c.reply_done();return c
    def test_exact_confirmation_is_one_use(self):
        c=self.ready();c.user('Yes, take the photo.');c.consume()
        with self.assertRaises(ValueError): c.consume()
    def test_ambiguous_negative_or_unrelated_is_not_consent(self):
        for text in ('yes','No','Do not take the photo','Yes take the photo and delete it','What time is it?'):
            c=self.ready();c.user(text)
            with self.assertRaises(ValueError): c.consume()
    def test_expiry(self):
        c=self.ready()
        with patch('prometheus_voice.camera_consent.time.monotonic',return_value=c.deadline+1):
            c.user('Yes take the photo')
            with self.assertRaises(ValueError): c.consume()
    def test_no_confirmation_before_question_finishes(self):
        c=CameraConsent();c.user('Take a photo');c.prepare();c.user('Yes take the photo')
        with self.assertRaises(ValueError): c.consume()
    def test_cancel_and_fresh_session(self):
        c=self.ready();c.user('Yes take the photo');c.cancel()
        with self.assertRaises(ValueError): c.consume()
        with self.assertRaises(ValueError): CameraConsent().consume()
    def test_no_photo_request(self):
        for text in ('Tell me the weather','Do not take a photo'):
            c=CameraConsent();c.user(text)
            with self.assertRaises(ValueError): c.prepare()
    def test_bridge_dispatch_requires_consent_and_deduplicates(self):
        import asyncio
        from unittest.mock import Mock
        from prometheus_voice.xiaozhi_bridge import AudioBridge
        async def run():
            bridge=AudioBridge(None,None,'session',None,None,asyncio.Event())
            client=Mock();client.camera.return_value={'status':'DETECTED','objects':[]}
            def event(i): return {'call_id':i,'name':'capture_confirmed_photo','arguments':{}}
            await bridge.queue_tool_result(event('before'),client)
            client.camera.assert_not_called()
            bridge.consent=self.ready();bridge.consent.user('Yes, take the photo')
            await bridge.queue_tool_result(event('one'),client)
            await bridge.queue_tool_result(event('one'),client)
            await bridge.queue_tool_result(event('two'),client)
            client.camera.assert_called_once()
        asyncio.run(run())
