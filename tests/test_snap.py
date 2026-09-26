import pytest

from backend.pipeline import segments, snap


def w(t, start, end):
    return segments.SegWord(t=t, raw=t, start=start, end=end, kind="hinglish", prob=0.9)


def line(text, start=0.0, step=0.4, dur=0.35):
    """Words back to back with 50 ms gaps (never a cut pause)."""
    return [w(t, start + i * step, start + i * step + dur) for i, t in enumerate(text.split())]


def test_back_to_pause_moves_to_previous_pause():
    words = [w("a", 0.0, 0.5), w("b", 1.0, 1.4), w("c", 1.45, 1.8), w("d", 1.85, 2.2)]
    assert snap.back_to_pause(words, 3) == 1


def test_back_to_pause_gives_up_after_three_seconds():
    words = line(" ".join(f"x{i}" for i in range(30)))
    assert snap.back_to_pause(words, 20) == 20


def test_back_to_pause_stops_at_transcript_start():
    words = line("a b c d e f")
    assert snap.back_to_pause(words, 5) == 0


def test_forward_to_pause_moves_to_next_pause():
    words = [w("a", 0.0, 0.4), w("b", 0.45, 0.8), w("c", 0.85, 1.2), w("d", 2.0, 2.4)]
    assert snap.forward_to_pause(words, 0) == 2


def test_forward_to_pause_rejects_a_run_on():
    words = line(" ".join(f"x{i}" for i in range(30)))
    with pytest.raises(snap.Reject) as e:
        snap.forward_to_pause(words, 5)
    assert e.value.reason == "hanging_end"


def test_start_cut_leads_by_220ms_without_eating_previous_word():
    words = [w("a", 0.0, 3.0), w("b", 5.0, 5.4)]
    assert snap.start_cut(words, 1) == 4.78
    words = [w("a", 0.0, 4.9), w("b", 5.0, 5.4)]
    assert snap.start_cut(words, 1) == 4.93
    assert snap.start_cut([w("a", 0.1, 0.4)], 0) == 0.0


def test_end_cut_adds_400ms_air_without_reaching_next_word():
    words = [w("a", 9.0, 10.0), w("b", 11.0, 11.4)]
    assert snap.end_cut(words, 0) == 10.4
    words = [w("a", 9.0, 10.0), w("b", 10.2, 10.6)]
    assert snap.end_cut(words, 0) == 10.15
    assert snap.end_cut([w("a", 9.0, 10.0)], 0) == 10.4


def test_strip_leading_filler_words_and_phrases():
    words = line("toh matlab " + "yeh baat sahi hai " * 6)
    assert snap.strip_leading_filler(words, 0, len(words) - 1) == 2
    words = line("you know " + "yeh baat sahi hai " * 6)
    assert snap.strip_leading_filler(words, 0, len(words) - 1) == 2
    words = line("yeh baat sahi hai " * 6)
    assert snap.strip_leading_filler(words, 0, len(words) - 1) == 0


def test_strip_leading_filler_rejects_when_too_short():
    words = line("toh yeh baat sahi hai")
    with pytest.raises(snap.Reject) as e:
        snap.strip_leading_filler(words, 0, len(words) - 1)
    assert e.value.reason == "filler_start"


def test_fix_last_line_trims_hanging_word_to_sentence_end():
    words = line("yeh baat sahi hai " * 6 + "bilkul. aur")
    last = snap.fix_last_line(words, 0, len(words) - 1)
    assert words[last].t == "bilkul."


def test_fix_last_line_strips_trailing_um():
    words = line("yeh baat sahi hai " * 6 + "bilkul. um")
    assert words[snap.fix_last_line(words, 0, len(words) - 1)].t == "bilkul."


def test_fix_last_line_rejects_hanging_end_without_sentence_end():
    words = line("yeh baat sahi hai " * 6 + "lekin")
    with pytest.raises(snap.Reject) as e:
        snap.fix_last_line(words, 0, len(words) - 1)
    assert e.value.reason == "hanging_end"


def test_snap_places_both_cuts():
    before = [w("pehle", 0.0, 0.5)]
    body = line("yeh baat sahi hai " * 6 + "bilkul.", start=2.0)
    after = [w("phir", body[-1].end + 1.0, body[-1].end + 1.3)]
    words = before + body + after
    cut = snap.snap(words, 1, len(words) - 2)
    assert (cut.first, cut.last) == (1, len(words) - 2)
    assert cut.start == 1.78
    assert cut.end == round(body[-1].end + 0.4, 3)
