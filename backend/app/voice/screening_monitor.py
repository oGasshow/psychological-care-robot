"""One coalescing background inference worker; never blocks audio forwarding."""
import asyncio
from . import concern_detector


class ScreeningMonitor:
    def __init__(self, controller, update_policy, *, provider='doubao_realtime', emit=None):
        self.controller, self.update_policy = controller, update_policy
        self.provider, self.emit = provider, emit
        self.turns, self.seen = [], set()
        self.user_count, self.scheduled_count = 0, 0
        self.queue = asyncio.Queue(maxsize=1)
        self.latest_user_id = None
        self.in_flight = False
        self.checked_count = 0
        self.last_error_code = None

    def observe(self, entry):
        if not entry.final or not entry.text.strip() or entry.message_id in self.seen:
            return
        self.seen.add(entry.message_id)
        self.turns = (self.turns + [entry])[-24:]
        if entry.role == 'user':
            self.user_count += 1
            self.latest_user_id = entry.message_id
            self.schedule()

    def schedule(self, *, force=False):
        if (not self.controller.enabled or self.provider != 'doubao_realtime'
                or self.controller.stage not in ('companionship', 'waiting_context')
                or self.user_count < 3 or self.user_count == self.scheduled_count
                or (not force and self.scheduled_count and self.user_count-self.scheduled_count < 2)):
            return
        data = concern_detector.snapshot(self.turns)
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait((self.user_count, data))
        self.scheduled_count = self.user_count

    async def run(self):
        while True:
            count, data = await self.queue.get()
            self.in_flight = True
            try:
                result = await concern_detector.assess(data)
                self.checked_count = count
                self.last_error_code = None
                fresh = self.latest_user_id == data['latest_user_id']
                changed = self.controller.apply_decision(result, fresh=fresh)
                if changed:
                    await self.update_policy()
                if self.emit:
                    await self.emit(dict(type='screening.detector_checked', status='checked',
                                         source_snapshot_hash=data['source_snapshot_hash']))
            except asyncio.CancelledError:
                raise
            except Exception:
                # No keyword fallback, forced questionnaire, guessed answers,
                # raw private text or provider exception in the browser.
                self.controller.detector_status = 'unavailable'
                self.checked_count = count
                self.last_error_code = 'context_detector_unavailable'
                if self.emit:
                    await self.emit(dict(type='screening.detector_checked', status='unavailable'))
            finally:
                self.in_flight = False
            if self.user_count > count and self.queue.empty():
                self.schedule(force=True)
