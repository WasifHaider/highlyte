"""Ad-hoc verification for the reworked highlight.py — not part of the
pipeline, just exercised manually to confirm clip boundaries land on
sentence edges instead of mid-sentence."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pipeline.transcript import TranscriptSegment
from backend.pipeline.highlight import (
    _split_sentences,
    _group_candidates,
    score_chunks_heuristic,
    _select_clips,
    detect_highlights,
    MIN_CLIP_S,
)

# Build a synthetic transcript designed so that OLD fixed 45s tumbling
# windows would slice mid-sentence: long run-on sentences straddling the
# 45s/90s/135s marks, deliberately with no punctuation near those marks.
SEGMENTS = []
t = 0.0


def seg(text, dur, gap=0.15):
    global t
    SEGMENTS.append(TranscriptSegment(start=t, end=t + dur, text=text))
    t += dur + gap


# Sentence 1 (0s - ~14s): honest opinion, spans across where a 45s window
# wouldn't cut it, but chosen to show sentence grouping works at small scale.
seg("So honestly I think the biggest mistake founders make", 4.0)
seg("is they build the product before they've talked to a single customer", 5.0)
seg("and by the time they launch it's already wrong.", 4.0)

# Pause (bigger gap) then a new thought, no terminal punctuation immediately
t += 0.8  # extra pause to force a boundary
seg("Honestly the truth is most people are scared of rejection", 4.0)
seg("so they'd rather guess in a vacuum for six months", 4.0)
seg("than go ask ten strangers if they'd actually pay for this thing", 5.0)
seg("and that fear alone kills more startups than bad code ever will.", 5.0)

t += 0.7
seg("Wait, here's the crazy part though", 3.0)
seg("the founders who DO talk to customers early", 4.0)
seg("almost always end up building something completely different", 4.0)
seg("from what they originally pitched, and it's usually way better.", 5.0)

t += 0.6
seg("Um so yeah anyway", 1.5)
seg("that's basically the whole insight, honestly.", 3.0)


def check_no_mid_sentence_cuts(clips, sentences):
    print(f"\n{len(clips)} clip(s) produced:")
    sentence_starts = {round(s.start, 2) for s in sentences}
    sentence_ends = {round(s.end, 2) for s in sentences}
    all_ok = True
    for c in clips:
        start_ok = any(abs(c.start - s) < 0.05 for s in sentence_starts)
        end_ok = any(abs(c.end - s) < 0.05 for s in sentence_ends)
        status = "OK" if (start_ok and end_ok) else "MID-SENTENCE CUT"
        if not (start_ok and end_ok):
            all_ok = False
        print(f"  [{status}] {c.start:6.2f}s -> {c.end:6.2f}s  score={c.score:5.2f}  tag={c.tag!r}")
        print(f"      text: {c.text[:100]}")
    return all_ok


sentences = _split_sentences(SEGMENTS)
print("=== Sentence segmentation ===")
for s in sentences:
    print(f"  [{s.idx}] {s.start:6.2f}-{s.end:6.2f}: {s.text}")

print("\n=== Heuristic (offline) path ===")
os.environ.pop("GROQ_KEY", None)
clips = detect_highlights(SEGMENTS)
ok = check_no_mid_sentence_cuts(clips, sentences)
print(f"\nAll clips land on sentence boundaries: {ok}")
assert ok, "heuristic path produced a mid-sentence cut"
assert all(c.end - c.start >= MIN_CLIP_S for c in clips), "clip under MIN_CLIP_S"

# Check filler trim: last sentence has leading filler "Um so yeah" merged
# into the sentence before it via short-gap grouping isn't guaranteed here,
# so directly unit-test _trim_leading_filler via a manual chunk.
from backend.pipeline.highlight import _trim_leading_filler

filler_sentences = [s for s in sentences if "Um so yeah" in s.text or "basically the whole insight" in s.text]
if len(filler_sentences) >= 1:
    new_start, new_text = _trim_leading_filler(filler_sentences)
    print(f"\nFiller trim test: start={new_start}, text={new_text!r}")

print("\nALL CHECKS PASSED")
