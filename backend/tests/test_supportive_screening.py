"""Supportive wording must retain item identity, score direction and safety priority."""
import pytest

from app.voice.screening import CORE_OPENERS, CUSTOM_OPTIONS, OPTIONS, question_item
from test_guided_screening import collect, say


def core_controller(scale, index):
    controller = collect([scale])
    controller.core_only = controller.direct_collection = True
    controller.preferred_item = (scale, index)
    return controller


@pytest.mark.parametrize('scale,index', CORE_OPENERS)
@pytest.mark.parametrize('value', range(4))
def test_supportive_question_preserves_item_frequency_and_safety(scale, index, value):
    controller = core_controller(scale, index)
    question = CORE_OPENERS[scale, index]
    assert question_item(question, scale) == index
    other = 'GAD-7' if scale == 'PHQ-9' else 'PHQ-9'
    assert question_item(question, other) is None
    asked = say(controller, question, 'assistant')
    assert controller.question_key == f'{scale}:{index}'
    answer = say(controller, OPTIONS[value])
    saved = controller.answers[f'{scale}:{index}']
    assert saved['value'] == value
    assert saved['question_context_id'] == asked.message_id
    assert saved['evidence_ids'] == [answer.message_id]
    if (scale, index) == ('PHQ-9', 9) and value > 0:
        assert controller.stage == 'urgent'
        assert controller.history_danger_unresolved
    else:
        assert controller.stage == 'collecting'


@pytest.mark.parametrize('reply', [
    '最近两周几乎每天都很开心。',
    '我想积极一点。',
    '你说得对，我应该往好处想。',
    '我不确定有多少天。',
])
def test_encouraging_exchange_does_not_supply_a_missing_frequency(reply):
    controller = core_controller('PHQ-9', 1)
    say(controller, CORE_OPENERS['PHQ-9', 1], 'assistant')
    say(controller, reply)
    assert controller.answers == {}


def test_warm_question_keeps_pause_and_resume_progress():
    controller = core_controller('PHQ-9', 1)
    say(controller, CORE_OPENERS['PHQ-9', 1], 'assistant')
    say(controller, '有几天')
    say(controller, '我想先休息一下')
    assert controller.stage == 'paused'
    assert controller.answers['PHQ-9:1']['value'] == 1
    assert '按你的节奏来' in controller.instructions()


def test_prompt_preserves_subjective_responses_and_direct_safety_questions():
    controller = core_controller('PHQ-9', 9)
    prompt = controller.instructions()
    assert CORE_OPENERS['PHQ-9', 9] in prompt
    assert '不暗示答案' in prompt
    assert '不评价回答好坏' in prompt
    assert '不能据此代填' in prompt
    assert '安全相关问题保持清楚直接' in prompt


@pytest.mark.parametrize('value', range(5))
def test_support_resources_remain_positive_instead_of_reversing_scores(value):
    controller = collect(['coping_resources'])
    controller.direct_collection = True
    prompt = controller.instructions()
    assert '保留资源存在的正向含义' in prompt
    say(controller, '我们可以慢慢回想。最近两周，你面对变化时调整自己的能力出现的频率怎么样？', 'assistant')
    say(controller, CUSTOM_OPTIONS[value])
    assert controller.answers['coping_resources:1']['value'] == value
