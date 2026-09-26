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

__all__ = ["Clip", "Selection", "SelectionFailed", "select", "skipped_note"]

TITLES_FAILED_NOTE = "Hook titles could not be written this time."


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


@dataclass
class Selection:
    clips: list[Clip]
    note: str | None = None


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

    candidates: list[scoring.Candidate] = []
    for p in ranked.picks:
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
        candidates.append(scoring.score(c, loudness))

    kept = scoring.pack(candidates)
    texts = [" ".join(w.t for w in c.words) for c in kept]
    meta, titles_ok = titles.write_titles(chat, texts)
    clips = [
        Clip(
            start=c.start, end=c.end, text=text, score=round(c.total * 10, 1), tag=m.tag,
            hook_title=m.hook_title, emphasis=m.emphasis, flags=[*scoring.qa_flags(c), *c.flags],
            standalone=c.standalone, hook=c.hook, payoff=c.payoff,
            energy=c.energy, duration_fit=c.duration_fit,
        )
        for c, text, m in zip(kept, texts, meta)
    ]

    notes = [skipped_note(ranked.skipped)]
    if kept and not titles_ok:
        notes.append(TITLES_FAILED_NOTE)
    return Selection(clips, " ".join(n for n in notes if n) or None)
