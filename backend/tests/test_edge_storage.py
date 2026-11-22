"""Edge roles never spool business records to a device database."""
from types import SimpleNamespace
import uuid
import pytest
from app.voice import recording
from app.voice.transcripts import Utterance, utc_now
from app.main import app
from app.deployment import require_compute


def use_edge(monkeypatch, actor, fail=None):
    monkeypatch.setenv('ROBOT_CARE_DEPLOYMENT_ROLE','edge')
    monkeypatch.setattr(recording,'REMOTE_PENDING',{})
    def no_disk(*a,**kw):raise AssertionError('Local business spool accessed')
    monkeypatch.setattr(recording,'directory',no_disk)
    monkeypatch.setattr(recording,'Outbox',no_disk)
    class Transport:
        def __init__(self,base,token,timeout):self.token=token
        def request(self,method,path,**kw):
            if fail and fail(method,path,kw):raise OSError('Synthetic network outage')
            return actor.client.request(method,path,headers={'Authorization':'Bearer '+self.token},**kw)
        def close(self):pass
    monkeypatch.setattr(recording,'Transport',Transport)
    return recording.Recorder(actor.uid,actor.token,'http://localhost',is_test=True)


def entry():return Utterance(uuid.uuid4().hex,'user','turn_1',text='虚构测试近况',final=True,occurred_at=utc_now())


def test_edge_records_go_to_shared_database_without_disk_queue(actors,monkeypatch):
    a,b=actors;recorder=use_edge(monkeypatch,a)
    assert recorder.persistent_local is False
    line=entry();recorder.enqueue(line);recorder.enqueue(line)
    assert len(a.messages(recorder.sid).json()['items'])==1
    assert b.detail(recorder.sid).status_code==404
    assert recorder.finish()['type']=='records.saved'
    assert a.detail(recorder.sid).json()['is_complete']
    assert recording.retry(a.uid,a.token,'http://localhost')['pending']==0


def test_edge_does_not_acknowledge_an_unavailable_server(actors,monkeypatch):
    a,_=actors;outage={'active':False}
    def fails(method,path,kwargs):return outage['active'] and method=='POST'
    recorder=use_edge(monkeypatch,a,fails);outage['active']=True
    recorder.enqueue(entry())
    assert recorder.sync_partial()['type']=='records.pending'
    assert recorder.finish()['type']=='records.pending'
    assert not a.detail(recorder.sid).json()['is_complete']
    outage['active']=False
    assert recording.retry(a.uid,a.token,'http://localhost')['pending']==0
    assert a.detail(recorder.sid).json()['is_complete']


def test_edge_can_retry_unacknowledged_text_in_memory(actors,monkeypatch):
    a,_=actors;outage={'active':True}
    def fails(method,path,kwargs):return outage['active'] and path.endswith('/messages')
    recorder=use_edge(monkeypatch,a,fails);recorder.enqueue(entry())
    assert len(recorder.pending)==1
    outage['active']=False
    assert recorder.sync_partial()['pending']==0
    assert len(a.messages(recorder.sid).json()['items'])==1
    assert recorder.finish()['type']=='records.saved'


def test_central_service_rejects_user_processing_and_registration(actors,monkeypatch):
    a,_=actors;monkeypatch.setenv('ROBOT_CARE_DEPLOYMENT_ROLE','central')
    assert a.client.get('/api/deployment').json()=={'role':'central'}
    for path in ['/api/robot-voice/config','/api/robot-records/sessions','/api/robot-insights/assessments']:
        assert a.request('GET',path).status_code==403
    assert a.client.post('/api/auth/register',json={'username':'forbidden_user','password':'fictional-only'}).status_code==403
    assert a.client.post('/api/auth/login',json={'username':'virtual_a','password':'fictional-only'}).status_code==403
    with pytest.raises(RuntimeError,match='not_allowed'):require_compute()


def test_edge_sensitive_features_refuse_persistent_temp_storage(monkeypatch):
    from app import private_temp
    monkeypatch.setenv('ROBOT_CARE_DEPLOYMENT_ROLE','edge')
    monkeypatch.setattr(private_temp,'volatile_available',lambda:False)
    with pytest.raises(RuntimeError,match='requires_tmpfs'):
        with private_temp.sensitive_directory('synthetic-test-'):
            raise AssertionError('Should not allocate a disk directory')
