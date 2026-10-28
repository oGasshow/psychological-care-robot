"""Fault-injection subprocess used ONLY by the L1 tests, never server startup."""
import json
import os
from pathlib import Path
import threading
from robot_client import Outbox, Transport, Worker

def main():
    kind = os.environ['CLIENT_FAULT']
    ready = Path(os.environ['CLIENT_READY'])
    class FaultTransport(Transport):
        def request(self, method, path, **kwargs):
            matches = method == 'POST' and (
                (kind in ('before_session', 'after_session') and path.endswith('/sessions')) or
                (kind == 'after_message' and path.endswith('/messages')) or
                (kind == 'after_close' and path.endswith('/close')))
            if matches and kind == 'before_session':
                ready.write_text('{"before_http":true}', encoding='utf-8')
                threading.Event().wait()
            response = super().request(method, path, **kwargs)
            if matches:
                body = response.json()
                ready.write_text(json.dumps({'after_commit':True,'status':response.status_code,
                                            'recording_session_id':body.get('recording_session_id'),
                                            'record_id':body.get('record_id')}), encoding='utf-8')
                threading.Event().wait()
            return response
    transport = FaultTransport(os.environ['ROBOT_BASE_URL'], os.environ['ROBOT_TOKEN'])
    box = Outbox(os.environ['ROBOT_OUTBOX_PATH'], transport.base_url, int(os.environ['ROBOT_OWNER']), transport=transport)
    external = 'virtual_process'
    if not box.status():
        box.create_session({'source':'doubao_realtime','device_id':'virtual_process_device','external_session_id':external,
                            'started_at':'2026-10-28T00:00:00Z','is_test':True})
        box.enqueue(external,{'external_message_id':'virtual_process_message_1','role':'user','content':'虚构进程测试',
                              'occurred_at':'2026-10-28T00:00:01Z','text_status':'completed','playback_status':'not_applicable'})
        if kind != 'before_session':
            box.close_session(external,'2026-10-28T00:01:00Z')
    if kind == 'enqueue_second':
        sequence = box.enqueue(external,{'external_message_id':'virtual_process_message_2','role':'user','content':'虚构重连测试',
                                         'occurred_at':'2026-10-28T00:00:02Z','text_status':'completed','playback_status':'not_applicable'})
        assert sequence == 2
        ready.write_text(json.dumps({'next_sequence_used':sequence}),encoding='utf-8')
    else:
        worker=Worker(box,transport)
        for _ in range(10):
            if not worker.step():
                break
    transport.close()

if __name__ == '__main__':
    main()
