"""Windows/Pi adapter for voice-bridge-v1. Cloud credentials remain on the server.

Install device/requirements.txt. Microphone/speaker mode additionally needs PyAudio.
Use --wav fixture.wav --no-playback to test without opening physical devices.
"""
import argparse
import asyncio
import base64
from contextlib import suppress
import getpass
import json
import os
from pathlib import Path
import sys
import threading
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request
import wave

from websockets.asyncio.client import connect


def login(base, username):
    password=getpass.getpass('系统登录密码（不会显示）: ')
    request=Request(base+'/api/auth/login',data=json.dumps(dict(username=username,password=password)).encode(),
                    headers={'Content-Type':'application/json'},method='POST')
    with build_opener(ProxyHandler({})).open(request,timeout=15) as response:
        return json.load(response)['access_token']


class AudioDevice:
    """Replace this adapter to use ALSA/I2S or a robot's own audio driver."""
    def __init__(self, capture, playback):
        import pyaudio
        self.audio=pyaudio.PyAudio()
        self.input=self.audio.open(format=pyaudio.paInt16,channels=1,rate=16000,input=True,frames_per_buffer=320) if capture else None
        self.output=self.audio.open(format=pyaudio.paInt16,channels=1,rate=24000,output=True,frames_per_buffer=480) if playback else None

    def read(self):return self.input.read(320,exception_on_overflow=False)
    def write(self,pcm):self.output.write(pcm)
    def close(self):
        for stream in (self.input,self.output):
            if stream:
                with suppress(Exception):stream.stop_stream();stream.close()
        self.audio.terminate()


async def run(args):
    parsed=urlsplit(args.server)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('server 必须是系统 HTTP(S) 地址，不能包含凭证、查询或片段')
    if parsed.scheme!='https' and parsed.hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('远程终端请使用 HTTPS/WSS，或通过 SSH 转发到本机端口')
    base=args.server.rstrip('/')
    token=os.getenv('ROBOT_CARE_ACCESS_TOKEN')
    if not token:
        if not args.username:raise ValueError('请传 --username，或通过 ROBOT_CARE_ACCESS_TOKEN 提供系统 JWT')
        token=await asyncio.to_thread(login,base,args.username)
    pcm=None
    if args.wav:
        with wave.open(str(args.wav),'rb') as wav:
            if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,16000):
                raise ValueError('WAV 必须为 PCM16 小端、单声道、16000 Hz')
            pcm=wav.readframes(wav.getnframes())
    device=AudioDevice(capture=pcm is None,playback=not args.no_playback) if pcm is None or not args.no_playback else None
    finished=asyncio.Event();ready=asyncio.Event();greeted=asyncio.Event();said=False;paused=False
    queue=asyncio.Queue(maxsize=1500);blocked=set();current_id=None;tasks=[]
    uri=base.replace('https:','wss:',1).replace('http:','ws:',1)+'/api/robot-voice/live'
    try:
        async with connect(uri,proxy=None,open_timeout=15,max_size=2**21) as ws:
            async def send(value):await ws.send(json.dumps(value,ensure_ascii=False))
            await send(dict(type='authenticate',token=token,device_id=args.device_id))
            def clear():
                nonlocal current_id
                if current_id:blocked.add(current_id)
                while not queue.empty():
                    item=queue.get_nowait();blocked.add(item[0])
                current_id=None
            async def capture():
                await ready.wait()
                if pcm is not None:
                    await greeted.wait()  # Do not let the fixture interrupt the opening.
                    for offset in range(0,len(pcm),640):
                        await ws.send(pcm[offset:offset+640].ljust(640,b'\0'));await asyncio.sleep(.02)
                    await send(dict(type='commit'));await send(dict(type='mute'));return
                while not finished.is_set():
                    frame=await asyncio.to_thread(device.read)
                    if not paused:await ws.send(frame)
            async def playback():
                nonlocal current_id
                while True:
                    ident,chunk=await queue.get()
                    if ident in blocked:continue
                    current_id=ident
                    if not args.no_playback:await asyncio.to_thread(device.write,chunk)
            async def commands():
                nonlocal paused
                # Daemon stdin reader avoids a hanging executor on Pi service exit.
                commands=asyncio.Queue();loop=asyncio.get_running_loop()
                def read_stdin():
                    for line in sys.stdin:
                        try:loop.call_soon_threadsafe(commands.put_nowait,line.strip())
                        except RuntimeError:return
                threading.Thread(target=read_stdin,daemon=True).start()
                while True:
                    command=await commands.get()
                    if command in ('q','quit','退出'):
                        finished.set();clear();await send(dict(type='finish'));return
                    if command in ('i','打断'):clear();await send(dict(type='interrupt'))
                    if command in ('m','暂停'):paused=True;await send(dict(type='mute'))
                    if command in ('u','继续'):paused=False;await send(dict(type='unmute'))
            tasks=[asyncio.create_task(capture()),asyncio.create_task(playback()),asyncio.create_task(commands())]
            def task_done(task):
                if not task.cancelled() and task.exception():
                    print('音频设备或终端处理失败，正在结束连接。',file=sys.stderr)
                    asyncio.create_task(ws.close())
            for task in tasks:task.add_done_callback(task_done)
            print('连接中；q 结束并保存，i 打断，m 暂停，u 继续。不要关闭窗口代替保存。',flush=True)
            async for raw in ws:
                event=json.loads(raw);kind=event['type']
                if kind=='session.ready':ready.set();await send(dict(type='unmute'));print('已连接。',flush=True)
                elif kind=='transcript.final':
                    print(('您：' if event['role']=='user' else '助手：')+event['text'],flush=True)
                    if event['role']=='user':said=True
                elif kind=='audio.delta':
                    ident=event['message_id'];data=base64.b64decode(event['audio'],validate=True)
                    if len(data)%2:raise ValueError('服务端返回了无效 PCM')
                    if ident in blocked:continue
                    for start in range(0,len(data),960):
                        try:queue.put_nowait((ident,data[start:start+960]))
                        except asyncio.QueueFull:
                            clear();await send(dict(type='interrupt'));print('播放积压，已打断。',flush=True);break
                elif kind=='audio.done':
                    greeted.set()
                    if args.wav and said:
                        finished.set();await send(dict(type='finish'))
                elif kind=='playback.clear':clear()
                elif kind in ('records.saved','records.pending','records.error'):
                    print(json.dumps(event,ensure_ascii=False),flush=True)
                elif kind=='error':print('语音错误：'+str(event.get('code')),flush=True)
    finally:
        finished.set()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        if device:device.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server',default='http://127.0.0.1:8000')
    parser.add_argument('--username')
    parser.add_argument('--device-id',default='raspberry_pi')
    parser.add_argument('--wav',type=Path)
    parser.add_argument('--no-playback',action='store_true')
    args=parser.parse_args()
    try:asyncio.run(run(args))
    except KeyboardInterrupt:print('终端已退出；已有最终文字保留在服务端队列，可重新连接重试保存。')
    except Exception:
        # Socket exceptions may include headers. Never echo them with a JWT.
        print('连接或音频设备失败。请检查地址、登录、音频格式及设备依赖。',file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
