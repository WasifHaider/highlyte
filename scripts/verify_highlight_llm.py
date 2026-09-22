"""Verify the LLM-driven boundary selection path with a mocked Groq client
(no real network/API-key needed) — checks JSON span parsing, sentence-index
-> timestamp mapping, and that overlap suppression still enforces sentence
boundaries end to end."""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pipeline import highlight as hl
from backend.pipeline.transcript import TranscriptSegment

SEGMENTS = []
t = 0.0


def seg(text, dur, gap=0.15):
    global t
    SEGMENTS.append(TranscriptSegment(start=t, end=t + dur, text=text))
    t += dur + gap


seg("So honestly I think the biggest mistake founders make", 4.0)
seg("is they build the product before they've talked to a single customer", 5.0)
seg("and by the time they launch it's already wrong.", 4.0)
t += 0.8
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

sentences = hl._split_sentences(SEGMENTS)
print("Sentence count:", len(sentences))
for s in sentences:
    print(f"  [{s.idx}] {s.start:.2f}-{s.end:.2f}")


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResp:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def create(self, model, messages, max_tokens):
        # Simulate the LLM picking spans by sentence index directly.
        spans = [
            {"start_idx": 0, "end_idx": 0, "hook_score": 7.5, "reason": "opinion", "tag": "Strong opinion"},
            {"start_idx": 1, "end_idx": 2, "hook_score": 9.0, "reason": "setup->payoff", "tag": "Key insight"},
        ]
        return FakeResp(json.dumps(spans))


class FakeChat:
    completions = FakeCompletions()


class FakeClient:
    chat = FakeChat()


sentences_by_idx = {s.idx: s for s in sentences}
clips = hl._llm_score_window(FakeClient(), sentences, sentences_by_idx)
print("\nRaw LLM-derived candidate clips:")
for c in clips:
    print(f"  {c.start:.2f}-{c.end:.2f} score={c.score} tag={c.tag} text={c.text[:60]!r}")

assert len(clips) == 2
assert clips[0].start == sentences[0].start and clips[0].end == sentences[0].end
assert clips[1].start == sentences[1].start and clips[1].end == sentences[2].end

final = hl._select_clips(clips, sentences)
print("\nFinal selected clips (post snap/filler/overlap):")
sentence_starts = {round(s.start, 2) for s in sentences}
sentence_ends = {round(s.end, 2) for s in sentences}
for c in final:
    start_ok = any(abs(c.start - s) < 0.05 for s in sentence_starts)
    end_ok = any(abs(c.end - s) < 0.05 for s in sentence_ends)
    print(f"  [{'OK' if start_ok and end_ok else 'MID-SENTENCE'}] {c.start:.2f}-{c.end:.2f} tag={c.tag}")
    assert start_ok and end_ok

print("\nALL LLM-PATH CHECKS PASSED")


# Also verify score_chunks_llm_boundaries() end-to-end via monkeypatched
# openai.OpenAI + GROQ_KEY, confirming detect_highlights() picks the LLM
# path when the key is present.
import backend.pipeline.highlight as hl_mod

os.environ["GROQ_KEY"] = "fake-key-for-test"


class FakeOpenAIModule(SimpleNamespace):
    pass


import openai as real_openai_module

orig_OpenAI = real_openai_module.OpenAI
real_openai_module.OpenAI = lambda **kwargs: FakeClient()
try:
    clips2 = hl_mod.detect_highlights(SEGMENTS)
    print(f"\ndetect_highlights() with GROQ_KEY set -> {len(clips2)} clip(s)")
    for c in clips2:
        print(f"  {c.start:.2f}-{c.end:.2f} tag={c.tag}")
    assert len(clips2) >= 1
finally:
    real_openai_module.OpenAI = orig_OpenAI
    os.environ.pop("GROQ_KEY", None)

print("\nALL END-TO-END LLM-PATH CHECKS PASSED")
