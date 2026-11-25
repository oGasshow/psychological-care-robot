"""Current negative self-reports invite supportive collection without guessing scores."""
import pytest

from app.voice.screening import Screening, CORE_OPENERS
from test_guided_screening import say


def controller():
    result = Screening(True, 'local-supportive-followup-v1')
    result.core_only = result.direct_collection = True
    result.review_mode = 'post_session'
    return result


@pytest.mark.parametrize('text', [
    '我不开心。', '我今天很难过。', '今天我很伤心。',
    '我感觉很悲伤。', '我最近心情不好。', '我现在情绪不好。',
])
def test_current_negative_self_report_starts_supportive_followup(text):
    s = controller()
    say(s, text)
    assert s.stage == 'collecting'
    assert s.target_scales == ['PHQ-9']
    assert s.current()[:2] == ('PHQ-9', 2)
    assert not s.answers
    assert '先了解发生了什么' in s.instructions()
    assert CORE_OPENERS['PHQ-9', 2] not in s.instructions()
    say(s,'愿意说说发生了什么吗？','assistant')
    say(s,'今天工作不顺利，被领导批评了。')
    assert CORE_OPENERS['PHQ-9', 2] in s.instructions()
    say(s, CORE_OPENERS['PHQ-9', 2], 'assistant')
    say(s, '有几天')
    assert s.answers['PHQ-9:2']['value'] == 1


@pytest.mark.parametrize('text', [
    '我不难过。', '我不伤心。', '我并不悲伤。', '我不是不开心。',
    '我朋友很难过。', '如果我不开心你会怎么办？',
    '我说的是电影台词：我很伤心。', '我很开心。',
])
def test_non_symptom_context_does_not_trigger_or_score(text):
    s = controller()
    say(s, text)
    assert not s.triggered
    assert not s.answers


@pytest.mark.parametrize('text,expected', [
    ('我不想回答量表。', 'declined'), ('我想先休息一下', 'paused'),
    ('我想伤害自己。', 'urgent'),
])
def test_stop_and_safety_override_followup(text, expected):
    s = controller()
    say(s, '我今天很难过。')
    say(s, text)
    assert s.stage == expected
    assert not s.answers


def test_disabled_collection_does_not_start_followup():
    s = controller()
    s.enabled = False
    say(s, '我今天很难过。')
    assert not s.triggered
    assert not s.answers


@pytest.mark.parametrize('text',['我今天特别开心。','我很满足，想分享今天的好事。','最近很放松。'])
def test_positive_sharing_stays_companionship(text):
    s=controller()
    say(s,text)
    assert not s.triggered
    assert '不把积极状态变成量表' in s.instructions()
    assert not s.answers


def test_danger_interrupts_pending_item_and_prioritizes_support():
    s=controller()
    say(s,'我今天很难过。')
    say(s,CORE_OPENERS['PHQ-9',2],'assistant')
    assert s.question_key
    say(s,'我想死。')
    assert s.stage=='urgent'
    assert s.question_key is None
    prompt=s.instructions()
    assert '第一句先接住痛苦' in prompt
    assert '必要的即时安全确认不是量表' in prompt
    assert '不能只安慰后换话题' not in prompt
    assert CORE_OPENERS['PHQ-9',2] not in prompt
    say(s,'好点了，你继续问吧。')
    assert s.stage=='urgent'
    say(s,'偶尔几天吧。')
    assert not s.answers


def test_automatic_followup_does_not_interrupt_first_invitation():
    s=controller()
    say(s,'我有点难过。')
    reply=say(s,'愿意说说发生了什么吗？','assistant')
    assert s.supplemental_question(reply,20) is None
    say(s,'先听我说，我还想继续倾诉。')
    assert s.context_invitation_needed
    assert '先了解发生了什么' in s.instructions()


def test_model_trigger_also_invites_context_before_scale_questions():
    from test_guided_screening import decision
    s=controller()
    s.latest_user_text='有点难过。'
    s.apply_decision(decision(scales=['PHQ-9']))
    assert s.context_invitation_needed
    assert '先了解发生了什么' in s.instructions()
    say(s,'愿意说说发生了什么吗？','assistant')
    say(s,'今天和朋友吵架了。')
    assert not s.context_invitation_needed
