"""
Voice Lexy I/O layer.

This module isolates speech-to-text and text-to-speech provider calls.
It is intentionally independent of the Lexy clinical engine.

Install dependencies when ready:
    pip install openai streamlit-mic-recorder

Set environment variable:
    OPENAI_API_KEY=...
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import os
import tempfile


class VoiceProviderError(RuntimeError):
    pass


def speech_to_text(audio_bytes: bytes, filename: str = "voice_input.wav", language_hint: Optional[str] = None) -> str:
    """Transcribe audio bytes to text using OpenAI.

    language_hint may be 'en', 'yo', or 'ha'. If uncertain, pass None.
    """
    if not audio_bytes:
        return ""
    try:
        from openai import OpenAI
    except Exception as exc:
        raise VoiceProviderError("OpenAI Python package is not installed.") from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise VoiceProviderError("OPENAI_API_KEY is not configured.")

    client = OpenAI(api_key=api_key)
    suffix = Path(filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as audio_file:
            # Keep model as config if your developer wants to change it later.
            result = client.audio.transcriptions.create(
                model=os.getenv("LEXY_STT_MODEL", "gpt-4o-mini-transcribe"),
                file=audio_file,
                language=language_hint if language_hint in {"en", "yo", "ha"} else None,
            )
        return getattr(result, "text", "") or ""
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def text_to_speech(text: str, output_path: str | Path, voice: str = "alloy") -> Path:
    """Create spoken audio from text using OpenAI TTS and save as MP3."""
    if not text:
        raise ValueError("No text supplied for speech output.")
    try:
        from openai import OpenAI
    except Exception as exc:
        raise VoiceProviderError("OpenAI Python package is not installed.") from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise VoiceProviderError("OPENAI_API_KEY is not configured.")

    client = OpenAI(api_key=api_key)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    response = client.audio.speech.create(
        model=os.getenv("LEXY_TTS_MODEL", "gpt-4o-mini-tts"),
        voice=voice,
        input=text,
    )
    response.write_to_file(str(output_path))
    return output_path
