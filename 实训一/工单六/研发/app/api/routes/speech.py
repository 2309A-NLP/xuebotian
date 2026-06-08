from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import get_container, get_current_user
from app.core.container import AppContainer
from app.schemas.speech import SpeechTranscriptionData, SpeechTranscriptionResponse

router = APIRouter(prefix="/speech", tags=["speech"])


@router.post("/transcribe", response_model=SpeechTranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    container: AppContainer = Depends(get_container),
    _: dict = Depends(get_current_user),
) -> SpeechTranscriptionResponse:
    audio_bytes = await file.read()
    text = container.speech_transcriber.transcribe(audio_bytes, file.filename or "audio.wav")
    return SpeechTranscriptionResponse(
        message="transcribed",
        data=SpeechTranscriptionData(text=text),
    )
