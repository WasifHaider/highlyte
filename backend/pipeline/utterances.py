"""Utterances and thought units: what the clip ranker picks from (spec
2026-09-26-clip-selection-design.md, section 2).

An utterance is a run of words ended by a pause, a sentence end or a
speaker change. A thought unit groups utterances that belong together (a
question and its answer, a claim and its "kyunki ..."), so a pick widened
to whole units never ends mid-thought.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .segments import Segment, SegWord

PAUSE_S = 0.35
MAX_UTTERANCE_S = 20.0
UNIT_PAUSE_S = 0.8
BRIDGE_MAX_GAP_S = 2.0
BRIDGE_MAX_EXTRA_S = 12.0
MAX_UNIT_S = 45.0

HANGING_END = {"lekin", "kyunki", "aur", "toh", "but", "because", "and", "so"}
CONTINUATION_START = {"kyunki", "lekin", "matlab", "yaani", "isliye", "because", "but", "so"}
CLOSING_PHRASES = ("chalo next", "chalo aage", "moving on", "next question")

_SENTENCE_END = (".", "?", "!")
_EDGE_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)


def norm(word: str) -> str:
    return _EDGE_RE.sub("", word.lower())


@dataclass
class Utterance:
    id: str
    first: int   # index of the first word in flat_words(...)
    last: int    # index of the last word, inclusive
    start: float
    end: float
    words: list[SegWord]
    speaker: str = "A"

    @property
    def text(self) -> str:
        return " ".join(w.t for w in self.words)

    @property
    def confidence(self) -> float:
        return round(sum(w.prob for w in self.words) / len(self.words), 3) if self.words else 0.0

    @property
    def ends_sentence(self) -> bool:
        return bool(self.words) and self.words[-1].t.endswith(_SENTENCE_END)


@dataclass
class ThoughtUnit:
    utterances: list[Utterance]

    @property
    def start(self) -> float:
        return self.utterances[0].start

    @property
    def end(self) -> float:
        return self.utterances[-1].end


def _cap(words: list[SegWord]) -> list[list[SegWord]]:
    """Split a run longer than MAX_UTTERANCE_S at its longest gap."""
    if len(words) < 2 or words[-1].end - words[0].start <= MAX_UTTERANCE_S:
        return [words]
    _, i = max((words[k + 1].start - words[k].end, k) for k in range(len(words) - 1))
    return _cap(words[:i + 1]) + _cap(words[i + 1:])


def build_utterances(segments: list[Segment]) -> list[Utterance]:
    groups: list[tuple[list[SegWord], str]] = []
    cur: list[SegWord] = []
    speaker = "A"
    for seg in segments:
        for word in seg.words:
            if cur:
                prev = cur[-1]
                if (word.start - prev.end >= PAUSE_S
                        or prev.t.endswith(_SENTENCE_END)
                        or seg.speaker != speaker):
                    groups.append((cur, speaker))
                    cur = []
            if not cur:
                speaker = seg.speaker
            cur.append(word)
    if cur:
        groups.append((cur, speaker))

    out: list[Utterance] = []
    index = 0
    for words, spk in groups:
        for part in _cap(words):
            out.append(Utterance(
                id=f"u{len(out) + 1}", first=index, last=index + len(part) - 1,
                start=part[0].start, end=part[-1].end, words=part, speaker=spk,
            ))
            index += len(part)
    return out


def flat_words(utterances: list[Utterance]) -> list[SegWord]:
    return [w for u in utterances for w in u.words]


def _is_closing(u: Utterance) -> bool:
    text = f" {' '.join(norm(w.t) for w in u.words)} "
    return any(f" {p} " in text for p in CLOSING_PHRASES)


def _bridges(prev: Utterance, nxt: Utterance) -> bool:
    return (prev.words[-1].t.endswith("?")
            or norm(prev.words[-1].t) in HANGING_END
            or norm(nxt.words[0].t) in CONTINUATION_START)


def build_thought_units(utterances: list[Utterance]) -> list[ThoughtUnit]:
    units: list[ThoughtUnit] = []
    cur: list[Utterance] = []
    bridged = 0.0
    for u in utterances:
        if cur:
            prev = cur[-1]
            gap = u.start - prev.end
            join = False
            if u.end - cur[0].start <= MAX_UNIT_S and not _is_closing(u):
                if gap < UNIT_PAUSE_S:
                    join = True
                elif (gap <= BRIDGE_MAX_GAP_S and _bridges(prev, u)
                      and bridged + (u.end - prev.end) <= BRIDGE_MAX_EXTRA_S):
                    join = True
                    bridged += u.end - prev.end
            if join:
                cur.append(u)
                continue
            units.append(ThoughtUnit(cur))
        cur, bridged = [u], 0.0
    if cur:
        units.append(ThoughtUnit(cur))
    return units
