"""
Voice Lexy language + script layer.

Drop this file beside the main Lexy Streamlit app.
It keeps all patient-facing voice text outside the clinical engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import pandas as pd

SUPPORTED_LANGUAGES = {
    "en": "English",
    "yo": "Yoruba",
    "ha": "Hausa",
}

DEFAULT_LANGUAGE = "en"


@dataclass(frozen=True)
class VoiceScript:
    key: str
    context: str
    en: str
    yo: str
    ha: str
    response_type: str = ""
    risk_flag: str = ""


class VoiceScriptStore:
    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)
        self.df = pd.read_csv(self.csv_path).fillna("")
        required = {"script_key", "context", "english_spoken", "yoruba_spoken", "hausa_spoken"}
        missing = required - set(self.df.columns)
        if missing:
            raise ValueError(f"voice_scripts CSV missing columns: {sorted(missing)}")
        self._rows: Dict[str, dict] = {
            str(row["script_key"]): row.to_dict() for _, row in self.df.iterrows()
        }

    def get(self, key: str, lang: str = DEFAULT_LANGUAGE) -> str:
        lang = normalize_language(lang)
        row = self._rows.get(key)
        if not row:
            return f"[{key}]"
        col = {
            "en": "english_spoken",
            "yo": "yoruba_spoken",
            "ha": "hausa_spoken",
        }.get(lang, "english_spoken")
        value = str(row.get(col, "")).strip()
        if value:
            return value
        return str(row.get("english_spoken", "")).strip()

    def response_type(self, key: str) -> str:
        row = self._rows.get(key, {})
        return str(row.get("expected_response_type", "")).strip()

    def risk_flag(self, key: str) -> str:
        row = self._rows.get(key, {})
        return str(row.get("risk_flag", "")).strip()


def normalize_language(lang: Optional[str]) -> str:
    if not lang:
        return DEFAULT_LANGUAGE
    lang = lang.lower().strip()
    aliases = {
        "english": "en",
        "yoruba": "yo",
        "hausa": "ha",
        "en-us": "en",
        "en-gb": "en",
    }
    return aliases.get(lang, lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE)


def clean_transcript(text: str) -> str:
    return " ".join(str(text or "").lower().strip().replace(".", " ").replace(",", " ").split())


def load_voice_freetext_map(csv_path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path).fillna("")
    required = {"phrase", "language", "canonical_symptom", "confidence"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"voice FreeTextMap CSV missing columns: {sorted(missing)}")
    df["phrase_clean"] = df["phrase"].map(clean_transcript)
    df["language"] = df["language"].map(normalize_language)
    return df


def map_transcript_to_symptom(transcript: str, freetext_df: pd.DataFrame, lang: str = DEFAULT_LANGUAGE) -> Optional[str]:
    """Simple deterministic MVP mapper.

    Returns the canonical English symptom used by the existing Lexy engine.
    The main engine should receive this value, not the translated patient phrase.
    """
    text = clean_transcript(transcript)
    if not text:
        return None
    lang = normalize_language(lang)

    # 1) Exact phrase match, same language first.
    exact = freetext_df[(freetext_df["phrase_clean"] == text) & (freetext_df["language"] == lang)]
    if not exact.empty:
        return str(exact.sort_values("confidence", ascending=False).iloc[0]["canonical_symptom"])

    # 2) Exact phrase match, any language fallback.
    exact_any = freetext_df[freetext_df["phrase_clean"] == text]
    if not exact_any.empty:
        return str(exact_any.sort_values("confidence", ascending=False).iloc[0]["canonical_symptom"])

    # 3) Contains match for short user utterances.
    candidates = []
    for _, row in freetext_df.iterrows():
        phrase = str(row["phrase_clean"])
        if phrase and (phrase in text or text in phrase):
            candidates.append(row)
    if candidates:
        cdf = pd.DataFrame(candidates)
        same_lang = cdf[cdf["language"] == lang]
        if not same_lang.empty:
            return str(same_lang.sort_values("confidence", ascending=False).iloc[0]["canonical_symptom"])
        return str(cdf.sort_values("confidence", ascending=False).iloc[0]["canonical_symptom"])

    return None


def parse_yes_no_answer(transcript: str, lang: str = DEFAULT_LANGUAGE) -> Optional[bool]:
    text = clean_transcript(transcript)
    yes_terms = {
        "en": {"yes", "yeah", "yep", "i do", "i have", "true"},
        "yo": {"beeni", "bẹẹni", "bee ni", "mo ni", "o wa", "wa"},
        "ha": {"eh", "e", "na'am", "naam", "ina da", "akwai"},
    }
    no_terms = {
        "en": {"no", "nope", "not", "i do not", "i don't", "false"},
        "yo": {"rara", "ko si", "mi o", "emi ko"},
        "ha": {"a'a", "aa", "babu", "ba ni", "ba haka ba"},
    }
    all_yes = set().union(*yes_terms.values())
    all_no = set().union(*no_terms.values())
    if text in all_yes or any(term in text for term in all_yes if len(term) > 2):
        return True
    if text in all_no or any(term in text for term in all_no if len(term) > 2):
        return False
    return None
