"""Fictional WAVs -> real bridge/cloud -> actual records and optional report section.

The dedicated --runtime must have been prepared with demo_care --empty.
Does not open a microphone or speaker; credentials never enter receipts.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time
import wave
import httpx
from websockets.asyncio.client import connect


async def check(args,name):
    cfg=json.loads((args.runtime/'access.json').read_text('utf-8'))
    assert cfg['seed_sample_data'] is False, 'Use an isolated empty demo runtime'
    base=f'http://127.0.0.1:{cfg["backend_port"]}'
    with httpx.Client(trust_env=False,timeout=30) as client:
        auth=client.post(base+'/api/auth/login',json={k:cfg['users'][0][k] for k in ('username','password')})
        auth.raise_for_status();token=auth.json()['access_token'];headers={'Authorization':'Bearer '+token}
        counts={};finals=[];states=[];acks=[];saved=None;sent=0;last_audio_done=False;checked=False;feeding=None;finishing=False
        started=time.monotonic()
        async with connect(base.replace('http:','ws:')+'/api/robot-voice/live',proxy=None,max_size=2**21) as ws:
            # No guided_screening field, no questionnaire consent/ready controls.
            await ws.send(json.dumps(dict(type='authenticate',token=token,device_id='conditional_wav_probe')))
            async def feed(index):
                index=min(index,5)  # Extra natural confirmations reuse "是的".
                with wave.open(str(args.audio_dir/f'{name}_{index}.wav'),'rb') as source:
                    assert (source.getnchannels(),source.getsampwidth(),source.getframerate())==(1,2,16000)
                    pcm=source.readframes(source.getnframes())
                await ws.send(json.dumps(dict(type='unmute')))
                for offset in range(0,len(pcm),640):
                    await ws.send(pcm[offset:offset+640].ljust(640,b'\0'));await asyncio.sleep(.02)
                await ws.send(json.dumps(dict(type='commit')));await ws.send(json.dumps(dict(type='mute')))
            async with asyncio.timeout(240):
                async for raw in ws:
                    event=json.loads(raw);kind=event['type'];counts[kind]=counts.get(kind,0)+1
                    if kind=='error':raise RuntimeError(event['code'])
                    if kind=='transcript.final':
                        finals.append(event);print(name,event['role'],event['text'],flush=True)
                    elif kind=='screening.status':states.append(event)
                    elif kind=='screening.policy_applied':acks.append(event['version'])
                    elif kind=='screening.detector_checked':
                        assert event['status']=='checked','real_detector_failed'
                        checked=True
                    elif kind=='audio.done':last_audio_done=True
                    elif kind=='records.saved':saved=event;break
                    if finishing:continue
                    if last_audio_done and sent<3:
                        if feeding:await feeding
                        feeding=asyncio.create_task(feed(sent));sent+=1;last_audio_done=False
                    elif last_audio_done and sent>=3 and checked:
                        if name=='ordinary':
                            assert not any(s['triggered'] for s in states),'ordinary_case_triggered'
                            finishing=True;await ws.send(json.dumps(dict(type='finish')))
                        elif states and states[-1]['stage']=='collecting' and states[-1]['version'] in acks:
                            if sent<6 or (states[-1]['scales'][0]['answered']==0 and sent<9):
                                if feeding:await feeding
                                feeding=asyncio.create_task(feed(sent));sent+=1;last_audio_done=False
                            else:
                                assert states[-1]['scales'][0]['answered']>=1,'first_item_not_confirmed'
                                finishing=True;await ws.send(json.dumps(dict(type='finish')))
        if feeding:await feeding
        assert saved,'records_not_saved'
        sid=saved['recording_session_id']
        stored=client.get(base+f'/api/robot-records/sessions/{sid}/messages',headers=headers);stored.raise_for_status()
        preview=client.post(base+'/api/robot-insights/reports/preview',headers=headers,json={'scope':{'session_ids':[sid]}});preview.raise_for_status()
        sections=preview.json()['conversation_assessments']
        result=client.get(base+f'/api/robot-voice/screening-results/{sid}',headers=headers).json()['result']
        if name=='ordinary':assert sections==[] and result is None
        else:
            assert len(sections)==1 and [s['scale'] for s in result['scales']]==['PHQ-9']
            assert result['scales'][0]['answered']>=1 and result['scales'][0]['total'] is None
        new_replies=[e['text'] for e in finals if e['role']=='assistant'][4:]
        assert not any(any(word in reply for word in ('问卷','量表','PHQ','GAD','准备好','同意评估')) for reply in new_replies)
        row=dict(case=name,passed=True,real_cloud=True,all_input_fictional=True,elapsed_ms=round((time.monotonic()-started)*1000),
                 no_questionnaire_consent_frames=True,events=counts,finals=finals,states=states,policy_acks=acks,
                 recording_session_id=sid,stored_message_count=len(stored.json()['items']),report_assessment_sections=sections)
        args.output.mkdir(parents=True,exist_ok=True)
        (args.output/f'voice_{name}.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
        print('PASSED',name,sid,flush=True)
        return row


async def main(args):
    for name in args.cases:await check(args,name)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--audio-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cases',nargs='+',choices=['ordinary','depressive_concern'],default=['ordinary','depressive_concern'])
    asyncio.run(main(parser.parse_args()))
