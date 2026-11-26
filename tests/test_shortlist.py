import json

from backend.pipeline import scoring, selection, shortlist
from backend.pipeline.groq_llm import ChatResult
from tests.llm_fakes import FakeChat
from tests.test_selection import pick, transcript


def test_rerank_returns_the_model_order():
    chat = FakeChat(['Here: ["c3","c1","c2"]'])
    assert shortlist.rerank(chat, ["a", "b", "c"]) == [2, 0, 1]
    assert "c1: a" in chat.prompts[0] and "c3: c" in chat.prompts[0]


def test_rerank_appends_ids_the_model_left_out_and_ignores_junk():
    chat = FakeChat([json.dumps(["c2", "c9", "c2", 4, "x1"])])
    assert shortlist.rerank(chat, ["a", "b", "c"]) == [1, 0, 2]


def test_rerank_gives_up_on_failure():
    assert shortlist.rerank(FakeChat([RuntimeError("boom")]), ["a", "b"]) is None
    assert shortlist.rerank(FakeChat(["no json here"]), ["a", "b"]) is None
    assert shortlist.rerank(FakeChat([ChatResult("", "length")]), ["a", "b"]) is None
    assert shortlist.rerank(FakeChat(['["zz"]']), ["a", "b"]) is None


def test_rerank_skips_the_call_when_there_is_nothing_to_order():
    chat = FakeChat([])
    assert shortlist.rerank(chat, ["only one"]) is None
    assert shortlist.rerank(None, ["a", "b"]) is None
    assert chat.prompts == []


def _two_candidates(monkeypatch):
    # Two picks with equal scores; packing keeps one of them only (cap 1).
    monkeypatch.setattr(scoring, "MAX_CLIPS", 1)
    monkeypatch.setattr(scoring, "MIN_CLIPS", 1)
    return json.dumps([pick("u1", "u1"), pick("u3", "u3")])


def test_rank_and_pack_follows_the_shortlist_order(monkeypatch):
    ranked = _two_candidates(monkeypatch)
    _, _, kept = selection.rank_and_pack(transcript(), [], FakeChat([ranked, '["c2","c1"]']), rerank=True)
    plain = selection.rank_and_pack(transcript(), [], FakeChat([ranked]))[2]
    assert len(kept) == 1 and len(plain) == 1
    assert kept[0].start != plain[0].start      # the shortlist pass changed which one won


def test_rank_and_pack_keeps_its_own_order_when_the_shortlist_fails(monkeypatch):
    ranked = _two_candidates(monkeypatch)
    _, _, kept = selection.rank_and_pack(transcript(), [], FakeChat([ranked, RuntimeError("boom")]), rerank=True)
    plain = selection.rank_and_pack(transcript(), [], FakeChat([ranked]))[2]
    assert [c.start for c in kept] == [c.start for c in plain]
