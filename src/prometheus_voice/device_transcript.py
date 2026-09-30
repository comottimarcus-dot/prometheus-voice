"""Bounded, short-lived device transcript; never persisted or logged."""
import re
import threading
import time

class DeviceTranscript:
    def __init__(self):
        self.lock = threading.Lock()
        self.session = None
        self.rows = []
        self.updated = 0

    def publish(self, event):
        if not isinstance(event, dict) or set(event) != {'session', 'role', 'text'}:
            raise ValueError('Invalid transcript event')
        session, role, text = event['session'], event['role'], event['text']
        if (not isinstance(session, str) or not re.fullmatch('[a-f0-9]{32}', session)
                or role not in ('user', 'agent') or not isinstance(text, str) or not 1 <= len(text) <= 4000):
            raise ValueError('Invalid transcript event')
        with self.lock:
            if self.session != session or time.monotonic()-self.updated > 180:
                self.rows = []
            self.session = session
            self.rows.append({'role':role, 'text':text})
            self.rows = self.rows[-40:]
            self.updated = time.monotonic()

    def snapshot(self):
        with self.lock:
            if time.monotonic()-self.updated > 180:
                self.rows = []; self.session = None
            return {'session':self.session, 'rows':[dict(row) for row in self.rows]}
