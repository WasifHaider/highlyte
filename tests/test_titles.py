import json

from backend.pipeline import titles
from backend.pipeline.groq_llm import ChatResult
from tests.llm_fakes import FakeChat

TEXTS = [
    "Sach yeh hai ke startup mein paisa nahi, patience chahiye.",
    "Honestly marketing budget pehle din se rakho warna product koi nahi dekhega.",
]


def test_write_titles_parses_and_validates():
    answer = json.dumps([
        {"id": "c1", "hook_title": "Startup ka asli secret jo koi nahi batata aapko yaar",
         "emphasis": ["patience", "paisa", "rocket"], "tag": "Key insight"},
        {"id": "c2", "hook_title": "Marketing pehle", "emphasis": ["marketing"], "tag": "Not a tag"},
    ])
    out, ok = titles.write_titles(FakeChat([answer]), TEXTS)
    assert ok is True
    assert out[0].hook_title == "Startup ka asli secret jo koi nahi batata"  # 8 words
    assert out[0].emphasis == ["patience", "paisa"]                          # "rocket" not in text
    assert out[0].tag == "Key insight"
    assert out[1].tag in titles.TAGS                                           # invalid tag replaced


def test_missing_clip_gets_fallback():
    answer = json.dumps([{"id": "c1", "hook_title": "Ek", "emphasis": ["paisa"], "tag": "Key insight"}])
    out, ok = titles.write_titles(FakeChat([answer]), TEXTS)
    assert ok is True
    assert out[1].hook_title is None and out[1].emphasis


def test_failure_falls_back_for_every_clip():
    for reply in [RuntimeError("boom"), "no json", ChatResult("[", "length")]:
        out, ok = titles.write_titles(FakeChat([reply]), TEXTS)
        assert ok is False
        assert [t.hook_title for t in out] == [None, None]
        assert all(t.emphasis and t.tag in titles.TAGS for t in out)


def test_no_chat_or_no_clips():
    out, ok = titles.write_titles(None, TEXTS)
    assert ok is False and len(out) == 2
    assert titles.write_titles(FakeChat([]), []) == ([], True)


def test_code_emphasis_picks_longest_non_stopwords():
    # longest first; "din"/"se" are too short and "warna" is a stopword
    assert titles.code_emphasis("Honestly marketing budget pehle din se rakho warna") == ["marketing", "honestly", "budget"]
