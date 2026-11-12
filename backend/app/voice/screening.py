"""Conservative conversational collection, not a validated clinical instrument."""
import re
from sqlalchemy import Column, Integer, String, JSON, ForeignKey
from ..database import Base
from care_core import safety

ITEMS = {
    'PHQ-9': ['做事缺少兴趣或乐趣', '心情低落或没有盼头', '难以入睡、睡眠中断或睡得过多',
              '疲倦或缺乏精力', '食欲减少或吃得过多', '自责或觉得自己让人失望',
              '难以集中注意力（例如阅读或看电视）', '动作或说话变慢，或坐立不安', '伤害自己或觉得不如死去的念头'],
    'GAD-7': ['紧张、焦虑或坐立不安', '无法停止或控制担忧', '对不同事情担忧过多',
              '难以放松', '烦躁得难以安坐', '容易烦恼或急躁', '担心可怕的事情会发生'],
}
OPTIONS = ['完全没有', '有几天', '超过一半的天数', '几乎每天']
TOPIC_CUES = {
    'PHQ-9': [('兴趣','乐趣','喜欢','兴致'),('低落','盼头','沮丧','心情'),('睡','入眠','失眠'),
              ('疲倦','精力','累'),('食欲','吃饭','胃口','吃得'),('自责','失望','价值'),
              ('注意','集中','阅读'),('动作','说话','坐立','缓慢'),('死','伤害','活着')],
    'GAD-7': [('紧张','焦虑','坐立不安'),('控制','停不下','停止','担忧','担心'),('各种','不同事情','担忧','担心'),
              ('放松',),('安坐','坐立'),('烦躁','急躁','烦恼'),('害怕','可怕','发生')],
}
POLARITY_GUARDS = {
    ('PHQ-9',1): r'缺少兴趣|缺乏兴趣|没.{0,4}兴趣|不感兴趣|兴趣减退|提不起.{0,3}兴趣|提不起兴致|没.{0,4}乐趣|缺少.{0,5}乐趣',
    ('PHQ-9',7): r'难以集中|无法集中|注意力不集中|容易分心|难.{0,3}集中注意',
    ('GAD-7',4): r'难以放松|无法放松|不能放松|放松不下来|很难放松',
}

class ScreeningResult(Base):
    __tablename__='robot_voice_screening_results'
    session_id=Column(Integer,ForeignKey('robot_record_sessions.id',ondelete='CASCADE'),primary_key=True)
    owner=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    payload=Column(JSON,nullable=False)

class Screening:
    def __init__(self, enabled=False, notice_version=''):
        self.enabled = enabled
        self.notice_version = notice_version
        self.stage = 'companionship'
        self.signals, self.target_scales, self.decisions = [], [], []
        self.answers, self.pending = {}, None
        self.version, self.seen = 0, set()
        self.confirmation_asked = False
        self.question_key = None
        self.confirmation_context_id = None
        self.detector = None
        self.detector_status = 'not_checked'

    @property
    def triggered(self):
        return bool(self.target_scales and self.signals)

    def concern(self, ids, version, target_scales=None):
        # External models only identify a concern. They cannot bypass the pacing
        # decision, user stop, danger override, or select arbitrary instruments.
        if not self.enabled or self.stage != 'companionship':
            return
        targets = target_scales or list(ITEMS)
        if not ids or not targets or any(s not in ITEMS for s in targets):
            raise ValueError('invalid_concern_signal')
        self.signals = list(dict.fromkeys(ids))
        self.target_scales = list(dict.fromkeys(targets))
        self.detector = version
        self.stage = 'waiting_context'
        self.version += 1

    def apply_decision(self, result, *, fresh=True):
        if not self.enabled or self.stage in ('declined', 'urgent', 'complete'):
            return False
        self.detector_status = 'checked'
        self.decisions = (self.decisions + [result])[-6:]
        before = (self.stage, self.triggered)
        if result['decision'] == 'follow_up':
            if not self.triggered:
                self.concern([e['message_id'] for e in result['evidence']],
                             result['detector_version'], result['target_scales'])
            # A late inference may identify a continuing concern, but cannot
            # declare a newer user turn ready for transition.
            if fresh and result['transition_ready'] and self.stage == 'waiting_context':
                self.stage = 'collecting'
        if before != (self.stage, self.triggered):
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

    def observe(self, entry):
        if self.enabled and entry.role == 'assistant' and entry.final:
            item=self.current() if self.stage=='collecting' else None
            if item:
                scale,index,_=item
                if (re.search(r'两周|十四天',entry.text) and any(cue in entry.text for cue in TOPIC_CUES[scale][index-1])
                        and re.search(r'[？?]|吗|呢|如何|怎么样|有没有|多少|频繁',entry.text)):
                    self.question_key=f'{scale}:{index}'
            if (self.pending and item and OPTIONS[self.pending[0]] in entry.text
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
        before = (self.stage, len(self.answers), self.pending)
        if safety(text)['safety_signal'] == 'explicit_danger_expression':
            self.stage, self.pending = 'urgent', None
        elif self.stage not in ('declined', 'urgent', 'complete'):
            if re.search(r'不想(做|答|继续|聊)|不愿意|别再问|停止问|先不做', text):
                self.action('decline')
            elif self.stage == 'paused':
                if re.search(r'继续聊|接着聊', text):
                    self.stage = 'waiting_context'
            elif self.stage == 'collecting':
                if re.search(r'先停|休息一下|不舒服|有点难受|崩溃|很痛苦|撑不住|喘不过气|恐慌', text):
                    self.action('pause')
                elif (self.pending and self.confirmation_asked
                        and re.fullmatch(r'(是的|对|没错|确认|嗯，对)[。！! ]*', text)):
                    scale, index, _ = self.current()
                    value, source = self.pending
                    self.answers[f'{scale}:{index}'] = dict(value=value, evidence_ids=[source, entry.message_id],
                                                          confirmation_context_id=self.confirmation_context_id)
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
                    matches = [i for i, option in enumerate(OPTIONS) if option == canonical]
                    if len(matches) == 1:
                        self.pending = (matches[0], entry.message_id)
        if before != (self.stage, len(self.answers), self.pending):
            self.version += 1

    def view(self):
        scales = []
        for scale in self.target_scales:
            values = [self.answers.get(f'{scale}:{i+1}') for i in range(len(ITEMS[scale]))]
            complete = all(v is not None for v in values)
            scales.append(dict(scale=scale, answered=sum(v is not None for v in values), required=len(values),
                               total=sum(v['value'] for v in values) if complete else None,
                               status='complete_unverified' if complete else 'incomplete', items=values))
        return dict(type='screening.status', stage=self.stage, version=self.version, scales=scales,
                    triggered=self.triggered, source='conversation_assisted', verification_status='unverified',
                    protocol='conditional-collection-v2', recall_window='past_two_weeks',
                    authorization_source='purchase_notice_deployment_declaration',
                    purchase_notice_version=self.notice_version, signal_evidence=self.signals,
                    detector_version=self.detector, detector_status=self.detector_status,
                    decisions=self.decisions, formal_assessment=False)

    def instructions(self):
        base = ('你是温和的中文陪伴助手，先倾听回应感受。不诊断，不宣称情绪已稳定，不宣布分数。'
                '产品在购买须知中说明信息整理和后台辅助评分用途；无需再次征求量表同意、要求用户准备好、报量表名或念题号。'
                '不得否认或虚假解释信息整理用途，用户询问时如实说明。用户随时可以停止。'
                '每次至多一个具体问题，允许自然闲聊，不连续追问，不把话题转成答题。')
        if not self.enabled:
            return base+'当前会话未启用后台信息采集，只自然陪伴；用户问及功能时如实说明当前未启用，不说系统永远不会主动了解。'
        base += ('用户问“什么情况下会主动了解、是否会发起问卷”时，说明：会结合前面的具体交流，'
                 '在需要进一步了解且适合继续聊时自然问问近况，不需要用户主动要求或说特定口令，也不会据此诊断。'
                 '不要回答“我不会主动发起”“只有你主动提出才会涉及”；不把关于功能的假设问题当成用户症状。')
        if self.stage in ('companionship', 'waiting_context', 'paused', 'declined'):
            return base + '当前只自然陪伴，不进行量表相关信息采集，不询问固定条目，不催促。'
        if self.stage == 'urgent':
            return base + '立即停止信息采集，优先关怀与安全支持，鼓励及时获得身边可信任的人及专业支持，不保证安全。'
        if self.stage == 'complete':
            return base + '信息整理已结束，继续自然陪伴，不向用户宣布完成问卷、等级或诊断。'
        _, _, topic = self.current()
        if self.pending:
            return base + (f'自然复述并确认：最近两周，“{topic}”这个困扰出现的频率是“{OPTIONS[self.pending[0]]}”，我这样理解对吗？'
                           '必须保留困扰本身的含义，不得改成恢复正常、有兴趣或能放松的频率；不换话题、不要求报具体天数。')
        return base + (f'后台已根据对话线索安排进一步了解。下一次回应先接住用户经历，再自然衔接一个关于最近两周“{topic}”的简短问题，不要只说“你继续说”。'
                       '先开放交流，只有频率不明确时才温和澄清：完全没有、有几天、超过一半的天数、几乎每天。'
                       '不引导选择，不猜测答案。确认后先回应用户经历，允许自由闲聊，不急于下一话题。')


def has_collected_items(payload):
    return bool(payload.get('triggered', True) and any(s.get('answered', 0) > 0 for s in payload.get('scales', [])))


def save_result(uid, sid, controller):
    from ..database import SessionLocal
    # Ordinary conversation must not create empty PHQ/GAD records.
    if not controller.triggered:
        return False
    with SessionLocal() as db:
        db.merge(ScreeningResult(session_id=sid, owner=uid, payload=controller.view()))
        db.commit()
    return True
