"""Word-level timings for one clip, relative to the clip's start.

Karaoke/pop captions need to know when each word is spoken. The Groq and
local Whisper transcript paths already produce word-level segments (see
transcript.py), so those are sliced directly. The YouTube-captions path
only has caption-line timing, so for those clips the clip's own audio
span is sent to Groq Whisper — a few seconds of audio per clip, not the
whole episode. If that isn't possible (no GROQ_KEY, or the call fails),
each caption line's duration is spread evenly across its words and the
result is flagged approximate so the UI can say so.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Callable

from ..spec import Word
from .transcript import TranscriptSegment, _transcribe_chunk_groq

# Transcript sources whose segments are already individual words.
WORD_LEVEL_SOURCES = {"groq", "whisper"}

_NON_WORD_RE = re.compile(r"[^\w']+", re.UNICODE)


def _norm(token: str) -> str:
    return _NON_WORD_RE.sub("", token.lower())


def _overlaps(start: float, end: float, clip_start: float, clip_end: float) -> bool:
    return end > clip_start and start < clip_end


def words_from_segments(
    segments: list[TranscriptSegment], clip_start: float, clip_end: float
) -> list[Word]:
    out: list[Word] = []
    for s in segments:
        text = s.text.strip()
        if not text or not _overlaps(s.start, s.end, clip_start, clip_end):
            continue
        start = max(s.start, clip_start) - clip_start
        end = min(s.end, clip_end) - clip_start
        out.append(Word(text=text, start=round(start, 3), end=round(max(end, start), 3)))
    return out


def spread_words(
    segments: list[TranscriptSegment], clip_start: float, clip_end: float
) -> list[Word]:
    out: list[Word] = []
    for s in segments:
        tokens = s.text.split()
        if not tokens or not _overlaps(s.start, s.end, clip_start, clip_end):
            continue
        step = (s.end - s.start) / len(tokens)
        for i, tok in enumerate(tokens):
            ws = s.start + i * step
            we = ws + step
            if not _overlaps(ws, we, clip_start, clip_end):
                continue
            out.append(Word(
                text=tok,
                start=round(max(ws, clip_start) - clip_start, 3),
                end=round(min(we, clip_end) - clip_start, 3),
            ))
    return out


def mark_emphasis(words: list[Word], keywords: list[str]) -> list[Word]:
    targets = {_norm(tok) for kw in keywords for tok in kw.split()} - {""}
    return [w.model_copy(update={"emphasis": _norm(w.text) in targets}) for w in words]


def extract_audio_span(audio_path: str, start: float, end: float, out_path: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.2f}", "-i", audio_path,
        "-t", f"{max(end - start, 0.5):.2f}",
        "-vn", "-c:a", "aac", "-b:a", "128k",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg audio span failed: {proc.stderr.decode(errors='ignore')}")


def clip_words(
    segments: list[TranscriptSegment],
    source: str,
    audio_path: str,
    clip_start: float,
    clip_end: float,
    emphasis: list[str],
    *,
    groq_key: str | None = None,
    prompt: str | None = None,
    transcribe: Callable[[str, str, str | None], list[tuple[float, float, str]]] = _transcribe_chunk_groq,
) -> tuple[list[Word], bool]:
    """Returns (words relative to clip_start, approx)."""
    if source in WORD_LEVEL_SOURCES:
        return mark_emphasis(words_from_segments(segments, clip_start, clip_end), emphasis), False

    words: list[Word] | None = None
    if groq_key:
        tmp_dir = tempfile.mkdtemp(prefix="highlyte_words_")
        try:
            span_path = os.path.join(tmp_dir, "span.m4a")
            extract_audio_span(audio_path, clip_start, clip_end, span_path)
            duration = clip_end - clip_start
            words = [
                Word(text=t.strip(), start=round(max(s, 0.0), 3), end=round(min(e, duration), 3))
                for s, e, t in transcribe(span_path, groq_key, prompt)
                if t.strip()
            ]
        except Exception as e:  # noqa: BLE001
            print(f"[words] groq word timing failed, spreading evenly: {e}")
            words = None
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    approx = words is None
    if words is None:
        words = spread_words(segments, clip_start, clip_end)
    return mark_emphasis(words, emphasis), approx
