"""One observation per collection episode, with original answer timestamps."""
from collections import defaultdict
from .scale_catalog import summarize,VERSION


def collection_trends(collections):
    partitions=defaultdict(list)
    for row in collections:
        for scale in row.get('scales',[]):
            partitions[(scale['scale'],bool(row['is_test']),bool(row.get('demo_mode')))].append((row,scale))
    groups=[]
    for (scale,is_test,demo),pairs in sorted(partitions.items()):
        episodes=defaultdict(list)
        for row,value in pairs:
            episodes[row.get('episode_id') or f"session:{row['recording_session_id']}"].append((row,value))
        points=[]
        for episode,entries in episodes.items():
            reading=next(s for s in summarize([r for r,_ in entries],expected=[scale]) if s['scale_id']==scale)
            row,value=max(entries,key=lambda p:(p[1]['answered'],p[0]['source_status']=='current_original_text',p[0]['recording_session_id']))
            observed=value.get('observed_at')
            points.append(dict(id=f'{scale}:{episode}',episode_id=episode,observed_at=observed,
                completed_at=observed if reading['score'] is not None else None,time_source='last_original_user_answer',
                score=reading['score'],answered=reading['answered'],required=reading['item_count'],status=reading['status'],
                recording_session_ids=sorted(set(reading['recording_session_ids'] or [row['recording_session_id']])),
                source_record_ids=reading['source_record_ids'],is_test=is_test))
        points.sort(key=lambda p:(p['observed_at'] or '',p['id']))
        complete=[p for p in points if p['score'] is not None and p['observed_at']]
        d=next(s for s in summarize([r for r,_ in pairs],expected=[scale]) if s['scale_id']==scale)
        groups.append(dict(id=f'scale-trend:{scale}:{int(is_test)}:{int(demo)}',scale_id=scale,name=d['name'],
            kind=d['kind'],version=VERSION,source_kind='conversation_assisted',is_test=is_test,demo_mode=demo,
            max_score=d['max_score'],direction=d['direction'],points=points,completed_count=len(complete),
            numeric_change=complete[-1]['score']-complete[0]['score'] if len(complete)>=2 else None,
            status='available' if len(complete)>=2 else 'insufficient_results'))
    return groups
