# -*- coding: utf-8 -*-
"""Voice Lexy support module.

Sprint 2 adds:
- UI translation helper t()/tr()
- separate display text and TTS-friendly phonetic text
- translated voice controls and common Streamlit labels
- safer fallback when OpenAI key/audio is unavailable

Clinical logic remains in the main app.
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

# Display text is what users see on screen. Keep accents/diacritics here.
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

# TTS text is what the speech engine reads. It is intentionally phonetic-friendly.
# The screen still shows the proper display text above.
TTS_TEXT_OVERRIDES = {
    "yo": {
        OPENING_TEXT["yo"]: "Eh kaabo. Emi ni Lek-see, oluranlowo ilera yin. Mo le ran yin lowo pelu ohun. Maa bi yin ni ibere die, ki n le mo ohun to n she yin daadaa.",
        SAFETY_TEXT["yo"]: "Bi o ba nira gan-an fun yin lati mi, tabi eje n jade pupo, tabi e n ni ifarapa bi see-zha, tabi e fe daku, e jowo lo gba itoju pajawiri lesekese.",
    },
    "ha": {
        OPENING_TEXT["ha"]: "Sannu da zoo-wa. Nee neh Lek-see, mai taimaka maka kan lafiya. Zan iya taimaka maka da murya. Zan yi maka tambayoyi domin in fahimci abin da ke damunka.",
        SAFETY_TEXT["ha"]: "Idan numfashi yana yi maka wahala sosai, ko kana zubar da jini sosai, ko kana samun farfadiya, ko kana jin kamar za ka fadi, ka nemi taimakon gaggawa nan take.",
    },
}

UI_TEXT = {
    "voice_panel_title": {"en": "🎤 Voice Lexy Beta", "yo": "🎤 Voice Lexy Beta", "ha": "🎤 Voice Lexy Beta"},
    "enable_voice": {"en": "Enable voice support for this session", "yo": "Tan ìrànlọ́wọ́ ohùn fún ìpàdé yìí", "ha": "Kunna taimakon murya a wannan zama"},
    "voice_language": {"en": "Voice language", "yo": "Èdè ohùn", "ha": "Yaren murya"},
    "voice_key_missing": {"en": "Voice playback/transcription needs OPENAI_API_KEY in Streamlit Secrets. Text mode still works.", "yo": "Fifi ohùn ṣiṣẹ́ nilo OPENAI_API_KEY ninu Streamlit Secrets. Ọ̀nà ọrọ̀ ṣi ń ṣiṣẹ́.", "ha": "Kunna murya/rikodin murya na bukatar OPENAI_API_KEY a Streamlit Secrets. Rubutu zai ci gaba da aiki."},
    "play_voice": {"en": "🔊 Play voice", "yo": "🔊 Gbọ́ ohùn", "ha": "🔊 Kunna murya"},
    "start_recording": {"en": "🎙️ Start recording", "yo": "🎙️ Bẹ̀rẹ̀ gbigbasilẹ", "ha": "🎙️ Fara rikodi"},
    "stop_recording": {"en": "⏹️ Stop recording", "yo": "⏹️ Dúró gbigbasilẹ", "ha": "⏹️ Tsayar da rikodi"},
    "heard": {"en": "Heard", "yo": "Mo gbọ́", "ha": "Na ji"},
    "admin": {"en": "Admin", "yo": "Alábójútó", "ha": "Mai gudanarwa"},
    "admin_code": {"en": "Admin code", "yo": "Kóòdù alábójútó", "ha": "Lambar mai gudanarwa"},
    "cookie_notice_title": {"en": "Cookie notice", "yo": "Ìfitónilétí cookie", "ha": "Sanarwar cookie"},
    "cookie_notice_1": {"en": "Enable Remember Me so you do not re-enter your details on next visit.", "yo": "Tan Remember Me kí ẹ má bà a tún tẹ alaye yín sílẹ̀ nígbà míì.", "ha": "Kunna Remember Me don kada ka sake shigar da bayananka a ziyara ta gaba."},
    "cookie_notice_2": {"en": "Accept cookies to proceed.", "yo": "Gba cookies láti tẹ̀síwájú.", "ha": "Amince da cookies domin ci gaba."},
    "remember_me": {"en": "Remember Me", "yo": "Rántí mi", "ha": "Tuna da ni"},
    "accept_cookies": {"en": "Accept Cookies", "yo": "Gba Cookies", "ha": "Amince da Cookies"},
    "cookie_required": {"en": "This triage service requires necessary cookies to operate and enforce fair-use limits.", "yo": "Ìṣẹ́ triage yìí nilo cookies pàtàkì láti ṣiṣẹ́ àti láti ṣàkóso ìlò tó tọ́.", "ha": "Wannan aikin triage na bukatar cookies masu muhimmanci domin ya yi aiki kuma ya kiyaye iyakar amfani."},
    "consent_checkbox": {"en": "I understand that this is a triage tool and not a diagnosis.", "yo": "Mo ye pé ohun èlò triage ni èyí, kì í ṣe ìdánimọ̀ àìsàn.", "ha": "Na fahimci cewa wannan kayan triage ne, ba ganewar cuta ba."},
    "start_symptom_check": {"en": "Start Symptom Check", "yo": "Bẹ̀rẹ̀ àyẹ̀wò ààmì àìsàn", "ha": "Fara duba alamomi"},
    "emergency_heading": {"en": "Go for emergency care now if you have:", "yo": "Ẹ lọ gba ìtọ́jú pajawiri báyìí bí ẹ bá ní:", "ha": "Ka nemi taimakon gaggawa yanzu idan kana da:"},
    "triage_disclaimer": {"en": "Lexy is an AI-powered triage engine, not a diagnostic tool. It helps users understand symptom urgency, likely care pathways, and next steps. It does not confirm a diagnosis and does not replace care from a qualified health professional.", "yo": "Lexy jẹ́ ẹ̀rọ triage tí AI ń ṣiṣẹ́ lé lórí, kì í ṣe ohun èlò ìdánimọ̀ àìsàn. Ó ń ran àwọn olùlò lọ́wọ́ láti mọ bí ààmì àìsàn ṣe ṣe pàtàkì, ọ̀nà ìtọ́jú tó yẹ, àti ìgbésẹ̀ tó kàn. Kò jẹ́rìí àìsàn, kò sì rọ́pò onímọ̀ ìlera tó péye.", "ha": "Lexy injin triage ne mai amfani da AI, ba kayan gano cuta ba. Yana taimaka wa masu amfani su fahimci gaggawar alamomi, hanyar samun kulawa, da mataki na gaba. Ba ya tabbatar da cuta kuma ba ya maye gurbin kwararren ma'aikacin lafiya."},
    "user_info_title": {"en": "Before we begin, I’d like to know a little about you.", "yo": "Kí a tó bẹ̀rẹ̀, jọ̀ọ́ sọ díẹ̀ nípa ara yín.", "ha": "Kafin mu fara, ina so in san kadan game da kai."},
    "voice_mode_active_info": {"en": "Voice mode is active. For this page, age and gender remain tap/type inputs for safety and accuracy.", "yo": "Ohùn ti ṣiṣẹ́. Fún ojúewé yìí, ọjọ́-ori àti akọ/abo ṣi jẹ́ ohun tí ẹ máa tẹ̀ tàbí yan fún ààbò àti ìtóye.", "ha": "Yanayin murya yana kunne. A wannan shafi, shekaru da jinsi za su kasance abin dannawa/rubutawa domin tsaro da daidaito."},
    "age": {"en": "Age", "yo": "Ọjọ́-ori", "ha": "Shekaru"},
    "gender": {"en": "Gender", "yo": "Akọ/abo", "ha": "Jinsi"},
    "male": {"en": "Male", "yo": "Ọkùnrin", "ha": "Namiji"},
    "female": {"en": "Female", "yo": "Obìnrin", "ha": "Mace"},
    "existing_conditions": {"en": "Existing conditions", "yo": "Àìsàn tó ti wà tẹ́lẹ̀", "ha": "Cututtukan da kake da su"},
    "existing_conditions_placeholder": {"en": "Mention any long-term conditions or type none", "yo": "Sọ àìsàn pípẹ́ tó bá wà, tàbí kọ none", "ha": "Rubuta cuta mai dadewa idan akwai, ko rubuta none"},
    "continue": {"en": "Continue →", "yo": "Tẹ̀síwájú →", "ha": "Ci gaba →"},
    "back": {"en": "← Back", "yo": "← Padà", "ha": "← Koma"},
    "symptom_category_title": {"en": "Let’s start with what’s bothering you today", "yo": "Ẹ jẹ́ ká bẹ̀rẹ̀ pẹ̀lú ohun tó ń ṣe yín lónìí", "ha": "Mu fara da abin da ke damunka yau"},
    "symptom_category_voice": {"en": "Please tell me what is bothering you today, or choose the closest category below.", "yo": "Jọ̀ọ́ sọ ohun tó ń ṣe yín lónìí, tàbí yan ẹ̀ka tó sunmọ́ jù ní isalẹ.", "ha": "Don Allah gaya min abin da ke damunka yau, ko ka zabi rukuni mafi kusa a kasa."},
    "type_symptoms_cta": {"en": "You can type your symptoms in your own words, or choose the closest category below.", "yo": "Ẹ lè kọ àwọn ààmì àìsàn yín ní ọ̀rọ̀ tirẹ̀, tàbí yan ẹ̀ka tó sunmọ́ jù ní isalẹ.", "ha": "Za ka iya rubuta alamominka da kalmominka, ko ka zabi rukuni mafi kusa a kasa."},
    "type_my_symptoms": {"en": "Type my symptoms", "yo": "Kọ àwọn ààmì àìsàn mi", "ha": "Rubuta alamomina"},
    "or_choose_category": {"en": "Or choose a category:", "yo": "Tàbí yan ẹ̀ka kan:", "ha": "Ko ka zabi rukuni:"},
    "what_are_symptoms": {"en": "What are your symptoms?", "yo": "Kí ni àwọn ààmì àìsàn tí ẹ ń ní?", "ha": "Wadanne alamomi kake ji?"},
    "symptom_caption": {"en": "Use 1–2 simple symptoms. Separate multiple with commas.", "yo": "Lo ààmì àìsàn rọrùn kan tàbí méjì. Fi comma ya wọn sọ́tọ̀.", "ha": "Yi amfani da alamomi sauki 1 zuwa 2. Raba su da comma."},
    "speak_main_symptom": {"en": "Speak your main symptom, for example: my body is hot", "yo": "Sọ ààmì àìsàn pàtàkì yín, bíi: ara mi ń gbóná", "ha": "Fadi babban alamar da kake ji, misali: jikina yana zafi"},
    "your_symptoms": {"en": "Your symptoms", "yo": "Àwọn ààmì àìsàn yín", "ha": "Alamominka"},
    "search_symptoms": {"en": "Search Symptoms", "yo": "Wá ààmì àìsàn", "ha": "Nemi alamomi"},
}

# Extra direct overrides for common page titles/questions used by Sprint 1.
QUESTION_OVERRIDES = {
    "en": {},
    "yo": {
        "Before we begin, I’d like to know a little about you.": UI_TEXT["user_info_title"]["yo"],
        "What are your symptoms?": UI_TEXT["what_are_symptoms"]["yo"],
        "To guide me better, answer a few questions": "Láti lè tọ́ yín dáadáa, ẹ jọ̀ọ́ dáhùn ìbéèrè díẹ̀.",
        "Based on your answers, this may be:": "Gẹ́gẹ́ bí ìdáhùn yín ṣe rí, èyí lè jẹ́:",
        "Please tell me what is bothering you today, or choose the closest category below.": UI_TEXT["symptom_category_voice"]["yo"],
    },
    "ha": {
        "Before we begin, I’d like to know a little about you.": UI_TEXT["user_info_title"]["ha"],
        "What are your symptoms?": UI_TEXT["what_are_symptoms"]["ha"],
        "To guide me better, answer a few questions": "Domin in taimaka maka da kyau, amsa wasu tambayoyi.",
        "Based on your answers, this may be:": "Bisa amsoshinka, wannan na iya zama:",
        "Please tell me what is bothering you today, or choose the closest category below.": UI_TEXT["symptom_category_voice"]["ha"],
    },
}

TTS_TEXT_OVERRIDES["yo"].update({
    UI_TEXT["user_info_title"]["yo"]: "Ki a to bere, jowo so die nipa ara yin.",
    UI_TEXT["symptom_category_voice"]["yo"]: "Jowo so ohun to n she yin loni, tabi yan eka to sunmo ju ni isale.",
    UI_TEXT["what_are_symptoms"]["yo"]: "Kini awon aami aisan ti e n ni?",
})
TTS_TEXT_OVERRIDES["ha"].update({
    UI_TEXT["user_info_title"]["ha"]: "Kafin mu fara, ina so in san kadan game da kai.",
    UI_TEXT["symptom_category_voice"]["ha"]: "Don Allah gaya min abin da ke damunka yau, ko ka zabi rukuni mafi kusa a kasa.",
    UI_TEXT["what_are_symptoms"]["ha"]: "Wadanne alamomi kake ji?",
})

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


def t(key: str, lang: Optional[str] = None) -> str:
    """Translate a fixed UI key. Falls back to English then the key."""
    lang = normalize_language(lang or selected_language())
    item = UI_TEXT.get(key, {})
    return item.get(lang) or item.get("en") or key

tr = t


def translate_ui_text(text: str, lang: Optional[str] = None) -> str:
    """Translate a raw UI sentence/question where a known override exists."""
    lang = normalize_language(lang or selected_language())
    return QUESTION_OVERRIDES.get(lang, {}).get(text, text)


def tts_text(text: str, lang: Optional[str] = None) -> str:
    """Return phonetic-friendly text for TTS while preserving display text on screen.

    Handles both exact matches and combined strings such as opening + safety.
    """
    lang = normalize_language(lang or selected_language())
    translated = translate_ui_text(text, lang)
    overrides = TTS_TEXT_OVERRIDES.get(lang, {})
    if translated in overrides:
        return overrides[translated]
    out = translated
    for display, phonetic in sorted(overrides.items(), key=lambda kv: len(kv[0]), reverse=True):
        if display and display in out:
            out = out.replace(display, phonetic)
    return out


def render_voice_controls(location: str = "main") -> None:
    """Render translated voice mode toggle and language selector."""
    with st.expander(t("voice_panel_title"), expanded=voice_enabled()):
        enabled = st.toggle(
            t("enable_voice"),
            value=voice_enabled(),
            key=f"voice_toggle_{location}",
        )
        st.session_state["voice_mode_enabled"] = enabled
        if enabled:
            current = selected_language()
            labels = list(SUPPORTED_LANGUAGES.values())
            default_index = labels.index(SUPPORTED_LANGUAGES.get(current, "English"))
            label = st.selectbox(t("voice_language"), labels, index=default_index, key=f"voice_lang_{location}")
            st.session_state["voice_language"] = LANGUAGE_LABEL_TO_CODE.get(label, "en")
            if not _get_secret("OPENAI_API_KEY"):
                st.info(t("voice_key_missing"))


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
            kwargs = {"model": _get_secret("LEXY_STT_MODEL", "gpt-4o-mini-transcribe"), "file": audio_file}
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
    voice = _get_secret("LEXY_TTS_VOICE", "nova")
    response = client.audio.speech.create(
        model=_get_secret("LEXY_TTS_MODEL", "gpt-4o-mini-tts"),
        voice=voice,
        input=tts_text(text, lang=lang),
    )
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
    """Render a translated button that speaks text aloud in the selected language."""
    if not voice_enabled() or not text:
        return
    lang = normalize_language(lang or selected_language())
    if st.button(t("play_voice", lang), key=key, use_container_width=True):
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

    st.caption(translate_ui_text(prompt))
    audio = mic_recorder(
        start_prompt=t("start_recording"),
        stop_prompt=t("stop_recording"),
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
        st.success(f"{t('heard')}: {transcript}")
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
    duration_map = {
        "today": "Today", "one day": "1 day", "1 day": "1 day", "two days": "2 days",
        "2 days": "2 days", "three days": "3 days", "3 days": "3 days",
        "more than three days": "More than 3 days", "kwana biyu": "2 days", "ojo meji": "2 days",
    }
    for phrase, value in duration_map.items():
        if phrase in text:
            for option in options:
                if clean_transcript(option) == clean_transcript(value):
                    return option
    return None
