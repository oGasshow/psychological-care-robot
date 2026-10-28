"""Real subprocess harness: pause -> kill -> reopen -> explicit resume."""
import argparse
import json
import os
from pathlib import Path
import threading

from robot_client import Outbox, Transport, Worker

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['pause','check_paused','resume'])
    parser.add_argument('--ready',type=Path)
    args=parser.parse_args()
    calls=[]
    class RecordingTransport(Transport):
        def request(self,method,path,**kwargs):
            calls.append({'method':method,'path':path,'sequence':kwargs.get('json',{}).get('sequence_no')})
            if args.mode=='pause' and method=='POST' and path.endswith('/messages'):
                original=self.token
                try:
                    self.token='fictional-invalid-token'
                    return super().request(method,path,**kwargs)
                finally:
                    self.token=original
            return super().request(method,path,**kwargs)
    transport=RecordingTransport(os.environ['ROBOT_BASE_URL'],os.environ['ROBOT_TOKEN'])
    try:
        box=Outbox(os.environ['ROBOT_OUTBOX_PATH'],transport.base_url,int(os.environ['ROBOT_OWNER']),transport=transport)
        worker=Worker(box,transport)
        if args.mode=='pause':
            box.create_session({'source':'doubao_realtime','device_id':'virtual_process','external_session_id':'pause_session',
                                'started_at':'2026-10-28T00:00:00Z','is_test':True})
            assert worker.step()
            box.enqueue('pause_session',{'external_message_id':'m1','role':'user','content':'虚构暂停测试',
                                        'occurred_at':'2026-10-28T00:00:01Z','text_status':'completed','playback_status':'not_applicable'})
            assert worker.step() and box.partition_status()['auth_blocked'] is True
            report={'partition':box.partition_status(),'status':box.status(),'calls':calls}
            temporary=args.ready.with_suffix('.tmp')
            temporary.write_text(json.dumps(report),encoding='utf-8')
            temporary.replace(args.ready)
            threading.Event().wait()
        elif args.mode=='check_paused':
            calls.clear()
            assert worker.step() is False
            assert box.partition_status()['auth_blocked'] is True
            assert calls==[]
            print(json.dumps({'partition':box.partition_status(),'status':box.status(),'calls':calls}))
        else:
            box.resume()
            calls.clear()
            for _ in range(10):
                if not worker.step():
                    break
            assert all(s['state']=='acked' for s in box.status())
            print(json.dumps({'partition':box.partition_status(),'status':box.status(),'calls':calls}))
    finally:
        transport.close()

if __name__=='__main__':
    main()
