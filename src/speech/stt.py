# src/speech/stt.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from faster_whisper import WhisperModel


@dataclass
class STTResult:
    text: str
    language: Optional[str] = None


_MODEL: WhisperModel | None = None


def _get_model(model_size: str = "small") -> WhisperModel:
    """
    Lazy-load Whisper model once per process.
    """
    global _MODEL
    if _MODEL is None:
        # device="cpu" is safest; if you have GPU you can switch to "cuda"
        _MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _MODEL


def transcribe_audio(audio_path: str, model_size: str = "small") -> STTResult:
    """
    Transcribe an audio file (wav/mp3/m4a) into text using faster-whisper.

    :param audio_path: Path returned by gr.Audio(type="filepath")
    :param model_size: Whisper size ('tiny', 'base', 'small', 'medium', 'large-v3', ...)
    :return: STTResult(text=..., language=...)
    """
    model = _get_model(model_size=model_size)

    segments, info = model.transcribe(
        audio_path,
        vad_filter=True,
        beam_size=1,
    )

    parts = []
    for seg in segments:
        if seg.text:
            parts.append(seg.text.strip())

    text = " ".join(parts).strip()
    lang = getattr(info, "language", None)
    return STTResult(text=text, language=lang)
