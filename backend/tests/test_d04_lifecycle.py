"""D04 mock identities never query or signal an unrelated real process."""
import copy
import json
import types

import pytest

from tools import demo_care as demo


def linux_identity(root,**changes):
    value={'platform':'linux','pid':123456,'parent_pid':100,'argv':['/usr/bin/python3','-m','uvicorn','app.main:app'],
           'start_ticks':'82000','boot_id':'mock-boot-1','uid':1000,'cwd':'/opt/module236/backend',
           'runtime_id':'mock-runtime-1','runtime_root':str(root.resolve()),'process_id':'mock-process-1','state':'S'}
    value.update(changes)
    return value


def save_record(root,identity,**changes):
    record={'label':'backend','pid':identity['pid'],'command':identity['argv'],
            'cwd':identity['cwd'],'runtime_root':str(root.resolve()),'runtime_id':'mock-runtime-1',
            'process_id':'mock-process-1','identity_schema':1,'identity':identity,'children':[]}
    record.update(changes)
    (root/'pids.json').write_text(json.dumps([record]),encoding='utf-8')
    return record


@pytest.mark.parametrize('changes,expected_reason',[
    ({'argv':['/usr/bin/python3','-m','http.server','9000']},'identity_mismatch'),
    ({'runtime_root':'/different/runtime','runtime_id':'different-runtime'},'identity_mismatch'),
    ({'start_ticks':'99999'},'identity_mismatch'),
    ({'boot_id':'new-boot'},'identity_mismatch'),
    ({'uid':2000},'identity_mismatch'),
    ({'cwd':'/different/backend'},'identity_mismatch'),
])
def test_D04_linux_mismatch_never_signals_and_keeps_ledger(tmp_path,monkeypatch,trace,changes,expected_reason):
    expected=linux_identity(tmp_path)
    save_record(tmp_path,expected)
    actual=dict(expected,**changes)
    signals=[]
    monkeypatch.setattr(demo,'process_identity',lambda pid:actual)
    monkeypatch.setattr(demo,'child_pids',lambda pid:[])
    monkeypatch.setattr(demo,'signal_verified',lambda value:signals.append(value) or 'stopped')
    result=demo.stop(tmp_path,{'runtime_id':'mock-runtime-1'})
    assert signals==[] and result['stopped_recorded_demo_processes'] is False
    assert result['results'][0]['processes'][0]['reason']==expected_reason
    assert (tmp_path/'pids.json').exists()
    assert list(tmp_path.glob('stop_attempt_*.json'))
    trace.append({'pure_mock':True,'actual_query_or_signal':False,'result':result})


@pytest.mark.parametrize('condition',['unreadable','legacy','wrong_runtime','unknown_child'])
def test_D04_unverified_identity_never_signals(tmp_path,monkeypatch,trace,condition):
    identity=linux_identity(tmp_path)
    record=save_record(tmp_path,identity)
    if condition=='legacy':
        (tmp_path/'pids.json').write_text(json.dumps([{key:record[key] for key in ('label','pid','command')}]))
    elif condition=='wrong_runtime':
        record['runtime_id']='different-runtime'
        (tmp_path/'pids.json').write_text(json.dumps([record]))
    def read(pid):
        if condition=='unreadable':
            raise demo.ProcessIdentityError('process_identity_unreadable')
        return identity
    signals=[]
    monkeypatch.setattr(demo,'process_identity',read)
    monkeypatch.setattr(demo,'child_pids',lambda pid:[654321] if condition=='unknown_child' else [])
    monkeypatch.setattr(demo,'signal_verified',lambda value:signals.append(value) or 'stopped')
    result=demo.stop(tmp_path,{'runtime_id':'mock-runtime-1'})
    assert signals==[] and result['stopped_recorded_demo_processes'] is False
    assert (tmp_path/'pids.json').exists()
    trace.append({'condition':condition,'pure_mock':True,'actual_query_or_signal':False,'result':result})


def test_D04_correct_complete_identity_only_is_signaled_and_repeated_stop_clear(tmp_path,monkeypatch,trace):
    identity=linux_identity(tmp_path)
    save_record(tmp_path,identity)
    signals=[]
    monkeypatch.setattr(demo,'process_identity',lambda pid:identity)
    monkeypatch.setattr(demo,'child_pids',lambda pid:[])
    monkeypatch.setattr(demo,'signal_verified',lambda value:signals.append(copy.deepcopy(value)) or 'stopped')
    result=demo.stop(tmp_path,{'runtime_id':'mock-runtime-1'})
    assert signals==[identity] and result['stopped_recorded_demo_processes'] is True
    assert not (tmp_path/'pids.json').exists()
    repeated=demo.stop(tmp_path,{'runtime_id':'mock-runtime-1'})
    assert repeated['already_stopped'] is True and repeated['results']==[] and len(signals)==1
    trace.append({'pure_mock':True,'actual_query_or_signal':False,'first':result,'repeated':repeated})


def test_D04_missing_process_is_reported_without_signaling(tmp_path,monkeypatch,trace):
    save_record(tmp_path,linux_identity(tmp_path))
    monkeypatch.setattr(demo,'process_identity',lambda pid:None)
    signals=[]
    monkeypatch.setattr(demo,'signal_verified',lambda value:signals.append(value) or 'stopped')
    result=demo.stop(tmp_path,{'runtime_id':'mock-runtime-1'})
    assert signals==[] and not (tmp_path/'pids.json').exists()
    assert result['results'][0]['processes'][0]['status']=='already_gone'
    trace.append({'pure_mock':True,'actual_query_or_signal':False,'result':result})


def test_D04_reused_child_pid_is_never_signaled(tmp_path,monkeypatch,trace):
    identity=linux_identity(tmp_path)
    child=dict(identity,pid=123457,parent_pid=123456,start_ticks='82001')
    save_record(tmp_path,identity,children=[child])
    signals=[]
    def read(pid):
        return dict(child,start_ticks='99999',argv=['/usr/bin/python3','-m','http.server']) if pid==child['pid'] else identity
    monkeypatch.setattr(demo,'process_identity',read)
    monkeypatch.setattr(demo,'child_pids',lambda pid:[child['pid']] if pid==identity['pid'] else [])
    monkeypatch.setattr(demo,'signal_verified',lambda value:signals.append(value['pid']) or 'stopped')
    result=demo.stop(tmp_path,{'runtime_id':'mock-runtime-1'})
    assert child['pid'] not in signals and result['stopped_recorded_demo_processes'] is False
    assert (tmp_path/'pids.json').exists()
    trace.append({'pure_mock':True,'actual_query_or_signal':False,'mock_signal_pids':signals,'result':result})


def test_D04_pidfd_bound_check_rejects_reuse_between_check_and_signal(tmp_path,monkeypatch,trace):
    expected=linux_identity(tmp_path)
    opened,closed,signals=[],[],[]
    monkeypatch.setattr(demo,'os',types.SimpleNamespace(name='posix',
        pidfd_open=lambda pid,flags:opened.append(pid) or 42,close=lambda fd:closed.append(fd)))
    monkeypatch.setattr(demo,'signal',types.SimpleNamespace(SIGTERM=15,
        pidfd_send_signal=lambda *args:signals.append(args)))
    monkeypatch.setattr(demo,'process_identity',lambda pid:dict(expected,start_ticks='99999'))
    assert demo.signal_verified(expected)=='identity_changed'
    assert opened==[expected['pid']] and closed==[42] and signals==[]
    trace.append({'pure_mock':True,'actual_query_or_signal':False,'opened_mock_pidfds':opened,'signal_calls':signals})


def test_D04_without_instance_bound_signal_fails_closed(tmp_path,monkeypatch):
    monkeypatch.setattr(demo,'os',types.SimpleNamespace(name='posix'))
    monkeypatch.setattr(demo,'signal',types.SimpleNamespace(SIGTERM=15))
    with pytest.raises(demo.ProcessIdentityError,match='instance_bound_signal_unavailable'):
        demo.signal_verified(linux_identity(tmp_path))


def test_D04_linux_signal_uses_bound_descriptor_and_confirms_exit(tmp_path,monkeypatch,trace):
    expected=linux_identity(tmp_path)
    closed,signals=[],[]
    monkeypatch.setattr(demo,'os',types.SimpleNamespace(name='posix',pidfd_open=lambda pid,flags:42,
                                                     close=lambda fd:closed.append(fd)))
    monkeypatch.setattr(demo,'signal',types.SimpleNamespace(SIGTERM=15,
        pidfd_send_signal=lambda *args:signals.append(args)))
    identities=iter([expected,None])
    monkeypatch.setattr(demo,'process_identity',lambda pid:next(identities))
    assert demo.signal_verified(expected)=='stopped'
    assert signals==[(42,15,None,0)] and closed==[42]
    trace.append({'pure_mock':True,'actual_query_or_signal':False,'signal_descriptor_arguments':signals})


@pytest.mark.parametrize('changed',[False,True])
def test_D04_windows_handle_creation_is_checked_before_termination(monkeypatch,trace,changed):
    expected={'platform':'windows','pid':123456,'argv':['python.exe','-m','uvicorn','app.main:app'],
              'creation_ticks':'82000'}
    closed,terminated=[],[]
    kernel=types.SimpleNamespace(CloseHandle=lambda handle:closed.append(handle),
        TerminateProcess=lambda handle,code:terminated.append((handle,code)) or True,
        WaitForSingleObject=lambda handle,timeout:0)
    monkeypatch.setattr(demo,'os',types.SimpleNamespace(name='nt'))
    monkeypatch.setattr(demo,'windows_handle',lambda pid,access:(kernel,'mock-bound-handle',99999 if changed else 82000))
    monkeypatch.setattr(demo,'process_identity',lambda pid:expected)
    status=demo.signal_verified(expected)
    assert status==('identity_changed' if changed else 'stopped')
    assert terminated==([] if changed else [('mock-bound-handle',0)]) and closed==['mock-bound-handle']
    trace.append({'pure_mock':True,'actual_query_or_signal':False,'creation_changed':changed,
                  'mock_terminate_calls':terminated,'status':status})
