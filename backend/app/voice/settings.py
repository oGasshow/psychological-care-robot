from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit

DEFAULT_URL = 'wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue'

@dataclass(frozen=True)
class VoiceSettings:
    enabled: bool
    api_key: str = field(repr=False)
    url: str = DEFAULT_URL
    model: str = '1.2.6.1'
    voice: str = 'zh_female_vv_jupiter_bigtts'
    session_seconds: int = 900

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
    if model != '1.2.6.1' or not voice or len(voice) > 100 or not 30 <= limit <= 1800:
        raise ValueError('voice_configuration_invalid')
    return VoiceSettings(enabled == 'true', key, url, model, voice, limit)
