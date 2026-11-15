"""Service endpoints for opted-in voice input and downstream follow-up checks."""
import asyncio
import base64
import binascii
import hmac
import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..robot_records import RecordError
from . import sega_live

router = APIRouter(prefix='/sega/integration')
bearer = HTTPBearer(auto_error=False)
MAX_AUDIO = sega_live.MAX_FRAMES * sega_live.FRAME.size
MAX_BASE64 = 4 * ((MAX_AUDIO + 2) // 3)
MAX_BODY = 3 * MAX_BASE64 + 4096
Id = Annotated[int, Field(gt=0, le=2**63-1)]
MessageId = Annotated[str, Field(min_length=1, max_length=128)]


class Pair(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    question_message_id: MessageId
    answer_message_id: MessageId
    pcm_base64: Annotated[str, Field(min_length=1, max_length=MAX_BASE64)]


class VoiceInput(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    user_id: Id
    consent: Literal[True]
    gender: Literal['female', 'male']
    sample_rate: Literal[16000]
    pairs: Annotated[list[Pair], Field(min_length=3, max_length=3)]


def aligned_audio(encoded):
    pcm = base64.b64decode(encoded, validate=True)
    frame = sega_live.FRAME.size
    if len(pcm) % 2 or not sega_live.MIN_FRAMES * frame <= len(pcm) <= MAX_AUDIO:
        raise ValueError('sega_audio_length')
    voiced = 0
    for offset in range(0, len(pcm) - frame + 1, frame):
        if sega_live.speech_frame(pcm[offset:offset + frame]):
            voiced += 1
            if voiced >= sega_live.MIN_FRAMES:
                return pcm
    raise ValueError('sega_audio_silent')


def permit(credentials, variable):
    expected = os.getenv(variable, '')
    if len(expected) < 32:
        raise HTTPException(503, 'sega_integration_not_configured')
    if not credentials or not hmac.compare_digest(credentials.credentials.encode(), expected.encode()):
        raise HTTPException(401, 'sega_integration_unauthorized', headers={'WWW-Authenticate': 'Bearer'})


@router.post('/sessions/{sid}', status_code=202)
async def submit(sid: Annotated[int, Path(gt=0, le=2**63-1)], request: Request, response: Response,
                 credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    permit(credentials, 'ROBOT_CARE_SEGA_INPUT_TOKEN')
    if not await asyncio.to_thread(sega_live.available):
        raise HTTPException(503, 'sega_extractor_not_configured')
    response.headers['Cache-Control'] = 'no-store'
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY:
            raise HTTPException(413, 'sega_voice_input_too_large')
        body.extend(chunk)
    try:
        value = VoiceInput.model_validate_json(body)
        capture = sega_live.CallAudio(value.gender)
        for pair in value.pairs:
            capture.pairs.append((pair.question_message_id, pair.answer_message_id, aligned_audio(pair.pcm_base64)))
    except (ValidationError, ValueError, binascii.Error):
        raise HTTPException(422, 'sega_voice_input_invalid') from None
    try:
        return await asyncio.to_thread(sega_live.enqueue, value.user_id, sid, capture, strict=True)
    except RecordError as exc:
        raise HTTPException(exc.status, exc.code) from None


@router.get('/followups/{uid}')
def get_followup(uid: Annotated[int, Path(gt=0, le=2**63-1)], is_test: bool, response: Response,
                 credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    permit(credentials, 'ROBOT_CARE_SEGA_FOLLOWUP_TOKEN')
    response.headers['Cache-Control'] = 'no-store'
    return {'user_id': uid, 'is_test': is_test, **sega_live.followup(uid, is_test)}
