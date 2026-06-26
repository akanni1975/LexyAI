"""
Streamlit patch/example for adding Voice Lexy fever journey.

Paste/adapt this into the existing app as a new page or gated beta section.
It deliberately calls no clinical engine yet; replace run_existing_lexy_engine_stub()
with the existing Lexy recommendation function once your developer wires it in.
"""

from __future__ import annotations

from pathlib import Path
import streamlit as st

from voice_language_layer import (
    SUPPORTED_LANGUAGES,
    VoiceScriptStore,
    load_voice_freetext_map,
    map_transcript_to_symptom,
    parse_yes_no_answer,
)

# Optional package for browser microphone capture:
# pip install streamlit-mic-recorder
try:
    from streamlit_mic_recorder import mic_recorder
except Exception:
    mic_recorder = None

from voice_io_layer import speech_to_text, text_to_speech, VoiceProviderError

BASE_DIR = Path(__file__).parent
VOICE_SCRIPTS_PATH = BASE_DIR / "voice_scripts_fever_en_yo_ha.csv"
VOICE_FREETEXT_PATH = BASE_DIR / "voice_freetext_map_seed.csv"
AUDIO_OUT_DIR = BASE_DIR / "voice_audio_cache"

FEVER_QUESTION_KEYS = [
    "q_fever_duration",
    "q_temperature_measured",
    "q_chills",
    "q_cough",
    "q_breathing",
    "q_vomiting",
    "q_drinking",
]


def speak_text(text: str, key: str = "lexy_audio"):
    st.write(text)
    try:
        audio_path = text_to_speech(text, AUDIO_OUT_DIR / f"{key}.mp3")
        st.audio(str(audio_path), format="audio/mp3")
    except VoiceProviderError as exc:
        st.caption(f"Voice output unavailable: {exc}")
    except Exception as exc:
        st.caption(f"Voice output failed: {exc}")


def get_audio_transcript(lang: str, recorder_key: str) -> str:
    # Fallback text field keeps the demo usable without microphone package/API key.
    typed = st.text_input("Or type what the patient said", key=f"typed_{recorder_key}")

    if mic_recorder is None:
        return typed

    audio = mic_recorder(
        start_prompt="🎤 Start speaking",
        stop_prompt="⏹ Stop",
        just_once=False,
        key=recorder_key,
    )
    if audio and audio.get("bytes"):
        try:
            transcript = speech_to_text(audio["bytes"], language_hint=lang)
            st.caption(f"Transcript: {transcript}")
            return transcript
        except Exception as exc:
            st.error(f"Speech recognition failed: {exc}")
    return typed


def run_existing_lexy_engine_stub(answers: dict) -> str:
    """Replace this with the existing Lexy engine call.

    For MVP demo, all non-emergency fever journeys use same 'assess today' script.
    If breathing difficulty is yes or drinking fluids is no, this should become emergency/urgent.
    """
    if answers.get("q_breathing") is True or answers.get("q_drinking") is False:
        return "urgent"
    return "today"


def voice_lexy_fever_page():
    st.title("Voice Lexy — Fever MVP")
    scripts = VoiceScriptStore(VOICE_SCRIPTS_PATH)
    freetext_df = load_voice_freetext_map(VOICE_FREETEXT_PATH)

    lang_label = st.radio("Choose language", list(SUPPORTED_LANGUAGES.values()), horizontal=True)
    lang = {v: k for k, v in SUPPORTED_LANGUAGES.items()}[lang_label]

    if "voice_step" not in st.session_state:
        st.session_state.voice_step = "start"
        st.session_state.voice_answers = {}
        st.session_state.voice_symptom = None
        st.session_state.voice_q_index = 0

    if st.button("Reset Voice Demo"):
        st.session_state.voice_step = "start"
        st.session_state.voice_answers = {}
        st.session_state.voice_symptom = None
        st.session_state.voice_q_index = 0
        st.rerun()

    if st.session_state.voice_step == "start":
        speak_text(scripts.get("opening", lang), "opening")
        speak_text(scripts.get("safety", lang), "safety")
        speak_text(scripts.get("ask_main_symptom", lang), "ask_main_symptom")
        transcript = get_audio_transcript(lang, "main_symptom_audio")
        if st.button("Continue from symptom"):
            symptom = map_transcript_to_symptom(transcript, freetext_df, lang)
            if symptom == "fever":
                st.session_state.voice_symptom = symptom
                st.session_state.voice_step = "questions"
                st.rerun()
            else:
                speak_text(scripts.get("not_understood", lang), "not_understood")

    elif st.session_state.voice_step == "questions":
        speak_text(scripts.get("ack_fever", lang), "ack_fever")
        q_index = st.session_state.voice_q_index
        if q_index >= len(FEVER_QUESTION_KEYS):
            st.session_state.voice_step = "recommendation"
            st.rerun()

        q_key = FEVER_QUESTION_KEYS[q_index]
        speak_text(scripts.get(q_key, lang), q_key)
        transcript = get_audio_transcript(lang, f"audio_{q_key}")
        response_type = scripts.response_type(q_key)

        if st.button("Save answer and continue", key=f"save_{q_key}"):
            if response_type == "yes_no":
                parsed = parse_yes_no_answer(transcript, lang)
                if parsed is None:
                    speak_text(scripts.get("not_understood", lang), f"retry_{q_key}")
                    return
                st.session_state.voice_answers[q_key] = parsed
            else:
                st.session_state.voice_answers[q_key] = transcript
            st.session_state.voice_q_index += 1
            st.rerun()

    elif st.session_state.voice_step == "recommendation":
        outcome = run_existing_lexy_engine_stub(st.session_state.voice_answers)
        # Existing app should map outcome to its real recommendation text.
        speak_text(scripts.get("recommend_today", lang), "recommendation")
        speak_text(scripts.get("connect_doctor", lang), "connect_doctor")
        col1, col2 = st.columns(2)
        with col1:
            st.button(scripts.get("button_yes", lang))
        with col2:
            st.button(scripts.get("button_not_now", lang))
        st.caption(f"Internal MVP outcome: {outcome}")


# In main app router, call:
# voice_lexy_fever_page()
