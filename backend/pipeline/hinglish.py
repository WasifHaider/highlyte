"""Fix Whisper's Roman text in code: a glossary for names and brands, and
one house spelling for Roman Hindi/Urdu that Indian and Pakistani readers
both recognise (ye, woh, toh, bohat, farq, kyunki).

Both lists are plain JSON in data/ so they can grow without code changes.
A spelling key is never an English word (a test enforces it), so English
words like "to" or "the" are never rewritten.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from .segments import SegWord

DATA = Path(__file__).parent / "data"
_EDGE_RE = re.compile(r"^(\W*)(.*?)(\W*)$", re.UNICODE)


@lru_cache(maxsize=1)
def _glossary() -> dict[tuple[str, ...], str]:
    raw = json.loads((DATA / "glossary.json").read_text(encoding="utf-8"))
    return {tuple(k.split()): v for k, v in raw.items()}


@lru_cache(maxsize=1)
def _spelling() -> dict[str, str]:
    return json.loads((DATA / "spelling.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _english() -> frozenset[str]:
    return frozenset((DATA / "english_words.txt").read_text(encoding="utf-8").split())


@lru_cache(maxsize=1)
def _also_english() -> frozenset[str]:
    return frozenset((DATA / "hinglish_also_english.txt").read_text(encoding="utf-8").split())


def _split(text: str) -> tuple[str, str, str]:
    pre, core, post = _EDGE_RE.match(text).groups()
    return pre, core, post


def apply_glossary(words: list[SegWord]) -> list[SegWord]:
    glossary = _glossary()
    longest = max((len(k) for k in glossary), default=1)
    out: list[SegWord] = []
    i = 0
    while i < len(words):
        for n in range(min(longest, len(words) - i), 0, -1):
            span = words[i:i + n]
            key = tuple(_split(x.t)[1].lower() for x in span)
            if key in glossary:
                pre = _split(span[0].t)[0]
                post = _split(span[-1].t)[2]
                prob = 1.0
                for x in span:
                    prob *= x.prob
                out.append(replace(
                    span[0], t=pre + glossary[key] + post, raw=" ".join(x.raw for x in span),
                    end=span[-1].end, prob=round(prob, 3),
                ))
                i += n
                break
        else:
            out.append(words[i])
            i += 1
    return out


def apply_spelling(words: list[SegWord]) -> list[SegWord]:
    spelling = _spelling()
    out = []
    for x in words:
        pre, core, post = _split(x.t)
        fixed = spelling.get(core.lower())
        if fixed is None:
            out.append(x)
            continue
        if core[:1].isupper():
            fixed = fixed[:1].upper() + fixed[1:]
        out.append(replace(x, t=pre + fixed + post))
    return out


def classify(text: str) -> str:
    core = _split(text)[1]
    if core.replace(".", "").replace(",", "").isdigit():
        return "num"
    low = core.lower()
    if low in _also_english():
        return "hinglish"
    if low in _english() or any(core == v for v in _glossary().values()):
        return "en"
    return "hinglish"


def fix(words: list[SegWord], language: str) -> list[SegWord]:
    words = apply_glossary(words)
    if language == "hinglish":
        words = apply_spelling(words)
    return [replace(x, kind=classify(x.t)) for x in words]
