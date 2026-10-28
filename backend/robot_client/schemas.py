"""Shared wire validation, deliberately independent of database/JWT configuration."""
import re
from datetime import datetime, timezone
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, BeforeValidator, model_validator, field_validator, ValidationError
from .errors import InputValidationError

ID = Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')]
Seq = Annotated[StrictInt, Field(ge=1, le=2147483647)]
LastSeq = Annotated[StrictInt, Field(ge=0, le=2147483647)]

def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d+)?(?:[Zz]|[+-]\d\d:\d\d)', value):
        raise ValueError('RFC3339 with timezone required')
    try:
        if value[-1].upper() != 'Z' and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            raise ValueError()
        parsed = datetime.fromisoformat(value.upper().replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    except (ValueError, OverflowError):
        raise ValueError('Invalid RFC3339 time') from None

UTCText = Annotated[str, BeforeValidator(utc), Field(json_schema_extra={'format': 'date-time'})]

class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)

class SessionCreate(StrictBody):
    source: Literal['doubao_realtime']
    device_id: ID
    external_session_id: ID
    started_at: UTCText
    is_test: StrictBool

class MessageCreate(StrictBody):
    external_message_id: ID
    turn_id: ID | None = None
    sequence_no: Seq
    role: Literal['user', 'assistant']
    content: Annotated[str, Field(strict=True, max_length=8000)]
    occurred_at: UTCText
    text_status: Literal['completed', 'canceled']
    playback_status: Literal['not_applicable', 'completed', 'interrupted', 'not_started', 'unknown']

    @field_validator('content')
    @classmethod
    def valid_unicode(cls, value):
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise ValueError('Invalid Unicode content') from None
        return value

    @model_validator(mode='after')
    def valid_terminal(self):
        if self.text_status == 'completed' and not self.content.strip():
            raise ValueError('completed content must contain non-whitespace')
        if (self.role == 'user') != (self.playback_status == 'not_applicable'):
            raise ValueError('playback_status incompatible with role')
        return self

class SessionClose(StrictBody):
    ended_at: UTCText
    last_sequence_no: LastSeq

def validation_details(exc):
    """Whitelist field locations and error types, including hostile extra keys."""
    fields = set(SessionCreate.model_fields) | set(MessageCreate.model_fields) | set(SessionClose.model_fields)
    return [{'loc': [part if type(part) is int or part in fields else '*' for part in e['loc']],
             'type': e['type']}
            for e in exc.errors(include_input=False, include_context=False, include_url=False)]

def validate_body(model, data):
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise InputValidationError(validation_details(exc)) from None
