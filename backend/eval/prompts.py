"""Ranker prompts under evaluation. `current` is what production uses
(ranker.PROMPT); candidates live here until the comparison script shows they
do better, then replace ranker.PROMPT. Every template has {transcript} and
{n} slots, with literal braces doubled. `clock` adds each utterance's start
time (m:ss) to the transcript lines."""
from __future__ import annotations

from dataclasses import dataclass

from ..pipeline import ranker


@dataclass(frozen=True)
class Variant:
    template: str
    clock: bool = False
    rerank: bool = False  # add the shortlist pass (pipeline/shortlist.py)


V2 = """You pick short-form clips (Reels, Shorts, TikTok) from a podcast transcript. Each line is one utterance: "<id> [m:ss]: <text>", where m:ss is when it starts. A blank line separates complete thoughts. The text mixes English with Roman-script Hindi/Urdu.

{transcript}

Pick up to {n} clips that a stranger scrolling past would stop for, watch to the end, and understand with no other context. Each clip is a range of utterances from "s" to "e" (ids from above).

A strong clip opens with one of these in its first sentence:
- a bold or surprising claim ("Most people think X. That's wrong.")
- a specific number, result or stake ("He lost 40 crore in one night.")
- a question the clip itself answers
- the start of a short story with tension
- a strong opinion, emotion or confession
and ends on a payoff: the answer, the twist, the lesson, or a line that lands.

Never pick:
- sponsor reads, ads, course or product plugs, "link in description", "subscribe", "follow", giveaways;
- intros, outros, greetings, "welcome back", housekeeping;
- anything that leans on earlier context ("as I said", "that thing", "he" with no name given in the clip), or an answer whose question is not in the clip;
- a range that starts on toh, matlab, uh, um, so or like, or ends on lekin, kyunki, aur, but or because.

Length: from the start of "s" to the end of "e" should be about 15-45 seconds, never over 55. Use the m:ss times to check.

For each clip, first write "reason" (at most 12 words: what the hook is and how it pays off), then score from 0 to 1:
- "standalone": makes complete sense to a stranger
- "hook": how hard the first 3 seconds grab a scrolling viewer
- "payoff": how satisfying the ending is
Scale: 0.9 = you would post it today, 0.7 = good, 0.5 = okay, 0.3 = weak. Most picks should score below 0.8; reserve 0.9 for the best moment in this part. Set "starts_mid" or "ends_mid" to true if it starts or ends in the middle of a thought.

Reply with ONLY a JSON array, no prose:
[{{"s":"u12","e":"u19","reason":"surprising cost figure, ends with why it matters","standalone":0.8,"hook":0.7,"payoff":0.6,"starts_mid":false,"ends_mid":false}}]
If nothing here is worth clipping, reply [].
"""

VARIANTS: dict[str, Variant] = {
    "current": Variant(ranker.PROMPT),
    "v2": Variant(V2, clock=True),
    "current+rerank": Variant(ranker.PROMPT, rerank=True),
    "v2+rerank": Variant(V2, clock=True, rerank=True),
}
