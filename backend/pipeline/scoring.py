"""Scores, hard rejects, QA flags and packing for clip candidates (spec
section 3). Thresholds are first guesses; the Step 6 eval tunes them."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, replace

from .segments import SegWord

W_STANDALONE, W_HOOK, W_PAYOFF, W_ENERGY, W_DURATION = 0.40, 0.25, 0.15, 0.10, 0.10

MIN_STANDALONE = 0.7
MIN_HOOK = 0.55
NEAR_MIN_STANDALONE = 0.5
NEAR_MIN_HOOK = 0.35

MIN_CLIP_S = 8.0
MAX_CLIP_S = 60.0
FIT_LOW_S = 12.0
FIT_HIGH_S = 35.0
MAX_FIRST_WORD_DELAY_S = 1.2
MIN_MEAN_CONFIDENCE = 0.45

LOW_CONF_MEAN = 0.70
LOW_CONF_WORD = 0.4
LOW_CONF_SHARE = 0.15

ENERGY_RANGE_DB = 6.0
SPEECH_FLOOR_DB = -60.0
LOUDNESS_STEP_S = 0.5

MAX_CLIPS = 8
MIN_CLIPS = 5
MAX_OVERLAP = 0.30


@dataclass
class Candidate:
    start: float
    end: float
    words: list[SegWord]
    standalone: float
    hook: float
    payoff: float
    reason: str = ""
    energy: float = 0.5
    duration_fit: float = 0.0
    total: float = 0.0
    flags: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def mean_confidence(self) -> float:
        return sum(w.prob for w in self.words) / len(self.words) if self.words else 0.0


def duration_fit(seconds: float) -> float:
    if seconds < MIN_CLIP_S or seconds > MAX_CLIP_S:
        return 0.0
    if seconds < FIT_LOW_S:
        return (seconds - MIN_CLIP_S) / (FIT_LOW_S - MIN_CLIP_S)
    if seconds > FIT_HIGH_S:
        return (MAX_CLIP_S - seconds) / (MAX_CLIP_S - FIT_HIGH_S)
    return 1.0


def energy(loudness: list[float], start: float, end: float) -> float:
    """Clip mean loudness against the episode's median speech loudness,
    -6 dB -> 0, +6 dB -> 1. Neutral 0.5 when nothing is stored."""
    speech = [v for v in loudness if v > SPEECH_FLOOR_DB]
    if not speech:
        return 0.5
    i0 = int(start / LOUDNESS_STEP_S)
    i1 = max(i0 + 1, math.ceil(end / LOUDNESS_STEP_S))
    clip = [v for v in loudness[i0:i1] if v > SPEECH_FLOOR_DB]
    if not clip:
        return 0.0
    diff = statistics.fmean(clip) - statistics.median(speech)
    return max(0.0, min(1.0, (diff + ENERGY_RANGE_DB) / (2 * ENERGY_RANGE_DB)))


def score(c: Candidate, loudness: list[float]) -> Candidate:
    e = energy(loudness, c.start, c.end)
    fit = duration_fit(c.duration)
    total = (W_STANDALONE * c.standalone + W_HOOK * c.hook + W_PAYOFF * c.payoff
             + W_ENERGY * e + W_DURATION * fit)
    return replace(c, energy=round(e, 3), duration_fit=round(fit, 3), total=round(total, 4))


def structural_reject(c: Candidate) -> str | None:
    """Rejects that the near-miss fill never relaxes. Filler starts and
    hanging ends are rejected earlier, by snap.Reject."""
    if c.duration < MIN_CLIP_S:
        return "too_short"
    if c.duration > MAX_CLIP_S:
        return "too_long"
    if not c.words or c.words[0].start - c.start > MAX_FIRST_WORD_DELAY_S:
        return "late_speech"
    if c.mean_confidence < MIN_MEAN_CONFIDENCE:
        return "low_confidence"
    return None


def passes_thresholds(c: Candidate) -> bool:
    return c.standalone >= MIN_STANDALONE and c.hook >= MIN_HOOK


def near_miss(c: Candidate) -> bool:
    return c.standalone >= NEAR_MIN_STANDALONE and c.hook >= NEAR_MIN_HOOK


def qa_flags(c: Candidate) -> list[str]:
    if not c.words:
        return []
    low_share = sum(1 for w in c.words if w.prob < LOW_CONF_WORD) / len(c.words)
    if c.mean_confidence < LOW_CONF_MEAN or low_share > LOW_CONF_SHARE:
        return ["low_confidence"]
    return []


def span_overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Shared length of two time spans as a share of the shorter one."""
    shortest = min(a[1] - a[0], b[1] - b[0])
    shared = min(a[1], b[1]) - max(a[0], b[0])
    if shortest <= 0 or shared <= 0:
        return 0.0
    return shared / shortest


def overlap_ratio(a: Candidate, b: Candidate) -> float:
    return span_overlap((a.start, a.end), (b.start, b.end))


def _fits(c: Candidate, kept: list[Candidate]) -> bool:
    return all(overlap_ratio(c, k) < MAX_OVERLAP for k in kept)


def pack(cands: list[Candidate]) -> list[Candidate]:
    by_total = sorted(cands, key=lambda c: c.total, reverse=True)
    kept: list[Candidate] = []
    for c in by_total:
        if len(kept) >= MAX_CLIPS:
            break
        if passes_thresholds(c) and _fits(c, kept):
            kept.append(c)
    if len(kept) < MIN_CLIPS:
        for c in by_total:
            if len(kept) >= MIN_CLIPS:
                break
            if not passes_thresholds(c) and near_miss(c) and _fits(c, kept):
                kept.append(replace(c, flags=[*c.flags, "weak_pick"]))
    return sorted(kept, key=lambda c: c.start)
