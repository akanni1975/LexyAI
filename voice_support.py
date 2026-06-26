# -*- coding: utf-8 -*-
"""Voice Lexy support module.

This file is intentionally a thin wrapper around the existing Lexy engine.
It handles voice-mode state, microphone capture, speech-to-text, simple answer
parsing, and text-to-speech playback. The clinical logic remains in the main app.
"""
from __future__ import annotations

import base64
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable, Optional

import streamlit as st
import streamlit.components.v1 as components

SUPPORTED_LANGUAGES = {
    "en": "English",
    "yo": "Yoruba",
    "ha": "Hausa",
}

LANGUAGE_LABEL_TO_CODE = {v: k for k, v in SUPPORTED_LANGUAGES.items()}

OPENING_TEXT = {
    "en": "Hello. Welcome to Lexy, your AI health assistant. I can now support this session with voice. I will ask questions to better understand your symptoms.",
    "yo": "Ẹ káàbọ̀. Èmi ni Lexy, olùrànlọ́wọ́ ìlera yín. Mo lè ran yín lọ́wọ́ pẹ̀lú ohùn. Màá bi yín ní ìbéèrè díẹ̀ kí n lè mọ ohun tó ń ṣe yín dáadáa.",
    "ha": "Sannu da zuwa. Ni ne Lexy, mai taimaka maka kan lafiya. Zan iya taimaka maka da murya. Zan yi maka tambayoyi domin in fahimci abin da ke damunka.",
}

SAFETY_TEXT = {
    "en": "If you have severe breathing difficulty, heavy bleeding, seizures, collapse, confusion, or rapidly worsening symptoms, please seek emergency care immediately.",
    "yo": "Bí ó bá nira gan-an fún yín láti mí, tàbí ẹ̀jẹ̀ ń jáde púpọ̀, tàbí ẹ ń ní ìfarapa bíi seizure, tàbí ẹ fẹ́ dákú, ẹ jọ̀ọ́ lọ gba ìtọ́jú pajawiri lẹ́sẹ̀kẹsẹ̀.",
    "ha": "Idan numfashi yana yi maka wahala sosai, ko kana zubar da jini sosai, ko kana samun farfadiya, ko kana jin kamar za ka fadi, ka nemi taimakon gaggawa nan take.",
}

QUESTION_OVERRIDES = {
    "en": {},
    "yo": {
        "Before we begin, I’d like to know a little about you.": "Kí a tó bẹ̀rẹ̀, jọ̀ọ́ sọ díẹ̀ nípa ara yín.",
        "What are your symptoms?": "Kí ni àwọn ààmì àìsàn tí ẹ ń ní?",
        "To guide me better, answer a few questions": "Láti lè tọ́ yín dáadáa, ẹ jọ̀ọ́ dáhùn ìbéèrè díẹ̀.",
        "Based on your answers, this may be:": "Gẹ́gẹ́ bí ìdáhùn yín ṣe rí, èyí lè jẹ́:",
    },
    "ha": {
        "Before we begin, I’d like to know a little about you.": "Kafin mu fara, ina so in san kadan game da kai.",
        "What are your symptoms?": "Wadanne alamomi kake ji?",
        "To guide me better, answer a few questions": "Domin in taimaka maka da kyau, amsa wasu tambayoyi.",
        "Based on your answers, this may be:": "Bisa amsoshinka, wannan na iya zama:",
    },
}

YES_TERMS = {
    "en": {"yes", "yeah", "yep", "i do", "i have", "true"},
    "yo": {"beeni", "bẹẹni", "bee ni", "mo ni", "o wa", "wa"},
    "ha": {"eh", "e", "na'am", "naam", "ina da", "akwai"},
}
NO_TERMS = {
    "en": {"no", "nope", "not", "i do not", "i don't", "false"},
    "yo": {"rara", "ko si", "mi o", "emi ko"},
    "ha": {"a'a", "aa", "babu", "ba ni", "ba haka ba"},
}


def _get_secret(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    try:
        value = st.secrets.get(name, value)  # type: ignore[attr-defined]
    except Exception:
        pass
    return str(value or "")


def normalize_language(lang: Optional[str]) -> str:
    if not lang:
        return "en"
    lang = str(lang).strip().lower()
    aliases = {"english": "en", "yoruba": "yo", "hausa": "ha"}
    return aliases.get(lang, lang if lang in SUPPORTED_LANGUAGES else "en")


def voice_enabled() -> bool:
    return bool(st.session_state.get("voice_mode_enabled", False))


def selected_language() -> str:
    return normalize_language(st.session_state.get("voice_language", "en"))


def render_voice_controls(location: str = "main") -> None:
    """Render the voice mode toggle and language selector."""
    with st.expander("🎤 Voice Lexy Beta", expanded=voice_enabled()):
        enabled = st.toggle(
            "Enable voice support for this session",
            value=voice_enabled(),
            key=f"voice_toggle_{location}",
        )
        st.session_state["voice_mode_enabled"] = enabled
        if enabled:
            current = selected_language()
            labels = list(SUPPORTED_LANGUAGES.values())
            default_index = labels.index(SUPPORTED_LANGUAGES.get(current, "English"))
            label = st.selectbox("Voice language", labels, index=default_index, key=f"voice_lang_{location}")
            st.session_state["voice_language"] = LANGUAGE_LABEL_TO_CODE.get(label, "en")
            if not _get_secret("OPENAI_API_KEY"):
                st.info("Voice playback/transcription needs OPENAI_API_KEY in Streamlit Secrets. Text mode still works.")


def translate_ui_text(text: str, lang: Optional[str] = None) -> str:
    lang = normalize_language(lang or selected_language())
    return QUESTION_OVERRIDES.get(lang, {}).get(text, text)


def clean_transcript(text: str) -> str:
    text = str(text or "").strip().lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^a-zA-ZÀ-ÿ'\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def speech_to_text(audio_bytes: bytes, language_hint: Optional[str] = None, filename: str = "voice_input.wav") -> str:
    if not audio_bytes:
        return ""
    api_key = _get_secret("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("The openai package is not installed. Add openai to requirements.txt.") from exc

    client = OpenAI(api_key=api_key)
    suffix = Path(filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as audio_file:
            kwargs = {
                "model": _get_secret("LEXY_STT_MODEL", "gpt-4o-mini-transcribe"),
                "file": audio_file,
            }
            lang = normalize_language(language_hint)
            if lang in {"en", "yo", "ha"}:
                kwargs["language"] = lang
            result = client.audio.transcriptions.create(**kwargs)
        return str(getattr(result, "text", "") or "").strip()
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def text_to_speech(text: str, lang: Optional[str] = None) -> bytes:
    if not text:
        return b""
    api_key = _get_secret("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("The openai package is not installed. Add openai to requirements.txt.") from exc

    client = OpenAI(api_key=api_key)
    voice = _get_secret("LEXY_TTS_VOICE", "alloy")
    response = client.audio.speech.create(
        model=_get_secret("LEXY_TTS_MODEL", "gpt-4o-mini-tts"),
        voice=voice,
        input=text,
    )
    # Newer SDKs provide .content; older SDKs can stream/write. Keep both paths.
    content = getattr(response, "content", None)
    if content:
        return bytes(content)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        response.write_to_file(tmp_path)
        return Path(tmp_path).read_bytes()
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def autoplay_audio(audio_bytes: bytes, mime: str = "audio/mp3") -> None:
    if not audio_bytes:
        return
    b64 = base64.b64encode(audio_bytes).decode("utf-8")
    components.html(
        f"""
        <audio autoplay controls style="width: 100%; margin-top: 8px;">
          <source src="data:{mime};base64,{b64}" type="{mime}">
        </audio>
        """,
        height=54,
    )


def speak_text(text: str, key: str = "voice_speak", lang: Optional[str] = None) -> None:
    """Render a button that speaks text aloud in the selected language."""
    if not voice_enabled() or not text:
        return
    lang = normalize_language(lang or selected_language())
    if st.button("🔊 Play voice", key=key, use_container_width=True):
        try:
            autoplay_audio(text_to_speech(text, lang=lang))
        except Exception as exc:
            st.warning(f"Voice playback unavailable: {exc}")


def mic_capture(key: str, prompt: str = "Record voice") -> Optional[str]:
    """Capture microphone audio and return transcript, if available."""
    if not voice_enabled():
        return None
    try:
        from streamlit_mic_recorder import mic_recorder
    except Exception:
        st.warning("Voice recording package missing. Add streamlit-mic-recorder to requirements.txt.")
        return None

    st.caption(prompt)
    audio = mic_recorder(
        start_prompt="🎙️ Start recording",
        stop_prompt="⏹️ Stop recording",
        just_once=False,
        use_container_width=True,
        key=key,
    )
    if not audio:
        return None

    audio_bytes = audio.get("bytes") if isinstance(audio, dict) else None
    if not audio_bytes:
        return None

    try:
        transcript = speech_to_text(audio_bytes, language_hint=selected_language())
    except Exception as exc:
        st.warning(f"Voice transcription unavailable: {exc}")
        return None

    if transcript:
        st.success(f"Heard: {transcript}")
    return transcript or None


def parse_yes_no(transcript: str, lang: Optional[str] = None) -> Optional[str]:
    text = clean_transcript(transcript)
    lang = normalize_language(lang or selected_language())
    yes = set().union(*YES_TERMS.values()) | YES_TERMS.get(lang, set())
    no = set().union(*NO_TERMS.values()) | NO_TERMS.get(lang, set())
    if text in yes or any(term in text for term in yes if len(term) > 2):
        return "Yes"
    if text in no or any(term in text for term in no if len(term) > 2):
        return "No"
    return None


def match_option(transcript: str, options: Iterable[str]) -> Optional[str]:
    text = clean_transcript(transcript)
    if not text:
        return None
    options = list(options)
    for option in options:
        opt = clean_transcript(option)
        if opt and (opt == text or opt in text or text in opt):
            return option
    # common duration shortcuts
    duration_map = {
        "today": "Today",
        "one day": "1 day",
        "1 day": "1 day",
        "two days": "2 days",
        "2 days": "2 days",
        "three days": "3 days",
        "3 days": "3 days",
        "more than three days": "More than 3 days",
    }
    for phrase, value in duration_map.items():
        if phrase in text:
            for option in options:
                if clean_transcript(option) == clean_transcript(value):
                    return option
    return None
