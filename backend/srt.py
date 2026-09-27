"""SubRip captions for a clip. Pages follow the caption editor's lines
(renderer/src/captions/edit.ts: 14 words / 84 characters), built with a
Python port of renderer/src/captions/paginate.ts. Both sides are checked
against renderer/src/__fixtures__/paginate-cases.json so they can't drift.
"""
from __future__ import annotations

import re
from typing import Any

LINE_MAX_WORDS = 14
LINE_MAX_CHARS = 84
PAUSE_BREAK_S = 0.4
_ENDS_SENTENCE = re.compile(r"[.!?…][\"')\]]?$")


def paginate(words: list[dict[str, Any]], max_words: int, max_chars: float = float("inf")) -> list[list[int]]:
    pages: list[list[int]] = []
    cur: list[int] = []
    for i, word in enumerate(words):
        chars = sum(len(words[j]["text"]) + 1 for j in cur) + len(word["text"])
        if cur and chars > max_chars:
            pages.append(cur)
            cur = []
        cur.append(i)
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = nxt is not None and nxt["start"] - word["end"] > PAUSE_BREAK_S
        if len(cur) >= max_words or _ENDS_SENTENCE.search(word["text"]) or pause:
            pages.append(cur)
            cur = []
    if cur:
        pages.append(cur)
    return pages


def clip_words(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Words in clip time: v2 specs hold the whole cut file, so keep the
    words overlapping the clip and shift them (renderer toClipTime)."""
    words = spec.get("words") or []
    if spec.get("version") != 2:
        return list(words)
    start, end = float(spec["start"]), float(spec["end"])
    return [
        {**w, "start": round(w["start"] - start, 3), "end": round(w["end"] - start, 3)}
        for w in words if w["end"] > start and w["start"] < end
    ]


def _stamp(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(spec: dict[str, Any]) -> str:
    words = clip_words(spec)
    length = float(spec["end"]) - float(spec["start"])
    blocks = []
    for n, page in enumerate(paginate(words, LINE_MAX_WORDS, LINE_MAX_CHARS), start=1):
        first, last = words[page[0]], words[page[-1]]
        start = max(0.0, first["start"])
        end = min(length, max(last["end"], start))
        text = " ".join(words[i]["text"] for i in page)
        blocks.append(f"{n}\n{_stamp(start)} --> {_stamp(end)}\n{text}\n")
    return "\n".join(blocks)
