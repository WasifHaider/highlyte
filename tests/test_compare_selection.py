import json

import pytest

from backend.eval import compare_selection as cs
from backend.eval.prompts import V2, VARIANTS
from backend.pipeline import ranker
from backend.pipeline.groq_llm import ChatResult
from tests.llm_fakes import FakeChat
from tests.test_selection import pick, transcript


def kept(start, end):
    return cs.Kept(start, end, 0.8, 0.9, 0.8, 0.7, "r", "text", False)


def test_variants_format_with_both_slots():
    for v in VARIANTS.values():
        text = v.template.format(transcript="TRANSCRIPT", n=6)
        assert "TRANSCRIPT" in text and "{" not in text.replace("{\"s\"", "").replace('[{"', "")
    assert VARIANTS["current"].template == ranker.PROMPT and not VARIANTS["current"].clock
    assert VARIANTS["v2"].template == V2 and VARIANTS["v2"].clock


def test_recorded_answers_replay_to_the_same_result():
    answer = json.dumps([pick("u1", "u1"), pick("u2", "u2")])
    rec = cs.RecordingChat(FakeChat([answer]))
    first = cs.run_once(transcript(), [], rec, "current", 1)
    again = cs.run_once(transcript(), [], cs.ReplayChat(first.answers), "current", 1)
    assert [(k.start, k.end) for k in again.kept] == [(k.start, k.end) for k in first.kept]
    assert first.calls == 1 and first.est_tokens > 0


def test_replay_refuses_a_changed_prompt():
    saved = [{"prompt_sha": "000000000000", "content": "[]", "finish_reason": "stop"}]
    with pytest.raises(RuntimeError, match="prompt changed"):
        cs.ReplayChat(saved).complete("a different prompt", max_tokens=10)


def test_gold_found_counts_moments_covered_by_a_kept_clip():
    gold = [[10.0, 30.0], [100.0, 120.0], [300.0, 330.0]]
    assert cs.gold_found([kept(12.0, 32.0), kept(305.0, 312.0)], gold) == 2


def test_recurrence_groups_the_same_moment_across_runs():
    runs = [
        cs.Run("v", 1, [kept(10, 30), kept(100, 120)], 2, 2, [], {}, 1, 0),
        cs.Run("v", 2, [kept(11, 31)], 1, 1, [], {}, 1, 0),
    ]
    assert [(k.start, n) for k, n in cs.recurrence(runs)] == [(10, 2), (100, 1)]


def test_run_once_counts_drop_reasons(monkeypatch):
    from backend.pipeline import scoring

    monkeypatch.setattr(scoring, "MIN_CLIP_S", 30.0)   # every 20 s pick is now too short
    rec = cs.RecordingChat(FakeChat([json.dumps([pick("u1", "u1"), pick("u2", "u2")])]))
    run = cs.run_once(transcript(), [], rec, "current", 1)
    assert run.rejects == {"too_short": 2}
    assert run.kept == []
