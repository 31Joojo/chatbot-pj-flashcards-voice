# src/speech/tts.py
from __future__ import annotations

import os
import tempfile
from typing import Optional

import pyttsx3


_ENGINE = None


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = pyttsx3.init()
        _ENGINE.setProperty("rate", 175)  # vitesse (ajuste si besoin)
    return _ENGINE


def synthesize_to_wav(text: str, voice: Optional[str] = None) -> str:
    """
    Synthesize speech to a temporary wav file and return the path.

    :param text: Text to speak
    :param voice: Optional voice id/name (mac voices)
    :return: filepath to wav
    """
    t = (text or "").strip()
    if not t:
        raise ValueError("Empty text for TTS")

    engine = _get_engine()

    if voice:
        # best-effort: set a voice containing substring
        for v in engine.getProperty("voices") or []:
            if voice.lower() in (getattr(v, "name", "") or "").lower():
                engine.setProperty("voice", v.id)
                break

    fd, path = tempfile.mkstemp(suffix=".wav", prefix="tts_")
    os.close(fd)

    engine.save_to_file(t, path)
    engine.runAndWait()
    return path
