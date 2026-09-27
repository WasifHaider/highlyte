"""Word-level timings for one clip, relative to the clip's start.

Every transcript is word-level now (see transcript.py), so a clip's words
are sliced straight from it.
"""
from __future__ import annotations

import re

from ..spec import Word
from .transcript import TranscriptSegment

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


def mark_emphasis(words: list[Word], keywords: list[str]) -> list[Word]:
    targets = {_norm(tok) for kw in keywords for tok in kw.split()} - {""}
    return [w.model_copy(update={"emphasis": _norm(w.text) in targets}) for w in words]


def clip_words(
    segments: list[TranscriptSegment], clip_start: float, clip_end: float, emphasis: list[str]
) -> list[Word]:
    return mark_emphasis(words_from_segments(segments, clip_start, clip_end), emphasis)
