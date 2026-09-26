import json

import pytest

from backend.pipeline import ranker, segments
from backend.pipeline.groq_llm import BadAnswer, ChatResult, DailyLimit, SelectionFailed
from backend.pipeline.utterances import ThoughtUnit, Utterance
from tests.llm_fakes import FakeChat, RateLimitError


def utt(n, start, end, text="baat chal rahi hai"):
    words = [segments.SegWord(t=t, raw=t, start=start, end=end, kind="hinglish", prob=0.9) for t in text.split()]
    return Utterance(id=f"u{n}", first=0, last=0, start=start, end=end, words=words)


def units_of(n, length=20.0, gap=5.0):
    """n one-utterance units, each `length` seconds, `gap` apart."""
    return [ThoughtUnit([utt(i + 1, i * (length + gap), i * (length + gap) + length)]) for i in range(n)]


def pick(s, e, standalone=0.9, hook=0.8, payoff=0.7, **extra):
    return {"s": s, "e": e, "standalone": standalone, "hook": hook, "payoff": payoff,
            "starts_mid": False, "ends_mid": False, "reason": "good", **extra}


def test_format_window_separates_units_with_blank_line():
    units = [ThoughtUnit([utt(1, 0, 2, "kya hua?"), utt(2, 2.5, 4, "kuch nahi")]), ThoughtUnit([utt(3, 6, 8, "chalo")])]
    assert ranker.format_window(units, [0, 1]) == "u1: kya hua?\nu2: kuch nahi\n\nu3: chalo"


def test_windows_split_with_overlap(monkeypatch):
    monkeypatch.setattr(ranker, "WINDOW_TOKENS", 30)   # ~96 chars: about 3 units per window
    units = units_of(10)
    wins = ranker.windows(units)
    assert len(wins) > 1
    assert sorted({i for w in wins for i in w}) == list(range(10))
    for prev, nxt in zip(wins, wins[1:]):
        assert nxt[0] <= prev[-1]                # consecutive windows share units
        assert units[nxt[0]].start >= units[prev[-1]].end - ranker.OVERLAP_S


def test_single_window_for_short_transcripts():
    assert ranker.windows(units_of(3)) == [[0, 1, 2]]


def test_parse_picks_maps_ids_to_units():
    units = units_of(3)
    picks = ranker.parse_picks(json.dumps([pick("u1", "u2")]), units, [0, 1, 2])
    assert [(p.first_unit, p.last_unit, p.standalone, p.hook, p.payoff) for p in picks] == [(0, 1, 0.9, 0.8, 0.7)]


def test_parse_picks_drops_bad_items():
    units = units_of(3)
    items = [
        pick("u9", "u2"),                       # unknown id
        pick("u1", "u1", starts_mid=True),      # mid-thought
        pick("u2", "u2", ends_mid=True),
        {"s": "u1", "e": "u1", "hook": 0.5, "payoff": 0.5},  # missing standalone
        pick("u3", "u1", standalone=1.7),       # reversed, clamped
        "junk",
    ]
    picks = ranker.parse_picks("Sure! " + json.dumps(items), units, [0, 1, 2])
    assert [(p.first_unit, p.last_unit, p.standalone) for p in picks] == [(0, 2, 1.0)]


def test_parse_picks_ignores_ids_outside_the_window():
    units = units_of(3)
    assert ranker.parse_picks(json.dumps([pick("u3", "u3")]), units, [0, 1]) == []


def test_parse_picks_rejects_unreadable_answers():
    units = units_of(1)
    with pytest.raises(BadAnswer):
        ranker.parse_picks("no json here", units, [0])
    with pytest.raises(BadAnswer):
        ranker.parse_picks("[{bad json]", units, [0])


def test_rank_retries_a_bad_answer_once():
    chat = FakeChat(["not json", json.dumps([pick("u1", "u1")])])
    result = ranker.rank(chat, units_of(2))
    assert len(result.picks) == 1 and result.skipped == []
    assert len(chat.prompts) == 2 and "u1: baat chal rahi hai" in chat.prompts[0]


def test_rank_treats_cut_off_answers_as_bad():
    chat = FakeChat([ChatResult("[", "length"), ChatResult("[", "length")])
    with pytest.raises(SelectionFailed, match="failed for this video"):
        ranker.rank(chat, units_of(2))


def test_rank_keeps_other_windows_when_one_fails(monkeypatch):
    monkeypatch.setattr(ranker, "WINDOW_TOKENS", 30)
    units = units_of(10)
    n = len(ranker.windows(units))
    replies = ["bad", "bad"] + [json.dumps([]) for _ in range(n - 1)]
    result = ranker.rank(FakeChat(replies), units)
    assert len(result.skipped) == 1 and result.skipped[0].reason == "error"
    assert result.skipped[0].start == units[0].start


def test_rank_stops_on_daily_limit(monkeypatch):
    monkeypatch.setattr(ranker, "WINDOW_TOKENS", 30)
    units = units_of(10)
    n = len(ranker.windows(units))
    chat = FakeChat([json.dumps([pick("u1", "u1")]), DailyLimit("about 20 minutes")])
    result = ranker.rank(chat, units)
    assert len(chat.prompts) == 2                      # nothing sent after the limit
    assert len(result.skipped) == n - 1
    assert {s.reason for s in result.skipped} == {"daily limit"}


def test_rank_all_windows_daily_limited_raises_clear_message():
    with pytest.raises(SelectionFailed, match="daily limit. Try again in about 20 minutes."):
        ranker.rank(FakeChat([DailyLimit("about 20 minutes")]), units_of(2))


def test_rank_rate_limit_error_is_labelled():
    chat = FakeChat([RateLimitError("429 tokens per minute"), RateLimitError("429 tokens per minute")])
    with pytest.raises(SelectionFailed):
        ranker.rank(chat, units_of(1))
