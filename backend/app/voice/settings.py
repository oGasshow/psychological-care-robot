from dataclasses import dataclass, field
import os
from typing import Literal, get_args
from urllib.parse import urlsplit

DEFAULT_URL = 'wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue'
VoiceName = Literal['zh_female_qinqienv_uranus_bigtts', 'zh_male_tiancaitongsheng_uranus_bigtts',
                    'zh_female_xiaohe_uranus_bigtts', 'zh_female_wenroumama_uranus_bigtts']
VOICE_OPTIONS = tuple({'id': voice, 'name': name} for voice, name in zip(get_args(VoiceName),
                      ('亲切女声', '天才童声', '小何', '温柔妈妈')))

@dataclass(frozen=True)
class VoiceSettings:
    enabled: bool
    api_key: str = field(repr=False)
    url: str = DEFAULT_URL
    model: str = '1.2.6.1'
    voice: str = 'zh_female_vv_jupiter_bigtts'
    session_seconds: int = 900
    speed: int = 0

def settings():
    enabled = os.getenv('ROBOT_CARE_VOICE_ENABLED', 'false').lower()
    key = os.getenv('DOUBAO_VOICE_API_KEY', '')
    url = os.getenv('DOUBAO_VOICE_WS_URL', DEFAULT_URL)
    parsed = urlsplit(url)
    local_test = os.getenv('APP_ENV') == 'test' and parsed.scheme == 'ws' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')
    if (enabled not in ('true', 'false') or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (url != DEFAULT_URL and not local_test)):
        raise ValueError('voice_configuration_invalid')
    model = os.getenv('ROBOT_CARE_VOICE_MODEL', '1.2.6.1')
    voice = os.getenv('ROBOT_CARE_VOICE_NAME', 'zh_female_vv_jupiter_bigtts')
    limit = int(os.getenv('ROBOT_CARE_VOICE_SESSION_SECONDS', '900'))
    speed = int(os.getenv('ROBOT_CARE_VOICE_SPEED', '0'))
    if model != '1.2.6.1' or not voice or len(voice) > 100 or not 30 <= limit <= 1800 or not -50 <= speed <= 100:
        raise ValueError('voice_configuration_invalid')
    return VoiceSettings(enabled == 'true', key, url, model, voice, limit, speed)
