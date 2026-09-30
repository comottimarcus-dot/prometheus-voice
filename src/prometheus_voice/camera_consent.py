"""Session-local, one-use spoken camera consent; never accepts model arguments as consent."""
import re
import time

QUESTION = 'May I take one photo now and analyze it?'

def normalized(text):
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', text.lower()).split())

class CameraConsent:
    def __init__(self):
        self.state = 'idle'
        self.deadline = 0
        self.requested = False
        self.question_seen = False

    def user(self, text):
        words = normalized(text)
        if self.state == 'waiting':
            self.state = 'confirmed' if time.monotonic() < self.deadline and words == 'yes take the photo' else 'idle'
            return
        self.state = 'idle'
        self.requested = bool(re.search(r'\b(take|capture) (a |one |the )?(photo|picture)\b', words)) and not re.search(r'\b(no|not|dont|don t|never|cancel)\b',words)

    def prepare(self):
        if not self.requested: raise ValueError('No explicit photo request')
        self.requested = False
        self.state = 'question'
        self.question_seen = False
        return {'status':'CONFIRMATION_REQUIRED', 'say':QUESTION,
                'instruction':'Ask this question. Tell the user to say Yes, take the photo. Do not capture yet.'}

    def agent(self, text):
        if self.state == 'question' and normalized(QUESTION) in normalized(text):
            self.question_seen = True

    def reply_done(self):
        if self.state == 'question' and self.question_seen:
            self.state = 'waiting'
            self.deadline = time.monotonic()+20

    def cancel(self):
        self.state = 'idle'; self.requested = False; self.question_seen = False

    def consume(self):
        allowed = self.state == 'confirmed' and time.monotonic() < self.deadline
        self.cancel()
        if not allowed: raise ValueError('Spoken consent missing or expired')
