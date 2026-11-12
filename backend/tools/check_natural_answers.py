"""Fictional natural-answer cases using the actual configured Doubao service."""
import argparse,asyncio,json,os,sys
from pathlib import Path
BACKEND=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BACKEND))
from dotenv import load_dotenv
load_dotenv(BACKEND/'.env');os.environ['DATABASE_URL']='sqlite://'
os.environ.setdefault('SECRET_KEY','fictional-natural-answer-check-only-32-characters')
from app.voice.answer_extractor import extract
from app.voice.concern_detector import snapshot
from app.voice.transcripts import Utterance

async def main(args):
    cases=[('natural_days','最近两周，原来喜欢的事也提不起兴趣吗？','这两周里大概有三四天，其他时候还好。',True,1),
        ('missing_frequency','最近两周，原来喜欢的事也提不起兴趣吗？','是有点提不起兴趣，不过具体频率我说不准。',True,-1),
        ('generic_small_talk','最近有没有什么让你轻松的小事呀？','没有。',False,-1)]
    rows=[]
    for name,q,a,relevant,value in cases:
        turns=[Utterance(name+'q','assistant','t',text=q,final=True),Utterance(name+'a','user','t',text=a,final=True)]
        try:
            c=await extract(snapshot(turns),('PHQ-9',1,'做事缺少兴趣或乐趣'))
            row=dict(case=name,passed=c['relevant']==relevant and (not relevant or c['value']==value),relevant=c['relevant'],value=c['value'])
        except Exception as exc:row=dict(case=name,passed=False,error_type=type(exc).__name__)
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    result=dict(real_cloud=True,all_inputs_fictional=True,passed=all(r['passed'] for r in rows),cases=rows)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result['passed'] else 2

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    raise SystemExit(asyncio.run(main(p.parse_args())))
