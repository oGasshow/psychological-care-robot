"""Replay two fictional feature questions through the real voice bridge.

No microphone/speaker. Requires an isolated --empty demo and 16k mono WAVs
named capability_0.wav and capability_1.wav. Does not force collection.
"""
import argparse
import asyncio
import json
from pathlib import Path
import re
import wave
import httpx
from websockets.asyncio.client import connect


async def main(args):
    cfg=json.loads((args.runtime/'access.json').read_text('utf-8'))
    assert cfg['seed_sample_data'] is False
    base=f'http://127.0.0.1:{cfg["backend_port"]}'
    with httpx.Client(trust_env=False,timeout=15) as client:
        login=client.post(base+'/api/auth/login',json={k:cfg['users'][0][k] for k in ('username','password')})
        login.raise_for_status();headers={'Authorization':'Bearer '+login.json()['access_token']}
        finals=[];sent=0;feeding=None;saved=None;diagnostics=None
        async with connect(base.replace('http:','ws:')+'/api/robot-voice/live',proxy=None,max_size=2**21) as ws:
            await ws.send(json.dumps(dict(type='authenticate',token=login.json()['access_token'],device_id='capability_probe')))
            async def feed(index):
                with wave.open(str(args.audio_dir/f'capability_{index}.wav'),'rb') as wav:
                    assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())==(1,2,16000)
                    pcm=wav.readframes(wav.getnframes())
                await ws.send(json.dumps(dict(type='unmute')))
                for start in range(0,len(pcm),640):
                    await ws.send(pcm[start:start+640].ljust(640,b'\0'));await asyncio.sleep(.02)
                await ws.send(json.dumps(dict(type='commit')));await ws.send(json.dumps(dict(type='mute')))
            async with asyncio.timeout(100):
                async for raw in ws:
                    event=json.loads(raw)
                    if event['type']=='error':raise RuntimeError(event['code'])
                    if event['type']=='transcript.final':
                        finals.append(event);print(event['role'],event['text'],flush=True)
                    if event['type']=='audio.done':
                        if sent<2:
                            if feeding:await feeding
                            feeding=asyncio.create_task(feed(sent));sent+=1
                        else:
                            response=client.get(base+'/api/robot-voice/diagnostics',headers=headers);response.raise_for_status()
                            diagnostics=response.json();await ws.send(json.dumps(dict(type='finish')))
                    if event['type']=='records.saved':saved=event;break
        if feeding:await feeding
        replies=[e['text'] for e in finals if e['role']=='assistant'][1:]
        passed=bool(saved and diagnostics and diagnostics['user_turns']==2 and diagnostics['checked_user_turns']==0
                    and diagnostics['stage']=='companionship' and diagnostics['target_scales']==[])
        assert len(replies)==2
        for reply in replies:
            passed=passed and not bool(re.search(r'只有.{0,15}主动.{0,10}才|也不会主动|永远不会主动|不会主动发起问卷',reply))
        receipt=dict(passed=passed,all_input_fictional=True,real_cloud=True,physical_audio_devices_opened=False,
                     final_texts=finals,diagnostics=diagnostics,saved=saved)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'passed':passed,'user_turns':diagnostics['user_turns'],'checked_user_turns':diagnostics['checked_user_turns']},ensure_ascii=False))
        return 0 if passed else 2


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime',type=Path,required=True);p.add_argument('--audio-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    raise SystemExit(asyncio.run(main(p.parse_args())))
