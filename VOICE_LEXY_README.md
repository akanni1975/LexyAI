# Voice Lexy Fever MVP — English, Yoruba, Hausa

## Files

- `voice_language_layer.py` — scripts, language normalization, transcript cleaning, FreeTextMap mapper, yes/no parser.
- `voice_io_layer.py` — speech-to-text and text-to-speech wrapper.
- `voice_scripts_fever_en_yo_ha.csv` — fever journey spoken scripts.
- `voice_freetext_map_seed.csv` — initial multilingual symptom phrase map.
- `voice_lexy_streamlit_patch.py` — Streamlit page/patch for the fever MVP.

## Install

```bash
pip install openai streamlit-mic-recorder
```

Set:

```bash
OPENAI_API_KEY=your_key
```

Optional:

```bash
LEXY_STT_MODEL=gpt-4o-mini-transcribe
LEXY_TTS_MODEL=gpt-4o-mini-tts
```

## Integration

1. Copy all files into the same folder as the current Lexy Streamlit app.
2. Import the page function:

```python
from voice_lexy_streamlit_patch import voice_lexy_fever_page
```

3. Add it to your page router as a beta page:

```python
PAGES["Voice Lexy Fever MVP"] = voice_lexy_fever_page
```

4. Replace `run_existing_lexy_engine_stub()` with the existing Lexy clinical engine/recommendation function.

## Important rule

Do not translate or duplicate the clinical engine. Voice Lexy must pass canonical English symptoms into the existing engine.

Example:

```text
Ara mi n gbona → fever → existing Lexy engine
Jikina yana zafi → fever → existing Lexy engine
```

## Clinical/content review before live production

The Yoruba and Hausa scripts are suitable for prototype testing. Before production deployment, they should be reviewed by:

1. a native Yoruba speaker,
2. a native Hausa speaker,
3. a clinician familiar with patient-facing safety language.
