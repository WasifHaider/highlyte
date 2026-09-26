from backend.pipeline import segments
from backend.pipeline.utterances import (
    ThoughtUnit, Utterance, build_thought_units, build_utterances, flat_words, norm,
)


def w(t, start, end, prob=0.9):
    return segments.SegWord(t=t, raw=t, start=start, end=end, kind="hinglish", prob=prob)


def seg(words, speaker="A"):
    return segments.Segment(id="s", start=words[0].start, end=words[-1].end, speaker=speaker,
                            language="hi-Latn-EN", raw="", hinglish="", words=words, confidence=0.9)


def U(n, start, end, text):
    toks = text.split()
    step = (end - start) / len(toks)
    words = [w(t, start + i * step, start + (i + 1) * step) for i, t in enumerate(toks)]
    return Utterance(id=f"u{n}", first=0, last=0, start=start, end=end, words=words)


def texts(units):
    return [[u.id for u in unit.utterances] for unit in units]


def test_norm_strips_case_and_edge_punctuation():
    assert norm("Toh,") == "toh" and norm("hai?") == "hai" and norm("\"Yaar!\"") == "yaar"


def test_splits_on_pause_and_sentence_end():
    words = [w("hum", 0.0, 0.3), w("chalein.", 0.3, 0.7), w("phir", 0.75, 1.0),
             w("dekho", 1.0, 1.3), w("yaar", 1.7, 2.0)]
    utts = build_utterances([seg(words)])
    assert [u.text for u in utts] == ["hum chalein.", "phir dekho", "yaar"]
    assert [u.id for u in utts] == ["u1", "u2", "u3"]
    assert [(u.first, u.last) for u in utts] == [(0, 1), (2, 3), (4, 4)]
    assert flat_words(utts)[2].t == "phir"


def test_joins_across_segments_split_mid_sentence():
    utts = build_utterances([seg([w("a", 0.0, 0.3), w("b", 0.3, 0.6)]), seg([w("c", 0.6, 0.9)])])
    assert [u.text for u in utts] == ["a b c"]


def test_speaker_change_splits():
    utts = build_utterances([seg([w("a", 0.0, 0.3)], "A"), seg([w("b", 0.3, 0.6)], "B")])
    assert [(u.text, u.speaker) for u in utts] == [("a", "A"), ("b", "B")]


def test_long_utterance_split_at_longest_gap():
    words = []
    for i in range(50):
        shift = 0.15 if i >= 20 else 0.0
        words.append(w(f"w{i}", i * 0.5 + shift, i * 0.5 + 0.45 + shift))
    utts = build_utterances([seg(words)])
    assert len(utts) == 2
    assert utts[0].words[-1].t == "w19" and utts[1].words[0].t == "w20"
    assert all(u.end - u.start <= 20.0 for u in utts)


def test_confidence_and_sentence_end():
    u = build_utterances([seg([w("kya", 0.0, 0.3, prob=0.8), w("hua?", 0.3, 0.6, prob=0.6)])])[0]
    assert u.confidence == 0.7 and u.ends_sentence is True


def test_short_gaps_join_one_unit():
    assert texts(build_thought_units([U(1, 0, 3, "ek do teen"), U(2, 3.5, 6, "char paanch")])) == [["u1", "u2"]]


def test_long_pause_without_connector_splits():
    assert texts(build_thought_units([U(1, 0, 3, "ek do teen"), U(2, 4, 6, "char paanch")])) == [["u1"], ["u2"]]


def test_question_bridges_a_pause():
    units = build_thought_units([U(1, 0, 3, "kya scene hai?"), U(2, 4.5, 8, "scene ye hai")])
    assert texts(units) == [["u1", "u2"]]


def test_hanging_end_bridges_a_pause():
    assert texts(build_thought_units([U(1, 0, 3, "main gaya lekin"), U(2, 4, 6, "woh nahi aaya")])) == [["u1", "u2"]]


def test_continuation_start_bridges_a_pause():
    assert texts(build_thought_units([U(1, 0, 3, "main nahi gaya"), U(2, 4, 6, "kyunki barish thi")])) == [["u1", "u2"]]


def test_bridge_never_crosses_more_than_two_seconds():
    assert texts(build_thought_units([U(1, 0, 3, "kya hua?"), U(2, 5.5, 8, "kuch nahi")])) == [["u1"], ["u2"]]


def test_bridges_pull_in_at_most_twelve_seconds():
    units = build_thought_units([
        U(1, 0, 2, "sawal kya hai?"),
        U(2, 3, 10, "jawab ye hai lekin"),   # bridged: 8 s extra
        U(3, 11, 16, "aur phir kya"),        # would make 14 s extra
    ])
    assert texts(units) == [["u1", "u2"], ["u3"]]


def test_unit_capped_at_45_seconds():
    utts = [U(i + 1, i * 10.2, i * 10.2 + 10, "baat chal rahi hai") for i in range(5)]
    assert texts(build_thought_units(utts)) == [["u1", "u2", "u3", "u4"], ["u5"]]


def test_closing_phrase_starts_a_new_unit():
    units = build_thought_units([U(1, 0, 3, "ye baat khatam"), U(2, 3.2, 5, "chalo next sawal")])
    assert texts(units) == [["u1"], ["u2"]]
    assert isinstance(units[0], ThoughtUnit) and units[0].start == 0 and units[1].end == 5
