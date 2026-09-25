"""Transcription: audio in, v1 caption segments out.

  normalize (16kHz mono, loudnorm)
  -> language check on three samples (langcheck)
  -> VAD chunks of at most 120s, cut in silence (audio)
  -> Whisper per chunk, Groq first with local fallback (asr)
  -> glossary and house spelling in code (hinglish)
  -> segments (the v1 data contract)

Whisper always runs with language="en". On the Hinglish path it also gets
ROMAN_URDU_HINDI_SEED as a prompt: Whisper treats the prompt as "text so
far" and keeps writing Roman Hindi/Urdu in Latin letters instead of
switching script or translating to English. The spike (roadmap, "Spike
results") compared this with Hindi mode plus transliteration and this path
won clearly on English words, names and Urdu vocabulary. The prompt is not
sent on English audio, where it can make Whisper invent Urdu-looking words.

YouTube's own captions are no longer used: they have no word timings, the
English track on Hindi/Urdu videos is often a translation, and the captions
API is blocked on the server like yt-dlp.
"""
from __future__ import annotations

import os

# Must be set before faster_whisper/huggingface_hub is imported anywhere.
# On this environment the hf_xet accelerated transfer backend silently
# stalls at 0 bytes on large model files (plain HTTPS to the same host
# works fine) — forcing the plain-HTTP downloader avoids the hang.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import shutil
import tempfile
from dataclasses import dataclass
from typing import Callable

from . import asr, audio, hinglish, langcheck, segments

ROMAN_URDU_HINDI_SEED = (
    "Yeh podcast Roman Urdu aur Hindi mein baat karta hai, jaise "
    "'mujhe yeh cheez bohat pasand hai' ya 'hum log kal milenge'. "
    "Kabhi kabhi English words bhi beech mein aa jate hain, jaise "
    "'that's actually a great point' ya 'I totally agree with you'. "
    "Log apni baat normal tareeke se karte hain, bina kisi script ke, "
    "sirf Roman letters mein."
)

LANGUAGE_CODES = {"hinglish": "hi-Latn-EN", "english": "en"}


@dataclass
class TranscriptSegment:
    """One timed piece of text for the highlight scorer and clip prep.
    Built one per word by to_word_segments until piece 2 replaces them."""
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    segments: list[segments.Segment]
    language: str        # "hinglish" | "english", the path actually used
    note: str | None     # set when detection overrode the user's choice
    source: str          # "groq" | "whisper" | "mixed"


class NoSpeechError(RuntimeError):
    pass


def _providers(language: str) -> tuple[asr.AsrProvider | None, asr.AsrProvider]:
    key = os.environ.get("GROQ_KEY")
    model = asr.GROQ_HINGLISH_MODEL if language == "hinglish" else asr.GROQ_ENGLISH_MODEL
    return (asr.GroqAsr(key, model) if key else None), asr.LocalWhisperAsr("small")


def transcribe(
    audio_path: str,
    requested: str,
    on_progress: Callable[[int, int, str], None] | None = None,
    *,
    detect: Callable[[str], str | None] | None = None,
    primary: asr.AsrProvider | None = None,
    fallback: asr.AsrProvider | None = None,
) -> Transcript:
    tmp_dir = tempfile.mkdtemp(prefix="highlyte_asr_")
    try:
        wav = os.path.join(tmp_dir, "audio.wav")
        audio.normalize(audio_path, wav)
        samples = audio.load(wav)

        if detect is None:
            key = os.environ.get("GROQ_KEY")
            detect = langcheck.groq_detector(key) if key else langcheck.local_detect
        decision = langcheck.decide(audio.language_samples(samples, tmp_dir), requested, detect)

        chunks = audio.speech_chunks(samples, tmp_dir)
        if not chunks:
            raise NoSpeechError("No speech found in this video.")

        if primary is None and fallback is None:
            primary, fallback = _providers(decision.used)
        prompt = ROMAN_URDU_HINDI_SEED if decision.used == "hinglish" else None
        words, source = asr.transcribe_chunks(
            chunks, primary, fallback or primary, prompt=prompt, on_progress=on_progress,
        )

        fixed = hinglish.fix(segments.from_asr(words), decision.used)
        return Transcript(
            segments=segments.build(fixed, LANGUAGE_CODES[decision.used]),
            language=decision.used, note=decision.note, source=source,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def to_word_segments(t: Transcript) -> list[TranscriptSegment]:
    return [TranscriptSegment(w.start, w.end, w.t) for s in t.segments for w in s.words]
