from base64 import b64encode

import pytest

from app.robot_records import transaction
from app.voice import sega_live
from app.voice.collection_plan import public_plan
from app.voice.transcripts import Utterance


def test_capture_pairs_only_complete_played_prompts_with_sufficient_audio():
    capture = sega_live.CallAudio('female')
    answer = Utterance('answer', 'user', 'turn_1')
    question = Utterance('question', 'assistant', 'turn_0', text='虚构问题', final=True)
    voiced = b'\x00\x08' * 320
    quiet = bytes(640)
    assert sega_live.speech_frame(voiced) and not sega_live.speech_frame(quiet)
    for require_playback in (False, True):
        if require_playback:
            capture.played.add(question.message_id)
        capture.append(voiced, True)
        capture.start(answer)
        for _ in range(14):
            capture.append(voiced, True)
        capture.append(quiet, False)
        capture.finish_turn(answer, {'question': question})
        assert len(capture.pairs) == int(require_playback)
    assert capture.pairs[0] == (question.message_id, answer.message_id, voiced * 15)


@pytest.mark.parametrize('model_class', [0, 1, None])
def test_saved_voice_marks_only_positive_and_does_not_start_collection(actors, monkeypatch, model_class):
    owner, other = actors
    sid = owner.create('automatic-sega').json()['recording_session_id']
    capture = sega_live.CallAudio('female')
    for i in range(3):
        question, answer = f'question_{i}', f'answer_{i}'
        assert owner.send(sid, 2*i+1, role='assistant', playback_status='unknown', external_message_id=question).status_code == 201
        assert owner.send(sid, 2*i+2, external_message_id=answer).status_code == 201
        capture.pairs.append((question, answer, bytes(9600)))
    result = owner.request('POST', f'/api/robot-records/sessions/{sid}/close',
                           json={'ended_at': '2026-10-28T01:00:00+08:00', 'last_sequence_no': 6})
    assert result.status_code == 200
    monkeypatch.setattr(sega_live, 'extractor_config', lambda: 'test')

    def inference(config, inputs, audio):
        assert len(audio) == 28800 and len(inputs['pairs']) == 3
        if model_class is None:
            return {'status': 'failed'}
        return dict(status='succeeded', model_class=model_class,
                    record_ids=[pair['answer_id'] for pair in inputs['pairs']],
                    question_record_ids=[pair['question_id'] for pair in inputs['pairs']])

    monkeypatch.setattr(sega_live, 'infer', inference)
    sega_live.enqueue(other.uid, sid, capture)
    assert not sega_live.step()
    sega_live.enqueue(owner.uid, sid, capture)
    sega_live.enqueue(owner.uid, sid, capture)
    assert sega_live.step() and not sega_live.step()
    path = '/api/robot-voice/sega/followup'
    monkeypatch.setenv('APP_ENV', 'test')
    assert owner.request('GET', path).json()['marked'] == (model_class == 1)
    assert not other.request('GET', path).json()['marked']
    assert not sega_live.followup(owner.uid, False)['marked']
    assert not public_plan(owner.uid, True)['needs_collection']
    with transaction() as db:
        job = db.get(sega_live.SegaVoiceJob, sid)
        assert job.audio is None and job.inputs == {}
        assert job.state == ('failed' if model_class is None else 'succeeded')
    assert owner.request('DELETE', f'/api/robot-records/sessions/{sid}').status_code == 204
    assert not owner.request('GET', path).json()['marked']


def test_service_endpoints_scope_and_deduplicate(actors, monkeypatch):
    owner, other = actors
    root = '/api/robot-voice/sega/integration'
    input_token, followup_token = 'test-input-token'*3, 'test-followup-token'*3
    monkeypatch.setenv('ROBOT_CARE_SEGA_INPUT_TOKEN', input_token)
    monkeypatch.setenv('ROBOT_CARE_SEGA_FOLLOWUP_TOKEN', followup_token)
    monkeypatch.setattr(sega_live, 'available', lambda: True)
    sid = owner.create('integration').json()['recording_session_id']
    end = f'{root}/sessions/{sid}'
    input_headers = {'Authorization': 'Bearer '+input_token}
    followup_headers = {'Authorization': 'Bearer '+followup_token}
    pcm = b64encode(b'\x00\x08' * (320*15)).decode()
    body = dict(user_id=owner.uid, consent=True, gender='female', sample_rate=16000, pairs=[
        dict(question_message_id=f'q{i}', answer_message_id=f'a{i}', pcm_base64=pcm) for i in range(3)])
    assert owner.client.post(end, headers=followup_headers, json=body).status_code == 401
    assert owner.client.post(end, headers=input_headers, json={**body,'user_id':other.uid}).status_code == 404
    assert owner.client.post(end, headers=input_headers, json=body).status_code == 409
    for i in range(3):
        owner.send(sid, 2*i+1, role='assistant', playback_status='completed', external_message_id=f'q{i}')
        owner.send(sid, 2*i+2, external_message_id=f'a{i}')
    owner.request('POST', f'/api/robot-records/sessions/{sid}/close',
                  json={'ended_at':'2026-10-28T01:00:00+08:00','last_sequence_no':6})
    assert owner.client.post(end, headers=input_headers, json={**body,'consent':False}).status_code == 422
    first = owner.client.post(end, headers=input_headers, json=body)
    assert first.status_code == 202 and first.json()['status'] == 'pending' and not first.json()['duplicate']
    assert owner.client.post(end, headers=input_headers, json=body).json()['duplicate']
    followup = f'{root}/followups/{owner.uid}?is_test=true'
    assert owner.client.get(followup, headers=input_headers).status_code == 401
    result = owner.client.get(followup, headers=followup_headers)
    assert result.status_code == 200 and result.json()['marked'] is False
    assert result.headers['cache-control'] == 'no-store'
