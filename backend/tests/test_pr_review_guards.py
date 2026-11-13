"""Review regressions: readiness, durable scope and actual closing questions."""
from app.voice.screening import Screening
from app.voice.transcripts import Utterance
from app.voice.screening_policy import collection_targets
from app.voice.screening import CUSTOM_SCALE_IDS, ITEMS, OPTIONS_BY_SCALE
import pytest

def decision(*,ready=False,outcome='follow_up'):
    return dict(decision=outcome,target_scales=['mood_interest'] if outcome=='follow_up' else [],
        evidence=[dict(message_id='u1'),dict(message_id='u2')],detector_version='fictional',transition_ready=ready)

def speak(s,key,text,role='user'):
    s.observe(Utterance(key,role,key,text=text,final=True))

def test_review_never_bypasses_current_readiness():
    s=Screening(True);s.stage='reviewing';s.review_status='running'
    s.apply_decision(decision())
    assert s.stage=='waiting_context' and s.triggered

def test_new_followup_cancels_a_previous_normal_review():
    s=Screening(True);s.review_status='normal';s.review_completed=True
    s.apply_decision(decision(ready=True))
    assert s.stage=='collecting' and not s.review_completed and s.review_status=='follow_up'

def test_review_keeps_existing_unfinished_targets_even_without_new_signals():
    for outcome in ('follow_up','no_signal'):
        s=Screening(True);s.stage='reviewing';s.review_status='running'
        s.target_scales=['PHQ-9'];s.signals=['earlier-evidence']
        s.apply_decision(decision(outcome=outcome))
        assert 'PHQ-9' in s.target_scales and 'earlier-evidence' in s.signals
        assert not s.review_completed and s.stage=='waiting_context'

def test_turn_count_alone_is_not_an_actual_goodbye_question():
    s=Screening(True);s.review_completed=True
    for i in range(2):
        speak(s,f'u{i}','今天吃过饭了。');speak(s,f'a{i}','我在听，可以慢慢说。','assistant')
    speak(s,'u3','没有。')
    assert not s.end_after_response

def test_new_user_speech_can_cancel_a_pending_goodbye():
    s=Screening(True);s.stage='complete';s.closing_question_asked=True
    speak(s,'u1','没有了。');assert s.end_after_response
    speak(s,'u2','等等，我还想再说说。')
    assert not s.end_after_response

def test_default_targets_include_both_scales_and_all_six_indicators():
    assert collection_targets()==['PHQ-9','GAD-7',*CUSTOM_SCALE_IDS]
    s=Screening(True);s.concern(['fictional-evidence'],'fictional-model')
    assert s.target_scales==collection_targets()

def test_grounded_detector_keeps_both_result_families():
    import json
    from test_concern_detector import fixture,output
    from app.voice.concern_detector import validate
    data=fixture()
    result=validate(json.dumps(output(data)),data)
    assert result['target_scales']==['PHQ-9','mood_interest']

@pytest.mark.parametrize('scale',CUSTOM_SCALE_IDS)
def test_custom_indicator_uses_five_levels_and_keeps_separate_totals(scale):
    s=Screening(True);s.concern(['fictional-evidence'],'fictional-model',[scale])
    s.apply_decision({**decision(ready=True),'target_scales':[scale]})
    assert s.stage=='collecting'
    for i,topic in enumerate(ITEMS[scale]):
        speak(s,f'q{i}',f'最近两周，{topic}的情况怎么样？','assistant')
        speak(s,f'a{i}',OPTIONS_BY_SCALE[scale][4])
        speak(s,f'c{i}',f'最近两周，{topic}几乎总是，对吗？','assistant')
        speak(s,f'y{i}','对')
    view=s.view()['scales'][0]
    assert s.stage=='complete' and view['answered']==3
    assert view['total']==12 and view['max_score']==12
    assert view['score_kind']=='project_dialogue_indicator'
