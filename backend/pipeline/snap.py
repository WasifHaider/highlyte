"""Cut points for a picked span, placed from word timings (spec section 3).

The ranker never supplies times. Everything here works on word indices
into the whole transcript's flat word list (utterances.flat_words).
"""
from __future__ import annotations

from dataclasses import dataclass

from .segments import SegWord
from .utterances import norm

LEAD_S = 0.22        # silence kept before the first word (spec: 180-250 ms)
AIR_S = 0.40         # silence kept after the last word (spec: 300-500 ms)
CUT_PAUSE_S = 0.30   # a gap this long is a safe place to cut
MAX_EXTEND_S = 3.0   # how far a cut may move to reach such a gap
PREV_GUARD_S = 0.03  # never start closer than this to the previous word
NEXT_GUARD_S = 0.05  # never end closer than this to the next word
MIN_SPAN_S = 8.0     # filler/last-line trims may not leave less than this

FILLER_START_WORDS = {"uh", "um", "hmm", "toh", "matlab", "acha", "achha", "haan", "so", "like", "basically"}
FILLER_START_PHRASES = {("you", "know"), ("i", "mean"), ("okay", "so"), ("ok", "so")}
HANGING_END_WORDS = {"lekin", "kyunki", "aur", "toh", "ki", "but", "because", "and", "so"}
TRAILING_FILLER = {"uh", "um"}
_SENTENCE_END = (".", "?", "!")


class Reject(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Cut:
    first: int
    last: int
    start: float
    end: float


def back_to_pause(words: list[SegWord], first: int) -> int:
    """If the speaker was mid-flow at `first`, move back to the previous
    gap >= CUT_PAUSE_S, but only within MAX_EXTEND_S."""
    i = first
    while i > 0:
        if words[i].start - words[i - 1].end >= CUT_PAUSE_S:
            return i
        if words[first].start - words[i - 1].start > MAX_EXTEND_S:
            return first
        i -= 1
    return 0


def forward_to_pause(words: list[SegWord], last: int) -> int:
    """Move forward to the next gap >= CUT_PAUSE_S within MAX_EXTEND_S;
    a speaker who never pauses there means the clip would end mid-flow."""
    i = last
    while i < len(words) - 1:
        if words[i + 1].start - words[i].end >= CUT_PAUSE_S:
            return i
        if words[i + 1].end - words[last].end > MAX_EXTEND_S:
            raise Reject("hanging_end")
        i += 1
    return i


def _filler_len(words: list[SegWord], i: int, last: int) -> int:
    here = norm(words[i].t)
    if i < last and (here, norm(words[i + 1].t)) in FILLER_START_PHRASES:
        return 2
    return 1 if here in FILLER_START_WORDS else 0


def strip_leading_filler(words: list[SegWord], first: int, last: int) -> int:
    i = first
    while i <= last:
        n = _filler_len(words, i, last)
        if n == 0:
            break
        i += n
    if i == first:
        return first
    if i > last or words[last].end - words[i].start < MIN_SPAN_S:
        raise Reject("filler_start")
    return i


def fix_last_line(words: list[SegWord], first: int, last: int) -> int:
    j = last
    while j > first and norm(words[j].t) in TRAILING_FILLER:
        j -= 1
    if norm(words[j].t) not in HANGING_END_WORDS:
        return j
    k = j - 1
    while k >= first and not words[k].t.endswith(_SENTENCE_END):
        k -= 1
    if k < first or words[k].end - words[first].start < MIN_SPAN_S:
        raise Reject("hanging_end")
    return k


def start_cut(words: list[SegWord], first: int) -> float:
    w = words[first]
    t = w.start - LEAD_S
    if first > 0:
        t = max(t, words[first - 1].end + PREV_GUARD_S)
    return round(min(max(t, 0.0), w.start), 3)


def end_cut(words: list[SegWord], last: int) -> float:
    w = words[last]
    t = w.end + AIR_S
    if last < len(words) - 1:
        t = min(t, words[last + 1].start - NEXT_GUARD_S)
    return round(max(t, w.end), 3)


def snap(words: list[SegWord], first: int, last: int) -> Cut:
    first = back_to_pause(words, first)
    last = forward_to_pause(words, last)
    first = strip_leading_filler(words, first, last)
    last = fix_last_line(words, first, last)
    return Cut(first, last, start_cut(words, first), end_cut(words, last))
