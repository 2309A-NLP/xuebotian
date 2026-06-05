from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import ApiResponse


class SpeechTranscriptionData(BaseModel):
    text: str


class SpeechTranscriptionResponse(ApiResponse):
    data: SpeechTranscriptionData
