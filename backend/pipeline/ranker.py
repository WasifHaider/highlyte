"""The LLM ranker (spec section 2). It shows the transcript to the model
in windows of thought units and gets back picks by utterance id. The
model never sees or returns timestamps; snap.py places every cut."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .groq_llm import CHARS_PER_TOKEN, BadAnswer, DailyLimit, SelectionFailed, is_auth_failure, is_rate_limit
from .utterances import ThoughtUnit

WINDOW_TOKENS = 4500
OVERLAP_S = 60.0
PICKS_PER_WINDOW = 6
MAX_TOKENS = 1500

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

PROMPT = """You pick short-form clips from a podcast transcript. Each line is one utterance: "<id>: <text>". A blank line separates complete thoughts. The text mixes English with Roman-script Hindi/Urdu.

{transcript}

Pick up to {n} clips. Each clip is a range of utterances from "s" to "e" (ids from above) that:
- makes sense to someone who has seen nothing else of this podcast;
- is one complete idea: setup and payoff, question and answer, or claim and explanation;
- lasts about 12-35 seconds;
- never starts on toh, matlab, uh, um, so or like;
- never ends on lekin, kyunki, aur, but or because.

Score each from 0 to 1: "standalone" (makes sense alone), "hook" (how hard its first 3 seconds grab a scrolling viewer), "payoff" (how satisfying its ending is). Set "starts_mid" or "ends_mid" to true if it starts or ends in the middle of a thought.

Reply with ONLY a JSON array, no prose:
[{{"s":"u12","e":"u19","standalone":0.8,"hook":0.7,"payoff":0.6,"starts_mid":false,"ends_mid":false,"reason":"at most 12 words"}}]
If nothing here is worth clipping, reply [].
"""


@dataclass
class Pick:
    first_unit: int
    last_unit: int
    standalone: float
    hook: float
    payoff: float
    reason: str = ""


@dataclass
class Skipped:
    start: float
    end: float
    reason: str  # "rate limit" | "daily limit" | "error"


@dataclass
class RankResult:
    picks: list[Pick]
    skipped: list[Skipped] = field(default_factory=list)


def _unit_chars(unit: ThoughtUnit) -> int:
    return sum(len(u.id) + 2 + len(u.text) + 1 for u in unit.utterances) + 1


def windows(units: list[ThoughtUnit]) -> list[list[int]]:
    """Unit indices per LLM call, broken only between units. Each window
    repeats the previous window's last OVERLAP_S seconds of units, so a
    clip straddling a boundary fits whole in one window."""
    budget = WINDOW_TOKENS * CHARS_PER_TOKEN
    out: list[list[int]] = []
    cur: list[int] = []
    chars = 0
    for i, unit in enumerate(units):
        size = _unit_chars(unit)
        if cur and chars + size > budget:
            out.append(cur)
            tail_from = units[cur[-1]].end - OVERLAP_S
            carry = [j for j in cur if units[j].start >= tail_from]
            if len(carry) == len(cur):
                carry = carry[1:]
            cur, chars = carry, sum(_unit_chars(units[j]) for j in carry)
        cur.append(i)
        chars += size
    if cur:
        out.append(cur)
    return out


def format_window(units: list[ThoughtUnit], idxs: list[int]) -> str:
    return "\n\n".join("\n".join(f"{u.id}: {u.text}" for u in units[i].utterances) for i in idxs)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def parse_picks(content: str, units: list[ThoughtUnit], idxs: list[int]) -> list[Pick]:
    match = _JSON_ARRAY_RE.search(content or "")
    if not match:
        raise BadAnswer("answer had no JSON array")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise BadAnswer(f"unreadable JSON: {e}") from e
    if not isinstance(data, list):
        raise BadAnswer("answer was not a list")

    unit_of = {u.id: i for i in idxs for u in units[i].utterances}
    picks: list[Pick] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        s, e = item.get("s"), item.get("e")
        if not isinstance(s, str) or not isinstance(e, str) or s not in unit_of or e not in unit_of:
            continue
        if item.get("starts_mid") is True or item.get("ends_mid") is True:
            continue
        try:
            standalone, hook, payoff = (_clamp01(float(item[k])) for k in ("standalone", "hook", "payoff"))
        except (KeyError, TypeError, ValueError):
            continue
        first, last = sorted((unit_of[s], unit_of[e]))
        picks.append(Pick(first, last, standalone, hook, payoff, reason=str(item.get("reason", ""))[:120]))
    return picks


def _rank_window(chat, units: list[ThoughtUnit], idxs: list[int]) -> list[Pick]:
    prompt = PROMPT.format(transcript=format_window(units, idxs), n=PICKS_PER_WINDOW)
    last_error: BadAnswer | None = None
    for _ in range(2):  # one retry for a cut-off or unreadable answer
        result = chat.complete(prompt, max_tokens=MAX_TOKENS)
        try:
            if result.finish_reason == "length":
                raise BadAnswer("cut off at the token limit")
            return parse_picks(result.content, units, idxs)
        except BadAnswer as e:
            last_error = e
    assert last_error is not None
    raise last_error


def rank(chat, units: list[ThoughtUnit]) -> RankResult:
    wins = windows(units)
    picks: list[Pick] = []
    skipped: list[Skipped] = []
    daily_wait: str | None = None
    daily = False
    last_error: Exception | None = None
    for n, idxs in enumerate(wins):
        start, end = units[idxs[0]].start, units[idxs[-1]].end
        try:
            picks.extend(_rank_window(chat, units, idxs))
        except DailyLimit as e:
            # Spend nothing more today: skip this window and every later one.
            daily, daily_wait = True, e.wait
            skipped.extend(Skipped(units[w[0]].start, units[w[-1]].end, "daily limit") for w in wins[n:])
            break
        except Exception as e:  # noqa: BLE001
            print(f"[ranker] window {start:.0f}-{end:.0f}s skipped: {e}")
            last_error = e
            skipped.append(Skipped(start, end, "rate limit" if is_rate_limit(e) else "error"))

    if wins and len(skipped) == len(wins):
        if daily:
            raise SelectionFailed(
                "Clip selection hit Groq's daily limit."
                + (f" Try again in {daily_wait}." if daily_wait else " Try again later.")
            )
        if last_error is not None and is_auth_failure(last_error):
            raise SelectionFailed("Clip selection couldn't reach Groq: the API key was rejected. Check GROQ_KEY.")
        raise SelectionFailed("Clip selection failed for this video. Try again.")
    return RankResult(picks, skipped)
