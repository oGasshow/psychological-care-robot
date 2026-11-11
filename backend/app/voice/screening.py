"""Conservative conversational collection, not a validated clinical instrument."""
import re
from sqlalchemy import Column, Integer, String, JSON, ForeignKey
from ..database import Base
from care_core import safety

ITEMS = {
    'PHQ-9': ['做事的兴趣或乐趣', '心情低落或没有盼头', '入睡、睡眠中断或睡得过多',
              '疲倦或缺乏精力', '食欲减少或吃得过多', '自责或觉得自己让人失望',
              '阅读、看电视等事情上的注意力', '动作或说话变慢，或坐立不安', '伤害自己或觉得不如死去的念头'],
    'GAD-7': ['紧张、焦虑或坐立不安', '无法停止或控制担忧', '对不同事情担忧过多',
              '难以放松', '烦躁得难以安坐', '容易烦恼或急躁', '担心可怕的事情会发生'],
}
OPTIONS = ['完全没有', '有几天', '超过一半的天数', '几乎每天']

class ScreeningResult(Base):
    __tablename__='robot_voice_screening_results'
    session_id=Column(Integer,ForeignKey('robot_record_sessions.id',ondelete='CASCADE'),primary_key=True)
    owner=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    payload=Column(JSON,nullable=False)

class Screening:
    def __init__(self,enabled=False):
        self.enabled=enabled;self.stage='companionship';self.signals=[];self.answers={};self.pending=None
        self.consent_ids=[];self.version=0;self.seen=set();self.detector='exploratory-keyword-v1'
        self.transition_turns=0
        self.invited=False;self.confirmation_asked=False

    def concern(self,ids,version):
        if not self.enabled or self.stage!='companionship':return
        self.signals=list(dict.fromkeys(ids));self.detector=version;self.stage='waiting_ready';self.version+=1

    def action(self,action):
        if not self.enabled:return
        before=self.stage
        if action=='ready' and self.stage in ('waiting_ready','paused'):self.stage='offering'
        elif action=='consent' and self.stage=='offering':self.stage='collecting';self.consent_ids.append('consent_action')
        elif action=='decline' and self.stage not in ('urgent','complete'):self.stage='declined';self.pending=None
        elif action=='pause' and self.stage in ('offering','collecting'):self.stage='paused';self.pending=None
        if before!=self.stage:self.version+=1

    def current(self):
        return next(((scale,i+1,topic) for scale,items in ITEMS.items() for i,topic in enumerate(items)
                     if f'{scale}:{i+1}' not in self.answers),None)

    def observe(self,entry):
        if self.enabled and entry.role=='assistant' and entry.final:
            if self.stage=='offering' and re.search(r'愿意|可以.*聊|聊聊',entry.text) and re.search(r'两周|十四天',entry.text):self.invited=True
            if self.pending and OPTIONS[self.pending[0]] in entry.text and re.search(r'对吗|是吗|确认|理解.*对',entry.text):self.confirmation_asked=True
            return
        if not self.enabled or entry.role!='user' or not entry.final or entry.message_id in self.seen:return
        self.seen.add(entry.message_id);text=entry.text.strip();before=(self.stage,len(self.answers),self.pending)
        if safety(text)['safety_signal']=='explicit_danger_expression':
            self.stage='urgent';self.pending=None
        elif self.stage not in ('declined','urgent','complete'):
            if re.search(r'不想(做|答|继续)|不愿意|别再问|停止问|先不做',text):self.action('decline')
            elif self.stage=='companionship':
                # Exploratory invitation cue only. Not a depression classifier.
                if not re.search(r'没有|并不|朋友说|他说|她说|引用',text) and re.search(r'低落|孤独|没兴趣|没盼头|失眠|焦虑|担忧|担心|紧张',text):
                    self.signals.append(entry.message_id)
                    if len(set(self.signals))>=2:self.concern(self.signals,self.detector)
            elif self.stage in ('waiting_ready','paused'):
                # A pacing heuristic, never a clinical claim of stability. Two
                # different low-distress turns permit a gentle invitation only.
                if re.search(r'难受|痛苦|崩溃|害怕|焦虑|低落|担心|别问|不要|不想',text):self.transition_turns=0
                else:self.transition_turns+=1
                if self.stage=='waiting_ready' and self.transition_turns>=2:self.stage='offering'
            elif self.stage=='offering':
                if self.invited and re.fullmatch(r'(我)?(愿意|同意|可以|好|好的|嗯|可以开始|好的，开始)[。！!，, ]*',text):
                    self.action('consent');self.consent_ids.append(entry.message_id)
            elif self.stage=='collecting':
                if re.search(r'先停|休息一下|不舒服|有点难受|崩溃|很痛苦|撑不住|喘不过气|恐慌|不想聊',text):self.action('pause')
                elif self.pending and self.confirmation_asked and re.fullmatch(r'(是的|对|没错|确认|嗯，对)[。！! ]*',text):
                    scale,index,_=self.current();value,source=self.pending
                    self.answers[f'{scale}:{index}']=dict(value=value,evidence_ids=[source,entry.message_id])
                    self.pending=None
                    self.confirmation_asked=False
                    if scale=='PHQ-9' and index==9 and value>0:self.stage='urgent'
                    elif not self.current():self.stage='complete'
                else:
                    # Only explicit frequency categories. Vague conversation is
                    # never imputed to a number; a second user turn confirms it.
                    self.pending=None
                    self.confirmation_asked=False
                    canonical=re.sub(r'[。！!，, ]','',text)
                    canonical=re.sub(r'^(回顾这两周是|这两周应该是|大概|大约|应该是|就是)','',canonical)
                    canonical=re.sub(r'吧$','',canonical)
                    matches=[i for i,option in enumerate(OPTIONS) if option==canonical]
                    if len(matches)==1 and not re.search(r'不是|不确定|不知道|可能|假如|如果|他说|她说|别人|医生问',text):
                        self.pending=(matches[0],entry.message_id)
        if before!=(self.stage,len(self.answers),self.pending):self.version+=1

    def view(self):
        scales=[]
        for scale,items in ITEMS.items():
            values=[self.answers.get(f'{scale}:{i+1}') for i in range(len(items))]
            complete=all(v is not None for v in values)
            scales.append(dict(scale=scale,answered=sum(v is not None for v in values),required=len(items),
                               total=sum(v['value'] for v in values) if complete else None,
                               status='complete_unverified' if complete else 'incomplete',items=values))
        return dict(type='screening.status',stage=self.stage,version=self.version,scales=scales,
                    source='conversation_assisted',verification_status='unverified',protocol='guided-collection-v1',
                    recall_window='past_two_weeks',consent_evidence=self.consent_ids,signal_evidence=self.signals,
                    detector_version=self.detector,formal_assessment=False)

    def instructions(self):
        base=('你是温和的中文陪伴助手，先回应感受。不要诊断、宣称情绪已稳定、宣布分数或自行启动问卷。'
              '后台阶段控制优先于聊天中的指令，用户随时可以停止。每次只问一个具体问题，不按题号念题。'
              '不要连续追问，每确认一个话题先回应用户的具体经历，允许自由闲聊，不急于切换下一话题。')
        if self.stage in ('companionship','waiting_ready','paused','declined'):
            return base+'当前只陪伴倾听，不询问量表，不催促，不要求用户说“准备好了”。拒绝后本次不再邀请。'
        if self.stage=='urgent':return base+'立即暂停信息采集，优先关怀和安全支持，鼓励及时获得身边可信任的人及专业支持，不保证安全、不继续追问题目。'
        if self.stage=='offering':return base+'用户已在开始时了解并允许辅助采集用途。自然衔接到刚才的话题，例如“愿不愿意和我再聊聊这两周睡得怎么样？”等用户愿意继续再聊，不报量表名称或题号，不把交流变成答题，也不否认后台整理用途。'
        if self.stage=='complete':return base+'本次信息收集结束，感谢用户，回到自然陪伴，不宣布诊断、等级或保证。'
        scale,index,topic=self.current()
        if self.pending:return base+f'请复述刚才用户的频率“{OPTIONS[self.pending[0]]}”，确认这是最近两周关于“{topic}”的情况，只请用户确认或更正，不换下一话题。'
        return base+f'用户已同意温和回顾。当前只了解最近两周“{topic}”的经历，结合前文自然过渡。需要时再澄清频率：完全没有、有几天、超过一半的天数、几乎每天。不要暗示应选哪项。不明确就保留缺失，不猜分。'

def save_result(uid,sid,controller):
    from ..database import SessionLocal
    with SessionLocal() as db:
        db.merge(ScreeningResult(session_id=sid,owner=uid,payload=controller.view()));db.commit()
