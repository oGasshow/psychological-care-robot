"""Optional model wording. Statistics and safety never depend on model output."""
from pathlib import Path
import json
import asyncio
import os
import re
import time
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Annotated
from .report_facts import rules_narrative

PROMPT_VERSION = 'report-summary-v2-scales'


class CitedText(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    text: Annotated[str, Field(min_length=1, max_length=220)]
    evidence_ids: Annotated[list[Annotated[str, Field(min_length=1, max_length=100)]], Field(min_length=1, max_length=8)]


class Narrative(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    overview: CitedText
    scale_readings: Annotated[list[CitedText], Field(max_length=8)] = Field(default_factory=list)
    changes: Annotated[list[CitedText], Field(max_length=2)]
    topics: Annotated[list[CitedText], Field(max_length=3)]
    conversation_suggestions: Annotated[list[CitedText], Field(max_length=3)]
    limitations: Annotated[list[CitedText], Field(max_length=3)]


def configuration():
    base = os.getenv('ROBOT_CARE_REPORT_MODEL_BASE_URL', os.getenv('ROBOT_CARE_MODEL_BASE_URL', ''))
    model = os.getenv('ROBOT_CARE_REPORT_MODEL_NAME', os.getenv('ROBOT_CARE_MODEL_NAME', ''))
    provider = os.getenv('ROBOT_CARE_REPORT_PROVIDER', 'ollama' if base and model else 'disabled')
    if provider == 'disabled':
        return None
    if provider == 'doubao_realtime':
        from ..voice.settings import settings as voice_settings
        voice_config = voice_settings()
        timeout = float(os.getenv('ROBOT_CARE_REPORT_TIMEOUT_SECONDS', '45'))
        if not voice_config.api_key or not 1 <= timeout <= 60:
            raise ValueError('model_configuration_invalid')
        return dict(provider=provider, model=voice_config.model, timeout=timeout)
    parsed = urlsplit(base)
    if (provider not in ('ollama', 'chat_completions', 'qwen', 'doubao') or parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment or not model.strip() or len(model) > 160):
        raise ValueError('model_configuration_invalid')
    timeout = float(os.getenv('ROBOT_CARE_REPORT_TIMEOUT_SECONDS', '25'))
    if not 1 <= timeout <= 60:
        raise ValueError('model_configuration_invalid')
    return dict(provider=provider, base=base.rstrip('/'), model=model, timeout=timeout,
                key=os.getenv('ROBOT_CARE_REPORT_API_KEY', ''))


def strict_json(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError('duplicate_key')
            result[key] = item
        return result
    return json.loads(value, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('constant')))


def validate_content(raw, facts):
    result = Narrative.model_validate(strict_json(raw))
    allowed = {e['id'] for e in facts['evidence']} | {f['id'] for f in facts['facts']}
    scale_facts={f['id']:f for f in facts['facts'] if f['kind']=='scale_result'}
    if any(f.get('answered',0)>0 for f in scale_facts.values()) and not result.scale_readings:
        raise ValueError('missing_scale_readings')
    for reading in result.scale_readings:
        selected=[scale_facts.get(i) for i in reading.evidence_ids]
        if len(selected)!=1 or selected[0] is None:raise ValueError('scale_reading_reference_invalid')
        f=selected[0]
        if f['score'] is None and re.search(r'轻度|中度|重度|正常|得分为|得分是|分数为|分数是',reading.text):raise ValueError('incomplete_scale_interpretation')
        if f['instrument_kind']=='project_indicator' and re.search(r'轻度|中度|重度|抑郁症|焦虑症',reading.text):raise ValueError('custom_indicator_clinical_claim')
        if f.get('reference_band'):
            expected=re.findall(r'中重度|轻度|中度|重度',f['reference_band'])
            if any(g not in expected for g in re.findall(r'中重度|轻度|中度|重度',reading.text)):raise ValueError('scale_band_mismatch')
        for name in ('PHQ-9','GAD-7'):
            if name!=f['scale_id']:
                for match in re.finditer(re.escape(name),reading.text):
                    if not re.search(r'不是|不等于|不能|不代表|不可|不应|并非|无法',reading.text[max(0,match.start()-24):match.start()]):raise ValueError('scale_name_mismatch')
        text=re.sub(r'PHQ-9|GAD-7','量表',reading.text)
        allowed_numbers={str(v) for v in (f['score'],f['max_score'],f['item_count']) if v is not None}
        if any(n not in allowed_numbers for n in re.findall(r'\d+(?:\.\d+)?',text)):raise ValueError('scale_number_not_verified')
    all_items = [result.overview, *result.changes, *result.topics, *result.conversation_suggestions, *result.limitations]
    for item in all_items:
        if len(set(item.evidence_ids)) != len(item.evidence_ids) or any(r not in allowed for r in item.evidence_ids):
            raise ValueError('invalid_evidence_reference')
        # Deliberately keep numbers in deterministic UI components. This is a guard,
        # not a proof of semantic fidelity; content still needs the documented review.
        numeric_text=item.text
        cited_scales=[scale_facts[i] for i in item.evidence_ids if i in scale_facts and scale_facts[i]['score'] is not None]
        for f in cited_scales:
            if len(cited_scales)==1 or f['scale_id'] in numeric_text:
                numeric_text=re.sub(r'(?<!\d)'+str(f['score'])+r'\s*分(?!钟)','已核实分数',numeric_text)
                numeric_text=re.sub(r'(?<!\d)'+str(f['score'])+r'\s*/\s*'+str(f['max_score'])+r'(?!\d)','已核实合计',numeric_text)
        numeric_text=re.sub(r'PHQ-9|GAD-7','量表',numeric_text)
        if item in result.conversation_suggestions:numeric_text=numeric_text.replace('一次','适当')
        if re.search(r'\d|百分之|百分点|[一二三四五六七八九十百]+(?:条|天|次|分)', numeric_text):
            raise ValueError('narrative_numeric_claim')
        if re.search(r'诊断为|患有|确诊|没有风险|绝对安全|健康总分|服用|用药|疗效显著|已联系|风险等级', item.text):
            raise ValueError('unsupported_claim')
        if '<' in item.text or '>' in item.text or re.search(r'https?://|\S+@\S+\.', item.text):
            raise ValueError('unsupported_markup_or_contact')
    for item in result.scale_readings:
        if re.search(r'诊断为|患有|确诊|绝对安全|服用|用药|疗效显著|已联系|<|>|https?://',item.text):raise ValueError('unsupported_scale_claim')
    if result.changes and not any(g['comparison']['eligible'] for g in facts['groups']):
        raise ValueError('comparison_not_eligible')
    return result.model_dump()


def generate(facts):
    started = time.monotonic()
    fallback = lambda reason: {**rules_narrative(facts, reason), 'elapsed_ms': round((time.monotonic() - started) * 1000)}
    if not facts['eligible_user_text_count']:
        return fallback('no_user_records')
    if facts['data_nature'] == 'mixed':
        return fallback('mixed_sources_use_separate_rules')
    try:
        config = configuration()
    except (ValueError, TypeError, OverflowError):
        return fallback('model_configuration_invalid')
    if config is None:
        return fallback('model_not_configured')
    if not facts['evidence']:
        return fallback('no_suitable_excerpts')
    prompt = (Path(__file__).parent / 'prompts' / 'report_summary_v2.txt').read_text('utf-8')
    schema = Narrative.model_json_schema()
    evidence_input = {k: facts[k] for k in ('report_facts_version', 'scope', 'comparison_scope', 'data_nature', 'facts', 'evidence', 'evidence_selection')}
    messages = [{'role': 'system', 'content': prompt + '\n输出 JSON Schema：' + json.dumps(schema, ensure_ascii=False)},
                {'role': 'user', 'content': json.dumps(evidence_input, ensure_ascii=False, separators=(',', ':'))}]
    if config['provider'] == 'doubao_realtime':
        from ..voice.upstream import structured_report, VoiceServiceError
        try:
            async def compose():
                selected=[f for f in facts['facts'] if f['kind']=='scale_result' and f.get('answered',0)>0]
                selected=sorted(selected,key=lambda f:f['instrument_kind']!='standard_reference')[:3]
                compact_keys=('id','kind','instrument_kind','scale_id','name','purpose','score','max_score','answered','item_count','status','reference_band','meaning','limitation','item9_attention')
                compact=[{k:f[k] for k in compact_keys if k in f} if f['kind']=='scale_result' else f for f in facts['facts']]
                async def text_part(instructions,payload):
                    raw=await structured_report(instructions+'\n只返回实际JSON对象，只有text和evidence_ids两个字段，不返回overview包装或schema。',CitedText.model_json_schema(),payload,config['timeout'])
                    value=strict_json(raw)
                    if isinstance(value,dict) and set(value)=={'overview'}:value=value['overview']
                    return CitedText.model_validate(value).model_dump()
                summary_input={**evidence_input,'facts':compact}
                tasks=[text_part(prompt+'\n本次仅写overview：以一段具体回顾联系该用户经历、已核验量表与一个可选择的小建议，不复述数字。',summary_input)]
                tasks.append(text_part(prompt+'\n本次只写一条适合该用户的小建议，联系真实经历，简短可做，不用固定开场，不给出天数、分钟或统计数字。',summary_input))
                for f in selected:
                    one={k:f[k] for k in compact_keys if k in f}
                    tasks.append(text_part('你是中文心理陪伴报告撰写者。针对输入唯一指标写一段具体解读：测到了什么、分数或完整度说明什么、哪些结论不能推出。标准量表只用给定参考段，自定义指标不分临床等级；不诊断。只引用这个事实的id，不重复缺失项目，不编造信息。使用阿拉伯数字表达给定的总分，文字不超过200字。',dict(facts=[one],evidence=[])))
                async with asyncio.timeout(config['timeout']):parts=await asyncio.gather(*tasks)
                return dict(overview=parts[0],scale_readings=parts[2:],changes=[],topics=[],conversation_suggestions=[parts[1]],limitations=[])
            data=validate_content(json.dumps(asyncio.run(compose()),ensure_ascii=False),facts)
        except TimeoutError:
            return fallback('model_timeout')
        except VoiceServiceError as exc:
            return fallback(exc.code)
        except (ValueError, TypeError, KeyError, OSError, ValidationError) as exc:
            value=fallback('model_output_rejected')
            value['validation_reason']=str(exc) if re.fullmatch(r'[a-z_]{1,80}',str(exc)) else 'schema_validation_failed'
            return value
        return dict(mode='model', status='ready', reason_code=None, prompt_version=PROMPT_VERSION,
                    model=config['model'], provider=config['provider'], content=data,
                    source_snapshot_hash=facts['source_snapshot_hash'], elapsed_ms=round((time.monotonic()-started)*1000))
    payload = dict(model=config['model'], messages=messages, stream=False)
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if config['key']:
        headers['Authorization'] = 'Bearer ' + config['key']
    if config['provider'] == 'ollama':
        url = config['base'] + '/api/chat'
        payload.update(format=schema, options={'temperature': 0, 'num_predict': 1400}, think=False)
    else:
        url = config['base'] + '/chat/completions'
        payload.update(temperature=0, max_tokens=1400, response_format={'type': 'json_object'})
        if config['provider'] == 'qwen':
            payload['enable_thinking'] = False
        elif config['provider'] == 'doubao':
            payload['thinking'] = {'type': 'disabled'}
    try:
        # Never inherit system proxies or follow redirects carrying private excerpts.
        with httpx.Client(timeout=config['timeout'], trust_env=False, follow_redirects=False) as client:
            with client.stream('POST', url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    return fallback('model_http_error')
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 65536:
                        return fallback('model_response_too_large')
        envelope = strict_json(raw)
        if config['provider'] == 'ollama':
            if envelope.get('done') is not True or envelope.get('model') != config['model'] or envelope['message'].get('role') != 'assistant':
                raise ValueError('model_protocol_invalid')
            content = envelope['message']['content']
        else:
            choice = envelope['choices'][0]
            if choice.get('finish_reason') != 'stop' or choice['message'].get('role') != 'assistant' or choice['message'].get('tool_calls'):
                raise ValueError('model_protocol_invalid')
            content = choice['message']['content']
        if not isinstance(content, str):
            raise ValueError('model_protocol_invalid')
        data = validate_content(content, facts)
    except httpx.TimeoutException:
        return fallback('model_timeout')
    except httpx.HTTPError:
        return fallback('model_unavailable')
    except (ValueError, KeyError, TypeError, IndexError, UnicodeError, RecursionError, ValidationError):
        return fallback('model_output_rejected')
    return dict(mode='model', status='ready', reason_code=None, prompt_version=PROMPT_VERSION,
                model=config['model'], provider=config['provider'], content=data,
                source_snapshot_hash=facts['source_snapshot_hash'], elapsed_ms=round((time.monotonic() - started) * 1000))
