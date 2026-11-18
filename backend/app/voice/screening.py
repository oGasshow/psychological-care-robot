"""Conservative conversational collection, not a validated clinical instrument."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
from types import SimpleNamespace

from sqlalchemy import Column, Integer, String, JSON, ForeignKey
from ..database import Base
from care_core import safety
from .screening_policy import CORE_TARGETS, collection_targets

ITEMS = {
    'PHQ-9': ['做事缺少兴趣或乐趣', '心情低落或没有盼头', '难以入睡、睡眠中断或睡得过多',
              '疲倦或缺乏精力', '食欲减少或吃得过多', '自责或觉得自己让人失望',
              '难以集中注意力（例如阅读或看电视）', '动作或说话变慢，或坐立不安', '伤害自己或觉得不如死去的念头'],
    'GAD-7': ['紧张、焦虑或坐立不安', '无法停止或控制担忧', '对不同事情担忧过多',
              '难以放松', '烦躁得难以安坐', '容易烦恼或急躁', '担心可怕的事情会发生'],
    # Project-defined conversation indicators. These are not the named/licensed
    # instruments and deliberately use original prompts and no clinical cutoffs.
    'mood_interest': ['持续低落或提不起兴趣', '精力与行动受到影响', '自我评价或希望感受影响'],
    'worry_anxiety': ['担忧反复出现或难以停下', '紧张焦虑影响日常状态', '放松与安定下来较困难'],
    'stress_load': ['事情显得难以掌控', '压力负荷难以应付', '压力影响生活安排'],
    'sleep_wellbeing': ['入睡过程受到困扰', '夜间睡眠或过早醒来受到困扰', '睡眠影响白天状态'],
    'coping_resources': ['面对变化时调整自己的能力', '遇到挫折后恢复和继续行动', '在需要时找到支持或帮助'],
    'social_comfort': ['与不熟悉或有权威的人互动时的不自在', '在群体中表达时的不自在', '被注视或评价时的不自在或回避'],
}
OPTIONS = ['完全没有', '有几天', '超过一半的天数', '几乎每天']
CUSTOM_OPTIONS = ['从不', '较少', '有时', '经常', '几乎总是']
OPTIONS_BY_SCALE = {scale: OPTIONS for scale in ('PHQ-9','GAD-7')}
OPTIONS_BY_SCALE.update({scale: CUSTOM_OPTIONS for scale in (
    'mood_interest','worry_anxiety','stress_load','sleep_wellbeing','coping_resources','social_comfort')})
SCALE_LABELS = {
    'PHQ-9':'PHQ-9语音辅助结果','GAD-7':'GAD-7语音辅助结果',
    'mood_interest':'情绪与兴趣对话指标','worry_anxiety':'担忧与焦虑对话指标',
    'stress_load':'压力负荷对话指标','sleep_wellbeing':'睡眠状态对话指标',
    'coping_resources':'应对与支持资源对话指标','social_comfort':'社交舒适度对话指标',
}
SCALE_DIRECTIONS = {
    'mood_interest':'分数较高表示相关困扰在对话中的出现频率较高',
    'worry_anxiety':'分数较高表示相关困扰在对话中的出现频率较高',
    'stress_load':'分数较高表示相关困扰在对话中的出现频率较高',
    'sleep_wellbeing':'分数较高表示相关困扰在对话中的出现频率较高',
    'coping_resources':'分数较高表示用户提到的应对或支持资源较多',
    'social_comfort':'分数较高表示相关不适或回避在对话中的出现频率较高',
}
CUSTOM_SCALE_IDS = ('mood_interest','worry_anxiety','stress_load','sleep_wellbeing','coping_resources','social_comfort')
CONTEXT_CHECKIN_AFTER_USER_TURNS = 4
CORE_QUESTION_DUE_ROUND = 4
SAFETY_CHECK_QUESTION = '我也想确认一下，你现在还有伤害自己或不想活下去的念头吗？'
HOLD_CORE_FOLLOWUP = re.compile(r'崩溃|很痛苦|撑不住|喘不过气|恐慌|让我先说完|还想继续(?:说|倾诉)|先听我说|先别问')
SAFETY_AFFIRMATION = re.compile(r'(?:有|还有|仍然有|有一点|有时候有)(?:啊|呀|呢|的)?[。！! ]*')
SAFETY_DENIAL = re.compile(
    r'(?:没有(?:了|啊|呀|啦|的|呢)?|(?:没有[，, ]*)?(?:我)?现在没有'
    r'(?:(?:伤害自己|不想活(?:下去)?)(?:的)?(?:念头|想法)|这种念头))[。！! ]*')
TOPIC_CUES = {
    'PHQ-9': [('兴趣','乐趣','喜欢','兴致'),('低落','盼头','沮丧','心情','不开心'),('睡','入眠','失眠'),
              ('疲倦','精力','累'),('食欲','吃饭','胃口','吃得'),('自责','失望','价值'),
              ('注意','集中','阅读'),('动作','说话','坐立','缓慢'),('死','伤害','活着')],
    'GAD-7': [('紧张','焦虑','坐立不安'),('控制','停不下','停止','担忧','担心'),('各种','不同事情','担忧','担心'),
              ('放松',),('安坐','坐立'),('烦躁','急躁','烦恼'),('害怕','可怕','发生')],
    'mood_interest': [('低落','提不起兴趣','没兴趣','兴致','没乐趣','心情'),('精力','疲倦','疲惫','乏力','没力气','没有力气','没精神','没有精神','提不起劲','没有动力','没动力','行动','做事'),('自责','责怪自己','没希望','希望','评价自己','自我评价','没价值','没有价值','没什么用','没什么价值','盼头','一无是处','自己很差','没盼头','没有盼头')],
    'worry_anxiety': [('担忧','反复担忧','停不下来','担心','忧虑'),('紧张','焦虑','心慌'),('放松','安定','平静')],
    'stress_load': [('掌控','控制不了','安排不过来'),('压力','负担','应付不了'),('压力影响','生活安排','工作学习')],
    'sleep_wellbeing': [('入睡','睡不着','睡眠'),('夜里醒','早醒','醒来'),('白天疲惫','白天状态','睡眠影响')],
    'coping_resources': [('变化','调整','适应'),('挫折','恢复','继续行动'),('支持','帮助','找谁')],
    'social_comfort': [('不熟悉的人','权威','互动','交谈'),('群体','小组','表达'),('被注视','被评价','回避','不自在')],
}
POLARITY_GUARDS = {
    ('PHQ-9',1): r'缺少兴趣|缺乏兴趣|没.{0,4}兴趣|不感兴趣|兴趣减退|兴趣.{0,5}变[小少]|提不起.{0,3}兴趣|提不起兴致|没.{0,4}乐趣|缺少.{0,5}乐趣',
    ('PHQ-9',7): r'难以集中|无法集中|注意力不集中|容易分心|难.{0,3}集中注意',
    ('GAD-7',4): r'难以放松|无法放松|不能放松|放松不下来|很难放松',
}

CORE_OPENERS = {
    ('PHQ-9', 1): '最近两周，大概有几天对平常喜欢的事提不起兴趣？',
    ('PHQ-9', 2): '最近两周，大概有几天觉得心情低落？',
    ('PHQ-9', 3): '最近两周，大概有几天晚上睡不着？',
    ('PHQ-9', 4): '最近两周，大概有几天觉得没精力？',
    ('PHQ-9', 5): '最近两周，大概有几天胃口差？',
    ('PHQ-9', 6): '最近两周，大概有几天觉得自己没价值？',
    ('PHQ-9', 7): '最近两周，大概有几天难以集中注意力？',
    ('PHQ-9', 8): '最近两周，大概有几天觉得自己的动作变慢？',
    ('GAD-7', 1): '最近两周，大概有几天感到紧张或焦虑？',
    ('GAD-7', 2): '最近两周，大概有几天觉得无法停止或控制担忧？',
    ('GAD-7', 3): '最近两周，大概有几天会对不同事情担忧过多？',
    ('GAD-7', 4): '最近两周，大概有几天觉得很难放松？',
    ('GAD-7', 5): '最近两周，大概有几天难以安坐？',
    ('GAD-7', 6): '最近两周，大概有几天比平时容易烦恼或急躁？',
    ('GAD-7', 7): '最近两周，大概有几天会害怕有不好的事发生？',
}
CORE_CONCERN = re.compile(
    r'^(?:最近|这阵子|这几天|最近两周|这两周)?[，, ]*我(?:最近|这阵子|这几天|最近两周|这两周)?'
    r'(?:一直|经常|反复|这段时间|很|总是|总|挺|常常|老是|有点|特别|真的|感到|感觉|觉得|心情|情绪|变得|都|几乎每天|很容易|实在|好像)*'
    r'(?:(?P<interest>提不起(?:什么|任何|一点|什么样的)?兴趣|对[^，。！？；]{1,18}(?:提不起兴趣|没了兴趣|没什么兴趣))'
    r'|(?P<low_mood>很?低落|很?沮丧|没什么盼头|没有盼头)'
    r'|(?P<worry>担心得停不下来|担心[^，。！？；]{0,12}(?:停不下来|无法控制|控制不住)|控制不住地担心|怎么都停不下(?:担心|担忧))'
    r'|(?P<anxiety>紧张|焦虑))')
CORE_CONCERN_ITEMS = {
    'interest': ('PHQ-9', 1), 'low_mood': ('PHQ-9', 2),
    'worry': ('GAD-7', 2), 'anxiety': ('GAD-7', 1),
}
SELF_REPORT_EXCLUSION = re.compile(
    r'如果|假[如设]|假装|例如|举例|比方说|开玩笑|台词|测试一下|模拟|我朋友|我同学|我家人|不是|并不|不觉得|'
    r'不再|好多了|已经.{0,6}(?:好了|缓解|过去)|刚才|今天才|只是今天|过去曾|明年|昨天才')
CORE_WINDOW = r'(?:最近|过去|这|近)(?:两周|两个星期|十四天|14天)'


def core_concern_item(text):
    if SELF_REPORT_EXCLUSION.search(text) or re.search(r'[？?]|(?:吗|呢)[。！!]?$', text):
        return None
    match = CORE_CONCERN.match(text)
    if not match or re.match(r'症|障碍|患者|的话|这个词', text[match.end():]):
        return None
    if match.lastgroup == 'anxiety' and not re.search(r'最近|这阵子|这几天|这两周|经常|反复|老是|总是|一直', match.group()):
        return None
    return CORE_CONCERN_ITEMS[match.lastgroup]


def core_day_count(text):
    number = r'十[一二三四]?|[一二两三四五六七八九零〇]|0?[0-9]|1[0-4]'
    chinese_digit = '一二两三四五六七八九'
    match = re.fullmatch(
        rf'(?:是的|对的|对|嗯)?(?:大概|大约|差不多|差不离)?(?:有|出现了|是|这)?({number})'
        rf'(?:天?[到至、~-]({number})|(?<=[{chinese_digit}])([{chinese_digit}]))?天(?:左右|吧|的样子|都这样)?', text)
    if not match:
        return None
    chinese = dict(zip('零一二三四五六七八九', range(10))) | {'〇': 0, '两': 2, '十': 10}

    def band(raw):
        days = int(raw) if raw.isdigit() else 10 + chinese[raw[1]] if len(raw) == 2 else chinese[raw]
        if days == 0:
            return 0
        if days <= 7:
            return 1
        if days <= 11:
            return 2
        if days == 14:
            return 3
        return None  # Near-daily vs. more than half requires clarification.

    first, separated, adjacent = match.groups()
    last = separated or adjacent
    value = band(first)
    return value if not last or value == band(last) else None

def declines_collection(text, *, question_pending=False):
    """Recognize a refusal to the collection itself, not an unrelated task."""
    text = re.sub(r'\s+', '', text)
    explicit = (
        r'(不想|不愿意|不需要|拒绝).{0,8}(回答|答题|问卷|量表|采集|这些问题|这个问题|继续问|再问)',
        r'(别再问|停止问|停止采集|先不做(问卷|量表|采集)|不想聊这个(问题|话题|问卷|量表|采集))',
    )
    if any(re.search(pattern, text) for pattern in explicit):
        return True
    if re.fullmatch(r'不想继续了[。！!，,？?]*',text):
        return True
    # A brief standalone refusal immediately answering a specific collection
    # question is meaningful; longer statements need an explicit target.
    return question_pending and len(text) <= 8 and bool(
        re.fullmatch(r'(不愿意|不想|算了|先不|不回答)[。！!，,？?]*', text))


def accepts_review_transition(text):
    """Only treat a clear reply to the explicit pacing check-in as readiness."""
    normalized=re.sub(r'\s+','',text)
    if re.search(r'还没说完|还想(继续)?(说|聊|讲|倾诉)|继续(说|聊|讲|倾诉)|先让我说完|想再说',normalized):
        return False
    return bool(re.search(
        r'差不多(了|说完了)?|说完了|可以(一起)?(梳理|看看|聊聊|了解)|想(一起)?(梳理|看看|了解)|'
        r'聊到这里|先这样(吧)?|嗯[，, ]*(好|可以)|^(好|好的|可以|行|嗯)[。！!，,？? ]*$',
        normalized))


def explicit_frequency(text, options):
    """Extract one explicit self-reported frequency, never severity or a guess."""
    normalized=re.sub(r'[。！!，,？?\s]','',text)
    if re.search(r'不确定|说不准|也许|可能|假如|如果|比如|举例|听说|别人|朋友说|他说|她说|家人说',normalized):return None
    zero=bool(re.fullmatch(r'(这|那)?倒?是?(完全|确实|真的)?没有(啊|呀|呢|的)?',normalized)
        or re.search(r'从来没有|完全没有|没有这种情况|这种情况(我)?没有|一点(也|都)没有',normalized))
    if re.search(r'(不(太|算|是|怎么)?|没有)(经常|常常|有时|偶尔|几乎总是)',normalized):return None
    if options==CUSTOM_OPTIONS:
        patterns={4:r'几乎总是|几乎每次',3:r'经常|常常',2:r'有时候|有时|时不时',1:r'较少|很少|偶尔',0:r'从不|从未'}
    else:
        patterns={3:r'几乎每天|差不多天天|基本每天',2:r'超过一半(的)?天数|一半以上|超过半数',1:r'有几天',0:r'从不|从未'}
    found={value for value,pattern in patterns.items() if re.search(pattern,normalized)}
    if zero:found.add(0)
    return next(iter(found)) if len(found)==1 else None


def frequency_answer(text,options,question,topic_question=None):
    if options == OPTIONS:
        normalized = re.sub(r'[。！!，,？?\s]', '', text)
        days = core_day_count(normalized)
        if days is not None:
            return days
        if re.fullmatch(r'(?:我)?(?:基本每天|差不多天天|每天|天天|一半以上|超过半数|一次也没有|一天都没有)(?:都(?:有|会)|吧)?', normalized):
            if '没有' in normalized:
                return 0
            return 2 if '半' in normalized else 3
    value=explicit_frequency(text,options)
    if value is not None:
        if value==0 and re.fullmatch(r'(这|那)?倒?是?(完全|确实|真的)?没有(啊|呀|呢|的)?[。！!？?，,\s]*',text):
            if options==OPTIONS and '完全没有' not in text and re.search(r'大多|经常|频繁|大半|一半|每天',question):
                return None
            return 0
        residue=re.sub(r'[。！!，,？?\s]','',text)
        phrases=['最近两周','最近十四天','这两周','近两周','这种感觉','这种感受','这种情况','这类情况','那种感觉','我感觉','我觉得',
            '这倒是没有','那倒是没有','从来没有','完全没有','没有这种情况','一点也没有','一点都没有',
            '几乎总是','几乎每天','超过一半的天数','有几天','几乎每次','有时候','时不时','常常','经常','有时','偶尔','较少','很少','从不','从未',
            '出现','发生','这样','感觉','觉得','大概','大约','吧','呢','呀','啊','的','我','会','有']
        for phrase in sorted(phrases,key=len,reverse=True):residue=residue.replace(phrase,'')
        if residue and residue not in (topic_question or question):return None
        return value
    if re.fullmatch(r'(是的|对|没错|确实|确实是|会的呀|会的|会呀|对呀|是呀|会的会的)[。！!，,\s]*',text):
        if re.search(r'不是|不算|不怎么|不太|并不|并非|很少|不常|少有',question):return None
        values=[i for i,option in enumerate(options) if option in question]
        if len(values)==1:return values[0]
    return None


def core_self_report(text):
    """Accept a standalone first-person report only when it states all three parts."""
    text = re.sub(r'\s+', '', text).strip('。！!')
    window = re.match(rf'{CORE_WINDOW}[，,、]?', text)
    if not window or SELF_REPORT_EXCLUSION.search(text) or re.search(r'[？?]', text):
        return None
    body = text[window.end():]
    before, separator, after = body.partition('我')
    if not separator:
        return None
    if before:
        statement, frequency = separator + after, before.strip('，,')
        match = CORE_CONCERN.fullmatch(statement)
    else:
        match = CORE_CONCERN.match(body)
        frequency = body[match.end():].strip('，,') if match else ''
    value = frequency_answer(frequency, OPTIONS, '') if frequency else None
    if match and value is not None and value > 0:
        return (*CORE_CONCERN_ITEMS[match.lastgroup], value)
    return None


def demo_question_item(text):
    """Route only explicit project indicator questions, independent of ask order."""
    if not re.search(r'两周|十四天',text) or not re.search(r'[？?]|吗|呢|如何|怎么样|有没有|多少|频繁',text):return None
    question_text=re.split(r'两周|十四天',text)[-1]
    matches=[i+1 for i,cues in enumerate(TOPIC_CUES['mood_interest']) if any(cue in question_text for cue in cues)]
    if len(matches)!=1:return None
    direction={1:r'低落|没.{0,4}(兴趣|兴致|乐趣)|提不起.{0,3}(兴趣|兴致)|持续低落',
        2:r'不足|没.{0,3}(精力|力气|精神|动力)|疲倦|疲惫|乏力|提不起劲|受到影响|行动.{0,4}(困难|受|影响)',
        3:r'自责|责怪自己|自己.{0,6}没.{0,4}用|没.{0,4}(希望|价值|盼头)|一无是处|自己很差|自我评价.{0,6}(影响|差|低)|希望感.{0,4}影响'}
    return matches[0] if re.search(direction[matches[0]],question_text) else None


def question_item(text,scale):
    if scale=='mood_interest':return demo_question_item(text)
    if not re.search(r'两周|十四天|14天',text) or not re.search(r'[？?]|吗|呢|如何|怎么样|有没有|多少|频繁',text):return None
    question=re.split(r'两周|十四天|14天',text)[-1]
    exact=[i+1 for i,topic in enumerate(ITEMS[scale]) if topic in question]
    if scale in CORE_TARGETS and not exact:
        question=re.split(r'比如|譬如|例如',question,maxsplit=1)[0]
    matched=exact or [i+1 for i,cues in enumerate(TOPIC_CUES[scale]) if any(c in question for c in cues)]
    if len(matched)!=1:return None
    index=matched[0]
    guard=POLARITY_GUARDS.get((scale,index))
    if guard and not re.search(guard,question):return None
    negative={
        ('PHQ-9',2):r'低落|沮丧|没有盼头|没盼头|不开心|心情不好',('PHQ-9',3):r'难以入睡|睡不着|睡不好|睡眠中断|睡得过多|失眠|难以睡|睡得太多',
        ('PHQ-9',4):r'疲倦|疲惫|缺乏精力|没精力|累',('PHQ-9',5):r'食欲减少|吃得过多|胃口差|吃不下|吃太多',
        ('PHQ-9',6):r'自责|失望|没价值|没有价值',('PHQ-9',8):r'变慢|缓慢|坐立不安',('PHQ-9',9):r'伤害|死|不想活',
        ('GAD-7',1):r'紧张|焦虑|坐立不安',('GAD-7',2):r'停止|控制|停不下',('GAD-7',3):r'担忧|担心',
        ('GAD-7',5):r'烦躁|难以安坐|坐立',('GAD-7',6):r'烦恼|急躁|烦躁',('GAD-7',7):r'可怕|害怕|担心'}
    if (scale,index) in negative and not re.search(negative[(scale,index)],question):return None
    return index

class ScreeningResult(Base):
    __tablename__='robot_voice_screening_results'
    session_id=Column(Integer,ForeignKey('robot_record_sessions.id',ondelete='CASCADE'),primary_key=True)
    owner=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    payload=Column(JSON,nullable=False)

class CollectionTrace(Base):
    """Progress receipt, never an empty PHQ/GAD assessment record."""
    __tablename__='robot_voice_collection_traces'
    session_id=Column(Integer,ForeignKey('robot_record_sessions.id',ondelete='CASCADE'),primary_key=True)
    owner=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    payload=Column(JSON,nullable=False)

class Screening:
    def __init__(self, enabled=False, notice_version=''):
        self.enabled = enabled
        self.notice_version = notice_version
        self.review_mode = 'live'
        self.core_only = False
        self.verifying_saved_call = False
        self.demo_mode = False
        self.direct_collection = False
        self.trigger_origin = 'context_model'
        self.stop_reason = None
        self.stage = 'companionship'
        self.signals, self.target_scales, self.decisions = [], [], []
        self.answers, self.pending = {}, None
        self.version, self.seen = 0, set()
        self.confirmation_asked = False
        self.question_key = None
        self.question_context = None
        self.user_invited_questions = False
        self.question_followup = None
        self.window_context = None
        self.preferred_item = None
        self.recent_topic_text = ''
        self.last_answered_scale = None
        self.confirmation_context_id = None
        self.detector = None
        self.detector_status = 'not_checked'
        self.history_session_ids=[]
        self.history_danger_unresolved=False
        self.current_safety_discussed=False
        self.safety_check_asked=False
        self.safety_question_turn=None
        self.current_call_answered=False
        self.latest_user_text=''
        self.background=''
        self.observations=[]
        self.candidate_context=None
        self.episode_id=None
        self.window_end=None
        self.transport_diagnostics={}
        self.dialogue_rounds=0
        self.user_turn_waiting_for_reply=False
        self.context_checkin_due=False
        self.context_checkin_asked=False
        self.closing_question_asked=False
        self.end_after_response=False
        self.review_status='not_started'
        self.review_completed=False
        self.post_review_turns=0

    @property
    def streamlined(self):return self.demo_mode or self.direct_collection

    @property
    def normal_live(self):
        return self.enabled and self.direct_collection and self.core_only and not self.verifying_saved_call

    @property
    def needs_current_safety_check(self):
        return self.history_danger_unresolved and not self.current_safety_discussed

    def supplemental_question(self, reply, round_number):
        """Supply one question after a finished reply missed a needed follow-up."""
        if not self.normal_live or self.end_after_response or HOLD_CORE_FOLLOWUP.search(self.latest_user_text):
            return None
        if self.stage not in ('checking_in','waiting_context','collecting'):
            return None
        if self.needs_current_safety_check:
            return SAFETY_CHECK_QUESTION if not self.safety_check_asked else None
        if not self.triggered or self.current_call_answered or round_number < CORE_QUESTION_DUE_ROUND - 1:
            return None
        item=self.current()
        if not item or item[:2] not in CORE_OPENERS:
            return None
        if self.start_collection():
            self.version+=1
        if round_number < CORE_QUESTION_DUE_ROUND:
            return None
        if self.question_context and self.question_context.turn_id == reply.turn_id and re.search(
                r'几天|多少天|超过一半|几乎每天', (self.question_followup or self.question_context).text):
            return None
        return CORE_OPENERS[item[:2]]

    def start_collection(self):
        if self.stage=='collecting':
            return False
        self.stage='collecting'
        self.review_status='follow_up'
        self.review_completed=False
        return True

    def read_safety_reply(self, entry):
        if not (self.normal_live and self.needs_current_safety_check and self.safety_question_turn
                and self.safety_question_turn!=entry.turn_id):
            return None
        self.safety_question_turn=None
        text=entry.text.strip()
        if SAFETY_AFFIRMATION.fullmatch(text):
            return 'danger'
        if SAFETY_DENIAL.fullmatch(text):
            return 'addressed'
        return None

    def inherit(self,context):
        from .continuity import background_instructions
        self.history_session_ids=context['session_ids']
        self.history_danger_unresolved=context['danger_history']
        self.background=background_instructions(context)
        if self.enabled and context['danger_history']:
            self.stage='checking_in'
            self.target_scales=['PHQ-9']
            self.signals=context.get('danger_message_ids',[])

    def accept_candidate(self,candidate,item):
        if self.stage!='collecting' or self.current()!=item or not candidate['relevant']:
            return False
        status='awaiting_confirmation' if candidate['value']>=0 else 'needs_frequency_or_window'
        note=dict(scale=item[0],display_name=SCALE_LABELS.get(item[0],item[0]),item=item[1],status=status,answer_id=candidate['answer_id'],
            question_id=candidate['question_id'],window_id=candidate['window_id'])
        self.observations=[o for o in self.observations if (o['scale'],o['item'])!=(item[0],item[1])]+[note]
        if candidate['value']>=0 and self.pending is None:
            self.pending=(candidate['value'],candidate['answer_id'])
            self.confirmation_asked=False
            self.candidate_context=dict(question_context_id=candidate['question_id'],window_context_id=candidate['window_id'],
                extraction_version='conversation-indicator-rubric-v1')
        self.version+=1
        return True

    @property
    def triggered(self):
        return bool(self.target_scales and self.signals)

    def concern(self, ids, version, target_scales=None):
        # External models only identify a concern. They cannot bypass the pacing
        # decision, user stop, danger override, or select arbitrary instruments.
        if not self.enabled or self.stage not in ('companionship','checking_in'):
            return
        targets = target_scales or (['mood_interest'] if self.demo_mode else list(CORE_TARGETS) if self.core_only else collection_targets())
        if self.core_only:
            targets = [scale for scale in targets if scale in CORE_TARGETS]
            if not targets:
                return
        if self.demo_mode and any(s!='mood_interest' for s in targets):
            raise ValueError('collection_demo_target_invalid')
        if not ids or not targets or any(s not in ITEMS for s in targets):
            raise ValueError('invalid_concern_signal')
        self.signals = list(dict.fromkeys(ids))
        self.target_scales = list(dict.fromkeys(targets))
        self.detector = version
        self.stage = 'waiting_context'
        self.context_checkin_due=(self.review_mode=='live' and self.dialogue_rounds>=CONTEXT_CHECKIN_AFTER_USER_TURNS
                                  and not self.context_checkin_asked)
        self.version += 1

    def apply_normal_decision(self, result):
        """Use only a current live decision to advance ordinary mode."""
        if (self.stage=='collecting' or self.needs_current_safety_check
                or HOLD_CORE_FOLLOWUP.search(self.latest_user_text)):
            return False
        before=(self.stage, tuple(self.target_scales), self.review_status)
        if result['decision']=='follow_up':
            evidence=result['evidence']
            ids=[entry['message_id'] for entry in evidence]
            if not self.triggered:
                self.concern(ids,result['detector_version'],result['target_scales'])
            else:
                self.signals=list(dict.fromkeys([*self.signals,*ids]))
                self.target_scales=list(dict.fromkeys([*self.target_scales,*result['target_scales']]))
            if self.preferred_item is None:
                self.preferred_item=next((item for entry in evidence
                    if (item:=CORE_CONCERN_ITEMS.get(entry['domain'])) and item[0] in self.target_scales
                    and f'{item[0]}:{item[1]}' not in self.answers),None)
            if self.stage=='waiting_context':
                self.review_status='waiting_context'
        if self.triggered and result['transition_ready'] and self.stage=='waiting_context':
            self.start_collection()
        changed=before!=(self.stage, tuple(self.target_scales), self.review_status)
        if changed:
            self.version+=1
        return changed

    def apply_decision(self, result, *, fresh=True):
        if not self.enabled or self.stage in ('declined', 'paused', 'urgent', 'complete'):
            return False
        if self.core_only and result['decision']=='follow_up':
            targets=[scale for scale in result['target_scales'] if scale in CORE_TARGETS]
            if not targets:
                return False
            result={**result,'target_scales':targets}
        if not fresh and (self.normal_live or self.review_status in ('running','pending')):
            return False
        self.detector_status = 'checked'
        self.decisions = (self.decisions + [result])[-6:]
        if self.normal_live:
            return self.apply_normal_decision(result)
        before = (self.stage, tuple(self.target_scales), self.review_status, self.review_completed)
        if self.review_status in ('running','pending') and fresh:
            if result['decision'] == 'follow_up':
                self.signals=list(dict.fromkeys([*self.signals,*[e['message_id'] for e in result['evidence']]]))
                self.target_scales=list(dict.fromkeys([*self.target_scales,*result['target_scales']]))
                self.detector=result['detector_version']
            if self.triggered:
                self.stage='collecting' if result['transition_ready'] else 'waiting_context'
                self.review_status='follow_up' if result['transition_ready'] else 'waiting_context'
                self.review_completed=False
            else:
                self.stage='companionship'
                self.review_status='normal'
                self.review_completed=True
                self.post_review_turns=0
        elif result['decision'] == 'follow_up':
            self.review_completed=False
            if not self.triggered:
                self.concern([e['message_id'] for e in result['evidence']],
                             result['detector_version'], result['target_scales'])
            else:
                self.target_scales=list(dict.fromkeys([*self.target_scales,*result['target_scales']]))
                self.signals=list(dict.fromkeys([*self.signals,*[e['message_id'] for e in result['evidence']]]))
                if self.stage=='checking_in':self.stage='waiting_context'
            if fresh and result['transition_ready'] and self.stage=='waiting_context':
                self.stage='collecting'
                if self.core_only and self.preferred_item is None:
                    for evidence in result['evidence']:
                        item = CORE_CONCERN_ITEMS.get(evidence['domain'])
                        if item and item[0] in self.target_scales and f'{item[0]}:{item[1]}' not in self.answers:
                            self.preferred_item = item
                            break
            if self.stage in ('waiting_context','collecting'):
                self.review_status='follow_up' if self.stage=='collecting' else 'waiting_context'
        elif (self.review_mode=='post_session' and self.triggered and fresh
              and self.stage in ('waiting_context','checking_in')):
            # A saved task survives a quiet follow-up call. Current readiness,
            # rather than another symptom trigger, governs continuing it.
            if result['transition_ready']:
                self.stage,self.review_status='collecting','follow_up'
            self.review_completed=False
        if before != (self.stage, tuple(self.target_scales), self.review_status, self.review_completed):
            self.version += 1
            return True
        return False

    def action(self, action):
        if not self.enabled:
            return
        previous = self.stage
        if action == 'decline' and self.stage not in ('urgent', 'complete'):
            self.stage, self.pending = 'declined', None
            self.stop_reason = 'user_requested'
        elif action == 'pause' and self.stage == 'collecting':
            self.stage, self.pending = 'paused', None
        # ready/consent from older clients deliberately cannot authorize or
        # trigger collection; the product notice is configured server-side.
        if previous != self.stage:
            self.version += 1

    def current(self):
        if self.core_only and self.question_key and self.question_key not in self.answers:
            scale, index=self.question_key.split(':')
            if scale in self.target_scales:
                index=int(index)
                return scale,index,ITEMS[scale][index-1]
        if self.preferred_item:
            scale, index = self.preferred_item
            if scale in self.target_scales and f'{scale}:{index}' not in self.answers:
                return scale, index, ITEMS[scale][index-1]
        remaining=((scale,i+1,topic) for scale in self.target_scales for i,topic in enumerate(ITEMS[scale])
                   if f'{scale}:{i+1}' not in self.answers)
        if not self.core_only:
            return next(remaining,None)
        def topic_order(item):
            scale,index,_=item
            relevant=sum(cue in self.recent_topic_text for cue in TOPIC_CUES[scale][index-1])
            tie=sha256(f'{self.episode_id or ""}:{scale}:{index}'.encode()).digest()
            general_topic=(scale,index) in (('PHQ-9',2),('GAD-7',1))
            return ((scale,index)==('PHQ-9',9),-relevant,scale==self.last_answered_scale,not general_topic,tie)
        return min(remaining,key=topic_order,default=None)

    def follow_core_topic(self,entry):
        if not self.core_only or self.verifying_saved_call:
            return
        text=entry.text
        if any(cue in text for scale in CORE_TARGETS for cues in TOPIC_CUES[scale] for cue in cues):
            self.recent_topic_text=text[-600:]
        if SELF_REPORT_EXCLUSION.search(text):
            return
        topics=[core_concern_item(part.strip()) for part in re.split(r'[。；，,!！]',text)]
        for topic in filter(None,topics):
            scale,index=topic
            if scale not in self.target_scales:
                self.target_scales.append(scale)
                self.signals=list(dict.fromkeys([*self.signals,entry.message_id]))
                self.version+=1
            if not self.question_key and not self.pending and f'{scale}:{index}' not in self.answers:
                self.preferred_item=topic

    def start_demo(self, evidence_id):
        if not (self.enabled and self.demo_mode and self.stage in ('companionship','waiting_context')):
            return False
        if not self.triggered:self.concern([evidence_id],'manual_demo_trigger_v1',['mood_interest'])
        self.trigger_origin='manual_demo'
        self.detector='manual_demo_trigger_v1'
        self.stage,self.review_status='collecting','manual_demo'
        self.version+=1
        return True

    def reconcile_demo_turns(self, turns):
        """Recover explicit Q/A that arrived before the asynchronous trigger."""
        if not self.streamlined or self.stage!='collecting':return False
        before=len(self.answers)
        for entry in turns:
            if not entry.final:continue
            if self.stage!='collecting':break
            self.seen.discard(entry.message_id)
            self.observe(entry)
        return len(self.answers)!=before

    def open_core_followup(self, entry, text, self_report):
        if not self.core_only or self.needs_current_safety_check or declines_collection(text, question_pending=bool(self.question_key)):
            return False
        requested = bool(re.fullmatch(r'(?:(?:我)?(?:现在)?(?:想|愿意|希望)(?:做|开始|继续|恢复)|请(?:你)?(?:给我|帮我)(?:做)?)'
            r'(?:一下|一次|个|一份)?(?:(?:心理|近况|情绪)(?:辅助)?(?:自评|筛查|评估|量表)|量表|心理问卷)[吧呀。！!]*', text))
        if self.stage not in ('companionship', 'waiting_context') and not (
                requested and self.stage in ('declined', 'paused')):
            return False
        if HOLD_CORE_FOLLOWUP.search(text):
            return False
        item = self_report[:2] if self_report else core_concern_item(text)
        if not item and not requested:
            return False
        if requested and self.stage in ('declined', 'paused'):
            self.stage = 'waiting_context' if self.triggered else 'companionship'
        if item:
            scale, index = item
        else:
            current = self.current()
            scale, index = current[:2] if current else ('PHQ-9', 2)
        if not self.triggered:
            self.concern([entry.message_id], 'current-core-followup-v1', [scale])
        elif scale not in self.target_scales:
            self.target_scales.append(scale)
        if f'{scale}:{index}' not in self.answers:
            self.preferred_item = (scale, index)
        self.start_collection()
        self.detector_status = 'checked'
        self.version += 1
        return True

    def save_explicit_answer(self, scale, index, value, entry, *, standalone=False):
        answer = dict(value=value, evidence_ids=[entry.message_id],
                      confirmation_method='explicit_self_report' if standalone else 'explicit_frequency_answer',
                      extraction_version='explicit-frequency-v3' if self.core_only else 'explicit-frequency-v2')
        if standalone:
            answer['window_context_id'] = entry.message_id
        else:
            answer.update(confirmation_context_id=(self.question_followup or self.question_context).message_id,
                          question_context_id=self.question_context.message_id,
                          window_context_id=(self.window_context or self.question_context).message_id)
        self.answers[f'{scale}:{index}'] = answer
        self.current_call_answered=True
        self.last_answered_scale=scale
        self.detector_status, self.collection_feedback = 'checked', None
        self.pending,self.confirmation_asked,self.candidate_context=None,False,None
        self.question_key,self.question_context,self.question_followup=None,None,None
        self.observations=[o for o in self.observations if (o['scale'],o['item'])!=(scale,index)]
        if scale=='PHQ-9' and index==9 and value>0:
            self.stage='urgent';self.history_danger_unresolved=True
        elif not self.current():
            self.stage='complete'

    def capture_frequency_answer(self, entry, *, while_waiting=False):
        if not (self.streamlined and self.question_context and self.question_key
                and self.question_key not in self.answers):
            return False
        scale,index=self.question_key.split(':')
        index=int(index)
        question=self.question_context.text
        if while_waiting:
            if not self.core_only or not self.triggered or (scale,index)==('PHQ-9',9):
                return False
            if not re.search(CORE_WINDOW,question):
                return False
            if self.window_end and (not entry.occurred_at or self.window_end!=recall_date(entry.occurred_at)):
                return False
            # Accept a volunteered count without treating general agreement as a score.
            normalized=re.sub(r'[。！!，,？?\s]','',entry.text)
            value=core_day_count(normalized)
        else:
            confirmation=(self.question_followup or self.question_context).text
            value=frequency_answer(entry.text,OPTIONS_BY_SCALE[scale],confirmation,question)
        if value is None:
            return False
        self.save_explicit_answer(scale,index,value,entry)
        return True

    def observe(self, entry):
        if self.enabled and entry.role == 'assistant' and entry.final:
            if (self.normal_live and self.needs_current_safety_check
                    and entry.text.replace(' ','') == SAFETY_CHECK_QUESTION):
                self.safety_question_turn=entry.turn_id
                self.safety_check_asked=True
                self.version+=1
            if self.review_completed and self.user_turn_waiting_for_reply:
                self.post_review_turns+=1
                self.user_turn_waiting_for_reply=False
            if self.review_mode=='live' and self.stage in ('companionship','waiting_context') and self.user_turn_waiting_for_reply:
                self.dialogue_rounds+=1
                self.user_turn_waiting_for_reply=False
                if (self.stage in ('companionship','waiting_context')
                        and self.dialogue_rounds>=CONTEXT_CHECKIN_AFTER_USER_TURNS
                        and not self.context_checkin_asked):
                    self.context_checkin_due=True
                    self.version+=1
            if (self.review_mode=='live' and self.stage in ('companionship','waiting_context') and self.context_checkin_due and not self.context_checkin_asked
                    and re.search(r'继续.{0,4}(说|聊|分享|倾诉)|还想.{0,4}(说|聊|分享|倾诉)|一起.{0,4}(了解|看看|梳理)', entry.text)):
                self.context_checkin_due=False
                self.context_checkin_asked=True
                self.version+=1
            if ((self.stage=='complete' or self.review_completed) and re.search(r'还有.{0,12}[想要需要].{0,6}[聊说]|有什么.{0,12}(想聊|想说|要聊)|如果.{0,8}没有.{0,8}(到这里|先这样)', entry.text)):
                self.closing_question_asked=True
            item=self.current() if self.stage=='collecting' or (self.streamlined and self.triggered and self.stage=='waiting_context') else None
            if item:
                scale,index,_=item
                if self.streamlined:
                    if self.verifying_saved_call:
                        scoped=entry.text if re.search(CORE_WINDOW,entry.text) and '截至' not in entry.text else ''
                        if scoped:self.window_context=entry
                    else:
                        if re.search(r'两周|十四天|14天',entry.text):self.window_context=entry
                        scoped=entry.text if re.search(r'两周|十四天|14天',entry.text) else ('最近两周，'+entry.text if self.window_context else entry.text)
                    if self.core_only:
                        matches=[(target,question_item(scoped,target)) for target in self.target_scales]
                        matches=[(target,number) for target,number in matches if number]
                        if len(matches)==1:scale,asked=matches[0]
                        else:asked=None
                    else:
                        asked=question_item(scoped,scale)
                    if asked:
                        self.question_key=f'{scale}:{asked}' if f'{scale}:{asked}' not in self.answers else None
                        self.question_context=entry if self.question_key else None
                        self.question_followup=entry if self.question_key else None
                        if f'{scale}:{asked}' in self.answers:
                            self.last_repeated_topic=ITEMS[scale][asked-1];self.version+=1
                        else:self.last_repeated_topic=None
                    elif (self.question_key and self.question_context and re.search(r'这种|这类|那种|这个感受|这种感受|频率|属于|程度',entry.text)
                          and re.search(r'出现|频率|多久|哪种|属于|有时|偶尔|经常|从不|较少',entry.text)
                          and re.search(r'[？?]|吗|呢',entry.text)):
                        self.question_followup=entry
                    elif (self.core_only and self.question_key and self.question_context
                          and re.search(r'(?:^|[。！!；])\s*(?:那|那这两周里[，,]?)?(?:大概|大约)?(?:有|出现了)?'
                                        r'(?:几|多少)天(?:呢|呀|吗)?[？?]?$',entry.text)):
                        self.question_followup=entry
                    else:
                        self.question_key,self.question_context,self.question_followup=None,None,None
                        if self.core_only and self.stage=='collecting' and not self.pending and not self.end_after_response:
                            feedback = '刚才先回应了感受。用户愿意继续聊时，下一次回应请接上当前条目的两周频率问题。'
                            if getattr(self,'collection_feedback',None)!=feedback:
                                self.collection_feedback=feedback
                                self.version+=1
                elif (re.search(r'两周|十四天',entry.text) and any(cue in entry.text for cue in TOPIC_CUES[scale][index-1])
                        and re.search(r'[？?]|吗|呢|如何|怎么样|有没有|多少|频繁',entry.text)):
                    self.question_key=f'{scale}:{index}'
                    self.question_context=entry
                elif re.search(r'[？?]|吗|呢|怎么样|有没有',entry.text) and not any(cue in entry.text for cue in TOPIC_CUES[scale][index-1]):
                    self.question_key=None;self.question_context=None
            if (self.pending and item and OPTIONS_BY_SCALE[item[0]][self.pending[0]] in entry.text
                    and re.search(r'两周|十四天',entry.text)
                    and any(cue in entry.text for cue in TOPIC_CUES[item[0]][item[1]-1])
                    and (not POLARITY_GUARDS.get((item[0],item[1]))
                         or re.search(POLARITY_GUARDS[(item[0],item[1])],entry.text))
                    and re.search(r'对吗|是吗|确认|理解.*对|吗[？?]?', entry.text)):
                self.confirmation_asked = True
                self.confirmation_context_id = entry.message_id
            return
        if (not self.enabled or entry.role != 'user' or not entry.final
                or entry.message_id in self.seen):
            return
        self.seen.add(entry.message_id)
        text = entry.text.strip()
        self.latest_user_text=text
        safety_reply=self.read_safety_reply(entry)
        self_report = core_self_report(text) if self.core_only and (
            not self.needs_current_safety_check or self.stage=='collecting') else None
        before = (self.stage, len(self.answers), self.pending, self.end_after_response)
        # New speech can withdraw a previous wish to end, including a danger signal.
        self.end_after_response=False
        if self.review_completed or (self.review_mode=='live' and self.stage in ('companionship','waiting_context','complete')):
            self.user_turn_waiting_for_reply=True
        if safety_reply=='danger' or safety(text)['safety_signal']=='explicit_danger_expression':
            if self.stage=='complete':
                self.answers,self.target_scales,self.signals={},[],[]
                self.episode_id,self.window_end=None,None
            self.stage, self.pending = 'urgent', None
            self.history_danger_unresolved=True
            self.current_safety_discussed=False
            self.target_scales=list(dict.fromkeys([*self.target_scales,'PHQ-9']))
            self.signals=list(dict.fromkeys([*self.signals,entry.message_id]))
        elif ((self.stage=='complete' or self.review_completed) and self.closing_question_asked
              and re.fullmatch(r'(没有(啦|了)?|没了|暂时(没有|没了|没什么)|没什么(了)?|不用(了)?|不想聊(了)?|先这样|就这些|算了|好了)(谢谢|谢了|吧|啦)?[。！!，,？? ]*', text)):
            self.end_after_response=True
            self.closing_question_asked=False
        elif (self.stage=='collecting' and re.fullmatch(r'(好的[，,]?)?那?(我们)?(就|先)?(结束对话|聊到这里|不聊了|下次再聊)(吧|了)?[。！!，, ]*',text)):
            self.end_after_response=True
        elif self.open_core_followup(entry, text, self_report):
            if self_report and f'{self_report[0]}:{self_report[1]}' not in self.answers:
                self.save_explicit_answer(*self_report, entry, standalone=True)
        elif self.stage not in ('declined', 'urgent', 'complete'):
            if declines_collection(text, question_pending=bool(self.question_key)):
                self.action('decline')
            elif safety_reply=='addressed':
                self.current_safety_discussed=True
                self.stage='waiting_context' if self.triggered else 'companionship'
            elif self.stage=='waiting_context' and self.capture_frequency_answer(entry,while_waiting=True):
                pass
            elif (self.triggered and not self.needs_current_safety_check and self.stage in ('waiting_context','collecting')
                  and re.search(r'还有.{0,8}想问|有什么想问|还想问|你(可以|来|继续|多|再).{0,4}问|我愿意.{0,5}(回答|继续聊)',text)):
                self.user_invited_questions=True;self.start_collection();self.version+=1
            elif (self.review_mode=='live' and self.stage in ('waiting_context','companionship') and self.context_checkin_asked
                  and accepts_review_transition(text)):
                # A clear answer marks the end of the venting segment. Keep the
                # same call open while its transcript is reviewed in background.
                self.stage='reviewing'
                self.review_status='running'
                self.review_completed=False
                self.context_checkin_due=False
                self.context_checkin_asked=False
                self.user_turn_waiting_for_reply=False
                self.question_key=None
                self.version+=1
            elif self.stage == 'paused':
                if re.search(r'继续聊|接着聊', text):
                    self.stage = 'waiting_context'
            elif self.stage == 'collecting':
                if re.search(r'先停|休息一下|不舒服|有点难受|崩溃|很痛苦|撑不住|喘不过气|恐慌', text):
                    self.action('pause')
                else:
                    self.follow_core_topic(entry)
                    if self_report and self_report[0] in self.target_scales and f'{self_report[0]}:{self_report[1]}' not in self.answers:
                        self.save_explicit_answer(*self_report, entry, standalone=True)
                    elif self.capture_frequency_answer(entry):
                        pass
                    elif (self.pending and self.confirmation_asked
                            and re.fullmatch(r'(是的|对|没错|确认|嗯，对)[。！! ]*', text)):
                        scale, index, _ = self.current()
                        value, source = self.pending
                        self.answers[f'{scale}:{index}'] = dict(value=value, evidence_ids=[source, entry.message_id],
                                                              confirmation_context_id=self.confirmation_context_id,
                                                              **(self.candidate_context or {}))
                        self.last_answered_scale=scale
                        self.current_call_answered=True
                        self.observations=[o for o in self.observations if (o['scale'],o['item'])!=(scale,index)]
                        self.candidate_context=None
                        self.pending, self.confirmation_asked = None, False
                        self.question_key = None
                        if scale == 'PHQ-9' and index == 9 and value > 0:
                            self.stage = 'urgent'
                        elif not self.current():
                            self.stage = 'complete'
                    else:
                        self.pending, self.confirmation_asked = None, False
                        canonical = re.sub(r'[。！!，, ]', '', text)
                        canonical = re.sub(r'^(回顾这两周是|这两周应该是|大概|大约|应该是|就是)', '', canonical)
                        canonical = re.sub(r'吧$', '', canonical)
                        matches = [i for i, option in enumerate(OPTIONS_BY_SCALE[self.current()[0]]) if option == canonical]
                        if len(matches) == 1 and (not self.streamlined or self.question_key==f'{self.current()[0]}:{self.current()[1]}'):
                            self.pending = (matches[0], entry.message_id)
        if (self.streamlined and self.stage=='collecting' and len(self.answers)==before[1]
                and not self.end_after_response and self.pending is None):
            self.collection_feedback=('刚才的回答还不能确定该条目频率，请温和补问一次，不要反复要求确认。'
                if self.question_key else '刚才的问题没有对应仍缺的方向。下一次请纠正话题，只询问后台指定的下一项，不能自行认为已经采齐。')
            self.version+=1
        if (self.review_mode=='live' and self.stage in ('companionship','waiting_context') and not self.context_checkin_asked
                and self.user_turn_waiting_for_reply
                and self.dialogue_rounds+1>=CONTEXT_CHECKIN_AFTER_USER_TURNS
                and not self.context_checkin_due):
            self.context_checkin_due=True
            self.version+=1
        if before != (self.stage, len(self.answers), self.pending, self.end_after_response):
            self.version += 1

    def view(self):
        scales = []
        for scale in self.target_scales:
            values = [self.answers.get(f'{scale}:{i+1}') for i in range(len(ITEMS[scale]))]
            complete = all(v is not None for v in values)
            scales.append(dict(scale=scale, display_name=SCALE_LABELS.get(scale,scale),
                               direction=SCALE_DIRECTIONS.get(scale),
                               score_kind='project_dialogue_indicator' if scale in SCALE_DIRECTIONS else 'conversation_assisted',
                               answered=sum(v is not None for v in values), required=len(values),
                               max_score=len(values)*(len(OPTIONS_BY_SCALE[scale])-1),
                               total=sum(v['value'] for v in values) if complete else None,
                               status='complete_unverified' if complete else 'incomplete', items=values))
        return dict(type='screening.status', stage=self.stage, version=self.version, review_status=self.review_status, review_mode=self.review_mode, scales=scales,
                    demo_mode=self.demo_mode,trigger_origin=self.trigger_origin,
                    triggered=self.triggered, source='conversation_assisted', verification_status='unverified',
                    protocol='conditional-dialogue-indicators-v1', indicator_version='conversation-indicator-3x5-v1',
                    recall_window='past_two_weeks',
                    authorization_source='purchase_notice_deployment_declaration',
                    purchase_notice_version=self.notice_version, signal_evidence=self.signals,
                    detector_version=self.detector, detector_status=self.detector_status,
                    decisions=self.decisions, formal_assessment=False,observations=self.observations,
                    history_session_ids=self.history_session_ids,history_danger_unresolved=self.history_danger_unresolved,
                    episode_id=self.episode_id,window_end=self.window_end,transport_diagnostics=self.transport_diagnostics)

    def public_status(self):
        value=dict(type='screening.status',stage=self.stage,version=self.version,
                    review_mode=self.review_mode,
                    triggered=self.triggered,detector_status=self.detector_status,
                    review_status=self.review_status,
                    formal_assessment=False,collection_progress=dict(answered=sum(s['answered'] for s in self.view()['scales']),required=sum(s['required'] for s in self.view()['scales'])))
        if self.demo_mode:
            scale=next((s for s in self.view()['scales'] if s['scale']=='mood_interest'),None)
            value.update(demo_mode=True,trigger_origin=self.trigger_origin,
                demo_progress={k:scale[k] for k in ('answered','required','total','max_score')} if scale else None)
        return value

    def instructions(self):
        base = ('你是温和的中文陪伴助手，先倾听回应感受。不诊断，不宣称情绪已稳定，不宣布分数。'
                '产品在购买须知中说明信息整理和后台辅助评分用途；无需再次征求量表同意、要求用户准备好、报量表名或念题号。'
                '不得否认或虚假解释信息整理用途，用户询问时如实说明。用户随时可以停止。'
                '每次至多一个具体问题，先回应再提问，避免机械串题；用户请你主导时要主动提出与经历相关的问题，不只安慰或让用户自己找话题。'
                '平台会保存采集任务和已确认条目并带入后续通话。不要编造“会话隔离所以没保存或看不到旧进度”的解释；只能如实说明当前提供的任务摘要，实际保存以平台显示为准。'
                '不提供未经核实的热线号码，不从模型记忆编造联系方式。')+self.background
        if self.window_end:base+=f'本次回顾范围固定为截至{self.window_end}的前两周，跨会话保持同一回顾范围，不混用不同时段。'
        if self.normal_live and self.current_safety_discussed:
            base+='本次已直接了解过用户此刻是否仍有相关念头，请回应当前对话，不用重复询问过去的情况。后续有新的危险表达仍须优先安全关怀。'
        if not self.enabled:
            return base+'当前会话未启用后台信息采集，只自然陪伴；用户问及功能时如实说明当前未启用，不说系统永远不会主动了解。'
        if self.demo_mode:
            base+=('当前为隔离的快速采集演示，只演示3项自定义对话指标，不能称为PHQ-9/GAD-7或正式量表。'
                '只有后台已安排采集任务并进入collecting阶段后才询问指定条目，未安排时不要一开场就问频率。每一段先明确最近两周的范围，后续承接同一范围，不必逐句机械重复，'
                '用户明确回答频率后简短回应并等待后台切换下一项，不再逐项要求回答“对”。只有含糊或无法确定频率时才补问；不宣布或猜测分数。'
                '严格按后台当前话题逐项交流，不自行改成睡眠、食欲等其他问题。频率可为从不、较少、有时、经常、几乎总是。仍尊重拒绝，危险表达优先安全支持。')
        if self.triggered and self.answers:
            completed=[ITEMS[scale][int(index)-1] for key in self.answers for scale,index in [key.split(':')]]
            remaining=[topic for scale in self.target_scales for i,topic in enumerate(ITEMS[scale],1) if f'{scale}:{i}' not in self.answers]
            base+=('后台已保存的方向：'+'、'.join(completed)+'。这些方向已完成，不重复询问它们的频率，也不重新确认。'
                '尚缺的方向：'+('、'.join(remaining) or '无')+'。')
            next_item=self.current()
            if next_item:base+='下一项只了解“'+next_item[2]+'”，不要重问已完成方向，不跳到未安排的条目。'
            if self.streamlined and getattr(self,'last_repeated_topic',None):
                base+='刚才重复询问了已保存的“'+self.last_repeated_topic+'”。请立即纠正后续话题，不能再问这一方向或把其回答当成其他条目。'
        if self.streamlined:base+='已明确时间范围和频率的回答由后台记录，不重复索要确认；只有含糊回答才温和澄清。只使用当前条目对应的频率选项，不混用不同量表的选项。'
        if self.end_after_response:
            return base+'用户已明确表示暂时没有其他想聊的内容。简短温暖告别，不再提问，不总结分数或诊断。'
        base += ('用户问“什么情况下会主动了解、是否会发起问卷”时，说明：会结合前面的具体交流，'
                 '在需要进一步了解且适合继续聊时自然问问近况，不需要用户主动要求或说特定口令，也不会据此诊断。'
                 '不要回答“我不会主动发起”“只有你主动提出才会涉及”；不把关于功能的假设问题当成用户症状。')
        if self.stage=='checking_in':
            if self.normal_live:
                status=('平台刚问过此刻是否有伤害自己的念头，紧接着的简短是或否回答是对此问题的回应。'
                        if self.safety_question_turn else '本次先回应此刻感受，由平台在适当时补充安全关怀。')
                return base+status+'不要当作已经安全，不开始量表，也不重复平台已问的安全问题。'
            return base+'上次有需要持续关注的表达，本次先温和询问此刻感受和是否仍被那些念头困住。不要当作已经安全，不直接开始量表，不用问卷确认安全。'
        if self.stage=='reviewing':
            return base+'用户刚结束一段倾诉，先温和说“我先把咱们刚才聊的内容梳理一下，稍等我一小会儿，马上回来跟你接着说。”后台最多等待约4秒，整个语音连接保持开启。期间若用户明确在问你或继续对你说话，正常回应并倾听；若明显是在自言自语或对旁人说话，不要插话。后台会根据本段文字决定是否以及沿哪些方向进一步了解，不要自行猜测是否要做、做哪些指标，不要宣布情绪正常。'
        if self.stage in ('companionship', 'waiting_context'):
            if self.review_mode=='post_session':
                if self.core_only and not self.triggered:
                    return base+'自然倾听，回应用户刚提到的感受；可以温和问一句近况。后台会在当前对话期间查看是否适合继续了解，不自行启动固定条目。'
                return base+('新的关注线索会在本次通话文字保存后由后台复核，不要让用户等待后台分析、说“准备好了”或确认是否开始问卷。'
                    '本次先自然倾听并回应具体经历。已有跨会话任务时先留意此刻是否适合继续，后台下发采集阶段后再自然衔接指定话题；未安排任务时不自行执行固定条目。')
            if self.review_completed:
                if self.closing_question_asked:
                    return base+'刚才的对话回顾未发现足够线索安排项目内对话指标。自然继续陪伴几轮，不提量表，不判断用户情绪“正常”或“平复”。已经委婉问过是否还想聊；若用户明确表示没有，就温暖告别并结束本次通话。'
                return base+'刚才的对话回顾未发现足够线索安排项目内对话指标。自然回应并继续聊一小会儿；不要说用户情绪正常，也不要提量表。约两轮后委婉问：“我们还可以再聊一会儿；如果你觉得今天先到这里也可以，你还有什么想和我说的吗？”用户明确表示没有时温暖告别并结束本次通话。'
            if self.context_checkin_due and not self.context_checkin_asked:
                return base+'用户已经和你来回聊了约3到4轮，你仍不确定对方是否暂告一段落。先回应刚才的内容，再清楚而委婉地问：“你还想继续说说吗？如果差不多了，我可以陪你一起梳理最近的情况。”不要直接开始固定条目。用户说还想继续时就继续倾听，不重复催问；用户明确说差不多了或愿意梳理时，再从后台选定的相关方向自然聊起。'
            if self.context_checkin_asked:
                return base+'你已经委婉确认过对话节奏。若用户还想继续倾诉，就接着听并回应具体内容，不重复问是否说完；若用户表示差不多了或愿意一起梳理，顺着其表达进入后台选定的一个相关方向。不要把普通的“好”或对话功能询问当作症状。'
            return base+'当前先自然了解近况，可围绕用户提到的具体困扰温和问一个问题，留意持续时间和生活影响；后台未安排前不执行固定条目采集，不否认后续会主动了解。'
        if self.stage in ('paused','declined'):
            return base+'尊重暂停或停止信息采集，不继续相关追问。'
        if self.stage == 'urgent':
            return base + '立即停止信息采集，优先关怀与安全支持，温和了解当前是否有立即伤害自己的可能，鼓励及时获得身边可信任的人及专业支持，不保证安全、不编造热线号码。'
        if self.stage=='complete':
            if self.end_after_response:
                return base+'用户已表示暂时没有其他想聊的内容。简短温暖告别，不再提问，也不总结分数或诊断。'
            return base+'相关问题结束后，不要立即结束对话。继续温和倾听与支持，回应用户自己的感受，不宣布情绪已平缓，不直接问“好些了吗”。留意用户表达内容、语气和对话节奏是否显示愿意告一段落，不凭一次简短回答就推断；自然出现收尾信号时，委婉问今天是否还有想聊的；若用户表示没有，就简短告别不再追问。'
        if getattr(self,'collection_feedback',None):base+=self.collection_feedback
        if self.user_invited_questions:base+='用户已明确邀请你继续提问。请在本轮依次了解多个未完成方向，不把邀请转回让用户自己找话题；仍须回应感受、一次一个问题并尊重停止。'
        scale,index,topic = self.current()
        conversational_style='每次只问一项，语气温和自然，不报量表名或题号；根据近两周的真实回答整理信息，结果属于对话辅助采集、待核实，不等同标准自填量表或诊断；用户问起用途时如实说明。'
        if scale in CUSTOM_SCALE_IDS:
            conversational_style+='当前是项目自定义指标，不能称为标准量表分数。'
        if (scale,index) in POLARITY_GUARDS:
            conversational_style+='保留问题的负向含义，问清困难或缺少的情况，不把有兴趣、能放松等正向经历误记为症状。'
        if self.pending:
            option=OPTIONS_BY_SCALE[scale][self.pending[0]]
            if scale=='coping_resources':
                return base + conversational_style + (f'自然复述并确认：最近两周，你提到“{topic}”这样的应对或支持资源时，频率大约是“{option}”，我理解得对吗？'
                               '不推断用户缺乏韧性，不把资源存在与否当成诊断；不换话题、不要求报具体天数。')
            return base + conversational_style + (f'自然复述并确认：最近两周，“{topic}”出现的情况是“{option}”，我这样理解对吗？'
                           '保留用户描述的含义，不引导选择；不换话题、不要求报具体天数。')
        options=OPTIONS_BY_SCALE[scale]
        if self.core_only:
            conversational_style+='把近两周和大约多少天问在同一个问题里。只回答“有时”“有点”“经常”时，顺着原话自然问大概有几天，再继续其它话题。'
        opener = CORE_OPENERS.get((scale,index)) if self.core_only else None
        if opener:
            conversational_style += f'可直接采用这个自然问法：“{opener}”先回应一句，再立即问这一个问题，等用户回答。'
        return base + conversational_style + (f'后台已根据对话线索安排进一步了解。下一次回应先接住用户经历，再自然衔接一个关于最近两周“{topic}”的简短问题，不要只说“你继续说”。'
                       f'若自由表达无法整理出频率，才温和澄清，选项为：{"、".join(options)}。'
                       '不引导选择，不猜测答案。已确认一个条目后，先简短回应，再自然衔接后台指定的下一项；不能把一轮通话限制成一个条目，也不要在尚缺信息时反复说随时再来聊。每次只问一个具体小问题，连续了解两三项后留出倾诉或休息空间，用户不愿意、痛苦或想结束时立即停止。')


def recall_date(timestamp):
    return datetime.fromisoformat(timestamp).astimezone(timezone(timedelta(hours=8))).date().isoformat()


def verify_saved_call_answers(records):
    """Read the complete transcript in sequence and return grounded current-call items."""
    if any(row.role=='user' and row.text_status=='completed' and (
            declines_collection(row.content,question_pending=True)
            or safety(row.content)['safety_signal']=='explicit_danger_expression') for row in records):
        return {}
    controller=Screening(True)
    controller.core_only=controller.direct_collection=controller.verifying_saved_call=True
    controller.target_scales=list(CORE_TARGETS)
    controller.stage='collecting'
    for row in records:
        if row.role=='user' and row.text_status!='completed':
            continue
        text=row.content if row.text_status=='completed' and row.playback_status!='interrupted' else ''
        controller.observe(SimpleNamespace(message_id=row.external_message_id,role=row.role,
            text=text,final=True,occurred_at=row.occurred_at))
        if controller.stage in ('urgent','declined'):
            return {}
        if controller.stage!='collecting':
            break
    return controller.answers


def has_collected_items(payload):
    return bool(payload.get('triggered', True) and any(s.get('answered', 0) > 0 for s in payload.get('scales', [])))


def save_result(uid, sid, controller):
    from ..database import SessionLocal
    # Ordinary conversation must not create empty PHQ/GAD records.
    if not controller.enabled:
        return False
    with SessionLocal() as db:
        view=controller.view()
        db.merge(CollectionTrace(session_id=sid,owner=uid,payload={k:view[k] for k in
            ('version','stage','triggered','detector_status','detector_version','review_status','review_mode','demo_mode','trigger_origin','protocol','purchase_notice_version',
             'observations','history_session_ids','history_danger_unresolved','episode_id','window_end','transport_diagnostics')}))
        if has_collected_items(view):
            db.merge(ScreeningResult(session_id=sid, owner=uid, payload=view))
        db.commit()
    return has_collected_items(view)
