"""Fictional per-utterance model checks, no application database or audio devices."""
import asyncio
import argparse
import json
import os
from pathlib import Path
import sys
BACKEND=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BACKEND))
from dotenv import load_dotenv
load_dotenv(BACKEND/'.env')
os.environ['DATABASE_URL']='sqlite://'
os.environ.setdefault('APP_ENV','test')
os.environ.setdefault('SECRET_KEY','fictional-check-only-key-32-characters')
from app.care.sentiment import analyze

def main(args):
    cases=[('positive','今天见到老同学，心里暖洋洋的，整个人都轻快了。'),
           ('negative','最近做什么都提不起劲，心里很沉，连喜欢的事情也不想碰。'),
           ('neutral','那如果你能够感受到我明显的有心理不健康的趋势的时候，也不会主动向我提问吗？')]
    results=[]
    for expected,text in cases:
        try:
            result=analyze(text)
            row=dict(expected=expected,actual=result['emotion_label'],passed=result['emotion_label']==expected,engine=result['engine_version'])
        except Exception as exc:row=dict(expected=expected,passed=False,error_type=type(exc).__name__)
        print(json.dumps(row,ensure_ascii=False),flush=True);results.append(row)
    receipt=dict(passed=all(r['passed'] for r in results),all_input_fictional=True,real_cloud=True,cases=results)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if receipt['passed'] else 2

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path)
    raise SystemExit(main(p.parse_args()))
