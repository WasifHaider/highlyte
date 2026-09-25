"""The v1 segment data contract (roadmap, "Data contract").

A segment is a run of words split on a pause, a sentence end or a length
cap. `raw` is what Whisper wrote; `hinglish` is after the glossary and
spelling list. Captions, exports and the ranker read `hinglish`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .asr import AsrWord

PAUSE_S = 0.35
MAX_SEGMENT_S = 15.0


@dataclass
class SegWord:
    t: str
    raw: str
    start: float
    end: float
    kind: str  # "en" | "hinglish" | "num"; "" until hinglish.fix runs
    prob: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Segment:
    id: str
    start: float
    end: float
    speaker: str
    language: str
    raw: str
    hinglish: str
    words: list[SegWord] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["words"] = [x.to_dict() for x in self.words]
        return d


def from_asr(words: list[AsrWord]) -> list[SegWord]:
    return [SegWord(t=x.text, raw=x.text, start=x.start, end=x.end, kind="", prob=x.prob) for x in words]


def _segment(n: int, words: list[SegWord], language_code: str) -> Segment:
    return Segment(
        id=f"seg_{n:04d}",
        start=words[0].start,
        end=words[-1].end,
        speaker="A",  # no diarization in v1
        language=language_code,
        raw=" ".join(x.raw for x in words),
        hinglish=" ".join(x.t for x in words),
        words=words,
        confidence=round(sum(x.prob for x in words) / len(words), 2),
    )


def build(words: list[SegWord], language_code: str) -> list[Segment]:
    out: list[Segment] = []
    current: list[SegWord] = []
    for word in words:
        if current:
            prev = current[-1]
            if (word.start - prev.end >= PAUSE_S
                    or prev.t.endswith((".", "?", "!"))
                    or word.end - current[0].start > MAX_SEGMENT_S):
                out.append(_segment(len(out) + 1, current, language_code))
                current = []
        current.append(word)
    if current:
        out.append(_segment(len(out) + 1, current, language_code))
    return out
