"""Hook titles, emphasis words and tags for the final clips: one small
LLM call over the winners only (spec section 3). Failure is harmless:
clips keep code-picked emphasis and a keyword tag, and no hook title."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .groq_llm import BadAnswer
from .utterances import norm

TAGS = ["Strong opinion", "Key insight", "Funny moment", "Actionable advice", "Contrarian take", "Wild claim"]
HOOK_TITLE_MAX_WORDS = 8
MAX_EMPHASIS_WORDS = 5
CODE_EMPHASIS_WORDS = 3
MAX_TOKENS = 1200
_MIN_EMPHASIS_LEN = 4

STOPWORDS = {
    "that", "this", "with", "have", "from", "they", "there", "their", "what", "when", "where",
    "which", "would", "could", "should", "about", "just", "like", "really", "because", "then",
    "than", "them", "were", "been", "your", "into", "some", "very", "also",
    "hai", "hain", "tha", "thi", "the", "kya", "kyun", "kyunki", "lekin", "matlab", "toh",
    "yeh", "woh", "voh", "aur", "bhi", "nahi", "nahin", "mein", "main", "hum", "tum", "aap",
    "kuch", "sab", "abhi", "phir", "karo", "kar", "raha", "rahe", "rahi", "wala", "wali",
    "yaar", "bhai", "haan", "acha", "achha", "isliye", "yaani", "warna",
}

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

PROMPT = """You write short-form video metadata for podcast clips. The text mixes English with Roman-script Hindi/Urdu.

{clips}

For each clip id above return:
- "hook_title": at most 8 words, punchy, in the same language mix the speakers use;
- "emphasis": up to 5 single words copied exactly from that clip's text that carry its meaning;
- "tag": one of {tags}.

Reply with ONLY a JSON array, no prose:
[{{"id":"c1","hook_title":"...","emphasis":["..."],"tag":"Key insight"}}]
"""


@dataclass
class Titles:
    hook_title: str | None
    emphasis: list[str]
    tag: str


def pick_tag(text: str, idx: int) -> str:
    lower = text.lower()
    if "?" in text and any(w in lower for w in ["what", "how", "kya", "kaise"]):
        return "Key insight"
    if any(w in lower for w in ["lol", "funny", "haha", "hilarious"]):
        return "Funny moment"
    if any(w in lower for w in ["should", "you need to", "try this", "karo", "chahiye"]):
        return "Actionable advice"
    if any(w in lower for w in ["everyone says", "actually", "myth", "wrong"]):
        return "Contrarian take"
    if any(w in lower for w in ["insane", "crazy", "wild", "hairan"]):
        return "Wild claim"
    return TAGS[idx % len(TAGS)]


def code_emphasis(text: str) -> list[str]:
    seen: set[str] = set()
    words: list[str] = []
    for token in text.split():
        n = norm(token)
        if len(n) < _MIN_EMPHASIS_LEN or n in STOPWORDS or n in seen:
            continue
        seen.add(n)
        words.append(n)
    return sorted(words, key=len, reverse=True)[:CODE_EMPHASIS_WORDS]


def fallback(text: str, idx: int) -> Titles:
    return Titles(None, code_emphasis(text), pick_tag(text, idx))


def _parse(content: str, texts: list[str]) -> list[Titles]:
    match = _JSON_ARRAY_RE.search(content or "")
    if not match:
        raise BadAnswer("answer had no JSON array")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise BadAnswer(f"unreadable JSON: {e}") from e
    if not isinstance(data, list):
        raise BadAnswer("answer was not a list")
    by_id = {item["id"]: item for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)}

    out: list[Titles] = []
    for i, text in enumerate(texts):
        item = by_id.get(f"c{i + 1}")
        if item is None:
            out.append(fallback(text, i))
            continue
        title = item.get("hook_title")
        hook = " ".join(title.split()[:HOOK_TITLE_MAX_WORDS]) if isinstance(title, str) and title.strip() else None
        present = {norm(t) for t in text.split()}
        raw = item.get("emphasis") if isinstance(item.get("emphasis"), list) else []
        emphasis: list[str] = []
        for word in raw:
            n = norm(word) if isinstance(word, str) else ""
            if n and n in present and n not in emphasis:
                emphasis.append(n)
        tag = item.get("tag")
        out.append(Titles(
            hook_title=hook,
            emphasis=emphasis[:MAX_EMPHASIS_WORDS] or code_emphasis(text),
            tag=tag if isinstance(tag, str) and tag in TAGS else pick_tag(text, i),
        ))
    return out


def write_titles(chat, texts: list[str]) -> tuple[list[Titles], bool]:
    if not texts:
        return [], True
    if chat is None:
        return [fallback(t, i) for i, t in enumerate(texts)], False
    clips = "\n\n".join(f"c{i + 1}: {t}" for i, t in enumerate(texts))
    try:
        result = chat.complete(PROMPT.format(clips=clips, tags=", ".join(TAGS)), max_tokens=MAX_TOKENS)
        if result.finish_reason == "length":
            raise BadAnswer("cut off at the token limit")
        return _parse(result.content, texts), True
    except Exception as e:  # noqa: BLE001
        print(f"[titles] skipped: {e}")
        return [fallback(t, i) for i, t in enumerate(texts)], False
