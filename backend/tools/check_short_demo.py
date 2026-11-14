"""Fictional speech-provider events -> real WebSocket -> three confirmed scores."""
import base64
import json
import os
from pathlib import Path
import subprocess
import threading
from websockets.sync.server import serve
import demo_care
import collection_demo

ROOT=Path(__file__).resolve().parents[2]
TOPICS=['持续低落或提不起兴趣','精力与行动受到影响','自我评价或希望感受影响']
OPTIONS=['有时','经常','较少']


def provider(ws):
    tools=[];first=False;sent=set()
    def emit(value):ws.send(json.dumps(value,ensure_ascii=False))
    def user(key,text):
        emit(dict(type='conversation.item.input_audio_transcription.started',item_id=key))
        emit(dict(type='conversation.item.input_audio_transcription.completed',item_id=key,text=text))
    def assistant(key,text):
        emit(dict(type='response.output_text.done',question_id=key,response_id=key,text=text))
        emit(dict(type='response.output_audio.delta',question_id=key,response_id=key,delta=base64.b64encode(bytes(640)).decode()))
        emit(dict(type='response.output_audio.done',question_id=key,response_id=key))
    try:
        for raw in ws:
            event=json.loads(raw);kind=event['type']
            if kind=='session.create':
                tools=event.get('session',{}).get('tools',[])
                emit(dict(type='session.created'))
            elif kind=='input_audio_buffer.commit' and tools:
                name=tools[0]['name']
                value=(dict(decision='no_signal',target_scales=[],evidence=[],transition_ready=False,
                    latest_user_quote='',reason='虚构协议测试，不作自动判断。')
                    if name=='decide_conversation_followup' else dict(relevant=False,value=-1))
                emit(dict(type='response.function_call_arguments.done',items=[dict(name=name,arguments=json.dumps(value,ensure_ascii=False))]))
            elif kind=='session.update':
                emit(dict(type='session.updated'))
                if os.getenv('SHORT_DEMO_SCENARIO')=='late':continue
                instructions=event.get('session',{}).get('instructions',event.get('instructions',''))
                for i,topic in enumerate(TOPICS):
                    if topic not in instructions:continue
                    if '自然复述并确认' in instructions and ('confirm',i) not in sent:
                        sent.add(('confirm',i));assistant('confirm'+str(i),f'最近两周，{topic}大约是{OPTIONS[i]}，我这样理解对吗？')
                        user('yes'+str(i),'对。');break
                    if '后台已根据对话线索安排进一步了解' in instructions and ('question',i) not in sent:
                        sent.add(('question',i));assistant('question'+str(i),f'最近两周，{topic}的情况怎么样？')
                        user('frequency'+str(i),OPTIONS[i]+'。');break
            elif kind=='input_audio_unmute.commit' and not tools and not first:
                first=True;user('initial_demo','最近心情有点低落，做事情没什么兴致。')
                assistant('initial_reply','我在听，可以慢慢说。')
                if os.getenv('SHORT_DEMO_SCENARIO')=='late':
                    for i in (0,2,1):
                        assistant('late_question'+str(i),f'最近两周，{TOPICS[i]}的情况怎么样？')
                        user('late_frequency'+str(i),OPTIONS[i]+'。')
            elif kind=='speech_text_buffer.commit':
                emit(dict(type='response.output_audio.done',response_id='hello'))
            elif kind=='session.close':emit(dict(type='session.closed'));break
    except Exception:
        pass  # Provider connections may be canceled once their test completes.


def main():
    local=serve(provider,'127.0.0.1',0)
    thread=threading.Thread(target=local.serve_forever,daemon=True);thread.start()
    root,cfg=collection_demo.load()
    original=demo_care.environment
    def environment(runtime,config):
        return dict(original(runtime,config),APP_ENV='test',DOUBAO_VOICE_API_KEY='fictional-protocol-test-key',
            DOUBAO_VOICE_WS_URL=f'ws://127.0.0.1:{local.socket.getsockname()[1]}',ROBOT_CARE_ANALYSIS_ENGINE='rules')
    demo_care.environment=environment
    try:
        if (root/'pids.json').exists():
            assert demo_care.stop(root,cfg)['stopped_recorded_demo_processes']
        cfg.update(backend_port=demo_care.port(),frontend_port=demo_care.port())
        demo_care.write_json(root/'access.json',cfg)
        demo_care.start(root,cfg)
        output=ROOT/'runtime/short-demo-ui-evidence'
        env=dict(os.environ,CARE_BASE_URL=f'http://127.0.0.1:{cfg["frontend_port"]}',EVIDENCE_DIR=str(output),
            DEMO_USER=cfg['users'][0]['username'],DEMO_PASSWORD=cfg['users'][0]['password'])
        result=subprocess.run(['node','tools/check-durable-demo-ui.mjs' if os.getenv('SHORT_DEMO_SCENARIO')=='late' else 'tools/check-short-demo-ui.mjs'],cwd=ROOT/'frontend',env=env,timeout=120)
        raise SystemExit(result.returncode)
    finally:
        if (root/'pids.json').exists():demo_care.stop(root,cfg)
        local.shutdown();thread.join(timeout=3)


if __name__=='__main__':main()
