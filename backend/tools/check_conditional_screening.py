"""Real detector check with fictional conversations only; no DB/microphone/user data."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

BACKEND=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BACKEND))
from dotenv import load_dotenv
load_dotenv(BACKEND/'.env')
from app.voice import concern_detector
from app.voice.transcripts import Utterance

CASES=[
    ('ordinary',[],['今天和老朋友散步，挺开心的。','这两周吃饭睡觉都挺规律，也有兴趣做饭。','明天打算和家人买点菜，没什么持续烦心事。']),
    ('temporary_sadness',[],['今天下雨没去成公园，有点失落。','就今天这件事不太顺心，其他时间还挺好的。','刚才和老朋友聊过，现在开心多了，明天再去公园。']),
    ('third_party',[],['邻居说他这两周一直低落、什么都没兴趣。','我是转述他的情况，我自己没有这些困扰，吃饭睡觉都正常。','我这两周工作和生活都顺利，也很享受和家人相处。']),
    ('depressive_concern',['PHQ-9'],['这两周一直心情低落，原来喜欢的做饭和散步现在也没兴趣了。','持续半个月都没力气，睡不好，已经影响到我做饭和日常生活。','谢谢你听我说，慢慢说出来后没那么压着了，我现在还能继续聊聊日常。']),
    ('anxiety_concern',['GAD-7'],['这两周每天都忍不住担心各种事情，想停也停不下来。','我持续担心家里的小事，已经影响工作和睡眠，停下事情也还是担忧。','慢慢喝了点水，现在没那么慌了，还想继续聊聊家里的事。']),
]


async def main(args):
    results=[]
    for name,expected,texts in CASES:
        turns=[]
        for index,text in enumerate(texts):
            if index:
                turns.append(Utterance(f'{name}-a{index}','assistant',f't{index}',text='我在听，可以慢慢说说你的日常。',final=True))
            turns.append(Utterance(f'{name}-u{index}','user',f't{index}',text=text,final=True))
        started=time.monotonic()
        try:
            result=await concern_detector.assess(concern_detector.snapshot(turns))
            passed=(result['decision']=='follow_up' and set(result['target_scales'])==set(expected)) if expected else result['decision']!='follow_up'
            row=dict(case=name,passed=passed,elapsed_ms=round((time.monotonic()-started)*1000),result=result)
        except Exception as exc:
            row=dict(case=name,passed=False,error_type=type(exc).__name__)
        results.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    receipt=dict(all_input_fictional=True,real_cloud=True,clinical_validation=False,passed=all(r['passed'] for r in results),cases=results)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if receipt['passed'] else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
