"""Clip selection (roadmap Step 3; spec 2026-09-26-clip-selection-design.md).

utterances -> thought units -> LLM ranker (ids only) -> cut points snapped
in code -> hard rejects -> score -> pack -> titles call.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import groq_llm, ranker, scoring, snap, titles
from .groq_llm import SelectionFailed
from .ingest import duration_label
from .segments import Segment
from .utterances import build_thought_units, build_utterances, flat_words

__all__ = ["Clip", "Selection", "SelectionFailed", "select", "skipped_note", "regenerate", "alternate_to_clip"]

TITLES_FAILED_NOTE = "Hook titles could not be written this time."
ZERO_CLIPS_NOTE = "No moment passed the clip checks. Try another video, or re-run later."

MAX_ALTERNATES = 10
REGENERATE_MARGIN_S = 120.0
SAME_MOMENT_OVERLAP = 0.9


@dataclass
class Clip:
    start: float
    end: float
    text: str
    score: float  # virality score, 0-10
    tag: str
    hook_title: str | None = None
    emphasis: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    standalone: float = 0.0
    hook: float = 0.0
    payoff: float = 0.0
    energy: float = 0.5
    duration_fit: float = 0.0
    reason: str = ""


@dataclass
class Selection:
    clips: list[Clip]
    note: str | None = None
    alternates: list[dict] = field(default_factory=list)


def skipped_note(skipped: list[ranker.Skipped]) -> str | None:
    if not skipped:
        return None
    spans = sorted((s.start, s.end) for s in skipped)
    merged = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    ranges = ", ".join(f"{duration_label(a)}–{duration_label(b)}" for a, b in merged)
    reasons = ", ".join(sorted({s.reason for s in skipped}))
    return f"Skipped {ranges} ({reasons}). Some moments may be missing."


def _candidates(words, units, picks, loudness) -> list[scoring.Candidate]:
    out: list[scoring.Candidate] = []
    for p in picks:
        first = units[p.first_unit].utterances[0].first
        last = units[p.last_unit].utterances[-1].last
        try:
            cut = snap.snap(words, first, last)
        except snap.Reject:
            continue
        c = scoring.Candidate(
            start=cut.start, end=cut.end, words=words[cut.first:cut.last + 1],
            standalone=p.standalone, hook=p.hook, payoff=p.payoff, reason=p.reason,
        )
        if scoring.structural_reject(c):
            continue
        out.append(scoring.score(c, loudness))
    return out


def _text(c: scoring.Candidate) -> str:
    return " ".join(w.t for w in c.words)


def _to_clip(c: scoring.Candidate, meta: titles.Titles) -> Clip:
    flags = [*scoring.qa_flags(c), *c.flags]
    if not scoring.passes_thresholds(c) and "weak_pick" not in flags:
        flags.append("weak_pick")
    return Clip(
        start=c.start, end=c.end, text=_text(c), score=round(c.total * 10, 1), tag=meta.tag,
        hook_title=meta.hook_title, emphasis=meta.emphasis, flags=flags,
        standalone=c.standalone, hook=c.hook, payoff=c.payoff,
        energy=c.energy, duration_fit=c.duration_fit, reason=c.reason,
    )


def _alternates(candidates: list[scoring.Candidate], kept: list[scoring.Candidate]) -> list[dict]:
    out: list[dict] = []
    chosen: list[tuple[float, float]] = [(k.start, k.end) for k in kept]
    for i, c in enumerate(sorted(candidates, key=lambda c: c.total, reverse=True)):
        if len(out) >= MAX_ALTERNATES:
            break
        span = (c.start, c.end)
        if any(scoring.span_overlap(span, s) >= scoring.MAX_OVERLAP for s in chosen):
            continue
        chosen.append(span)
        clip = _to_clip(c, titles.fallback(_text(c), i))
        out.append({
            "start": clip.start, "end": clip.end, "text": clip.text, "score": clip.score,
            "tag": clip.tag, "flags": clip.flags, "reason": clip.reason, "emphasis": clip.emphasis,
        })
    return out


def alternate_to_clip(d: dict) -> Clip:
    return Clip(
        start=float(d["start"]), end=float(d["end"]), text=d.get("text", ""), score=float(d.get("score", 0.0)),
        tag=d.get("tag") or titles.TAGS[0], emphasis=list(d.get("emphasis") or []),
        flags=list(d.get("flags") or []), reason=d.get("reason", ""),
    )


def select(segments: list[Segment], loudness: list[float], *, chat=None) -> Selection:
    if chat is None:
        chat = groq_llm.build_chat()
    if chat is None:
        raise SelectionFailed("Clip selection needs GROQ_KEY.")

    utterances = build_utterances(segments)
    if not utterances:
        return Selection([])
    units = build_thought_units(utterances)
    ranked = ranker.rank(chat, units)
    words = flat_words(utterances)

    candidates = _candidates(words, units, ranked.picks, loudness)
    kept = scoring.pack(candidates)
    texts = [_text(c) for c in kept]
    meta, titles_ok = titles.write_titles(chat, texts)
    clips = [_to_clip(c, m) for c, m in zip(kept, meta)]

    notes = [skipped_note(ranked.skipped)]
    if not kept:
        notes.append(ZERO_CLIPS_NOTE)
    elif not titles_ok:
        notes.append(TITLES_FAILED_NOTE)
    return Selection(clips, " ".join(n for n in notes if n) or None, alternates=_alternates(candidates, kept))


def regenerate(
    segments: list[Segment], loudness: list[float], current: tuple[float, float],
    avoid: list[tuple[float, float]], *, chat=None,
) -> Clip | None:
    """A fresh take on one clip: re-rank the transcript around it and pick
    the best candidate that is not the same moment and does not collide
    with the job's other clips."""
    if chat is None:
        chat = groq_llm.build_chat()
    if chat is None:
        raise SelectionFailed("Regenerate needs GROQ_KEY.")
    utterances = build_utterances(segments)
    if not utterances:
        return None
    units = [u for u in build_thought_units(utterances)
             if u.end >= current[0] - REGENERATE_MARGIN_S and u.start <= current[1] + REGENERATE_MARGIN_S]
    if not units:
        return None
    ranked = ranker.rank(chat, units)
    words = flat_words(utterances)
    fresh = [
        c for c in _candidates(words, units, ranked.picks, loudness)
        if scoring.span_overlap((c.start, c.end), current) < SAME_MOMENT_OVERLAP
        and all(scoring.span_overlap((c.start, c.end), a) < scoring.MAX_OVERLAP for a in avoid)
    ]
    usable = [c for c in fresh if scoring.passes_thresholds(c)] or [c for c in fresh if scoring.near_miss(c)]
    if not usable:
        return None
    best = max(usable, key=lambda c: c.total)
    meta, _ = titles.write_titles(chat, [_text(best)])
    return _to_clip(best, meta[0])
