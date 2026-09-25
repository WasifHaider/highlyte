"""Check the user's spoken-language choice against the audio.

Three short samples go to Whisper with no language set. All three English
means the English path; any Hindi or Urdu means Hinglish; anything unclear
keeps the user's choice. When the result overrides the choice, the note is
shown on the status screen so it is never a silent surprise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import asr

NOTE_ENGLISH = "Detected English audio. Captions will be in English."
NOTE_HINGLISH = "Detected Hindi/Urdu speech. Captions will be in Hinglish."

_CODES = {"english": "en", "en": "en", "hindi": "hi", "hi": "hi", "urdu": "ur", "ur": "ur"}


@dataclass(frozen=True)
class LanguageDecision:
    used: str            # "hinglish" | "english"
    note: str | None


def normalize_code(name: str | None) -> str | None:
    if not name:
        return None
    return _CODES.get(name.strip().lower(), "other")


def rule(detected: list[str | None], requested: str) -> LanguageDecision:
    if any(d in ("hi", "ur") for d in detected):
        return LanguageDecision("hinglish", NOTE_HINGLISH if requested == "english" else None)
    if detected and all(d == "en" for d in detected):
        return LanguageDecision("english", NOTE_ENGLISH if requested == "hinglish" else None)
    return LanguageDecision(requested, None)


def decide(sample_paths: list[str], requested: str, detect: Callable[[str], str | None]) -> LanguageDecision:
    detected: list[str | None] = []
    for path in sample_paths:
        try:
            detected.append(normalize_code(detect(path)))
        except Exception as e:  # noqa: BLE001
            print(f"[langcheck] detection failed on {path}: {e}")
            detected.append(None)
    return rule(detected, requested)


def groq_detector(key: str) -> Callable[[str], str | None]:
    def detect(path: str) -> str | None:
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=asr.GROQ_BASE_URL)
        with open(path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model=asr.GROQ_ENGLISH_MODEL, file=f, response_format="verbose_json",
            )
        # openai 1.57.4 types duration as str while Groq returns a float,
        # so a plain model_dump() prints a pydantic UserWarning per call.
        return resp.model_dump(warnings=False).get("language")

    return detect


def local_detect(path: str) -> str | None:
    from . import audio

    lang, _prob, _all = asr.get_local_model().detect_language(audio.load(path))
    return lang
