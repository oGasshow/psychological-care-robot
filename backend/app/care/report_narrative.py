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

PROMPT_VERSION = 'report-summary-v1'


class CitedText(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    text: Annotated[str, Field(min_length=1, max_length=220)]
    evidence_ids: Annotated[list[Annotated[str, Field(min_length=1, max_length=100)]], Field(min_length=1, max_length=8)]


class Narrative(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    overview: CitedText
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
    all_items = [result.overview, *result.changes, *result.topics, *result.conversation_suggestions, *result.limitations]
    for item in all_items:
        if len(set(item.evidence_ids)) != len(item.evidence_ids) or any(r not in allowed for r in item.evidence_ids):
            raise ValueError('invalid_evidence_reference')
        # Deliberately keep numbers in deterministic UI components. This is a guard,
        # not a proof of semantic fidelity; content still needs the documented review.
        if re.search(r'\d|百分之|百分点|[一二三四五六七八九十百]+(?:条|天|次|分)', item.text):
            raise ValueError('narrative_numeric_claim')
        if re.search(r'诊断为|患有|确诊|没有风险|绝对安全|健康总分|服用|用药|疗效显著|已联系|风险等级', item.text):
            raise ValueError('unsupported_claim')
        if '<' in item.text or '>' in item.text or re.search(r'https?://|\S+@\S+\.', item.text):
            raise ValueError('unsupported_markup_or_contact')
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
    prompt = (Path(__file__).parent / 'prompts' / 'report_summary_v1.txt').read_text('utf-8')
    schema = Narrative.model_json_schema()
    evidence_input = {k: facts[k] for k in ('report_facts_version', 'scope', 'comparison_scope', 'data_nature', 'facts', 'evidence', 'evidence_selection')}
    messages = [{'role': 'system', 'content': prompt + '\n输出 JSON Schema：' + json.dumps(schema, ensure_ascii=False)},
                {'role': 'user', 'content': json.dumps(evidence_input, ensure_ascii=False, separators=(',', ':'))}]
    if config['provider'] == 'doubao_realtime':
        from ..voice.upstream import structured_report, VoiceServiceError
        try:
            raw = asyncio.run(structured_report(prompt, schema, evidence_input, config['timeout']))
            data = validate_content(raw, facts)
        except TimeoutError:
            return fallback('model_timeout')
        except VoiceServiceError as exc:
            return fallback(exc.code)
        except (ValueError, TypeError, KeyError, OSError, ValidationError):
            return fallback('model_output_rejected')
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
