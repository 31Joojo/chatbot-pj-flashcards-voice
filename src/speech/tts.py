# src/speech/tts.py
### Modules importation
from __future__ import annotations

import os
import re
import time
import uuid
import subprocess
from pathlib import Path
from typing import Optional

### Directory to store TSS file generated
TTS_DIR = Path("data/tts")

### ------------------------------ Helpers ------------------------------ ###
### Helper : _sanitize_filename()
def _sanitize_filename(s: str) -> str:
    """
    Sanitize a string to make it safe for use as a filename.

    This function removes any character that is not alphanumeric
    and replaces invalid characters with
    underscores, and truncates the result to a reasonable length.

    :param str s: Raw input string
    :return str: Sanitized filename-safe string
    """
    ### Replace invalid filename characters with underscores
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", s).strip("_")

    ### Limit filename length to avoid filesystem issues
    return s[:40] if s else "tts"

### ----------------------------- Functions ----------------------------- ###
### Function : synthesize_to_wav()
def synthesize_to_wav(text: str, voice: Optional[str] = None) -> str:
    """
    Synthesize speech from text and export it as a WAV audio file.

    This function generate an AIFF audio file, then converts it
    to a browser-compatible WAV file using afconvert.

    A unique filename is generated for each synthesis to avoid
    caching issues in the client.

    :param str text: Text to synthesize into speech
    :param Optional[str] voice: Optional macOS voice identifier
    :return str: Path to the generated WAV audio file
    :raises ValueError: If the input text is empty
    :raises RuntimeError: If the generated audio file is invalid
    """
    ### Validate and normalize input text
    t = (text or "").strip()
    if not t:
        raise ValueError("Empty text for TTS")

    ### Ensure output directory exists
    TTS_DIR.mkdir(parents=True, exist_ok=True)

    ### Generate a unique base filename to prevent caching conflicts
    ts = int(time.time() * 1000)
    uid = uuid.uuid4().hex
    base = f"tts_{ts}_{uid}"

    aiff_path = TTS_DIR / f"{base}.aiff"
    wav_path = TTS_DIR / f"{base}.wav"

    ### Step 1 : Use say to generate an AIFF file
    say_cmd = ["say", "-o", str(aiff_path)]
    if voice:
        say_cmd += ["-v", voice]
    say_cmd.append(t)

    subprocess.run(say_cmd, check=True)

    ### Step 2 : Convert AIFF to WAV
    conv_cmd = [
        "afconvert",
        "-f", "WAVE",
        "-d", "LEI16@22050",
        str(aiff_path),
        str(wav_path),
    ]
    subprocess.run(conv_cmd, check=True)

    ### Cleanup intermediate AIFF file
    try:
        os.remove(aiff_path)
    except Exception:
        pass

    ### Basic sanity check on the resulting WAV file
    if not wav_path.exists() or wav_path.stat().st_size < 1024:
        raise RuntimeError("TTS produced an invalid/empty wav file")

    return str(wav_path)
