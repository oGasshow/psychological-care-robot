"""Isolated SEGA EATD checkpoint inference. No LLM, microphone or application DB.

Loads the author's separately installed reference code/weights; does not vendor them.
Input NPZ requires text/audio/question/gender/emotion with the author's aligned layout.
"""
import argparse,hashlib,json,os,sys
from pathlib import Path

PIN='0514201653d71728015cf4aea2816c9151b94f71'
CHECKPOINT_SHA='f9b427f3928a56fde91e25265eea5aac8677e5fd4c369f2cb2ebac438cfbc8bd'

def run(args):
    import numpy as np
    import torch
    torch.set_num_threads(2)
    root=args.reference/'EATD/3-model'
    sys.path.insert(0,str(root));sys.path.insert(0,str(root/'scripts'))
    checkpoint=root/'checkpoints/sega_best.pt'
    digest=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    if digest!=CHECKPOINT_SHA:raise ValueError('checkpoint_digest_mismatch')
    ck=torch.load(checkpoint,map_location='cpu',weights_only=True)
    for name,value in ck['env'].items():
        if value!='':os.environ[name]=str(value)
    from models.graph_fusion import GraphFusion
    device='cuda' if torch.cuda.is_available() else 'cpu'
    config=dict(ck['config']);config['cuda']=device=='cuda'
    if device!='cuda':raise RuntimeError('author_reference_requires_cuda')
    names=['text','audio','question','gender','emotion']
    if args.fixture:
        import train as T
        raw=T.load_dataset(T.DATA)
        folds=[list(map(int,line.split())) for line in Path(T.FOLDSPLIT).read_text('utf-8').splitlines()]
        heldout=[i for i in range(len(raw[-1])) if i not in folds[0]]
        data=T.get_eatd_mm_data(heldout,raw,'test')
        values={n:data[n+'_feature'][:1] for n in names}
        source='author_heldout_feature_fixture'
    else:
        with np.load(args.features,allow_pickle=False) as data:
            values={n:data[n] for n in names}
            record_ids=data['record_ids'];question_ids=data['question_record_ids']
            if record_ids.shape!=(3,) or question_ids.shape!=(3,) or record_ids.dtype.kind not in 'iu' or question_ids.dtype.kind not in 'iu':
                raise ValueError('source_record_ids_required')
        source='manual_aligned_features_unverified'
    for name,width in [('text',768),('audio',88),('question',768)]:
        v=values[name]
        if v.ndim!=4 or v.shape[0]!=1 or v.shape[1]!=3 or not 1<=v.shape[2]<=2048 or v.shape[3]!=width:
            raise ValueError('feature_shape_invalid')
    if values['emotion'].shape!=(1,3,7) or values['gender'].shape not in ((1,),(1,1)):
        raise ValueError('auxiliary_feature_shape_invalid')
    if not all(np.issubdtype(v.dtype,np.number) and np.isfinite(v).all() for v in values.values()):
        raise ValueError('nonfinite_features')
    if not np.isin(values['gender'],[0,1]).all():raise ValueError('gender_feature_missing')
    if not np.allclose(values['emotion'].sum(-1),1,atol=1e-3):raise ValueError('emotion_probabilities_invalid')
    model=GraphFusion(config,None,None).to(device)
    # For a submitted sample use a single explicit fold; no mixing of evaluation protocols.
    model.load_state_dict(ck['folds'][1]['state_dict'],strict=True);model.eval()
    with torch.inference_mode():
        output,_,_=model(*[torch.from_numpy(values[n]).float().to(device) for n in names],'test')
        logits=output.detach().cpu().numpy()[0]
    if not np.isfinite(logits).all():raise ValueError('nonfinite_model_output')
    return dict(status='succeeded',engine='SEGA-EATD-author-checkpoint',source_kind=source,
        reference_commit=PIN,checkpoint_sha256=digest,fold=1,device=device,
        model_class=int(np.argmax(logits)),logits=[float(x) for x in logits],
        experimental=True,clinical_validation=False,formal_assessment=False,
        automatic_questionnaire_trigger=False,
        record_ids=[] if args.fixture else record_ids.tolist(),question_record_ids=[] if args.fixture else question_ids.tolist(),
        limitation='作者中文访谈特征域的实验输出，不能等同当前用户诊断或量表分数。')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',type=Path,required=True)
    group=p.add_mutually_exclusive_group(required=True);group.add_argument('--fixture',action='store_true');group.add_argument('--features',type=Path)
    args=p.parse_args()
    try:result=run(args)
    except Exception as exc:
        # No private features, tokens or provider errors in process output.
        result=dict(status='failed',error_type=type(exc).__name__)
    print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['status']=='succeeded' else 2)
