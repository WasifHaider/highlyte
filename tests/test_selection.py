import json

import pytest

from backend.pipeline import ranker, segments, selection


def thought(start, n=50, text="baat"):
    """One 20 s sentence: n words, 0.4 s apart, ending in a full stop."""
    words = [segments.SegWord(t=text, raw=text, start=start + i * 0.4, end=start + i * 0.4 + 0.35,
                              kind="hinglish", prob=0.9) for i in range(n)]
    words[-1].t = f"{text}."
    return words


def transcript(n_thoughts=3):
    words = [w for i in range(n_thoughts) for w in thought(i * 25.0)]
    return [segments.Segment(id="seg_0001", start=words[0].start, end=words[-1].end, speaker="A",
                             language="hi-Latn-EN", raw="", hinglish="", words=words, confidence=0.9)]


def pick(s, e, standalone=1.0, hook=1.0, payoff=1.0, **extra):
    return {"s": s, "e": e, "standalone": standalone, "hook": hook, "payoff": payoff,
            "starts_mid": False, "ends_mid": False, "reason": "r", **extra}


def test_select_end_to_end():
    from tests.llm_fakes import FakeChat

    ranked = json.dumps([pick("u1", "u1"), pick("u2", "u2", hook=0.6), pick("u3", "u3", starts_mid=True)])
    named = json.dumps([
        {"id": "c1", "hook_title": "Pehla clip", "emphasis": ["baat"], "tag": "Key insight"},
        {"id": "c2", "hook_title": "Doosra clip", "emphasis": [], "tag": "Wild claim"},
    ])
    chat = FakeChat([ranked, named])
    result = selection.select(transcript(), [], chat=chat)

    assert [c.hook_title for c in result.clips] == ["Pehla clip", "Doosra clip"]
    first = result.clips[0]
    assert first.start == 0.0
    assert first.end == pytest.approx(19.95 + 0.4)
    assert first.score == pytest.approx(9.5)
    assert first.emphasis == ["baat"] and first.tag == "Key insight"
    assert first.flags == []
    assert result.clips[1].start == pytest.approx(25.0 - 0.22)
    assert result.note is None
    assert "u1: baat" in chat.prompts[0]


def test_select_notes_failed_titles():
    from tests.llm_fakes import FakeChat

    chat = FakeChat([json.dumps([pick("u1", "u1")]), RuntimeError("boom")])
    result = selection.select(transcript(), [], chat=chat)
    assert result.clips[0].hook_title is None
    assert result.note == "Hook titles could not be written this time."


def test_select_flags_a_weak_pick_when_short_of_five():
    from tests.llm_fakes import FakeChat

    chat = FakeChat([json.dumps([pick("u1", "u1", standalone=0.6, hook=0.4)]), "[]"])
    result = selection.select(transcript(), [], chat=chat)
    assert result.clips[0].flags == ["weak_pick"]


def test_select_without_key_fails_visibly(monkeypatch):
    monkeypatch.setenv("GROQ_KEY", "")
    with pytest.raises(selection.SelectionFailed, match="GROQ_KEY"):
        selection.select(transcript(), [])


def test_select_empty_transcript():
    from tests.llm_fakes import FakeChat

    assert selection.select([], [], chat=FakeChat([])).clips == []


def test_skipped_note_merges_ranges():
    note = selection.skipped_note([
        ranker.Skipped(750.0, 900.0, "rate limit"),
        ranker.Skipped(880.0, 1120.0, "rate limit"),
        ranker.Skipped(1500.0, 1860.0, "error"),
    ])
    assert note == "Skipped 12:30–18:40, 25:00–31:00 (error, rate limit). Some moments may be missing."
    assert selection.skipped_note([]) is None
