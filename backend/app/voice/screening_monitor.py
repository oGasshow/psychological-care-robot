"""One coalescing background inference worker; never blocks audio forwarding."""
import asyncio
from . import concern_detector


class ScreeningMonitor:
    def __init__(self, controller, update_policy, *, provider='doubao_realtime', emit=None,history=None):
        self.controller, self.update_policy = controller, update_policy
        self.provider, self.emit = provider, emit
        self.turns, self.seen = [], set()
        self.user_count, self.scheduled_count = 0, 0
        self.revision, self.scheduled_revision = 0, -1
        self.queue = asyncio.Queue(maxsize=1)
        self.latest_user_id = None
        self.in_flight = False
        self.checked_count = 0
        self.last_error_code = None
        self.history=history or []
        self.completed_hash=None
        self.completed_event=asyncio.Event()

    async def wait_for_snapshot(self, snapshot_hash, timeout):
        """Wait briefly for the exact transcript snapshot, without blocking audio."""
        loop=asyncio.get_running_loop()
        deadline=loop.time()+timeout
        while True:
            if self.completed_hash==snapshot_hash:
                return True
            self.completed_event.clear()
            if self.completed_hash==snapshot_hash:
                return True
            remaining=deadline-loop.time()
            if remaining<=0:
                return False
            try:await asyncio.wait_for(self.completed_event.wait(),remaining)
            except TimeoutError:return False

    def snapshot(self):
        data=concern_detector.snapshot(self.turns)
        if self.history:
            import hashlib,json
            old=concern_detector.snapshot(self.history[-14:])['turns']
            data['turns']=old+data['turns'][-16:]
            data['source_snapshot_hash']=hashlib.sha256(json.dumps(data['turns'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        data['historical_danger']=self.controller.history_danger_unresolved
        if self.controller.demo_mode:data['demo_mode']=True
        return data

    def observe(self, entry):
        if not entry.final or not entry.text.strip() or entry.message_id in self.seen:
            return
        self.seen.add(entry.message_id)
        self.turns = (self.turns + [entry])[-24:]
        self.revision += 1
        if entry.role == 'user':
            self.user_count += 1
            self.latest_user_id = entry.message_id
            if any(entry.message_id in answer.get('evidence_ids',[]) for answer in self.controller.answers.values()):
                self.last_error_code=None
                self.checked_count=self.user_count
                return
            self.schedule(force=self.controller.review_status in ('running','pending'))
        elif (self.controller.stage in ('waiting_context','checking_in','reviewing')
              and self.user_count and self.scheduled_revision != self.revision):
            # Readiness depends on the assistant's latest reply too. Recheck
            # once after that reply, without waiting for another user turn.
            self.schedule(force=True)

    def schedule(self, *, force=False):
        if (self.controller.streamlined and self.controller.stage=='collecting'
                and self.controller.question_key is None and self.controller.pending is None):
            return
        post_session=self.controller.review_mode=='post_session'
        if post_session and not self.controller.triggered:
            return
        minimum=1 if self.controller.stage=='collecting' or self.controller.demo_mode else (2 if post_session else 1 if self.history else 3)
        if (not self.controller.enabled or self.provider != 'doubao_realtime'
                or self.controller.stage not in ('companionship', 'waiting_context','checking_in','reviewing','collecting')
                or self.user_count < minimum
                or self.scheduled_revision == self.revision
                or (not force and self.scheduled_count
                    and self.controller.stage not in ('collecting', 'waiting_context', 'checking_in')
                    and self.user_count-self.scheduled_count < 2)):
            return
        data = self.snapshot()
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait((self.user_count, data))
        self.scheduled_count = self.user_count
        self.scheduled_revision = self.revision

    async def run(self):
        while True:
            count, data = await self.queue.get()
            self.in_flight = True
            collecting = self.controller.stage == 'collecting'
            try:
                if collecting:
                    from .answer_extractor import extract
                    item=self.controller.current()
                    candidate=await extract(data,item)
                    # Never carry an answer candidate across a newer transcript
                    # revision. It may refer to the previous question/answer.
                    if self.snapshot()['source_snapshot_hash'] != data['source_snapshot_hash']:
                        self.last_error_code='answer_candidate_superseded'
                        self.checked_count=count
                    else:
                        self.last_error_code = None
                        if self.controller.accept_candidate(candidate,item):
                            await self.update_policy()
                        self.checked_count=count
                else:
                    result = await concern_detector.assess(data)
                    self.checked_count = count
                    self.last_error_code = None
                    fresh = (self.latest_user_id == data['latest_user_id']
                             and self.snapshot()['source_snapshot_hash']==data['source_snapshot_hash']
                             and not (self.controller.history_danger_unresolved and count<2))
                    changed = self.controller.apply_decision(result, fresh=fresh)
                    if fresh and self.controller.reconcile_demo_turns(self.turns):changed=True
                    if changed:
                        await self.update_policy()
                    if self.emit:
                        await self.emit(self.controller.public_status())
                        await self.emit(dict(type='screening.detector_checked', status='checked',
                                             source_snapshot_hash=data['source_snapshot_hash']))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # No keyword fallback, forced questionnaire, guessed answers,
                # raw private text or provider exception in the browser.
                self.checked_count = count
                from .upstream import VoiceServiceError
                if collecting:
                    self.last_error_code = ('answer_candidate_timeout' if isinstance(exc, TimeoutError)
                                            else 'answer_candidate_invalid' if isinstance(exc, ValueError)
                                            else 'answer_candidate_unavailable')
                else:
                    self.controller.detector_status = 'unavailable'
                    if isinstance(exc, TimeoutError):
                        self.last_error_code = 'context_detector_timeout'
                    elif isinstance(exc, VoiceServiceError):
                        self.last_error_code = {
                            'voice_timeout': 'context_detector_timeout',
                            'voice_authentication_failed': 'context_detector_authentication_failed',
                            'voice_service_unavailable': 'context_detector_transport_unavailable',
                            'voice_connection_closed': 'context_detector_transport_unavailable',
                            'voice_provider_error': 'context_detector_provider_error',
                        }.get(exc.code, 'context_detector_unavailable')
                    elif isinstance(exc, ValueError):
                        self.last_error_code = 'context_detector_invalid_output'
                    else:
                        self.last_error_code = 'context_detector_unavailable'
                    if self.controller.review_status=='running':
                        self.controller.review_status='pending'
                        self.controller.stage='companionship'
                        self.controller.version+=1
                        try:await self.update_policy()
                        except Exception:pass
                if self.emit:
                    await self.emit({**self.controller.public_status(),
                                     'error_code':self.last_error_code})
                    await self.emit(dict(type='screening.detector_checked', status='unavailable'))
            finally:
                self.in_flight = False
                self.completed_hash=data['source_snapshot_hash']
                self.completed_event.set()
            if self.revision > self.scheduled_revision and self.queue.empty():
                self.schedule(force=True)
