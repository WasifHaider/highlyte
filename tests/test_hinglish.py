import json
from pathlib import Path

from backend.pipeline import hinglish
from backend.pipeline.segments import SegWord

DATA = Path(hinglish.__file__).parent / "data"


def w(t, start=0.0, end=0.1, prob=0.9):
    return SegWord(t=t, raw=t, start=start, end=end, kind="", prob=prob)


def test_no_spelling_key_is_an_english_word():
    english = set((DATA / "english_words.txt").read_text(encoding="utf-8").split())
    keys = set(json.loads((DATA / "spelling.json").read_text(encoding="utf-8")))
    assert keys & english == set()


def test_spelling_keys_avoid_ambiguous_words():
    ambiguous = set((DATA / "hinglish_also_english.txt").read_text(encoding="utf-8").split())
    keys = set(json.loads((DATA / "spelling.json").read_text(encoding="utf-8")))
    assert keys & ambiguous == set()


def test_apply_spelling_keeps_punctuation_and_capital():
    out = hinglish.apply_spelling([w("Bhoat,"), w("fark?"), w("the"), w("to")])
    assert [x.t for x in out] == ["Bohat,", "farq?", "the", "to"]
    assert [x.raw for x in out] == ["Bhoat,", "fark?", "the", "to"]


def test_apply_glossary_merges_phrases_and_keeps_timing():
    out = hinglish.apply_glossary([w("you", 1.0, 1.2, 0.9), w("tube", 1.2, 1.5, 0.5), w("pe", 1.5, 1.7)])
    assert [x.t for x in out] == ["YouTube", "pe"]
    assert (out[0].raw, out[0].start, out[0].end, out[0].prob) == ("you tube", 1.0, 1.5, 0.45)


def test_apply_glossary_single_word_keeps_punctuation():
    assert hinglish.apply_glossary([w("instagram.")])[0].t == "Instagram."


def test_classify():
    assert hinglish.classify("2026") == "num"
    assert hinglish.classify("video,") == "en"
    assert hinglish.classify("the") == "hinglish"
    assert hinglish.classify("dekho") == "hinglish"
    assert hinglish.classify("YouTube") == "en"


def test_fix_hinglish_runs_glossary_spelling_and_kind():
    out = hinglish.fix([w("yar"), w("you"), w("tube"), w("pe"), w("video"), w("bhoat")], "hinglish")
    assert [x.t for x in out] == ["yaar", "YouTube", "pe", "video", "bohat"]
    assert [x.kind for x in out] == ["hinglish", "en", "hinglish", "en", "hinglish"]


def test_fix_english_skips_spelling():
    out = hinglish.fix([w("yar"), w("youtube")], "english")
    assert [x.t for x in out] == ["yar", "YouTube"]
