"""Try the configured report model using fictional text; never touches the DB."""
import argparse
import json
from pathlib import Path
import sys

BACKEND=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BACKEND))
from dotenv import load_dotenv
load_dotenv(BACKEND/'.env')
from app.care.report_narrative import generate

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--show-text',action='store_true',help='Also display the generated summary of fictional text')
    args=parser.parse_args()
    coverage=dict(id='coverage:test',kind='coverage',is_test=True,user_text_count=2,classified_count=2,
                  unclassified_count=0,active_days=1,window_days=7)
    facts=dict(report_facts_version='report-facts-v1',source_snapshot_hash='0'*64,
        scope={'session_ids':[1]},comparison_scope=None,data_nature='test_only',eligible_user_text_count=2,
        coverage=[coverage],groups=[],topics=[],facts=[coverage,dict(id='limitations',kind='limitations',comparison_reason='selected_sessions')],
        evidence=[dict(id='record:1@0',record_id=1,input_revision=0,is_test=True,occurred_at='2026-11-09T00:00:00Z',text='虚构示例：今天和朋友散步，我很开心。',truncated=False),
                  dict(id='record:2@0',record_id=2,input_revision=0,is_test=True,occurred_at='2026-11-09T01:00:00Z',text='虚构示例：晚上一个人，觉得有点孤独。',truncated=False)],
        evidence_selection=dict(sampled=False,evidence_count=2,eligible_candidate_count=2))
    result=generate(facts)
    receipt={k:result.get(k) for k in ('mode','status','reason_code','provider','model','prompt_version','elapsed_ms')}
    receipt['all_input_fictional']=True
    if args.show_text:receipt['overview']=result['content']['overview']['text']
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    return 0 if result['mode']=='model' else 2

if __name__=='__main__':raise SystemExit(main())
