"""Explainable priority rules based on current evidence, not just a numeric band."""
def advice(combined,signals,chart,sections,support):
    if support:
        return ['请优先由关怀人员核实当前安全状况，并人工联系已登记的紧急联系人；系统提醒不代表已经联系。',
            '若此刻可能受伤，请立即寻求身边可信任人员及当地紧急服务支持，不等待补全量表。',
            '本次先安排陪伴与安全核实，待合适时再继续日常对话或未完成问答。']
    confirmed={s['key'] for s in signals if s['confirmed']}
    valid=[p['score'] for p in chart['points'] if p['score'] is not None]
    suggestions=[]
    if valid and sum(valid)/len(valid)<40:
        suggestions.append('所选记录中消极表达较多，可以先倾听最近最困扰的事情，并了解用户希望获得的支持。')
    if len(valid)>=2 and valid[-1]<valid[0]:
        suggestions.append('较后记录的表达参考分较低，可以进一步了解最近是否出现新的压力；不能仅据曲线认定状态恶化。')
    if 'sleep' in confirmed:suggestions.append('可以具体了解近期睡眠困难及白天感受，讨论用户愿意尝试的规律作息与支持方式。')
    if 'withdrawal' in confirmed:suggestions.append('可以了解用户减少交流的原因，并鼓励按自己的节奏与信任的人保持联系。')
    if sections['daily_function']['status']=='recorded':suggestions.append('可以结合用户提到的工作、学习或自我照顾情况，进一步核实是否需要日常协助。')
    if combined['score_kind']=='complete' and combined['score']>=20:
        suggestions.insert(0,'完整问答提示相关困扰值得进一步关注；若持续或影响生活，可考虑由专业人员进一步评估。')
    if combined['score_kind']=='incomplete':suggestions.append('当前作答尚未完整，仅展示已答题小计；可以在愿意时继续，不据此判断症状程度。')
    return suggestions[:3] or ['可以按自己的节奏回顾最近在意的事，并与信任的人交流。']
