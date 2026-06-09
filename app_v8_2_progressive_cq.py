
# -*- coding: utf-8 -*-
"""
SymptomBot app adapted for the rebuilt multi-sheet workbook.

Key design choices
------------------
1) Uses the rebuilt workbook as the source of truth:
   - Taxonomy
   - Subcategory Logic
   - Condition Rows
   - optional FreeTextMap
2) Builds a runtime compatibility dataframe so the UI can stay close to the old app flow.
3) Uses symptom overlap + CQ support + risk flags + confidence + acuity scoring
   instead of trying to execute the new prose ConditionSpecificRule text.
4) Pediatrics are handled through PopulationGroup filtering, not a special primary category.

Expected workbook sheets
------------------------
Required:
- Taxonomy
- Subcategory Logic
- Condition Rows

Optional:
- FreeTextMap

If FreeTextMap is missing in the new workbook, the app will try to read it from
a legacy workbook path if available.
"""
from __future__ import annotations

import html
import os
import re
import csv
from datetime import datetime
from difflib import SequenceMatcher
from typing import Dict, List, Tuple, Set

import pandas as pd
import streamlit as st
import urllib.parse
import streamlit.components.v1 as components
from uuid import uuid4

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None
st.set_page_config(page_title="Lexy — AI Triage Engine", page_icon="🩺", layout="centered")

# ----------------------------
# Configuration
# ----------------------------
APP_NAME = os.getenv("SYMPTOMBOT_BRAND_NAME", "Lexy")
APP_TITLE = os.getenv("SYMPTOMBOT_BRAND_TITLE", f"{APP_NAME} — AI Triage Engine")
APP_SUBTITLE = os.getenv(
    "SYMPTOMBOT_BRAND_SUBTITLE",
    "AI-powered symptom triage support for urgency guidance and next steps."
)
APP_HELP_URL = os.getenv("SYMPTOMBOT_HELP_URL", "https://lexconsult.carekonnect.net/")

WORKBOOK_PATH = os.getenv("SYMPTOMBOT_WORKBOOK", "SymptomBot_v2_engine_refined_with_freetextmap.xlsx")
LEGACY_WORKBOOK_PATH = os.getenv("SYMPTOMBOT_LEGACY_WORKBOOK", "SymptomBotDB.xlsx")
LOG_PATH = os.getenv("SYMPTOMBOT_LOG", "failure_log_v8.csv")
SESSIONS_LOG_PATH = os.getenv("SYMPTOMBOT_SESSIONS_LOG", "analytics_sessions_v1.csv")
MAX_REVEALS_PER_DAY = 5
DEV_PASSWORD = os.getenv("SYMPTOMBOT_DEV_PASSWORD", "Akinola")
LOGO_PATH = os.getenv("SYMPTOMBOT_LOGO", "logo.png")
LEADS_LOG_PATH = os.getenv("SYMPTOMBOT_LEADS_LOG", "analytics_leads_v1.csv")
COOKIE_CONSENT_NAME = os.getenv("SYMPTOMBOT_COOKIE_CONSENT", "lexy_cookie_pref")
DEVICE_COOKIE_NAME = os.getenv("SYMPTOMBOT_DEVICE_COOKIE", "lexy_device_id")
USER_COOKIE_NAME = os.getenv("SYMPTOMBOT_USER_COOKIE", "lexy_user_id")
PHONE_REGEX = re.compile(r"^\+234\d{10}$")

ACUITY_TEXT_TO_NUM = {
    "low": 1,
    "moderate": 2,
    "high": 3,
    "emergency": 4,
}
CONFIDENCE_TEXT_TO_NUM = {"low": 0, "medium": 1, "high": 2}

GENDER_BLOCK_TERMS = {
    "Male": ("women’s health", "women's health", "vaginal", "vulva", "labia", "uterine", "cervic", "ovarian", "menstrual", "pregnan"),
    "Female": ("men’s health", "men's health", "prostate", "penile", "testicular", "scrot", "erectile", "semen", "male genital"),
}

GENERIC_TOKENS = {
    "pain", "ache", "aches", "soreness", "discomfort", "rash", "rashes", "fever",
    "cough", "vomiting", "diarrhea", "diarrhoea", "dizziness", "fatigue", "weakness",
    "swelling", "itch", "itching", "bleeding", "nausea"
}

STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "these", "those", "your",
    "have", "has", "had", "were", "was", "been", "very", "more", "than", "into", "about",
    "today", "still", "just", "part", "mainly", "main", "also", "then", "them", "they"
}

BODY_PART_HINTS = {
    "head": {"Headache, dizziness, weakness, or balance symptoms"},
    "eye": {"Eye / Ear symptoms", "Fever / General unwellness / Flu-like symptoms"},
    "ear": {"Eye / Ear symptoms", "Headache, dizziness, weakness, or balance symptoms"},
    "nose": {"Respiratory / Nose / Throat symptoms"},
    "throat": {"Respiratory / Nose / Throat symptoms"},
    "mouth": {"Dentistry / Teeth / Gums", "Respiratory / Nose / Throat symptoms"},
    "tooth": {"Dentistry / Teeth / Gums"},
    "teeth": {"Dentistry / Teeth / Gums"},
    "gum": {"Dentistry / Teeth / Gums"},
    "gums": {"Dentistry / Teeth / Gums"},
    "jaw": {"Dentistry / Teeth / Gums", "Bone, joint, muscle, or limb symptoms"},
    "chest": {"Chest / Heart-related symptoms", "Respiratory / Nose / Throat symptoms"},
    "breast": {"Women’s Health", "General body, blood sugar, thyroid, or weakness symptoms"},
    "abdomen": {"Stomach, bowel, or abdominal symptoms"},
    "abdominal": {"Stomach, bowel, or abdominal symptoms"},
    "belly": {"Stomach, bowel, or abdominal symptoms"},
    "stomach": {"Stomach, bowel, or abdominal symptoms"},
    "rectal": {"Stomach, bowel, or abdominal symptoms"},
    "rectum": {"Stomach, bowel, or abdominal symptoms"},
    "anal": {"Stomach, bowel, or abdominal symptoms"},
    "anus": {"Stomach, bowel, or abdominal symptoms"},
    "stool": {"Stomach, bowel, or abdominal symptoms"},
    "stooling": {"Stomach, bowel, or abdominal symptoms"},
    "constipation": {"Stomach, bowel, or abdominal symptoms"},
    "bowel": {"Stomach, bowel, or abdominal symptoms"},
    "poo": {"Stomach, bowel, or abdominal symptoms"},
    "pooping": {"Stomach, bowel, or abdominal symptoms"},
    "groin": {"Men’s Health", "Women’s Health", "Stomach, bowel, or abdominal symptoms"},
    "penis": {"Men’s Health", "Urinary symptoms"},
    "testicle": {"Men’s Health"},
    "testicles": {"Men’s Health"},
    "scrotum": {"Men’s Health"},
    "vagina": {"Women’s Health"},
    "vaginal": {"Women’s Health"},
    "vulva": {"Women’s Health"},
    "urine": {"Urinary symptoms"},
    "urination": {"Urinary symptoms"},
    "pee": {"Urinary symptoms"},
    "back": {"Bone, joint, muscle, or limb symptoms", "Urinary symptoms"},
    "leg": {"Bone, joint, muscle, or limb symptoms"},
    "arm": {"Bone, joint, muscle, or limb symptoms"},
    "skin": {"Skin, rash, wound, or lump symptoms"},
    "rash": {"Skin, rash, wound, or lump symptoms", "Fever / General unwellness / Flu-like symptoms"},
}

# ----------------------------
# Utility functions
# ----------------------------
def normalize_text(value: str) -> str:
    value = str(value or "").strip().lower()
    value = (value.replace("’", "'")
                  .replace("‘", "'")
                  .replace("“", '"')
                  .replace("”", '"')
                  .replace("–", "-")
                  .replace("—", "-"))
    value = re.sub(r"[\u00A0\s]+", " ", value)
    return value


def normalize_compact(value: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(value)).strip()


def choose_override(override_value, base_value):
    return base_value if is_blankish(override_value) else override_value


def remove_redundant_recommendation(narrative: str, recommendation: str) -> tuple[str, str]:
    narrative = str(narrative or "").strip()
    recommendation = str(recommendation or "").strip()
    if not narrative or not recommendation:
        return narrative, recommendation

    n_comp = normalize_compact(narrative)
    r_comp = normalize_compact(recommendation)

    if r_comp and r_comp in n_comp:
        return narrative, ""

    if n_comp and n_comp in r_comp:
        return narrative, ""

    return narrative, recommendation




def is_blankish(value) -> bool:
    if value is None:
        return True
    try:
        import pandas as _pd
        if _pd.isna(value):
            return True
    except Exception:
        pass
    s = str(value).strip().lower()
    return s in {"", "nan", "none", "null"}

def tokenize(value: str) -> List[str]:
    return [tok for tok in re.findall(r"[a-zA-Z]{3,}", normalize_text(value)) if tok not in STOPWORDS]


def stem(word: str) -> str:
    w = normalize_text(word)
    for suf in ("ness", "ions", "ion", "ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    if w.endswith("y") and len(w) > 4:
        w = w[:-1] + "i"
    return w


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def split_csvish(value: str) -> List[str]:
    return [part.strip() for part in re.split(r"[;,]\s*", str(value or "")) if part.strip()]


def log_failure(record: dict) -> None:
    exists = os.path.isfile(LOG_PATH)
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(record.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(record)


def severity_label(level_num: int) -> str:
    return {1: "Low", 2: "Moderate", 3: "High", 4: "Emergency"}.get(level_num, "Moderate")


def confidence_rank(label: str) -> int:
    return CONFIDENCE_TEXT_TO_NUM.get(normalize_text(label), 0)


def load_logo():
    if Image and os.path.isfile(LOGO_PATH):
        return Image.open(LOGO_PATH)
    return None
def get_request_cookies() -> Dict[str, str]:
    ctx = getattr(st, "context", None)
    cookies = getattr(ctx, "cookies", {}) if ctx is not None else {}
    try:
        return dict(cookies)
    except Exception:
        try:
            return cookies.to_dict()
        except Exception:
            return {}


def set_cookie_js(name: str, value: str, days: int = 365) -> None:
    safe_name = urllib.parse.quote(name, safe="")
    safe_value = urllib.parse.quote(value, safe="")
    max_age = int(days) * 86400
    components.html(
        f"""
        <script>
        document.cookie = "{safe_name}={safe_value}; path=/; max-age={max_age}; SameSite=Lax";
        </script>
        """,
        height=0,
        width=0,
    )


def get_cookie_pref() -> str:
    if st.session_state.get("cookie_pref"):
        return st.session_state["cookie_pref"]
    cookies = get_request_cookies()
    pref = urllib.parse.unquote(cookies.get(COOKIE_CONSENT_NAME, "") or "")
    if pref:
        st.session_state["cookie_pref"] = pref
    return pref


def set_cookie_pref(pref: str) -> None:
    st.session_state["cookie_pref"] = pref
    set_cookie_js(COOKIE_CONSENT_NAME, pref, days=365)


def get_or_create_device_id() -> str:
    if st.session_state.get("device_id"):
        return st.session_state["device_id"]

    cookies = get_request_cookies()
    device_id = urllib.parse.unquote(cookies.get(DEVICE_COOKIE_NAME, "") or "")

    if not device_id:
        device_id = str(uuid4())
        st.session_state["device_id"] = device_id
        if get_cookie_pref() in {"necessary", "optional"}:
            set_cookie_js(DEVICE_COOKIE_NAME, device_id, days=365)
    else:
        st.session_state["device_id"] = device_id

    return device_id


def get_repeat_user_cookie() -> str:
    if st.session_state.get("repeat_user_id"):
        return st.session_state["repeat_user_id"]

    cookies = get_request_cookies()
    user_id = urllib.parse.unquote(cookies.get(USER_COOKIE_NAME, "") or "")
    if user_id:
        st.session_state["repeat_user_id"] = user_id
    return user_id


def set_repeat_user_cookie(user_id: str) -> None:
    st.session_state["repeat_user_id"] = user_id
    if get_cookie_pref() == "optional":
        set_cookie_js(USER_COOKIE_NAME, user_id, days=365)


def get_leads_df() -> pd.DataFrame:
    if not os.path.isfile(LEADS_LOG_PATH):
        return pd.DataFrame()
    try:
        return pd.read_csv(LEADS_LOG_PATH)
    except Exception:
        return pd.DataFrame()


def find_repeat_user_record() -> dict | None:
    if get_cookie_pref() != "optional":
        return None

    user_id = get_repeat_user_cookie()
    if not user_id:
        return None

    leads = get_leads_df()
    if leads.empty or "user_id" not in leads.columns:
        return None

    matched = leads[leads["user_id"].astype(str) == str(user_id)]
    if matched.empty:
        return None

    row = matched.sort_values("timestamp", ascending=False).iloc[0]
    return row.to_dict()

# ----------------------------
# Data loading and adaptation
# ----------------------------
@st.cache_data(ttl=60)
def load_freetext_map(workbook_path: str, legacy_workbook_path: str) -> Dict[str, str]:
    def _read(path: str) -> Dict[str, str]:
        if not os.path.isfile(path):
            return {}
        try:
            df_map = pd.read_excel(path, sheet_name="FreeTextMap")
            df_map.columns = [str(c).strip().lower() for c in df_map.columns]
            if not {"from_phrase", "to_phrase"}.issubset(df_map.columns):
                return {}
            out = {}
            for _, row in df_map.iterrows():
                src = normalize_text(row["from_phrase"])
                dst = normalize_text(row["to_phrase"])
                if src and dst and src != "nan" and dst != "nan":
                    out[src] = dst
            return out
        except Exception:
            return {}

    current = _read(workbook_path)
    if current:
        return current
    return _read(legacy_workbook_path)


def normalize_free_text(raw: str, ft_map: Dict[str, str]) -> str:
    text = normalize_text(raw)
    text = text.replace("heatbeat", "heartbeat")
    for src in sorted(ft_map.keys(), key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", ft_map[src], text)
    text = text.replace("side effects", "side_effects")
    return text


@st.cache_data(ttl=60)
def load_runtime_data(workbook_path: str, legacy_workbook_path: str) -> Dict[str, pd.DataFrame]:
    if not os.path.isfile(workbook_path):
        raise FileNotFoundError(f"Workbook not found: {workbook_path}")

    taxonomy = pd.read_excel(workbook_path, sheet_name="Taxonomy")
    sublogic = pd.read_excel(workbook_path, sheet_name="Subcategory Logic")
    conditions = pd.read_excel(workbook_path, sheet_name="Condition Rows")

    for df in (taxonomy, sublogic, conditions):
        df.columns = [str(c).strip() for c in df.columns]

    runtime = conditions.merge(
        sublogic,
        on=["SubcategoryCode", "PrimaryCategoryName", "SubcategoryName"],
        how="left",
        suffixes=("", "_logic"),
    )

    runtime["Primary Category"] = runtime["PrimaryCategoryName"]
    runtime["SubCategory"] = runtime["SubcategoryName"]
    runtime["Symptoms"] = runtime["CoreSymptoms"].fillna("")
    runtime["Clarifying Questions 1"] = runtime.get("CQ1_Text", runtime.get("CQ1_Confirm", "")).fillna("")
    runtime["Clarifying Questions2"] = runtime.get("CQ2_Text", runtime.get("CQ2_Discriminator", "")).fillna("")
    runtime["Clarifying Questions 3"] = runtime.get("CQ3_Text", runtime.get("CQ3_Discriminator", "")).fillna("")
    runtime["Clarifying Questions 4"] = runtime.get("CQ4_Text", "").fillna("")
    runtime["Clarifying Questions 5"] = runtime.get("CQ5_Text", "").fillna("")
    runtime["CQ1_ResponseType"] = runtime.get("CQ1_ResponseType", "").fillna("")
    runtime["CQ1_Options"] = runtime.get("CQ1_Options", "").fillna("")
    runtime["CQ2_ResponseType"] = runtime.get("CQ2_ResponseType", "").fillna("")
    runtime["CQ2_Options"] = runtime.get("CQ2_Options", "").fillna("")
    runtime["CQ3_ResponseType"] = runtime.get("CQ3_ResponseType", "").fillna("")
    runtime["CQ3_Options"] = runtime.get("CQ3_Options", "").fillna("")
    runtime["CQ4_ResponseType"] = runtime.get("CQ4_ResponseType", "").fillna("")
    runtime["CQ4_Options"] = runtime.get("CQ4_Options", "").fillna("")
    runtime["CQ5_ResponseType"] = runtime.get("CQ5_ResponseType", "").fillna("")
    runtime["CQ5_Options"] = runtime.get("CQ5_Options", "").fillna("")
    runtime["EffectiveRedFlagQuestions"] = runtime.apply(
        lambda r: choose_override(r.get("RedFlagOverride", ""), r.get("RedFlagQuestions", "")),
        axis=1,
    )
    runtime["EffectiveRiskModifierQuestions"] = runtime.apply(
        lambda r: choose_override(r.get("RiskModifierOverride", ""), r.get("RiskModifierQuestions", "")),
        axis=1,
    )
    runtime["RiskFlags"] = runtime["EffectiveRedFlagQuestions"].fillna("")
    runtime["RiskModifierQuestions"] = runtime["EffectiveRiskModifierQuestions"].fillna("")
    runtime["Labeling Confidence"] = runtime["LabelingConfidence"].fillna("Medium")
    runtime["Labeling Rule"] = runtime["ConditionSpecificRule"].fillna("")
    runtime["Default Narrative Template"] = runtime["DefaultNarrativeTemplate"].fillna("")
    runtime["Escalated Narrative Template (Risk Flags Present)"] = runtime["EscalatedNarrativeTemplate"].fillna("")
    runtime["Emergency (Time-critical) Narrative (If Applicable)"] = runtime["EmergencyNarrative"].fillna("")
    runtime["Default Recommendation"] = runtime["DefaultRecommendation"].fillna("")
    runtime["Escalated Recommendation"] = runtime["EscalatedRecommendation"].fillna("")
    runtime["Referral"] = runtime.get("Referral", "").fillna("")

    runtime["Acuity Level"] = runtime["BaseAcuityLevel"].map(
        lambda x: ACUITY_TEXT_TO_NUM.get(normalize_text(x), 2)
    ).astype(int)

    # Normalize eligibility fields.
    runtime["PopulationGroup"] = runtime.get("PopulationGroup", "General").fillna("General")
    runtime["PopulationEligibility"] = runtime.get("PopulationEligibility", runtime["PopulationGroup"]).fillna("General")
    runtime["SexEligibility"] = runtime.get("SexEligibility", "Both").fillna("Both")
    for col in ["UsesCQ1", "UsesCQ2", "UsesCQ3", "UsesCQ4", "UsesCQ5"]:
        runtime[col] = runtime.get(col, "Yes").fillna("Yes")
    runtime["Condition"] = runtime["Condition"].fillna("").astype(str)

    # Try to attach FreeTextMap presence info for debugging.
    ft_map = load_freetext_map(workbook_path, legacy_workbook_path)
    free_text_map_df = pd.DataFrame(
        [{"from_phrase": k, "to_phrase": v} for k, v in ft_map.items()]
    ) if ft_map else pd.DataFrame(columns=["from_phrase", "to_phrase"])

    # Optional Version 10 anchor-gate policy sheet.
    try:
        anchor_policy = pd.read_excel(workbook_path, sheet_name="Anchor Gate Policy")
        anchor_policy.columns = [str(c).strip() for c in anchor_policy.columns]
    except Exception:
        anchor_policy = pd.DataFrame(
            columns=[
                "PolicyKey", "ConditionContains", "AppliesToPopulation", "AnchorQuestion",
                "PositiveAnswers", "FallbackTitle", "FallbackAdvice", "Priority", "Notes"
            ]
        )

    return {
        "taxonomy": taxonomy,
        "sublogic": sublogic,
        "conditions": conditions,
        "runtime": runtime,
        "freetext_map": free_text_map_df,
        "anchor_policy": anchor_policy,
    }


DATA = load_runtime_data(WORKBOOK_PATH, LEGACY_WORKBOOK_PATH)
db = DATA["runtime"]
taxonomy_df = DATA["taxonomy"]
sublogic_df = DATA["sublogic"]
logo = load_logo()
FT_MAP = load_freetext_map(WORKBOOK_PATH, LEGACY_WORKBOOK_PATH)
ANCHOR_POLICY_DF = DATA.get("anchor_policy", pd.DataFrame())


# ----------------------------
# Session defaults
# ----------------------------


st.markdown("""
<style>
.report-block {
  background-color: #f8d7da;
  border: 1px solid #f5c6cb;
  border-radius: 10px;
  padding: 16px;
  font-size: 1rem;
  line-height: 1.6;
  color: #2b0000;
  word-wrap: break-word;
  overflow-wrap: anywhere;
}
.report-block--ok {
  background-color: #d4edda;
  border-color: #c3e6cb;
  color: #062b0a;
}
.report-block--warn {
  background-color: #fff3cd;
  border: 1px solid #ffeeba;
  color: #3a2e00;
}
.emergency-block {
  margin-top: 16px;
  padding: 14px;
  background-color: #f8d7da;
  border: 1px solid #f5c6cb;
  border-radius: 10px;
  font-weight: 600;
  font-size: 1rem;
  line-height: 1.6;
  color: #2b0000;
}
.referral-block {
  margin-top: 10px;
  padding: 12px 14px;
  background-color: #eef6ff;
  border: 1px solid #cfe2ff;
  border-radius: 10px;
  color: #083b6b;
}
.free-text-cta {
  margin: 12px 0 16px 0;
  padding: 14px 16px;
  background-color: #f7fbff;
  border: 1px solid #cfe2ff;
  border-radius: 12px;
  color: #083b6b;
  line-height: 1.45;
}
.free-text-cta strong {
  font-size: 1.03rem;
}
.category-section-title {
  margin-top: 12px;
  margin-bottom: 8px;
  font-weight: 700;
}
.stButton > button {
  width: 100% !important;
  min-height: 44px;
  white-space: normal !important;
  overflow-wrap: break-word !important;
  word-break: normal !important;
  text-align: center !important;
  line-height: 1.25 !important;
  padding: 8px 14px !important;
}
@media (max-width: 640px) {
  .report-block, .emergency-block {
    font-size: 1.05rem;
    line-height: 1.7;
    padding: 18px;
  }
  .stButton > button {
    width: 100% !important;
    min-height: 44px;
    padding: 9px 12px !important;
  }
}
</style>
""", unsafe_allow_html=True)

DEFAULT_STATE = {
    "page": "welcome",
    "free_input_mode": False,
    "user_data": {},
    "current_condition": None,
    "matched_conditions": pd.DataFrame(),
    "confirmed_risks": [],
    "confirmed_red_flags": [],
    "confirmed_risk_modifiers": [],
    "confirm_stage_done": False,
    "clarifying_answers": {},
    "admin_authed": False,
    "lead_captured": False,
    "lead_record": {},
    "device_id": "",
    "result_reveal_logged": False,
    "current_reveal_id": "",
    "cookie_pref": "",
    "repeat_user_id": "",
    "pending_anchor_gate": None,
    "anchor_fallback": None,
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value



# ----------------------------
# Filtering helpers
# ----------------------------
def population_group_for_age(age: int) -> str:
    return "Pediatric" if age is not None and age <= 14 else "General"


def normalize_choice(value: str) -> str:
    return normalize_text(value).replace(" ", "").replace("-", "")


def row_allowed_for_population(row: pd.Series, age: int | None) -> bool:
    if age is None:
        return True
    elig = normalize_text(row.get("PopulationEligibility", row.get("PopulationGroup", "General")))
    if age <= 14:
        return elig in {"pediatric", "both"}
    return elig in {"general", "both", ""}


def is_gender_allowed(row: pd.Series, gender: str | None) -> bool:
    if not gender:
        return True
    elig = normalize_text(row.get("SexEligibility", "Both"))
    if gender == "Male":
        if elig == "female":
            return False
        return True
    if gender == "Female":
        if elig == "male":
            return False
        return True
    text = " ".join([
        str(row.get("Primary Category", "")),
        str(row.get("SubCategory", "")),
        str(row.get("Condition", "")),
        str(row.get("Symptoms", "")),
    ]).lower()
    block_terms = GENDER_BLOCK_TERMS.get(gender, ())
    return not any(term in text for term in block_terms)


def pediatric_category_allowed(row: pd.Series, age: int | None) -> bool:
    if age is None or age > 14:
        return True
    primary = normalize_text(row.get("Primary Category", ""))
    return primary not in {"women's health", "womens health", "men's health", "mens health"}


def pediatric_condition_allowed(row: pd.Series, age: int | None) -> bool:
    if age is None or age > 14:
        return True
    combined = " ".join([
        str(row.get("Condition", "")),
        str(row.get("SubCategory", "")),
        str(row.get("Symptoms", "")),
    ]).lower()
    blocked_terms = ("sti-related", "sexually transmitted", "sexual health", "sexual contact")
    return not any(term in combined for term in blocked_terms)


def filter_rows(df: pd.DataFrame, age: int | None, gender: str | None) -> pd.DataFrame:
    out = df.copy()
    out = out[out.apply(lambda r: row_allowed_for_population(r, age), axis=1)]
    out = out[out.apply(lambda r: pediatric_category_allowed(r, age), axis=1)]
    out = out[out.apply(lambda r: pediatric_condition_allowed(r, age), axis=1)]
    out = out[out.apply(lambda r: is_gender_allowed(r, gender), axis=1)]
    return out


def available_primary_categories(age: int | None, gender: str | None, source_df: pd.DataFrame | None = None) -> List[str]:
    source = db if source_df is None else source_df
    filtered = filter_rows(source, age, gender)
    return sorted(filtered["Primary Category"].dropna().astype(str).unique().tolist())


def available_subcategories(primary: str, age: int | None, gender: str | None, source_df: pd.DataFrame | None = None) -> List[str]:
    source = db if source_df is None else source_df
    filtered = filter_rows(source, age, gender)
    filtered = filtered[filtered["Primary Category"] == primary]
    return sorted(filtered["SubCategory"].dropna().astype(str).unique().tolist())


# ----------------------------
# Matching and ranking
# ----------------------------
def symptom_tokens_from_row(row: pd.Series) -> Set[str]:
    tokens = set()
    for field in ("Symptoms", "Condition", "SubCategory", "Primary Category"):
        for tok in tokenize(row.get(field, "")):
            tokens.add(tok)
            tokens.add(stem(tok))
    return tokens


def split_anchor_groups(value: str) -> List[str]:
    """Split database anchor text into small matchable groups.

    The Version 6 workbook stores anchors as human-readable prose such as:
    "known sickle cell disease/HbSS/HbSC/Hb genotype history OR previous similar pain crisis".
    This helper converts commas/semicolons/pipes/new lines and explicit ORs into candidate groups.
    """
    if is_blankish(value):
        return []
    raw = str(value).replace("\n", ";").replace("|", ";")
    parts: List[str] = []
    for chunk in re.split(r"[;,]", raw):
        chunk = chunk.strip()
        if not chunk:
            continue
        for sub in re.split(r"\s+OR\s+|\s+or\s+|/", chunk):
            sub = sub.strip(" .:;,-")
            if sub:
                parts.append(sub)
    return parts


ANCHOR_STOPWORDS = STOPWORDS | GENERIC_TOKENS | {
    "known", "history", "previous", "possible", "suspected", "actual", "credible",
    "clinical", "clinician", "review", "testing", "test", "confirmed", "requires",
    "require", "surface", "only", "when", "with", "plus", "present", "pattern",
    "symptoms", "symptom", "features", "signs", "risk", "context", "relevant",
    "persistent", "severe", "strong", "likely", "illness", "disease", "condition",
    "lower", "upper", "back", "yellow", "dark", "urine", "eyes", "eye", "body",
    "limb", "limbs", "chest", "recurrent", "similar", "crisislike",
}


def meaningful_anchor_tokens(text: str) -> Set[str]:
    toks = set()
    for tok in re.findall(r"[a-zA-Z0-9]{2,}", normalize_text(text)):
        if tok in ANCHOR_STOPWORDS:
            continue
        toks.add(tok)
        toks.add(stem(tok))
    return toks


def answer_is_positive_or_specific(meta: dict) -> bool:
    """Return True only when the user's answer provides positive/specific evidence.

    Important: question text alone must not count as evidence. For example, the
    question "Have you been diagnosed with sickle cell?" should not add "sickle"
    to the evidence when the user answers No.
    """
    if not isinstance(meta, dict):
        return False

    value = meta.get("value", "")
    rtype = normalize_text(meta.get("response_type", ""))
    if isinstance(value, list):
        value_text = " ".join([str(v) for v in value])
    else:
        value_text = str(value or "")

    v = normalize_text(value_text)
    if not v:
        return False

    negative_values = {
        "no", "none", "not sure", "unsure", "unknown", "neither/not sure",
        "other/unknown", "prefer not to say", "nil", "n/a"
    }
    if v in negative_values:
        return False

    if rtype == "yes_no":
        return v == "yes"

    return True


def build_evidence_text(selected_symptoms: List[str], cq_answers: Dict[str, dict],
                        red_flags: List[str], risk_modifiers: List[str]) -> str:
    user = st.session_state.get("user_data", {}) or {}
    evidence_parts: List[str] = []
    evidence_parts.extend([str(x) for x in selected_symptoms or []])
    evidence_parts.extend([str(x) for x in red_flags or []])
    evidence_parts.extend([str(x) for x in risk_modifiers or []])
    evidence_parts.append(str(user.get("conditions", "")))
    evidence_parts.append(str(user.get("free_symptoms", "")))

    # Include anchor-gate answers only when explicitly positive/specific.
    anchor_answers = user.get("anchor_answers", {}) or {}
    if isinstance(anchor_answers, dict):
        evidence_parts.extend([str(v) for v in anchor_answers.values() if str(v).strip()])

    # Include only user answers, not CQ question text unless the answer is positive/specific.
    for meta in (cq_answers or {}).values():
        if not isinstance(meta, dict):
            continue
        value = meta.get("value", "")
        if isinstance(value, list):
            value_text = " ".join([str(v) for v in value])
        else:
            value_text = str(value or "")

        if answer_is_positive_or_specific(meta):
            evidence_parts.append(value_text)
            # Add question text only when the answer is positive/specific, because then
            # the question context is evidence-bearing.
            evidence_parts.append(str(meta.get("text", "")))

    return normalize_text(" ; ".join([p for p in evidence_parts if str(p).strip()]))


def anchor_group_matches(group: str, evidence_text: str) -> bool:
    group_norm = normalize_text(group)
    if not group_norm or not evidence_text:
        return False

    # Direct phrase match first.
    if exact_phrase_in_text(group_norm, evidence_text):
        return True

    # Stricter token fallback for non-policy strict rows only.
    # One generic overlapping token must not unlock a high-risk condition.
    anchor_tokens = meaningful_anchor_tokens(group_norm)
    if not anchor_tokens:
        return False

    evidence_tokens = meaningful_anchor_tokens(evidence_text)
    overlap = anchor_tokens & evidence_tokens

    # Require at least two specific matching tokens for multi-token anchors.
    if len(anchor_tokens) >= 2:
        return len(overlap) >= 2

    # For one-token anchors, require a distinctive token, not short/generic words.
    only = next(iter(anchor_tokens))
    return len(only) >= 5 and only in evidence_tokens


def count_anchor_matches(anchor_text: str, evidence_text: str) -> int:
    groups = split_anchor_groups(anchor_text)
    return sum(1 for group in groups if anchor_group_matches(group, evidence_text))


def strict_match_required(row: pd.Series) -> bool:
    value = normalize_text(row.get("StrictMatchRequired", ""))
    return value in {"yes", "true", "1", "required", "strict"}


def strict_match_passes(row: pd.Series, selected_symptoms: List[str], cq_answers: Dict[str, dict],
                        red_flags: List[str], risk_modifiers: List[str]) -> Tuple[bool, str]:
    """Return whether a Version 6 strict-match condition is allowed to rank.

    For strict rows, the condition should only surface if the user's selected symptoms/CQs/
    red flags/risk modifiers/free-text/existing conditions contain the required anchors.
    """
    if not strict_match_required(row):
        return True, "not_strict"

    evidence_text = build_evidence_text(selected_symptoms, cq_answers, red_flags, risk_modifiers)

    # If an Anchor Gate Policy exists for this condition, use its exact/specific
    # PositiveAnswers as the hard gate. Do not fall back to broad token overlap.
    policy = get_anchor_policy_for_row(row)
    if policy:
        if policy_anchor_passes(policy, evidence_text):
            return True, "anchor_policy_pass"
        return False, "missing_anchor_policy_confirmation"

    symptom_required = str(row.get("RequiredSymptomAnchors", "") or "")
    context_required = str(row.get("RequiredContextAnchors", "") or "")

    symptom_groups = split_anchor_groups(symptom_required)
    context_groups = split_anchor_groups(context_required)
    symptom_hits = count_anchor_matches(symptom_required, evidence_text)
    context_hits = count_anchor_matches(context_required, evidence_text)

    # If a strict row defines symptom anchors, at least one must be present.
    if symptom_groups and symptom_hits == 0:
        return False, "missing_required_symptom_anchor"

    # If a strict row defines context anchors, at least one must be present.
    # This is what prevents loosely calling conditions such as sickle-cell disease,
    # toxic exposure, rabies-risk exposure, cancer warning signs, etc.
    if context_groups and context_hits == 0:
        return False, "missing_required_context_anchor"

    return True, "strict_pass"



def policy_terms_match(condition_text: str, contains_value: str) -> bool:
    condition_text = normalize_text(condition_text)
    if not condition_text or is_blankish(contains_value):
        return False
    terms = [t.strip() for t in re.split(r"[|,;]", str(contains_value)) if t.strip()]
    for term in terms:
        term_norm = normalize_text(term)
        if term_norm and term_norm in condition_text:
            return True
    return False


def split_policy_positive_terms(policy: dict) -> List[str]:
    """Return exact/specific anchor terms from Anchor Gate Policy.PositiveAnswers.

    We intentionally ignore generic confirmation words like "yes" so that ordinary
    symptom words or a yes/no answer from another CQ cannot unlock a hard-gated
    condition. For example, lower back pain + tiredness must not unlock Sickle Cell.
    """
    raw = str((policy or {}).get("PositiveAnswers", "") or "")
    terms: List[str] = []
    for term in re.split(r"[|;,]", raw):
        t = normalize_text(term).strip()
        if not t:
            continue
        if t in {"yes", "y", "true", "diagnosed", "known", "previous", "history", "not sure", "no"}:
            continue
        # Ignore very short generic tokens except genotype abbreviations.
        if len(t) < 3 and t not in {"ss", "sc"}:
            continue
        terms.append(t)
    # Longest first makes phrase matching deterministic and easier to debug.
    return sorted(set(terms), key=len, reverse=True)


def exact_phrase_in_text(phrase: str, evidence_text: str) -> bool:
    phrase = normalize_text(phrase)
    evidence_text = normalize_text(evidence_text)
    if not phrase or not evidence_text:
        return False
    # Exact substring with word-ish boundaries. This prevents "sc" matching inside "muscle".
    pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
    return re.search(pattern, evidence_text) is not None


def policy_anchor_passes(policy: dict, evidence_text: str) -> bool:
    """Hard gate pass based only on exact/specific policy terms.

    This is deliberately stricter than general token overlap. It prevents serious
    conditions from being unlocked by common symptoms such as pain, tiredness, fever,
    cough, weakness, back pain, dark urine, or yellow eyes.
    """
    for term in split_policy_positive_terms(policy):
        if exact_phrase_in_text(term, evidence_text):
            return True
    return False


def get_anchor_policy_for_row(row: pd.Series) -> dict | None:
    """Return the first matching anchor-gate policy row for a condition."""
    if ANCHOR_POLICY_DF is None or ANCHOR_POLICY_DF.empty:
        return None

    condition_text = " ".join([
        str(row.get("Condition", "")),
        str(row.get("ConditionSpecificRule", "")),
        str(row.get("MinimumEvidenceRule", "")),
        str(row.get("RequiredContextAnchors", "")),
    ])
    population = normalize_text(row.get("PopulationGroup", ""))

    policy_df = ANCHOR_POLICY_DF.copy()
    if "Priority" in policy_df.columns:
        try:
            policy_df["__priority"] = pd.to_numeric(policy_df["Priority"], errors="coerce").fillna(9999)
            policy_df = policy_df.sort_values("__priority")
        except Exception:
            pass

    for _, policy in policy_df.iterrows():
        applies = normalize_text(policy.get("AppliesToPopulation", "both"))
        if applies and applies not in {"both", "all", population}:
            continue
        if policy_terms_match(condition_text, str(policy.get("ConditionContains", ""))):
            return policy.to_dict()
    return None


def find_pending_anchor_gate_candidate(subset: pd.DataFrame, selected_symptoms: List[str],
                                       cq_answers: Dict[str, dict], red_flags: List[str],
                                       risk_modifiers: List[str]) -> dict | None:
    """Find the best strict-gated candidate that was blocked and can be clarified by an anchor question."""
    candidates = []
    for _, row in subset.iterrows():
        if not strict_match_required(row):
            continue

        policy = get_anchor_policy_for_row(row)
        if not policy:
            continue

        strict_ok, strict_reason = strict_match_passes(row, selected_symptoms, cq_answers, red_flags, risk_modifiers)
        if strict_ok:
            continue

        base_score = compute_condition_score(
            row,
            selected_symptoms,
            cq_answers,
            red_flags,
            risk_modifiers,
            enforce_strict=False,
        )
        if base_score <= 0:
            continue

        candidates.append({
            "base_score": float(base_score),
            "acuity": int(row.get("Acuity Level", 2) or 2),
            "condition_row": row.to_dict(),
            "policy": policy,
            "strict_reason": strict_reason,
        })

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x["base_score"], x["acuity"]), reverse=True)
    return candidates[0]


def proceed_after_condition_selected() -> None:
    """Send user to the same next step after a condition has been selected."""
    st.session_state.result_reveal_logged = False
    st.session_state.current_reveal_id = str(uuid4())

    repeat_record = find_repeat_user_record()

    if session_limit_reached():
        st.session_state.page = "usage_limit"
    elif repeat_record:
        st.session_state["lead_captured"] = True
        st.session_state["lead_record"] = repeat_record
        st.session_state.page = "results"
    elif st.session_state.get("lead_captured"):
        st.session_state.page = "results"
    else:
        st.session_state.page = "lead_capture"


def category_hints_from_input(text: str) -> Set[str]:
    toks = set(tokenize(text))
    hints = set()
    for tok in toks:
        hints |= BODY_PART_HINTS.get(tok, set())
        hints |= BODY_PART_HINTS.get(stem(tok), set())
    return hints


def extract_anchor_tokens(text: str) -> Set[str]:
    toks = set(tokenize(text))
    anchors = set()
    for tok in toks:
        if tok in BODY_PART_HINTS or stem(tok) in BODY_PART_HINTS:
            anchors.add(tok)
    return anchors


def rank_free_text_categories(query: str, source_df: pd.DataFrame, age: int | None, gender: str | None) -> Tuple[List[str], pd.DataFrame]:
    clean = normalize_free_text(query, FT_MAP)
    toks = set(tokenize(clean))
    if not toks:
        return [], source_df.iloc[0:0]

    filtered = filter_rows(source_df, age, gender).copy()
    if filtered.empty:
        return [], filtered

    cat_hints = category_hints_from_input(clean)
    anchor_tokens = extract_anchor_tokens(clean)
    if anchor_tokens and cat_hints:
        hinted = filtered[filtered["Primary Category"].isin(cat_hints)].copy()
        if not hinted.empty:
            filtered = hinted

    def _row_score(row: pd.Series) -> float:
        row_tokens = symptom_tokens_from_row(row)
        overlap = 0
        fuzzy = 0.0
        for tok in toks:
            if tok in row_tokens or stem(tok) in row_tokens:
                overlap += 1
            else:
                fuzzy = max(fuzzy, max((similarity(tok, rt) for rt in row_tokens), default=0.0))
        hint_bonus = 1.0 if str(row.get("Primary Category", "")) in cat_hints else 0.0
        generic_penalty = 0.25 if all(t in GENERIC_TOKENS for t in toks) else 0.0
        return overlap * 2.0 + fuzzy + hint_bonus - generic_penalty

    filtered["__score"] = filtered.apply(_row_score, axis=1)
    matched = filtered[filtered["__score"] > 0.75].copy()
    if matched.empty:
        return [], matched

    cat_scores = (
        matched.groupby("Primary Category")["__score"]
        .max()
        .sort_values(ascending=False)
    )
    ordered_categories = cat_scores.index.tolist()
    matched = matched.sort_values("__score", ascending=False).drop(columns="__score")
    return ordered_categories, matched



def compute_condition_score(row: pd.Series, selected_symptoms: List[str], cq_answers: Dict[str, str],
                            red_flags: List[str], risk_modifiers: List[str],
                            enforce_strict: bool = True) -> float:
    if enforce_strict:
        strict_ok, strict_reason = strict_match_passes(row, selected_symptoms, cq_answers, red_flags, risk_modifiers)
        if not strict_ok:
            # Keep strict high-risk/test-dependent labels from surfacing on loose symptom overlap.
            return 0.0
    else:
        strict_reason = "strict_bypassed_for_anchor_screening"

    row_symptoms = {normalize_text(x) for x in split_csvish(row.get("Symptoms", ""))}
    selected = {normalize_text(x) for x in selected_symptoms}
    symptom_overlap = sum(
        1 for sym in selected
        if sym in row_symptoms or any(similarity(sym, rs) >= 0.72 for rs in row_symptoms)
    )

    support = 0.0
    for n, weight in [(1, 1.5), (2, 1.0), (3, 0.75), (4, 0.6), (5, 0.5)]:
        if normalize_text(row.get(f"UsesCQ{n}", "No")) != "yes":
            continue
        q_key = f"cq{n}"
        q_meta = cq_answers.get(q_key, {})
        answer_value = normalize_text(q_meta.get("value", ""))
        rtype = normalize_text(q_meta.get("response_type", ""))
        if not answer_value:
            continue
        if rtype == "yes_no":
            if answer_value == "yes":
                support += weight
        elif rtype == "single_select":
            if answer_value not in {"not sure", "neither/not sure", "other/unknown", "unknown"}:
                support += weight * 0.35

    confidence = confidence_rank(row.get("Labeling Confidence", "Medium"))
    acuity = int(row.get("Acuity Level", 2) or 2)

    red_flag_terms = {normalize_text(x) for x in split_csvish(row.get("RiskFlags", ""))}
    risk_modifier_terms = {normalize_text(x) for x in split_csvish(row.get("RiskModifierQuestions", ""))}
    chosen_red = {normalize_text(x) for x in red_flags}
    chosen_mod = {normalize_text(x) for x in risk_modifiers}
    red_flag_bonus = 0.6 if (chosen_red and red_flag_terms) else 0.0
    risk_modifier_bonus = 0.3 if (chosen_mod and risk_modifier_terms) else 0.0

    strict_bonus = 0.4 if strict_reason in {"strict_pass", "anchor_policy_pass"} else 0.0

    return symptom_overlap * 2.5 + support + confidence * 0.75 + acuity * 0.3 + red_flag_bonus + risk_modifier_bonus + strict_bonus


# ----------------------------
# Recommendation rendering
# ----------------------------
def render_template(value: str, condition: pd.Series, risk_flags: List[str]) -> str:
    if not value:
        return ""
    certainty = "very likely" if confidence_rank(condition.get("Labeling Confidence", "Medium")) >= 2 else "symptoms suggest"
    try:
        return str(value).format(
            certainty=certainty,
            risk_flags=", ".join(risk_flags),
            default_rec=condition.get("Default Recommendation", ""),
            escalated_rec=condition.get("Escalated Recommendation", ""),
        )
    except Exception:
        return str(value)


def build_recommendation(condition: pd.Series, red_flags: List[str], risk_modifiers: List[str]) -> Dict[str, str]:
    acuity = int(condition.get("Acuity Level", 2) or 2)
    escalated = bool(red_flags) or acuity >= 3

    narrative_key = (
        "Escalated Narrative Template (Risk Flags Present)"
        if escalated else
        "Default Narrative Template"
    )
    recommendation_key = "Escalated Recommendation" if escalated else "Default Recommendation"

    narrative = render_template(condition.get(narrative_key, ""), condition, red_flags)
    recommendation = render_template(condition.get(recommendation_key, ""), condition, red_flags)
    narrative, recommendation = remove_redundant_recommendation(narrative, recommendation)
    emergency = str(condition.get("Emergency (Time-critical) Narrative (If Applicable)", "") or "").strip()
    referral = str(condition.get("Referral", "") or "").strip()

    return {
        "narrative": narrative,
        "recommendation": recommendation,
        "emergency": emergency if acuity >= 4 or red_flags else emergency,
        "referral": referral,
        "escalated": escalated,
    }


def generate_report_text() -> str:
    condition = st.session_state.get("current_condition")
    user = st.session_state.get("user_data", {})
    risk_flags = st.session_state.get("confirmed_red_flags", [])
    risk_modifiers = st.session_state.get("confirmed_risk_modifiers", [])
    if condition is None:
        return "No report available."
    rec = build_recommendation(condition, risk_flags, risk_modifiers)
    return f"""LEXY SYMPTOM CHECKER REPORT
===========================

Patient Details
- Age: {user.get("age", "N/A")}
- Gender: {user.get("gender", "N/A")}
- Existing conditions: {user.get("conditions", "N/A")}

Assessment
- Likely condition: {condition.get("Condition", "N/A")}
- Primary category: {condition.get("Primary Category", "N/A")}
- Subcategory: {condition.get("SubCategory", "N/A")}
- Baseline acuity: {severity_label(int(condition.get("Acuity Level", 2) or 2))}

Safety/context
- Red flags selected: {", ".join(risk_flags) if risk_flags else "None"}
- Risk modifiers selected: {", ".join(risk_modifiers) if risk_modifiers else "None"}

Narrative
{rec["narrative"]}

Recommendation
{rec["recommendation"]}

Emergency note
{rec["emergency"] or "None"}

Referral
{rec["referral"] or "None"}
"""


# ----------------------------
# UI helpers
# ----------------------------
def show_logo(width: int = 80):
    if logo is not None:
        st.image(logo, width=width)


def display_grid(items: List[str], cols: int = 2, key_prefix: str = "grid") -> str | None:
    rows = [items[i:i + cols] for i in range(0, len(items), cols)]
    for r_idx, row in enumerate(rows):
        columns = st.columns(len(row))
        for c_idx, (col, item) in enumerate(zip(columns, row)):
            with col:
                if st.button(item, key=f"{key_prefix}_{r_idx}_{c_idx}", use_container_width=True):
                    return item
    return None


def show_no_match_ui():
    st.subheader("We couldn’t safely identify a strong match.")
    st.markdown("""
    <div class="report-block report-block--warn">
      Your symptoms still deserve attention. The system did not find a strong enough fit
      to safely prioritize one condition in this pathway.
    </div>
    """, unsafe_allow_html=True)
    st.markdown("""
    <div class="report-block">
      Go to urgent care now if you have chest pain, severe breathing difficulty,
      heavy bleeding, fainting, confusion, seizure, or rapidly worsening symptoms.
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.link_button("📅 Get help / schedule a consultation", url="https://lexconsult.carekonnect.net/", use_container_width=True)
    with col2:
        if st.button("🔄 Start Over", use_container_width=True):
            reset_for_new_session()


def reset_for_new_session():
    keep = {"admin_authed", "lead_captured", "lead_record", "device_id", "cookie_pref", "repeat_user_id"}
    for key in list(st.session_state.keys()):
        if key not in keep:
            del st.session_state[key]
    st.session_state.page = "welcome"
    st.session_state.free_input_mode = False
    st.session_state.user_data = {}
    st.session_state.current_condition = None
    st.session_state.matched_conditions = pd.DataFrame()
    st.session_state.confirmed_risks = []
    st.session_state.result_reveal_logged = False
    st.session_state.current_reveal_id = ""
    st.rerun()



def build_cq_definitions(primary: str, subcat: str) -> List[dict]:
    block = sublogic_df[
        (sublogic_df["PrimaryCategoryName"] == primary) &
        (sublogic_df["SubcategoryName"] == subcat)
    ]
    if block.empty:
        return []
    logic_row = block.iloc[0]
    items = []
    valid_types = {"yes_no", "single_select", "multi_select", "numeric", "free_text_short", "duration"}
    for n in range(1, 6):
        raw_text = logic_row.get(f"CQ{n}_Text", "")
        raw_type = logic_row.get(f"CQ{n}_ResponseType", "")
        raw_opts = logic_row.get(f"CQ{n}_Options", "")

        if is_blankish(raw_text) or is_blankish(raw_type):
            continue

        text = str(raw_text).strip()
        rtype = normalize_text(raw_type)
        if rtype not in valid_types:
            continue

        options = []
        if not is_blankish(raw_opts):
            options = [opt.strip() for opt in str(raw_opts).split("|") if opt.strip() and normalize_text(opt) != "nan"]

        if rtype in {"single_select", "multi_select"} and not options:
            continue

        items.append({
            "id": f"cq{n}",
            "number": n,
            "text": text,
            "response_type": rtype,
            "options": options,
        })
    return items


def rank_peers(primary: str, subcat: str, current_condition: str, age: int | None, gender: str | None,
               selected_symptoms: List[str], limit: int = 3) -> pd.DataFrame:
    peers = filter_rows(db, age, gender)
    peers = peers[(peers["Primary Category"] == primary) & (peers["SubCategory"] == subcat)]
    peers = peers[peers["Condition"].astype(str).str.strip() != str(current_condition).strip()]
    if peers.empty:
        return peers
    selected = {normalize_text(x) for x in selected_symptoms}
    def _peer_score(row: pd.Series) -> float:
        row_symptoms = {normalize_text(x) for x in split_csvish(row.get("Symptoms", ""))}
        overlap = sum(
            1 for sym in selected
            if sym in row_symptoms or any(similarity(sym, rs) >= 0.72 for rs in row_symptoms)
        )
        return overlap * 2.0 + confidence_rank(row.get("Labeling Confidence", "Medium")) + int(row.get("Acuity Level", 2) or 2) * 0.15
    peers = peers.copy()
    peers["__peer_score"] = peers.apply(_peer_score, axis=1)
    return peers.sort_values(["__peer_score", "Acuity Level"], ascending=[False, False]).head(limit)
# ----------------------------
# Pages
# ----------------------------


def analytics_page():
    if not st.session_state.get("admin_authed", False):
        st.warning("Admin access required.")
        if st.button("← Back"):
            st.session_state.page = "welcome"
            st.rerun()
        return

    st.header("📊 App Failure Report")
    if not os.path.isfile(LOG_PATH):
        st.info("No failures logged yet.")
        return

    df = pd.read_csv(LOG_PATH)
    if "timestamp" in df.columns:
        st.subheader("Recent Failures")
        st.dataframe(df.sort_values("timestamp", ascending=False).head(25), use_container_width=True)
    if "reason" in df.columns:
        st.subheader("Failures by Reason")
        counts = df["reason"].value_counts().reset_index()
        counts.columns = ["Reason", "Count"]
        st.table(counts)

    if st.button("← Back"):
        st.session_state.page = "welcome"
        st.rerun()

def leads_page():
    if not st.session_state.get("admin_authed", False):
        st.warning("Admin access required.")
        if st.button("← Back"):
            st.session_state.page = "welcome"
            st.rerun()
        return

    st.header("📥 Captured Leads")
    st.write("Reading leads from:", os.path.abspath(LEADS_LOG_PATH))
    st.write("File exists:", os.path.isfile(LEADS_LOG_PATH))
    if os.path.isfile(LEADS_LOG_PATH):
        st.write("File size:", os.path.getsize(LEADS_LOG_PATH))






    df = get_leads_export_df()
    if df.empty:
        st.info("No leads captured yet.")
    else:
        st.dataframe(df.sort_values("timestamp", ascending=False), use_container_width=True)

        st.download_button(
            label="⬇️ Download Leads CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="analytics_leads_v1.csv",
            mime="text/csv",
        )

    if st.button("← Back to Analytics"):
        st.session_state.page = "analytics"
        st.rerun()

def render_admin_sidebar():
    with st.sidebar:
        st.markdown("### Admin")
        pwd = st.text_input("Admin code", type="password", key="admin_pwd")
        if pwd == DEV_PASSWORD:
            st.session_state["admin_authed"] = True
        if st.session_state.get("admin_authed", False):
            if st.button("View Analytics"):
                st.session_state.page = "analytics"
                st.rerun()
            st.caption(f"Workbook: {WORKBOOK_PATH}")

            if st.button("View Leads"):
                st.session_state.page = "leads"
                st.rerun()

def render_cookie_banner() -> None:
    pref = get_cookie_pref()
    if pref in {"necessary", "optional"}:
        return

    st.markdown("""
    <div class="referral-block">
      <strong>Cookie notice</strong><br>
      <p style="margin: 8px 0 0 0;">Enable "Remember Me" so you dont re-enter your details on next visit.</p>
      <p style="margin: 4px 0 0 0;">Accept cookies to proceed.</p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Remember Me", key="cookie_opt", use_container_width=True):
            set_cookie_pref("optional")
            get_or_create_device_id()
            st.rerun()

    with c2:
        if st.button("Accept Cookies", key="cookie_nec", use_container_width=True):
            set_cookie_pref("necessary")
            get_or_create_device_id()
            st.rerun()

def welcome_page():
    show_logo(120)
    st.title(APP_TITLE)
    st.markdown(f"**{APP_SUBTITLE}**")

    st.markdown(f"""
    {APP_NAME} is an **AI-powered triage engine**, not a diagnostic tool.
    It helps users understand symptom urgency, likely care pathways, and next steps.
    It does **not** confirm a diagnosis and does not replace care from a qualified health professional.

    **Go for emergency care now** if you have:
    - chest pain
    - severe breathing difficulty
    - heavy bleeding
    - fainting or collapse
    - seizure
    - confusion
    - rapidly worsening symptoms
    """)

    render_cookie_banner()

    pref = get_cookie_pref()
    if pref not in {"necessary", "optional"}:
        st.warning("This triage service requires necessary cookies to operate and enforce fair-use limits.")
        return

    confirm = st.checkbox("I understand that this is a triage tool and not a diagnosis.")
    if st.button("Start Symptom Check", disabled=not confirm):
        st.session_state.page = "user_info"
        st.rerun()


def user_info_page():
    show_logo()
    st.subheader("Before we begin, I’d like to know a little about you.")
    with st.form("user_info_form"):
        age = st.number_input("Age", min_value=0, max_value=120, step=1)
        if age <= 14:
            st.info("Ages 0–14 will use pediatric rows within the normal symptom taxonomy.")
        gender = st.radio("Gender", ["Male", "Female"], horizontal=True)
        conditions = st.text_input("Existing conditions", placeholder="Mention any long-term conditions or type none")
        submit = st.form_submit_button("Continue →")
    if st.button("← Back"):
        st.session_state.page = "welcome"
        st.rerun()

    if submit:
        st.session_state.user_data = {
            "age": int(age),
            "gender": gender,
            "conditions": conditions.strip(),
            "population_group": population_group_for_age(int(age)),
        }
        st.session_state.free_input_mode = False
        st.session_state.matched_conditions = pd.DataFrame()
        st.session_state.page = "symptom_category"
        st.rerun()


def symptom_category_page():
    show_logo()
    st.subheader("Let’s start with what’s bothering you today")
    age = st.session_state.user_data.get("age")
    if age is not None and age <= 14:
        st.info("🧸 Pediatric mode active. You are seeing categories that have pediatric or shared condition rows.")

    st.markdown("""
    <div class="free-text-cta">
      <strong>You can type your symptoms in your own words, or choose the closest category below.</strong>
    </div>
    """, unsafe_allow_html=True)

    if st.button("Type my symptoms", key="free_text_top", use_container_width=True):
        st.session_state.page = "symptom_free_input"
        st.rerun()

    st.markdown("<div class='category-section-title'>Or choose a category:</div>", unsafe_allow_html=True)

    gender = st.session_state.user_data.get("gender")
    categories = available_primary_categories(age, gender)
    choice = display_grid(categories, cols=2, key_prefix="pc")
    if choice:
        st.session_state.free_input_mode = False
        st.session_state.matched_conditions = pd.DataFrame()
        st.session_state.user_data["primary_category"] = choice
        st.session_state.page = "symptom_subcategory"
        st.rerun()

    if st.button("← Back"):
        st.session_state.page = "user_info"
        st.rerun()


def symptom_free_input_page():
    show_logo()
    st.subheader("What are your symptoms?")
    st.caption("Use 1–2 simple symptoms. Separate multiple with commas.")

    with st.form("free_input_form"):
        text = st.text_input("Your symptoms")
        submit = st.form_submit_button("Search Symptoms")

    if submit:
        if not text.strip():
            st.warning("Please enter at least one symptom.")
            return

        age = st.session_state.user_data.get("age")
        gender = st.session_state.user_data.get("gender")
        ordered_cats, matched = rank_free_text_categories(text, db, age, gender)

        if matched.empty or not ordered_cats:
            log_failure({
                "timestamp": datetime.utcnow().isoformat(),
                "step": "free_text_match",
                "input": text,
                "reason": "no_symptom_match",
            })
            st.warning("We couldn't find a close symptom match yet. Try one or two simple symptoms or speak with a doctor.")
            return

        st.session_state.free_input_mode = True
        st.session_state.matched_conditions = matched
        st.session_state.user_data["free_symptoms"] = text
        st.session_state.user_data["free_primary_ranking"] = ordered_cats
        st.session_state.page = "symptom_primary_category_freeinput"
        st.rerun()

    if st.button("← Back"):
        st.session_state.page = "symptom_category"
        st.rerun()
        
def log_lead(record: dict) -> None:
    exists = os.path.isfile(LEADS_LOG_PATH)
    with open(LEADS_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(record.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(record)

def get_leads_export_df() -> pd.DataFrame:
    if not os.path.isfile(LEADS_LOG_PATH):
        return pd.DataFrame()
    try:
        return pd.read_csv(LEADS_LOG_PATH)
    except Exception:
        return pd.DataFrame()
    


def get_device_id() -> str:
    if not st.session_state.get("device_id"):
        st.session_state["device_id"] = str(uuid4())
    return st.session_state["device_id"]


def log_reveal(record: dict) -> None:
    exists = os.path.isfile(SESSIONS_LOG_PATH)
    with open(SESSIONS_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(record.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(record)


def todays_reveal_count(device_id: str) -> int:
    if not os.path.isfile(SESSIONS_LOG_PATH):
        return 0
    try:
        df = pd.read_csv(SESSIONS_LOG_PATH)
    except Exception:
        return 0
    if df.empty:
        return 0
    today = datetime.utcnow().date().isoformat()
    if "device_id" not in df.columns or "date" not in df.columns:
        return 0
    filt = df[
        (df["device_id"].astype(str) == str(device_id)) &
        (df["date"].astype(str) == today)
    ]
    return len(filt)


def session_limit_reached() -> bool:
    return todays_reveal_count(get_or_create_device_id()) >= MAX_REVEALS_PER_DAY

def maybe_log_reveal_once() -> None:
    if st.session_state.get("result_reveal_logged"):
        return

    condition = st.session_state.get("current_condition")
    if condition is None:
        return

    reveal_id = st.session_state.get("current_reveal_id") or str(uuid4())
    st.session_state["current_reveal_id"] = reveal_id

    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "date": datetime.utcnow().date().isoformat(),
        "device_id": get_or_create_device_id(),
        "full_name": st.session_state.get("lead_record", {}).get("full_name", ""),
        "email": st.session_state.get("lead_record", {}).get("email", ""),
        "phone": st.session_state.get("lead_record", {}).get("phone", ""),
        "institutional_id": st.session_state.get("lead_record", {}).get("institutional_id", ""),
        "condition": str(condition.get("Condition", "")),
        "primary_category": str(condition.get("Primary Category", "")),
        "subcategory": str(condition.get("SubCategory", "")),
        "reveal_id": reveal_id,
    }
    log_reveal(record)
    st.session_state["result_reveal_logged"] = True


def symptom_primary_category_freeinput_page():
    show_logo()
    st.subheader("Review these categories to see what feels closest")
    if not st.session_state.get("free_input_mode") or st.session_state.matched_conditions.empty:
        st.session_state.page = "symptom_category"
        st.rerun()

    age = st.session_state.user_data.get("age")
    gender = st.session_state.user_data.get("gender")
    source = st.session_state.matched_conditions
    cats = available_primary_categories(age, gender, source)
    if not cats:
        st.warning("We found symptom matches, but none are available for the selected age/gender filters.")
        if st.button("← Back"):
            st.session_state.page = "symptom_free_input"
            st.rerun()
        return

    choice = display_grid(cats[:10], cols=2, key_prefix="ftpc")
    if choice:
        st.session_state.user_data["primary_category"] = choice
        st.session_state.page = "symptom_subcategory"
        st.rerun()
    if st.button("← Back"):
        st.session_state.page = "symptom_free_input"
        st.rerun()


def symptom_subcategory_page():
    show_logo()
    st.subheader("Select the category that best fits")
    primary = st.session_state.user_data.get("primary_category")
    age = st.session_state.user_data.get("age")
    if age is not None and age <= 14:
        st.info("🧸 Pediatric mode active for this pathway.")
    if not primary:
        st.error("Primary category missing. Please go back.")
        return

    age = st.session_state.user_data.get("age")
    gender = st.session_state.user_data.get("gender")
    source = st.session_state.matched_conditions if st.session_state.get("free_input_mode") else db
    subcats = available_subcategories(primary, age, gender, source)
    if not subcats:
        st.warning("No subcategories available in this category for the selected age/gender filter.")
        if st.button("← Back"):
            st.session_state.page = "symptom_category"
            st.rerun()
        return

    choice = display_grid(subcats, cols=2, key_prefix="sc")
    if choice:
        st.session_state.user_data["subcategory"] = choice
        st.session_state.page = "symptom_selection"
        st.rerun()
    if st.button("← Back"):
        st.session_state.page = (
            "symptom_primary_category_freeinput"
            if st.session_state.get("free_input_mode") else
            "symptom_category"
        )
        st.rerun()


def symptom_selection_page():
    show_logo()
    st.subheader("Tell me about your symptoms")
    primary = st.session_state.user_data.get("primary_category")
    subcat = st.session_state.user_data.get("subcategory")
    source = st.session_state.matched_conditions if st.session_state.get("free_input_mode") else db
    age = st.session_state.user_data.get("age")
    gender = st.session_state.user_data.get("gender")

    subset = filter_rows(source, age, gender)
    subset = subset[(subset["Primary Category"] == primary) & (subset["SubCategory"] == subcat)]
    if subset.empty:
        st.error("No conditions found in this pathway.")
        return

    seen = {}
    for value in subset["Symptoms"].dropna():
        for sym in split_csvish(value):
            key = normalize_text(sym)
            seen.setdefault(key, sym)
    options = sorted(seen.values(), key=lambda x: normalize_text(x))

    selected = st.multiselect("Review carefully and select all that apply:", options)
    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("← Back"):
            st.session_state.page = "symptom_subcategory"
            st.rerun()
    with col2:
        if st.button("Continue →"):
            if not selected:
                st.warning("Please select at least one symptom before continuing.")
                return
            st.session_state.user_data["selected_symptoms"] = selected
            st.session_state.page = "clarifying_questions"
            st.rerun()



def clarifying_questions_page():
    show_logo()
    st.subheader("To guide me better, answer a few questions")

    primary = st.session_state.user_data.get("primary_category")
    subcat = st.session_state.user_data.get("subcategory")
    age = st.session_state.user_data.get("age")
    gender = st.session_state.user_data.get("gender")
    source = st.session_state.matched_conditions if st.session_state.get("free_input_mode") else db

    subset = filter_rows(source, age, gender)
    subset = subset[(subset["Primary Category"] == primary) & (subset["SubCategory"] == subcat)]
    if subset.empty:
        st.error("No conditions found here. Please start over.")
        return

    cqs = build_cq_definitions(primary, subcat)
    if not cqs:
        st.session_state.user_data["clarifying_answers"] = {}
        st.session_state.page = "risk_flag_selection"
        st.rerun()

    # Progressive one-question-at-a-time flow
    cq_context = f"{primary}|||{subcat}"
    if st.session_state.get("cq_context") != cq_context:
        st.session_state["cq_context"] = cq_context
        st.session_state["cq_step_index"] = 0
        st.session_state.user_data["clarifying_answers"] = {}

    step_index = int(st.session_state.get("cq_step_index", 0) or 0)
    if step_index < 0:
        step_index = 0
    if step_index >= len(cqs):
        step_index = len(cqs) - 1
        st.session_state["cq_step_index"] = step_index

    item = cqs[step_index]
    qid = item["id"]
    qtext = item["text"]
    rtype = item["response_type"]
    saved_answers = st.session_state.user_data.get("clarifying_answers", {}) or {}
    saved_value = saved_answers.get(qid, {}).get("value")

    st.caption(f"Question {step_index + 1} of {len(cqs)}")

    with st.form(f"cq_form_{qid}"):
        if rtype == "yes_no":
            options = ["Yes", "No"]
            try:
                default_ix = options.index(saved_value) if saved_value in options else 0
            except Exception:
                default_ix = 0
            value = st.radio(qtext, options, index=default_ix, horizontal=True, key=f"{qid}_input")
        elif rtype == "single_select":
            options = item["options"] or ["Not sure"]
            try:
                default_ix = options.index(saved_value) if saved_value in options else 0
            except Exception:
                default_ix = 0
            value = st.radio(qtext, options, index=default_ix, key=f"{qid}_input")
        elif rtype == "multi_select":
            options = item["options"] or []
            default_vals = saved_value if isinstance(saved_value, list) else []
            value = st.multiselect(qtext, options, default=default_vals, key=f"{qid}_input")
        elif rtype == "numeric":
            try:
                default_num = float(saved_value) if saved_value not in (None, "") else 0.0
            except Exception:
                default_num = 0.0
            value = st.number_input(qtext, value=default_num, key=f"{qid}_input")
        else:
            value = st.text_input(qtext, value=str(saved_value or ""), key=f"{qid}_input")

        submitted = st.form_submit_button("Continue →")

    col1, col2 = st.columns([1, 3])
    with col1:
        back = st.button("← Back")

    if back:
        if step_index > 0:
            st.session_state["cq_step_index"] = step_index - 1
            st.rerun()
        st.session_state.user_data["clarifying_answers"] = {}
        st.session_state.pop("cq_context", None)
        st.session_state.pop("cq_step_index", None)
        st.session_state.page = "symptom_selection"
        st.rerun()

    if submitted:
        saved_answers[qid] = {
            "text": qtext,
            "response_type": rtype,
            "value": value,
            "normalized_value": normalize_text("|".join(value) if isinstance(value, list) else value),
        }
        st.session_state.user_data["clarifying_answers"] = saved_answers

        if step_index + 1 < len(cqs):
            st.session_state["cq_step_index"] = step_index + 1
            st.rerun()

        st.session_state.pop("cq_context", None)
        st.session_state.pop("cq_step_index", None)
        st.session_state.page = "risk_flag_selection"
        st.rerun()


def risk_flag_selection_page():
    show_logo()
    st.subheader("These factors can affect your care. Select any that apply, or None.")

    primary = st.session_state.user_data.get("primary_category")
    subcat = st.session_state.user_data.get("subcategory")
    selected_symptoms = st.session_state.user_data.get("selected_symptoms", [])
    cq_answers = st.session_state.user_data.get("clarifying_answers", {})
    age = st.session_state.user_data.get("age")
    gender = st.session_state.user_data.get("gender")
    source = st.session_state.matched_conditions if st.session_state.get("free_input_mode") else db

    subset = filter_rows(source, age, gender)
    subset = subset[(subset["Primary Category"] == primary) & (subset["SubCategory"] == subcat)]
    if subset.empty:
        st.error("No conditions available in this pathway.")
        return

    block = sublogic_df[
        (sublogic_df["PrimaryCategoryName"] == primary) &
        (sublogic_df["SubcategoryName"] == subcat)
    ]
    red_flag_options: List[str] = []
    risk_modifier_options: List[str] = []
    subset_red = [str(x) for x in subset.get("EffectiveRedFlagQuestions", pd.Series(dtype=object)).dropna().tolist() if str(x).strip()]
    subset_mod = [str(x) for x in subset.get("EffectiveRiskModifierQuestions", pd.Series(dtype=object)).dropna().tolist() if str(x).strip()]
    effective_red = next((x for x in subset_red if x.strip()), "")
    effective_mod = next((x for x in subset_mod if x.strip()), "")
    if effective_red or effective_mod:
        red_flag_options = split_csvish(effective_red)
        risk_modifier_options = split_csvish(effective_mod)
    elif not block.empty:
        logic_row = block.iloc[0]
        red_flag_options = split_csvish(logic_row.get("RedFlagQuestions", ""))
        risk_modifier_options = split_csvish(logic_row.get("RiskModifierQuestions", ""))

    with st.form("risk_form"):
        st.markdown("**Danger signs / red flags**")
        selected_red_flags = [rf for rf in red_flag_options if st.checkbox(rf, key=f"rf_{rf}")]
        no_red_flags = st.checkbox("None of the red flags above", key="rf_none")

        st.markdown("**Context / risk modifiers**")
        selected_risk_modifiers = [rm for rm in risk_modifier_options if st.checkbox(rm, key=f"rm_{rm}")]
        no_risk_modifiers = st.checkbox("None of the risk modifiers above", key="rm_none")

        submit = st.form_submit_button("Continue →")

    if st.button("← Back"):
        st.session_state.page = "clarifying_questions"
        st.rerun()

    if submit:
        if no_red_flags:
            selected_red_flags = []
        if no_risk_modifiers:
            selected_risk_modifiers = []

        st.session_state["confirmed_red_flags"] = selected_red_flags
        st.session_state["confirmed_risk_modifiers"] = selected_risk_modifiers

        ranked = subset.copy()
        ranked["__score"] = ranked.apply(
            lambda r: compute_condition_score(
                r,
                selected_symptoms,
                cq_answers,
                selected_red_flags,
                selected_risk_modifiers,
            ),
            axis=1,
        )

        ranked = ranked.sort_values(
            by=["__score", "Acuity Level"],
            ascending=[False, False],
        )

        # If a blocked hard-gated condition is a competitive candidate, ask its
        # anchor question before selecting a less-specific fallback or showing no-match.
        pending_gate = find_pending_anchor_gate_candidate(
            subset,
            selected_symptoms,
            cq_answers,
            selected_red_flags,
            selected_risk_modifiers,
        )
        top_score = 0.0 if ranked.empty else float(ranked.iloc[0]["__score"] or 0)
        if pending_gate and float(pending_gate.get("base_score", 0) or 0) >= max(1.0, top_score):
            st.session_state["pending_anchor_gate"] = pending_gate
            st.session_state.page = "anchor_gate"
            st.rerun()

        if ranked.empty or top_score <= 0:
            show_no_match_ui()
            return

        st.session_state.current_condition = ranked.iloc[0]
        proceed_after_condition_selected()
        st.rerun()


def anchor_gate_page():
    show_logo()
    pending = st.session_state.get("pending_anchor_gate")
    if not pending:
        st.session_state.page = "risk_flag_selection"
        st.rerun()
        return

    condition_row = pending.get("condition_row", {}) or {}
    policy = pending.get("policy", {}) or {}

    st.subheader("One more safety question")
    st.markdown("""
    <div class="report-block report-block--warn">
      Some symptoms can overlap with important conditions. I need one more detail before I can safely prioritize this pathway.
    </div>
    """, unsafe_allow_html=True)

    question = str(policy.get("AnchorQuestion", "") or "Does this specific condition or risk apply to you?")
    answer = st.radio(question, ["Yes", "No", "Not sure"], horizontal=True)

    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button("← Back"):
            st.session_state.page = "risk_flag_selection"
            st.rerun()

    with c2:
        if st.button("Continue →", use_container_width=True):
            policy_key = str(policy.get("PolicyKey", condition_row.get("Condition", "anchor")) or "anchor")
            user = st.session_state.get("user_data", {}) or {}
            anchor_answers = user.get("anchor_answers", {}) or {}

            if answer == "Yes":
                # Add one exact positive anchor term, then allow this condition to surface.
                # The question text itself is still not counted as evidence.
                terms = split_policy_positive_terms(policy)
                anchor_answers[policy_key] = terms[0] if terms else "confirmed anchor"
                user["anchor_answers"] = anchor_answers
                st.session_state["user_data"] = user
                st.session_state.current_condition = pd.Series(condition_row)
                st.session_state["pending_anchor_gate"] = None
                proceed_after_condition_selected()
                st.rerun()

            # No or Not sure: do not surface the gated condition. Show a safer pathway-specific fallback.
            st.session_state["anchor_fallback"] = {
                "condition_row": condition_row,
                "policy": policy,
                "answer": answer,
            }
            st.session_state["pending_anchor_gate"] = None
            st.session_state.page = "anchor_fallback"
            st.rerun()


def anchor_fallback_page():
    show_logo()
    fallback = st.session_state.get("anchor_fallback")
    if not fallback:
        show_no_match_ui()
        return

    policy = fallback.get("policy", {}) or {}
    title = str(policy.get("FallbackTitle", "") or "Symptoms needing medical review")
    advice = str(policy.get("FallbackAdvice", "") or "Your symptoms still deserve attention. Please speak with a clinician for review.")

    st.header(title)
    st.markdown(
        f"<div class='report-block report-block--warn'>{html.escape(advice).replace(chr(10), '<br>')}</div>",
        unsafe_allow_html=True
    )
    st.markdown("""
    <div class="emergency-block">
      🚨 Seek urgent care now if symptoms are severe, rapidly worsening, or include trouble breathing, chest pain, fainting, confusion, heavy bleeding, seizure, severe weakness, or inability to move.
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.link_button("📅 Get help / schedule a consultation", url=APP_HELP_URL, use_container_width=True)
    with c2:
        if st.button("🔄 Start Over", use_container_width=True):
            st.session_state["anchor_fallback"] = None
            reset_for_new_session()


def usage_limit_page():
    show_logo()
    st.subheader("Daily session limit reached")
    st.markdown(f"""
    <div class="report-block report-block--warn">
      This device/session has reached the daily fair-use limit of <strong>{MAX_REVEALS_PER_DAY}</strong> triage results today.
      Please try again tomorrow or use the consultation link below for further care support.
    </div>
    """, unsafe_allow_html=True)

    st.link_button("📅 Get help / schedule a consultation", url=APP_HELP_URL, use_container_width=True)

    if st.button("🔄 Start Over"):
        reset_for_new_session()

def results_page():
    show_logo()
    condition = st.session_state.get("current_condition")
    if condition is None:
        st.error("No condition selected. Please start over.")
        if st.button("🔄 Start New Check"):
            reset_for_new_session()
        return

    if session_limit_reached() and not st.session_state.get("result_reveal_logged"):
        st.session_state.page = "usage_limit"
        st.rerun()

    maybe_log_reveal_once()

    red_flags = st.session_state.get("confirmed_red_flags", [])
    risk_modifiers = st.session_state.get("confirmed_risk_modifiers", [])
    rec = build_recommendation(condition, red_flags, risk_modifiers)

    st.header("Based on your answers, this may be:")
    st.subheader(str(condition.get("Condition", "")))

    block_class = "report-block" if rec["escalated"] else "report-block report-block--ok"
    narrative = html.escape(rec["narrative"] or "A likely condition was identified.").replace("\n", "<br>")
    recommendation = html.escape(rec["recommendation"] or "").replace("\n", "<br>")

    st.markdown(
        f"<div class='{block_class}' style='font-size: 1.15rem;'>{narrative}<br><br>{recommendation}</div>",
        unsafe_allow_html=True
    )

    emergency = rec["emergency"]
    if emergency:
        st.markdown(
            f"<div class='emergency-block'>🚨 Important: {html.escape(emergency)}</div>",
            unsafe_allow_html=True
        )

    referral = rec["referral"]
    if referral:
        st.markdown(
            f"<div class='referral-block'>🩺 <strong>{html.escape(referral)}</strong></div>",
            unsafe_allow_html=True
        )

    # Show nearby conditions from same pathway.
    primary = condition.get("Primary Category", "")
    subcat = condition.get("SubCategory", "")
    current = condition.get("Condition", "")
    age = st.session_state.user_data.get("age")
    gender = st.session_state.user_data.get("gender")
    selected_symptoms = st.session_state.user_data.get("selected_symptoms", [])

    peers = rank_peers(primary, subcat, current, age, gender, selected_symptoms, limit=3)
    if not peers.empty:
        st.markdown("### More conditions in this subcategory")
        st.caption("Explore related options that share similar features.")
        for _, peer in peers.iterrows():
            peer_name = str(peer.get("Condition", "")).strip()
            row_symptoms = {normalize_text(x) for x in split_csvish(peer.get("Symptoms", ""))}
            selected = {normalize_text(x) for x in selected_symptoms}
            overlap = [sym for sym in selected if sym in row_symptoms]
            overlap_note = f"Matched {len(overlap)} of your selected symptoms" if overlap else "Shares similar features"
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"**{html.escape(peer_name)}**\n\n<small>{html.escape(overlap_note)}</small>", unsafe_allow_html=True)
            with c2:
                if st.button(f"Explore", key=f"peer_{peer_name}"):
                    st.session_state.current_condition = peer
                    st.rerun()

    if condition.get("Referral"):
        st.link_button("📅 Schedule a Consultation or Get Help", url=APP_HELP_URL)

    col1, col2 = st.columns([1, 1])
    with col1:
        st.download_button(
            label="📄 Download Full Report",
            data=generate_report_text(),
            file_name=f"{str(condition.get('Condition', 'symptom_report')).replace(' ', '_')}_report.txt",
            mime="text/plain",
        )
    with col2:
        if st.button("🔄 Start New Check"):
            reset_for_new_session()

def lead_capture_page():
    show_logo()
    st.subheader("Before we show your triage outcome")

    st.markdown("""
    Please provide your details to continue.

    Returning users in the same browser session will not need to do this again.
    """)

    with st.form("lead_capture_form"):
        mode = st.radio("Usage type", ["Public user", "Institutional user"], horizontal=True)
        full_name = st.text_input("Full name")
        email = st.text_input("Email")
        phone = st.text_input("Phone number", placeholder="+2348021235678")
        institutional_id = st.text_input("Institutional ID")
        submit = st.form_submit_button("View my triage result")

    if st.button("← Back"):
        st.session_state.page = "risk_flag_selection"
        st.rerun()

    if submit:
        full_name = full_name.strip()
        email = email.strip()
        phone = phone.strip()
        institutional_id = institutional_id.strip()

        if not full_name:
            st.warning("Please enter your full name.")
            return

        if mode == "Public user":
            if not email:
                st.warning("Please enter your email.")
                return
            if not PHONE_REGEX.match(phone):
                st.warning("Enter phone number in the format +2348021235678")
                return
        else:
            if not institutional_id:
                st.warning("Please enter your institutional ID.")
                return
        
        user_id = get_repeat_user_cookie() or str(uuid4())
        consent_pref = get_cookie_pref() or "necessary"        

        lead_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "consent_pref": consent_pref,
            "mode": "institutional" if mode == "Institutional user" else "public",
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "institutional_id": institutional_id,
            "age": st.session_state.user_data.get("age", ""),
            "gender": st.session_state.user_data.get("gender", ""),
            "existing_conditions": st.session_state.user_data.get("conditions", ""),
            "primary_category": st.session_state.user_data.get("primary_category", ""),
            "subcategory": st.session_state.user_data.get("subcategory", ""),
            "free_symptoms": st.session_state.user_data.get("free_symptoms", ""),
        }

        log_lead(lead_record)
        st.success(f"Lead saved to: {os.path.abspath(LEADS_LOG_PATH)}")
        st.write("Exists after save:", os.path.isfile(LEADS_LOG_PATH))
        st.session_state["lead_captured"] = True
        st.session_state["lead_record"] = lead_record

        if consent_pref == "optional":
            set_repeat_user_cookie(user_id)
            
        st.session_state.page = "results"
        st.rerun()

PAGES = {
    "welcome": welcome_page,
    "user_info": user_info_page,
    "symptom_category": symptom_category_page,
    "symptom_free_input": symptom_free_input_page,
    "symptom_primary_category_freeinput": symptom_primary_category_freeinput_page,
    "symptom_subcategory": symptom_subcategory_page,
    "symptom_selection": symptom_selection_page,
    "clarifying_questions": clarifying_questions_page,
    "risk_flag_selection": risk_flag_selection_page,
    "anchor_gate": anchor_gate_page,
    "anchor_fallback": anchor_fallback_page,
    "lead_capture": lead_capture_page,
    "results": results_page,
    "analytics": analytics_page,
    "usage_limit": usage_limit_page,
    "leads": leads_page,
}

render_admin_sidebar()
PAGES[st.session_state.get("page", "welcome")]()