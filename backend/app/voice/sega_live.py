"""Collect opted-in audio and mark eligible accounts from completed SEGA jobs."""
import hashlib
import json
import logging
import os
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, JSON, LargeBinary, String

from ..care.models import InputRevision
from ..database import Base
from ..robot_records import RecordError, RecordMessage, RecordSession, now, summary, transaction
from . import sega

FRAME = struct.Struct('<320h')
MIN_FRAMES = 15
MAX_FRAMES = 3000  # 60 seconds per selected answer.
MAX_INPUT_AGE = 900
log = logging.getLogger(__name__)


def silence_seconds():
    try:
        return max(15, min(300, int(os.getenv('ROBOT_CARE_VOICE_SILENCE_SECONDS', '60'))))
    except ValueError:
        return 60


def speech_frame(pcm):
    return sum(sample * sample for sample in FRAME.unpack(pcm)) >= 320 * 492**2


class CallAudio:
    def __init__(self, gender):
        self.gender = gender
        self.reset()
        self.played = set()
        self.pairs = []

    def reset(self):
        self.pcm = bytearray()
        self.last_voice = 0
        self.voice_frames = 0
        self.overflow = False
        self.turn = None
        self.played_at_start = set()

    def append(self, pcm, speech):
        if self.overflow or not (speech or self.pcm):
            return
        if len(self.pcm) >= FRAME.size * MAX_FRAMES:
            self.overflow = True
            self.pcm.clear()
            return
        if not self.pcm:
            self.played_at_start = self.played.copy()
        self.pcm.extend(pcm)
        if speech:
            self.last_voice = len(self.pcm)
            self.voice_frames += 1

    def start(self, entry):
        if self.turn and self.turn != entry.turn_id:
            self.reset()
        self.turn = entry.turn_id

    def finish_turn(self, entry, responses):
        if self.turn == entry.turn_id and not self.overflow and self.voice_frames >= MIN_FRAMES:
            previous = f'turn_{int(entry.turn_id.split("_")[-1]) - 1}'
            questions = [q for q in responses.values() if q.turn_id == previous and q.final
                         and not q.interrupted and q.text.strip() and q.message_id in self.played_at_start]
            if len(questions) == 1:
                self.pairs.append((questions[0].message_id, entry.message_id, bytes(self.pcm[:self.last_voice])))
                del self.pairs[:-3]
        self.reset()


class SegaVoiceJob(Base):
    __tablename__ = 'robot_voice_sega_jobs'
    session_id = Column(Integer, ForeignKey('robot_record_sessions.id'), primary_key=True)
    owner = Column(Integer, nullable=False, index=True)
    is_test = Column(Boolean, nullable=False)
    state = Column(String(24), nullable=False, index=True)
    expires = Column(Float, nullable=False)
    lease = Column(Float, nullable=False, default=0)
    token = Column(String(40))
    inputs = Column(JSON, nullable=False)
    audio = Column(LargeBinary)
    result = Column(JSON)


def extractor_config():
    from ..deployment import edge
    from ..private_temp import volatile_available
    if edge() and not volatile_available():return None
    path = os.getenv('ROBOT_CARE_SEGA_EXTRACTOR_CONFIG')
    if not path:
        return None
    try:
        path = Path(path).resolve(strict=True)
        settings = json.loads(path.read_text(encoding='utf-8-sig'))
        for key in ('answer_encoder', 'question_encoder', 'zh_en_translation', 'emotion_classifier'):
            model = Path(settings[key])
            if (not model.is_absolute() or not (model/'config.json').is_file()
                    or not ((model/'model.safetensors').is_file() or (model/'model.safetensors.index.json').is_file())):
                return None
        window, hop = settings['audio_window_ms'], settings['audio_hop_ms']
        if type(window) is int and type(hop) is int and 250 <= window <= 5000 and 20 <= hop <= window:
            return path
    except (OSError, ValueError, KeyError, TypeError):
        return None


def available():
    return extractor_config() is not None and sega.status()['installed']


def allowed_for(is_test):
    if is_test:
        return True
    path = extractor_config()
    if path is None:
        return False
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig')).get('test_only', True) is False
    except (OSError, ValueError, AttributeError):
        return False


def enqueue(uid, sid, capture, *, strict=False):
    with transaction(True) as db:
        session = db.get(RecordSession, sid)
        if not session or session.user_id != uid or session.state == 'deleted':
            if strict:
                raise RecordError(404, 'not_found')
            return
        if type(session.is_test) is not bool or not summary(db, session)['is_complete']:
            if strict:
                raise RecordError(409, 'sega_session_not_complete')
            return
        if not allowed_for(session.is_test):
            if strict:
                raise RecordError(409, 'sega_extractor_test_only')
            return
        existing = db.get(SegaVoiceJob, sid)
        if existing and (not strict or existing.state != 'insufficient_data'):
            return {'session_id': sid, 'status': existing.state, 'duplicate': True}
        messages = {m.external_message_id: m for m in db.query(RecordMessage).filter_by(
            recording_session_id=sid, text_status='completed')}
        pairs, pcm = [], bytearray()
        last = 0
        for question_key, answer_key, samples in capture.pairs:
            question, answer = messages.get(question_key), messages.get(answer_key)
            if (not question or not answer or question.role != 'assistant' or answer.role != 'user'
                    or question.playback_status == 'interrupted'
                    or not last < question.sequence_no < answer.sequence_no):
                continue
            pairs.append(dict(question_id=question.id, answer_id=answer.id, offset=len(pcm), size=len(samples)))
            pcm.extend(samples)
            last = answer.sequence_no
        complete = len(pairs) == 3
        if strict and not complete:
            raise RecordError(422, 'sega_invalid_question_answer_sources')
        job = existing or SegaVoiceJob(session_id=sid, owner=uid, is_test=session.is_test)
        job.state = 'pending' if complete else 'insufficient_data'
        job.expires = time.time() + MAX_INPUT_AGE
        job.inputs = {'pairs': pairs, 'gender': capture.gender} if complete else {}
        job.audio = bytes(pcm) if complete else None
        db.add(job)
        return {'session_id': sid, 'status': job.state, 'duplicate': False}


def infer(config, inputs, audio):
    python, _ = sega.config()
    env = {key: val for key, val in os.environ.items() if not any(
        word in key.upper() for word in ('KEY','TOKEN','PASSWORD','SECRET','DATABASE_URL'))}
    from ..private_temp import sensitive_directory
    with sensitive_directory('sega-voice-') as directory:
        path = Path(directory)
        (path/'input.json').write_text(json.dumps(inputs, ensure_ascii=False), encoding='utf-8')
        (path/'audio.pcm').write_bytes(audio)
        bundle = path/'features.npz'
        result = subprocess.run([str(python), '-X', 'utf8', str(sega.BACKEND/'tools/sega_extract.py'),
            str(config), str(path/'input.json'), str(path/'audio.pcm'), str(bundle)], env=env,
            capture_output=True, timeout=120, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            return {'status': 'failed', 'error_type': 'feature_extraction_failed'}
        value = sega.execute(features=bundle)
        if value['status'] == 'succeeded':
            value['source_kind'] = 'automatic_voice_experimental'
            value['feature_sha256'] = hashlib.sha256(bundle.read_bytes()).hexdigest()
        return value


def revision(db, rid):
    value = db.get(InputRevision, rid)
    return value.revision if value else 0


def step():
    config = extractor_config()
    timestamp = time.time()
    with transaction(True) as db:
        db.query(SegaVoiceJob).filter(SegaVoiceJob.audio.is_not(None), SegaVoiceJob.expires <= timestamp).update(
            {SegaVoiceJob.state: 'expired', SegaVoiceJob.audio: None, SegaVoiceJob.inputs: {}, SegaVoiceJob.token: None})
        if config is None:
            return False
        jobs = db.query(SegaVoiceJob).filter(SegaVoiceJob.state.in_(('pending', 'running')), SegaVoiceJob.lease <= timestamp)
        if not allowed_for(False):
            jobs = jobs.filter_by(is_test=True)
        job = jobs.order_by(SegaVoiceJob.session_id).first()
        if not job:
            return False
        sid, token, audio = job.session_id, uuid4().hex, job.audio
        job.state, job.token, job.lease = 'running', token, timestamp + 300
        inputs = {'pairs': [], 'gender': job.inputs['gender']}
        revisions = {}
        for pair in job.inputs['pairs']:
            question, answer = (db.get(RecordMessage, pair[key]) for key in ('question_id', 'answer_id'))
            if not question or not answer or any(revision(db, row.id) != 0 for row in (question, answer)):
                job.state, job.audio, job.inputs, job.token = 'source_changed', None, {}, None
                return True
            inputs['pairs'].append({**pair, 'question': question.content, 'answer': answer.content})
            revisions.update({question.id: 0, answer.id: 0})
    try:
        value = infer(config, inputs, audio)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        value = {'status': 'failed', 'error_type': 'sega_execution_unavailable'}
    with transaction(True) as db:
        job = db.get(SegaVoiceJob, sid)
        if not job or job.token != token:
            return True
        job.audio, job.inputs, job.token = None, {}, None
        if job.expires <= time.time():
            job.state = 'expired'
        elif any(revision(db, rid) != version for rid, version in revisions.items()):
            job.state = 'source_changed'
        elif (value.get('status') == 'succeeded' and type(value.get('model_class')) is int
              and value['model_class'] in (0, 1)
              and value.get('record_ids') == [p['answer_id'] for p in inputs['pairs']]
              and value.get('question_record_ids') == [p['question_id'] for p in inputs['pairs']]):
            job.state = 'succeeded'
            job.result = {**value, 'input_revisions': revisions, 'analyzed_at': now()}
        else:
            job.state = 'failed'
        owner, is_test = job.owner, job.is_test
    from .collection_plan import prepare_sega_plan
    prepare_sega_plan(owner, is_test)
    return True


def run(stop):
    while not stop.is_set():
        try:
            if step():
                continue
        except Exception:
            # Preserve pending jobs for the next poll without logging private inputs.
            log.warning('sega_voice_poll_failed')
        stop.wait(2)


def followup(uid, is_test):
    from .care_status import profile
    return profile(uid, is_test)
