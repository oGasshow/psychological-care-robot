import type {AssessmentsData} from '@/lib/care-types';

export default function AccountCareStatus({value}:{value:AssessmentsData['care_status']}){
  if(!value)return null;
  return <section className="care-card" data-testid="account-care-status">
    <h2>{value.care_label}</h2>
    <p>{value.needs_collection?'有未完成的了解任务，后续对话可在合适时机继续。':
      value.care_status==='high_concern'?'本轮量表已完成，后续继续关怀陪伴。':'继续自然交流，本轮已完成的内容会保留。'}</p>
    {value.scales.map(scale=><p key={scale.scale}>{scale.scale} 采集覆盖率 {Math.round(scale.coverage*100)}%（{scale.answered}/{scale.required} 项）</p>)}
  </section>;
}
