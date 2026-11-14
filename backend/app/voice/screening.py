"""Conservative conversational collection, not a validated clinical instrument."""
import re
from sqlalchemy import Column, Integer, String, JSON, ForeignKey
from ..database import Base
from care_core import safety
from .screening_policy import collection_targets

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
TOPIC_CUES = {
    'PHQ-9': [('兴趣','乐趣','喜欢','兴致'),('低落','盼头','沮丧','心情'),('睡','入眠','失眠'),
              ('疲倦','精力','累'),('食欲','吃饭','胃口','吃得'),('自责','失望','价值'),
              ('注意','集中','阅读'),('动作','说话','坐立','缓慢'),('死','伤害','活着')],
    'GAD-7': [('紧张','焦虑','坐立不安'),('控制','停不下','停止','担忧','担心'),('各种','不同事情','担忧','担心'),
              ('放松',),('安坐','坐立'),('烦躁','急躁','烦恼'),('害怕','可怕','发生')],
    'mood_interest': [('低落','提不起兴趣','没兴趣','兴致','没乐趣','心情'),('精力','疲倦','疲惫','乏力','没力气','没有力气','没精神','没有精神','提不起劲','没有动力','没动力','行动','做事'),('自责','责怪自己','没希望','希望','评价自己','自我评价','没价值','没有价值','一无是处','自己很差','没盼头','没有盼头')],
    'worry_anxiety': [('担忧','反复担忧','停不下来','担心','忧虑'),('紧张','焦虑','心慌'),('放松','安定','平静')],
    'stress_load': [('掌控','控制不了','安排不过来'),('压力','负担','应付不了'),('压力影响','生活安排','工作学习')],
    'sleep_wellbeing': [('入睡','睡不着','睡眠'),('夜里醒','早醒','醒来'),('白天疲惫','白天状态','睡眠影响')],
    'coping_resources': [('变化','调整','适应'),('挫折','恢复','继续行动'),('支持','帮助','找谁')],
    'social_comfort': [('不熟悉的人','权威','互动','交谈'),('群体','小组','表达'),('被注视','被评价','回避','不自在')],
}
POLARITY_GUARDS = {
    ('PHQ-9',1): r'缺少兴趣|缺乏兴趣|没.{0,4}兴趣|不感兴趣|兴趣减退|提不起.{0,3}兴趣|提不起兴致|没.{0,4}乐趣|缺少.{0,5}乐趣',
    ('PHQ-9',7): r'难以集中|无法集中|注意力不集中|容易分心|难.{0,3}集中注意',
    ('GAD-7',4): r'难以放松|无法放松|不能放松|放松不下来|很难放松',
}

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
    """Only explicit option wording, including simple spoken endings."""
    canonical=re.sub(r'[。！!，,\s]','',text)
    canonical=re.sub(r'^(大概|大约)','',canonical)
    canonical=re.sub(r'(会这样|会如此|这样|出现|有这种情况|吧|的)$','',canonical)
    if options==CUSTOM_OPTIONS:
        canonical={'常常':'经常','时不时':'有时','偶尔':'较少','从来没有':'从不','没有这种情况':'从不','完全没有':'从不','几乎每次':'几乎总是'}.get(canonical,canonical)
    matches=[i for i,option in enumerate(options) if canonical==option]
    return matches[0] if len(matches)==1 else None


def frequency_answer(text,options,question):
    value=explicit_frequency(text,options)
    if value is not None:return value
    if re.fullmatch(r'(是的|对|没错|确实|确实是)[。！!，,\s]*',text):
        if re.search(r'不是|不算|不怎么|不太|并不|并非|很少|不常|少有',question):return None
        values=[i for i,option in enumerate(options) if option in question]
        if len(values)==1:return values[0]
    return None


def demo_question_item(text):
    """Route only explicit project indicator questions, independent of ask order."""
    if not re.search(r'两周|十四天',text) or not re.search(r'[？?]|吗|呢|如何|怎么样|有没有|多少|频繁',text):return None
    question_text=re.split(r'两周|十四天',text)[-1]
    matches=[i+1 for i,cues in enumerate(TOPIC_CUES['mood_interest']) if any(cue in question_text for cue in cues)]
    if len(matches)!=1:return None
    direction={1:r'低落|没.{0,4}(兴趣|兴致|乐趣)|提不起.{0,3}(兴趣|兴致)|持续低落',
        2:r'不足|没.{0,3}(精力|力气|精神|动力)|疲倦|疲惫|乏力|提不起劲|受到影响|行动.{0,4}(困难|受|影响)',
        3:r'自责|责怪自己|没.{0,4}(希望|价值|盼头)|一无是处|自己很差|自我评价.{0,6}(影响|差|低)|希望感.{0,4}影响'}
    return matches[0] if re.search(direction[matches[0]],question_text) else None

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
        self.demo_mode = False
        self.trigger_origin = 'context_model'
        self.stage = 'companionship'
        self.signals, self.target_scales, self.decisions = [], [], []
        self.answers, self.pending = {}, None
        self.version, self.seen = 0, set()
        self.confirmation_asked = False
        self.question_key = None
        self.question_context = None
        self.confirmation_context_id = None
        self.detector = None
        self.detector_status = 'not_checked'
        self.history_session_ids=[]
        self.history_danger_unresolved=False
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
        targets = target_scales or (['mood_interest'] if self.demo_mode else collection_targets())
        if self.demo_mode and any(s!='mood_interest' for s in targets):
            raise ValueError('collection_demo_target_invalid')
        if not ids or not targets or any(s not in ITEMS for s in targets):
            raise ValueError('invalid_concern_signal')
        self.signals = list(dict.fromkeys(ids))
        self.target_scales = list(dict.fromkeys(targets))
        self.detector = version
        self.stage = 'waiting_context'
        self.context_checkin_due=(self.dialogue_rounds>=CONTEXT_CHECKIN_AFTER_USER_TURNS
                                  and not self.context_checkin_asked)
        self.version += 1

    def apply_decision(self, result, *, fresh=True):
        if not self.enabled or self.stage in ('declined', 'urgent', 'complete'):
            return False
        if self.review_status in ('running','pending') and not fresh:
            return False
        self.detector_status = 'checked'
        self.decisions = (self.decisions + [result])[-6:]
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
        elif action == 'pause' and self.stage == 'collecting':
            self.stage, self.pending = 'paused', None
        # ready/consent from older clients deliberately cannot authorize or
        # trigger collection; the product notice is configured server-side.
        if previous != self.stage:
            self.version += 1

    def current(self):
        return next(((scale, i+1, topic) for scale in self.target_scales
                     for i, topic in enumerate(ITEMS[scale])
                     if f'{scale}:{i+1}' not in self.answers), None)

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
        if not self.demo_mode or self.stage!='collecting':return False
        before=len(self.answers)
        question=None
        for entry in turns:
            if not entry.final:continue
            if not self.current():break
            if entry.role=='assistant':
                index=demo_question_item(entry.text)
                question=entry if index and f'mood_interest:{index}' not in self.answers else None
            elif entry.role=='user':
                if (safety(entry.text)['safety_signal']=='explicit_danger_expression'
                        or declines_collection(entry.text,question_pending=bool(question))
                        or re.search(r'先停|休息一下|不舒服|有点难受|崩溃|很痛苦|撑不住|喘不过气|恐慌',entry.text)):
                    self.seen.discard(entry.message_id);self.observe(entry);break
                if question and frequency_answer(entry.text,CUSTOM_OPTIONS,question.text) is not None:
                    self.question_context=question;self.question_key=f'mood_interest:{demo_question_item(question.text)}'
                    self.seen.discard(entry.message_id);self.observe(entry)
                question=None
        return len(self.answers)!=before

    def observe(self, entry):
        if self.enabled and entry.role == 'assistant' and entry.final:
            if self.review_completed and self.user_turn_waiting_for_reply:
                self.post_review_turns+=1
                self.user_turn_waiting_for_reply=False
            if self.stage in ('companionship','waiting_context') and self.user_turn_waiting_for_reply:
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
            item=self.current() if self.stage=='collecting' or (self.demo_mode and self.triggered and self.stage=='waiting_context') else None
            if item:
                scale,index,_=item
                if self.demo_mode:
                    asked=demo_question_item(entry.text)
                    self.question_key=f'mood_interest:{asked}' if asked and f'mood_interest:{asked}' not in self.answers else None
                    self.question_context=entry if self.question_key else None
                    if asked and f'mood_interest:{asked}' in self.answers:
                        self.last_repeated_topic=ITEMS['mood_interest'][asked-1];self.version+=1
                    elif asked:self.last_repeated_topic=None
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
        before = (self.stage, len(self.answers), self.pending, self.end_after_response)
        # New speech can withdraw a previous wish to end, including a danger signal.
        self.end_after_response=False
        if self.stage in ('companionship', 'waiting_context', 'complete') or self.review_completed:
            self.user_turn_waiting_for_reply=True
        if safety(text)['safety_signal'] == 'explicit_danger_expression':
            self.stage, self.pending = 'urgent', None
            self.history_danger_unresolved=True
            self.target_scales=list(dict.fromkeys([*self.target_scales,'PHQ-9']))
            self.signals=list(dict.fromkeys([*self.signals,entry.message_id]))
        elif ((self.stage=='complete' or self.review_completed) and self.closing_question_asked
              and re.fullmatch(r'(没有(啦|了)?|没了|暂时(没有|没了|没什么)|没什么(了)?|不用(了)?|不想聊(了)?|先这样|就这些|算了|好了)(谢谢|谢了|吧|啦)?[。！!，,？? ]*', text)):
            self.end_after_response=True
            self.closing_question_asked=False
        elif (self.stage=='collecting' and re.fullmatch(r'(好的[，,]?)?那?(我们)?(就|先)?(结束对话|聊到这里|不聊了|下次再聊)(吧|了)?[。！!，, ]*',text)):
            self.end_after_response=True
        elif self.stage not in ('declined', 'urgent', 'complete'):
            if declines_collection(text, question_pending=bool(self.question_key)):
                self.action('decline')
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
                elif (self.demo_mode and self.question_context is not None
                      and self.question_key and self.question_key not in self.answers
                      and frequency_answer(text,CUSTOM_OPTIONS,self.question_context.text) is not None):
                    scale,index=self.question_key.split(':');index=int(index)
                    value=frequency_answer(text,OPTIONS_BY_SCALE[scale],self.question_context.text)
                    self.detector_status='checked'
                    self.collection_feedback=None
                    context_id=self.question_context.message_id
                    self.answers[f'{scale}:{index}']=dict(value=value,evidence_ids=[entry.message_id],
                        confirmation_context_id=context_id,question_context_id=context_id,window_context_id=context_id,
                        confirmation_method='explicit_frequency_answer',extraction_version='explicit-demo-frequency-v1')
                    self.pending,self.confirmation_asked,self.candidate_context=None,False,None
                    self.question_key,self.question_context=None,None
                    self.observations=[o for o in self.observations if (o['scale'],o['item'])!=(scale,index)]
                    if not self.current():self.stage='complete'
                elif (self.pending and self.confirmation_asked
                        and re.fullmatch(r'(是的|对|没错|确认|嗯，对)[。！! ]*', text)):
                    scale, index, _ = self.current()
                    value, source = self.pending
                    self.answers[f'{scale}:{index}'] = dict(value=value, evidence_ids=[source, entry.message_id],
                                                          confirmation_context_id=self.confirmation_context_id,
                                                          **(self.candidate_context or {}))
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
                    if len(matches) == 1 and (not self.demo_mode or self.question_key==f'{self.current()[0]}:{self.current()[1]}'):
                        self.pending = (matches[0], entry.message_id)
        if (self.demo_mode and self.stage=='collecting' and len(self.answers)==before[1]
                and not self.end_after_response and self.pending is None):
            self.collection_feedback=('刚才的回答还不能确定该条目频率，请温和补问一次，不要反复要求确认。'
                if self.question_key else '刚才的问题没有对应仍缺的方向。下一次请纠正话题，只询问后台指定的下一项，不能自行认为已经采齐。')
            self.version+=1
        if (self.stage in ('companionship','waiting_context') and not self.context_checkin_asked
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
                    formal_assessment=False)
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
                '不提供未经核实的热线号码，不从模型记忆编造联系方式。')+self.background
        if self.window_end:base+=f'本次回顾范围固定为截至{self.window_end}的前两周，跨会话保持同一回顾范围，不混用不同时段。'
        if not self.enabled:
            return base+'当前会话未启用后台信息采集，只自然陪伴；用户问及功能时如实说明当前未启用，不说系统永远不会主动了解。'
        if self.demo_mode:
            base+=('当前为隔离的快速采集演示，只演示3项自定义对话指标，不能称为PHQ-9/GAD-7或正式量表。'
                '简短回应后进入后台指定的话题，不长篇安慰或追问无关背景。每项必须明确最近两周，'
                '用户明确回答频率后简短回应并等待后台切换下一项，不再逐项要求回答“对”。只有含糊或无法确定频率时才补问；不宣布或猜测分数。'
                '严格按后台当前话题逐项交流，不自行改成睡眠、食欲等其他问题。频率可为从不、较少、有时、经常、几乎总是。仍尊重拒绝，危险表达优先安全支持。')
        if self.triggered and self.answers:
            completed=[ITEMS[scale][int(index)-1] for key in self.answers for scale,index in [key.split(':')]]
            remaining=[topic for scale in self.target_scales for i,topic in enumerate(ITEMS[scale],1) if f'{scale}:{i}' not in self.answers]
            base+=('后台已保存的方向：'+'、'.join(completed)+'。这些方向已完成，不重复询问它们的频率，也不重新确认。'
                '尚缺的方向：'+('、'.join(remaining) or '无')+'。')
            if remaining:base+='下一项只了解“'+remaining[0]+'”，不要重问已完成方向，不跳到未安排的条目。'
            if self.demo_mode and getattr(self,'last_repeated_topic',None):
                base+='刚才重复询问了已保存的“'+self.last_repeated_topic+'”。请立即纠正后续话题，不能再问这一方向或把其回答当成其他条目。'
        if self.end_after_response:
            return base+'用户已明确表示暂时没有其他想聊的内容。简短温暖告别，不再提问，不总结分数或诊断。'
        base += ('用户问“什么情况下会主动了解、是否会发起问卷”时，说明：会结合前面的具体交流，'
                 '在需要进一步了解且适合继续聊时自然问问近况，不需要用户主动要求或说特定口令，也不会据此诊断。'
                 '不要回答“我不会主动发起”“只有你主动提出才会涉及”；不把关于功能的假设问题当成用户症状。')
        if self.stage=='checking_in':
            return base+'上次有需要持续关注的表达，本次先温和询问此刻感受和是否仍被那些念头困住。不要当作已经安全，不直接开始量表，不用问卷确认安全。'
        if self.stage=='reviewing':
            return base+'用户刚结束一段倾诉，先温和说“我先把咱们刚才聊的内容梳理一下，稍等我一小会儿，马上回来跟你接着说。”后台最多等待约4秒，整个语音连接保持开启。期间若用户明确在问你或继续对你说话，正常回应并倾听；若明显是在自言自语或对旁人说话，不要插话。后台会根据本段文字决定是否以及沿哪些方向进一步了解，不要自行猜测是否要做、做哪些指标，不要宣布情绪正常。'
        if self.stage in ('companionship', 'waiting_context'):
            if self.review_mode=='post_session':
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
        _, _, topic = self.current()
        conversational_style='每次只问一项，语气温和自然，不报量表名或题号；根据近两周的真实回答整理信息，结果属于对话辅助采集、待核实，不等同标准自填量表或诊断；用户问起用途时如实说明。'
        if self.current()[0] in CUSTOM_SCALE_IDS:
            conversational_style+='当前是项目自定义指标，不能称为标准量表分数。'
        if (self.current()[0],self.current()[1]) in POLARITY_GUARDS:
            conversational_style+='保留问题的负向含义，问清困难或缺少的情况，不把有兴趣、能放松等正向经历误记为症状。'
        if self.pending:
            option=OPTIONS_BY_SCALE[self.current()[0]][self.pending[0]]
            if self.current()[0]=='coping_resources':
                return base + conversational_style + (f'自然复述并确认：最近两周，你提到“{topic}”这样的应对或支持资源时，频率大约是“{option}”，我理解得对吗？'
                               '不推断用户缺乏韧性，不把资源存在与否当成诊断；不换话题、不要求报具体天数。')
            return base + conversational_style + (f'自然复述并确认：最近两周，“{topic}”出现的情况是“{option}”，我这样理解对吗？'
                           '保留用户描述的含义，不引导选择；不换话题、不要求报具体天数。')
        options=OPTIONS_BY_SCALE[self.current()[0]]
        return base + conversational_style + (f'后台已根据对话线索安排进一步了解。下一次回应先接住用户经历，再自然衔接一个关于最近两周“{topic}”的简短问题，不要只说“你继续说”。'
                       f'若自由表达无法整理出频率，才温和澄清，选项为：{"、".join(options)}。'
                       '不引导选择，不猜测答案。确认后先回应用户经历，允许自由闲聊，不急于下一话题。')


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
            ('stage','triggered','detector_status','detector_version','review_status','review_mode','demo_mode','trigger_origin','protocol','purchase_notice_version',
             'observations','history_session_ids','history_danger_unresolved','episode_id','window_end','transport_diagnostics')}))
        if has_collected_items(view):
            db.merge(ScreeningResult(session_id=sid, owner=uid, payload=view))
        db.commit()
    return has_collected_items(view)
