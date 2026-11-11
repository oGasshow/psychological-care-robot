"""Pure transcript/interrupt state: stable IDs, current turns, no audio devices."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')

@dataclass
class Utterance:
    key: str
    role: str
    turn_id: str
    text: str = ''
    final: bool = False
    recorded: bool = False
    interrupted: bool = False
    done: bool = False
    occurred_at: str = ''

    @property
    def message_id(self):
        return self.role+'_'+hashlib.sha256(self.key.encode()).hexdigest()[:32]

    def public(self, final=False):
        return dict(type='transcript.final' if final else 'transcript.delta', message_id=self.message_id,
                    role=self.role, text=self.text, turn_id=self.turn_id, interrupted=self.interrupted,occurred_at=self.occurred_at)

    def wire(self):
        return dict(external_message_id=self.message_id, turn_id=self.turn_id, role=self.role,
                    content=self.text, occurred_at=self.occurred_at,
                    text_status='completed' if self.final else 'canceled',
                    playback_status='not_applicable' if self.role=='user' else 'interrupted' if self.interrupted else 'unknown')

class Transcripts:
    def __init__(self):
        self.users, self.responses, self.aliases = {}, {}, {}
        self.active_user = None
        self.active_response = None
        self.turn = 0
        self.waiting_cancel = False

    def user(self, event):
        named = event.get('item_id') or event.get('question_id')
        current = self.users.get(self.active_user)
        if named and named not in self.users and current and not current.final and not current.text and current.key.startswith('user_turn_'):
            # The provider's .started may have an empty item_id. Adopt the real
            # ASR ID on the first delta instead of creating a phantom extra turn.
            del self.users[self.active_user]
            current.key=named;self.users[named]=current
        key = named or (self.active_user if current and not current.final else None)
        if not key:
            key = f'user_turn_{self.turn+1}'
        if key not in self.users:
            self.turn += 1
            self.users[key] = Utterance(key,'user',f'turn_{self.turn}',occurred_at=utc_now())
        self.active_user = key
        return self.users[key]

    def response(self, event):
        question, response = event.get('question_id'), event.get('response_id')
        question_key='question_'+question if question else None
        key = (self.aliases.get(question_key) if question_key else None) or (question_key or self.aliases.get(response) or response or self.active_response or 'greeting')
        if self.turn==0 and self.active_response=='greeting':key='greeting'
        if question_key:self.aliases[question_key]=key
        if response:
            self.aliases[response] = key
        if key not in self.responses:
            self.responses[key] = Utterance(key,'assistant',f'turn_{self.turn}',occurred_at=utc_now())
        entry = self.responses[key]
        if not entry.interrupted:
            self.active_response = key
        return entry

    def interrupt(self):
        active = [u for u in self.responses.values() if not u.done and not u.interrupted]
        for entry in active:
            entry.interrupted = True
        self.waiting_cancel = bool(active)
        return active

    def apply(self, event):
        kind = event['type']
        if kind.startswith('conversation.item.input_audio_transcription.'):
            entry = self.user(event)
            if kind.endswith('.started'):
                return entry, None
            if entry.final:
                return entry, None
            if kind.endswith('.delta'):
                entry.text = event.get('text') or (entry.text + event.get('delta',''))
                return entry, entry.public()
            if kind.endswith('.completed'):
                entry.text = event.get('text') or event.get('transcript') or entry.text
                entry.final = True
                return entry, entry.public(True) if entry.text.strip() else None
            if kind.endswith('.failed'):
                return entry, dict(type='status',state='transcription_failed',message='这句话未能识别清楚，可以再说一次。')
        if kind.startswith('response.output_'):
            if self.waiting_cancel and not event.get('question_id') and not event.get('response_id'):
                return None, None
            entry = self.response(event)
            if entry.interrupted:
                return entry, None
            if kind=='response.output_text.delta' and not entry.final:
                entry.text += event.get('delta','')
                return entry, entry.public()
            if kind=='response.output_text.done' and not entry.final:
                entry.text = event.get('text') or event.get('transcript') or entry.text
                entry.final = True
                return entry, entry.public(True) if entry.text.strip() else None
            if kind=='response.output_audio.done':entry.done=True
            return entry, None
        if kind=='response.canceled':
            # An ACK for the old response must not reset/discard a newer response.
            self.waiting_cancel = False
        return None, None

    def unfinished(self):
        return [u for u in [*self.users.values(),*self.responses.values()] if u.text.strip() and not u.recorded]
