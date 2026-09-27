"""Validation for caption text edited on a clip card.

The editor (renderer/src/captions/edit.ts) retimes words in the browser;
the backend only checks the result is sane before storing it as the
clip's spec.words, which both the preview and the Lambda export read.
"""
from __future__ import annotations

import math
from typing import Any

from .spec import Word

MAX_WORDS = 3000
MAX_WORD_CHARS = 40
# Word ends may run a touch past the clip end (the tail padding).
END_SLACK_S = 0.5


def validate_words(raw: list[dict[str, Any]], clip_length: float) -> list[Word]:
    if not raw:
        raise ValueError("Captions need at least one word.")
    if len(raw) > MAX_WORDS:
        raise ValueError(f"Captions can have at most {MAX_WORDS} words.")
    out: list[Word] = []
    prev_start = 0.0
    for i, item in enumerate(raw, start=1):
        word = Word.model_validate(item)
        text = word.text.strip()
        if not text:
            raise ValueError(f"Word {i} is empty.")
        if "\n" in text or "\r" in text:
            raise ValueError(f"Word {i} contains a line break.")
        if len(text) > MAX_WORD_CHARS:
            raise ValueError(f"Word {i} is too long (max {MAX_WORD_CHARS} characters).")
        if not (math.isfinite(word.start) and math.isfinite(word.end)):
            raise ValueError(f"Word {i} has a time outside the clip.")
        if word.start < 0 or word.end < word.start or word.end > clip_length + END_SLACK_S:
            raise ValueError(f"Word {i} has a time outside the clip.")
        if word.start < prev_start:
            raise ValueError(f"Word {i} is out of order.")
        prev_start = word.start
        out.append(word.model_copy(update={"text": text}))
    return out
