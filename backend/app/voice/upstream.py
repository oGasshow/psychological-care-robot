"""One versioned Seeduplex JSON protocol for Windows, browser and Pi adapters."""
import asyncio
import base64
from contextlib import asynccontextmanager, suppress
import json
from pathlib import Path
import wave

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, ConnectionClosed
from .settings import settings

COMPANION_PROMPT = (
    '你是温和、耐心的中文陪伴助手。用简单自然的中文，回答简洁，每次一两句话。'
    '先倾听并回应用户当下的感受，适当复述具体内容，不机械重复同一句鼓励，不连续追问。'
    '用户插话时停止旧话题，优先听取新的表达；用户明确结束时简短道别。'
    '不施测或推荐量表，不生成分数和评估报告，不进行心理疾病诊断、不承诺疗效。'
    '如出现明确伤害自己的表达，温和回应并鼓励获得身边可信任的人及专业人员的及时支持。'
)
GREETING = '你好，我在这里。今天有什么想聊的吗？'

class VoiceServiceError(Exception):
    def __init__(self, code, provider_code=None):
        self.code, self.provider_code = code, provider_code
        super().__init__(code)

class NoRedirectConnect(connect):
    def process_redirect(self, exc):
        # The provider key must never follow a redirect to a different origin.
        return exc

def session_payload(config, instructions=COMPANION_PROMPT, tools=None):
    session = dict(model=config.model, instructions=instructions,
                   audio=dict(input={'format': {'type': 'pcm', 'rate': 16000}},
                              output={'format': {'type': 'pcm_s16le', 'rate': 24000}, 'voice': config.voice}))
    if tools:
        session['tools'] = tools
    return dict(type='session.create', session=session, extension={'asr': {}, 'tts': {}, 'dialog': {}})

def decode_event(raw):
    if not isinstance(raw, str) or len(raw) > 2**21:
        raise VoiceServiceError('voice_protocol_invalid')
    try:
        event = json.loads(raw)
        if not isinstance(event, dict) or not isinstance(event.get('type'), str):
            raise ValueError()
    except (ValueError, UnicodeError, RecursionError):
        raise VoiceServiceError('voice_protocol_invalid') from None
    if event['type'] == 'error':
        code = event.get('code') or (event.get('error', {}).get('code') if isinstance(event.get('error'), dict) else None)
        raise VoiceServiceError('voice_provider_error', str(code)[:60] if code is not None else None)
    return event

@asynccontextmanager
async def connection(config=None, *, instructions=COMPANION_PROMPT, tools=None):
    config = config or settings()
    if not config.api_key:
        raise VoiceServiceError('voice_not_configured')
    try:
        async with NoRedirectConnect(config.url, additional_headers={'X-Api-Key': config.api_key}, proxy=None,
                                     open_timeout=12, close_timeout=3, max_size=2**21, max_queue=16,
                                     ping_interval=20, ping_timeout=20) as ws:
            await ws.send(json.dumps(session_payload(config, instructions, tools), ensure_ascii=False))
            async with asyncio.timeout(12):
                while True:
                    event = decode_event(await ws.recv())
                    if event['type'] == 'session.created':
                        break
            try:
                yield ws, event
            finally:
                with suppress(Exception):
                    await ws.send(json.dumps({'type': 'session.close'}))
    except InvalidStatus as exc:
        raise VoiceServiceError('voice_authentication_failed' if exc.response.status_code in (401, 403) else 'voice_service_unavailable') from None
    except TimeoutError:
        raise VoiceServiceError('voice_timeout') from None
    except ConnectionClosed:
        raise VoiceServiceError('voice_connection_closed') from None
    except (OSError, EOFError):
        raise VoiceServiceError('voice_service_unavailable') from None

async def structured_report(instructions, schema, facts, timeout=45):
    """Use the supplied speech entitlement via a synthetic trigger and FC output.

    No microphone or speaker is opened, and this private service session never
    enters a user's conversation history. A normal text API remains selectable.
    """
    # This speech tool implementation needs inline property definitions; $ref
    # produced plausible text with the wrong object shape in the live probe.
    definitions = schema.get('$defs', {})
    allowed = [item['id'] for item in facts['facts'] + facts['evidence']]
    def inline(value):
        if isinstance(value, list):
            return [inline(item) for item in value]
        if not isinstance(value, dict):
            return value
        if '$ref' in value:
            return inline(definitions[value['$ref'].rsplit('/', 1)[1]])
        result = {key: inline(item) for key, item in value.items() if key not in ('$defs', 'title')}
        if 'evidence_ids' in result.get('properties', {}):
            result['properties']['evidence_ids']['items']['enum'] = allowed
        return result
    parameters = inline(schema)
    tool = dict(type='function', name='write_companionship_report',
                description='将给定事实整理成有引用依据的中文陪伴记录摘要。所有文字字段均为含 text 和 evidence_ids 的对象。直接提交结构化报告。', parameters=parameters)
    prompt = (instructions + '\n本会话专用于整理报告。收到固定的合成语音开始信号后，立即调用 '
              'write_companionship_report，一次性提交完整结果，不进行普通聊天，不播报报告。'
              'overview 必须是 {"text":"中文回顾","evidence_ids":["输入中的真实id"]} 对象，不能是字符串。'
              'changes、topics、conversation_suggestions、limitations 的每个元素也必须具有 text 和 evidence_ids，不能使用 content 字段。'
              '建议和限制也要引用支持该表述的事实或原话id。没有可比条件时 changes 返回空数组。'
              '\n完整输出结构：' + json.dumps(parameters, ensure_ascii=False) + '\n'
              '统计和原话仅以以下 JSON 资料为依据，语音不包含报告事实。\n'
              + json.dumps(facts, ensure_ascii=False, separators=(',', ':')))
    asset = Path(__file__).parent / 'assets' / 'report_trigger.wav'
    with wave.open(str(asset), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise VoiceServiceError('voice_trigger_invalid')
        pcm = wav.readframes(wav.getnframes())
    async with asyncio.timeout(timeout):
        async with connection(instructions=prompt, tools=[tool]) as (ws, created):
            async def feed():
                # Real-time pacing is required by this speech protocol.
                for offset in range(0, len(pcm), 640):
                    await ws.send(json.dumps({'type': 'input_audio_buffer.append',
                                              'audio': base64.b64encode(pcm[offset:offset+640].ljust(640, b'\0')).decode('ascii')}))
                    await asyncio.sleep(.02)
                await ws.send(json.dumps({'type': 'input_audio_buffer.commit'}))
                await ws.send(json.dumps({'type': 'input_audio_mute.commit'}))
            feeder = asyncio.create_task(feed())
            text = ''
            try:
                async for raw in ws:
                    event = decode_event(raw)
                    if event['type'] == 'response.function_call_arguments.done':
                        items=event.get('items', [])
                        if not isinstance(items,list):raise VoiceServiceError('voice_protocol_invalid')
                        for item in items:
                            if not isinstance(item,dict):raise VoiceServiceError('voice_protocol_invalid')
                            if item.get('name') == tool['name'] and isinstance(item.get('arguments'), str):
                                if len(item['arguments'])>16000:raise VoiceServiceError('voice_report_too_large')
                                return item['arguments']
                    elif event['type'] == 'response.output_text.delta':
                        text += event.get('delta', '')
                        if len(text) > 16000:
                            raise VoiceServiceError('voice_report_too_large')
                    elif event['type'] == 'response.output_text.done':
                        text = event.get('text') or text
                        # Some model revisions return JSON text instead of a tool call.
                        if text.lstrip().startswith('{'):
                            return text
                    elif event['type'] == 'session.closed':
                        break
            finally:
                feeder.cancel()
                with suppress(asyncio.CancelledError):
                    await feeder
    raise VoiceServiceError('voice_report_missing')
