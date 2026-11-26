"""Second pass of clip selection: the ranker scores each transcript window
on its own, so a decent pick from a dull window can outscore a great one
from a strong window. This pass shows the best candidates from the whole
video side by side in one call and asks for an order. It is optional: when
the call fails for any reason the caller keeps its own order.
"""
from __future__ import annotations

import json
import re

from .groq_llm import BadAnswer

SHORTLIST_SIZE = 20
MAX_TOKENS = 1500

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

PROMPT = """These are candidate short-form clips (Reels, Shorts, TikTok) cut from one podcast. Each is "<id>: <text>". The text mixes English with Roman-script Hindi/Urdu.

{clips}

Rank all of them from best to worst. A better clip grabs a scrolling stranger in its first sentence, makes sense with no other context, and ends on a payoff. Sponsor reads, plugs, intros and clips that lean on earlier context go last.

Reply with ONLY a JSON array of every id, best first, no prose:
["c3","c1","c2"]
"""


def rerank(chat, texts: list[str]) -> list[int] | None:
    """Indices into `texts`, best first, or None when the call or its answer
    fails. Ids the model leaves out keep their original order at the end."""
    if chat is None or len(texts) < 2:
        return None
    clips = "\n\n".join(f"c{i + 1}: {t}" for i, t in enumerate(texts))
    try:
        result = chat.complete(PROMPT.format(clips=clips), max_tokens=MAX_TOKENS)
        if result.finish_reason == "length":
            raise BadAnswer("cut off at the token limit")
        match = _JSON_ARRAY_RE.search(result.content or "")
        if not match:
            raise BadAnswer("answer had no JSON array")
        ids = json.loads(match.group(0))
        if not isinstance(ids, list):
            raise BadAnswer("answer was not a list")
    except Exception as e:  # noqa: BLE001
        print(f"[shortlist] skipped: {e}")
        return None
    order: list[int] = []
    for item in ids:
        if isinstance(item, str) and re.fullmatch(r"c\d+", item):
            i = int(item[1:]) - 1
            if 0 <= i < len(texts) and i not in order:
                order.append(i)
    if not order:
        print("[shortlist] skipped: no usable ids")
        return None
    return order + [i for i in range(len(texts)) if i not in order]
