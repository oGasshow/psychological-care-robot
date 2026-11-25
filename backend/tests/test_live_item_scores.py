import pytest

from app.voice.screening import Screening, CORE_OPENERS
from test_guided_screening import say


def collecting():
    s=Screening(True,'test')
    s.core_only=s.direct_collection=True
    s.review_mode='post_session'
    say(s,'我很难过。')
    return s


@pytest.mark.parametrize('answer,points',[
    ('偶尔几天吧。',1),('偶尔有两三天吧。',1),('有时候有三四天。',1),
    ('有八九天吧。',2),('几乎每天。',3),('完全没有。',0),
])
def test_natural_answer_immediately_exposes_item_score_and_partial_total(answer,points):
    s=collecting()
    say(s,CORE_OPENERS['PHQ-9',2],'assistant')
    before=s.public_status()['scores'][0]
    assert before['partial_score'] is None and before['items']==[]
    say(s,answer)
    score=s.public_status()['scores'][0]
    assert score['answered']==1 and score['partial_score']==points
    assert score['total'] is None
    assert score['items']==[{'item':2,'topic':'心情低落或没有盼头','points':points}]


@pytest.mark.parametrize('answer',[
    '有时候吧。','有一点点。','有。','不确定有两三天吧。',
    '不是两三天。','我朋友有两三天。','七八天吧。',
])
def test_ambiguous_or_unrelated_answer_stays_unscored(answer):
    s=collecting()
    say(s,CORE_OPENERS['PHQ-9',2],'assistant')
    say(s,answer)
    assert not s.answers
    assert s.public_status()['scores'][0]['partial_score'] is None


def test_multiple_answers_add_without_counting_unanswered_items():
    s=collecting()
    for item,answer in [(2,'偶尔有两三天吧。'),(1,'完全没有。')]:
        say(s,CORE_OPENERS['PHQ-9',item],'assistant')
        say(s,answer)
    score=s.public_status()['scores'][0]
    assert score['answered']==2 and score['partial_score']==1
    assert score['total'] is None
    assert len(score['items'])==2


@pytest.mark.parametrize('answer,points',[
    ('偶尔吧。',1),('嗯，我偶尔会有一点点。',1),('有一点点，就是偶尔会。',1),
    ('就几天吧。',1),('大半的日子都有。',2),('超过一半的时间会。',2),
    ('基本天天。',3),('我差不多每天都会。',3),('基本上每天都有一点点。',3),
    ('一次都没。',0),('一点儿都没有。',0),
])
def test_colloquial_frequency_scores_without_exact_option_wording(answer,points):
    s=collecting()
    say(s,CORE_OPENERS['PHQ-9',2],'assistant')
    say(s,answer)
    assert s.answers['PHQ-9:2']['value']==points


@pytest.mark.parametrize('answer',[
    '我朋友偶尔会。','不是每天。','不确定是不是偶尔。','如果每天都有呢？',
    '偶尔会，但是最近每天都有。','有点严重。','经常吧。','还好。',
])
def test_colloquial_ambiguity_negation_and_third_party_not_guessed(answer):
    s=collecting()
    say(s,CORE_OPENERS['PHQ-9',2],'assistant')
    say(s,answer)
    assert not s.answers


def test_degree_answer_is_clarified_then_frequency_is_scored():
    s=collecting()
    say(s,CORE_OPENERS['PHQ-9',2],'assistant')
    say(s,'有一点点。')
    assert not s.answers
    assert '只说明程度' in s.instructions()
    say(s,'那最近两周，这种情况大概有多少天呢？','assistant')
    say(s,'偶尔会。')
    assert s.answers['PHQ-9:2']['value']==1
