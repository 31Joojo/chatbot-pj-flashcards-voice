# src/speech/stt.py
### Modules importation
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from faster_whisper import WhisperModel


### Cached Whisper model instance
_MODEL: WhisperModel | None = None

### Class : STTResult
@dataclass
class STTResult:
    """
    Container for speech-to-text transcription results.

    :arg str text: Transcribed text content
    :arg Optional[str] language: Detected or forced language code
    """
    text: str
    language: Optional[str] = None

### ------------------------------ Helpers ------------------------------ ###
### Helper : _get_model()
def _get_model(model_size: str = "small") -> WhisperModel:
    """
    Load and cache a Whisper model instance.

    The model is loaded only once per process and reused across
    transcription calls to reduce initialization overhead.

    :param str model_size: Whisper model size to load
    :return WhisperModel: Loaded Whisper model instance
    """
    global _MODEL
    if _MODEL is None:
        ### CPU inference
        _MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _MODEL

### ----------------------------- Functions ----------------------------- ###
### Function : transcribe_audio()
def transcribe_audio(audio_path: str, model_size: str = "small") -> STTResult:
    """
    Transcribe an audio file into text using the faster-whisper backend.

    This function performs automatic speech recognition on an
    audio file and returns the concatenated transcription along with
    the detected language.

    :param str audio_path: Path to the audio file
    :param str model_size: Whisper model size
    :return STTResult: Transcription result containing text and language
    """
    ### Load the Whisper model
    model = _get_model(model_size=model_size)

    ### Run transcription with tuned decoding parameters
    segments, info = model.transcribe(
        audio_path,
        language="fr",
        task="transcribe",
        vad_filter=True,
        beam_size=3,
        temperature=0.0,
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
        condition_on_previous_text=False,
    )

    ### Concatenate non-empty transcription segments
    parts = []
    for seg in segments:
        if seg.text:
            parts.append(seg.text.strip())

    ### Fallback to French if language metadata is missing
    text = " ".join(parts).strip()
    lang = getattr(info, "language", None) or "fr"
    return STTResult(text=text, language=lang)
