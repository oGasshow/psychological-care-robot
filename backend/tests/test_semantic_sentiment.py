import json
import pytest
from care_core import CoreAnalysisError
from app.care import sentiment
from app.care.worker import Worker
from app.voice import upstream


@pytest.fixture
def semantic(monkeypatch):
    monkeypatch.setenv('DOUBAO_VOICE_API_KEY','fictional-sentiment-key')
    monkeypatch.setenv('ROBOT_CARE_ANALYSIS_ENGINE','doubao_realtime')
    async def neutral(*args,**kwargs):return json.dumps({'label':'neutral'})
    monkeypatch.setattr(upstream,'structured_tool',neutral)


def test_worker_reclassifies_old_unknown_and_exposes_per_message_label(actors,monkeypatch):
    a,_=actors;sid=a.create('sentence-sentiment').json()['recording_session_id']
    text='系统会不会主动了解我的近况？'
    a.send(sid,content=text)
    assert a.send(sid,seq=2,role='assistant',playback_status='unknown',content='我会自然了解。').status_code==201
    before=Worker();before.scan();assert before.step()
    assert a.request('GET',f'/api/robot-insights/sessions/{sid}/summary').json()['emotion_counts']==dict(positive=0,neutral=0,negative=0)
    monkeypatch.setenv('DOUBAO_VOICE_API_KEY','fictional-sentiment-key')
    monkeypatch.setenv('ROBOT_CARE_ANALYSIS_ENGINE','doubao_realtime')
    async def neutral(*args,**kwargs):return '{"label":"neutral"}'
    monkeypatch.setattr(upstream,'structured_tool',neutral)
    worker=Worker();assert worker.scan()==1 and worker.step()
    summary=a.request('GET',f'/api/robot-insights/sessions/{sid}/summary').json()
    assert summary['emotion_counts']==dict(positive=0,neutral=1,negative=0)
    assert summary['source_references'][0]['emotion_label']=='neutral'
    assert summary['source_references'][0]['engine_kind']=='doubao_realtime'
    assert summary['analysis_counts']['excluded']==1
    assert a.messages(sid).json()['items'][0]['content']==text


@pytest.mark.parametrize('label',['positive','neutral','negative','undetermined'])
def test_labels_are_validated_without_erasing_independent_safety(semantic,monkeypatch,label):
    async def answer(*args,**kwargs):return json.dumps({'label':label})
    monkeypatch.setattr(upstream,'structured_tool',answer)
    result=sentiment.analyze('我不想活了。')
    assert result['emotion_label']==(None if label=='undetermined' else label)
    assert result['safety_signal']=='explicit_danger_expression'
    assert result['support']['template_id']=='safety_human_help'
    assert 'fictional-sentiment-key' not in json.dumps(result)


def test_invalid_output_is_failed_not_neutral(semantic,monkeypatch):
    async def bad(*args,**kwargs):return '{"label":"happy"}'
    monkeypatch.setattr(upstream,'structured_tool',bad)
    with pytest.raises(CoreAnalysisError) as caught:sentiment.analyze('虚构文本')
    assert caught.value.code=='sentiment_output_invalid'
    assert caught.value.retryable  # bounded worker retries; never substitute neutral


def test_timeout_remains_retryable_instead_of_inventing_neutral(semantic,monkeypatch):
    async def unavailable(*args,**kwargs):raise upstream.VoiceServiceError('voice_timeout')
    monkeypatch.setattr(upstream,'structured_tool',unavailable)
    with pytest.raises(CoreAnalysisError) as caught:sentiment.analyze('虚构文本')
    assert caught.value.retryable and caught.value.code=='voice_timeout'


def test_model_lease_must_cover_request_timeout(semantic,monkeypatch):
    from app.care.settings import engine_configuration
    monkeypatch.setenv('ROBOT_CARE_LEASE_SECONDS','30')
    with pytest.raises(RuntimeError,match='analysis_lease_too_short'):engine_configuration()


@pytest.mark.parametrize('always_invalid',[False,True])
def test_bad_model_output_retries_are_bounded_and_preserve_danger(actors,semantic,monkeypatch,always_invalid):
    monkeypatch.setenv('ROBOT_CARE_RETRY_SECONDS','0')
    a,_=actors;sid=a.create('retry-output').json()['recording_session_id']
    a.send(sid,content='我有点不想活了都。')
    count=0
    async def sometimes_bad(*args,**kwargs):
        nonlocal count
        count+=1
        return '{"label":"invalid"}' if always_invalid or count==1 else '{"label":"negative"}'
    monkeypatch.setattr(upstream,'structured_tool',sometimes_bad)
    worker=Worker();worker.scan()
    while worker.step():pass
    summary=a.request('GET',f'/api/robot-insights/sessions/{sid}/summary').json()
    assert count==(3 if always_invalid else 2)
    assert summary['analysis_counts']['failed' if always_invalid else 'succeeded']==1
    assert summary['emotion_counts']['negative']==(0 if always_invalid else 1)
    assert summary['danger_notice']['count']==1


def test_demo_launcher_honors_selected_engine(monkeypatch,tmp_path):
    from tools.demo_care import environment
    import dotenv
    monkeypatch.delenv('ROBOT_CARE_ANALYSIS_ENGINE',raising=False)
    monkeypatch.setattr(dotenv,'dotenv_values',lambda path:{'ROBOT_CARE_ANALYSIS_ENGINE':'doubao_realtime'})
    cfg=dict(database=str(tmp_path/'demo.db'),secret='fictional',fixture=str(tmp_path/'fixture.json'))
    assert environment(tmp_path,cfg)['ROBOT_CARE_ANALYSIS_ENGINE']=='doubao_realtime'
    monkeypatch.setenv('ROBOT_CARE_ANALYSIS_ENGINE','rules')
    assert environment(tmp_path,cfg)['ROBOT_CARE_ANALYSIS_ENGINE']=='rules'
