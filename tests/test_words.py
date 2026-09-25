from backend.pipeline import words as words_mod
from backend.pipeline.transcript import TranscriptSegment as Seg


def test_words_from_segments_slices_and_rebases():
    segs = [Seg(9.0, 9.8, "before"), Seg(10.2, 10.6, "Hello"), Seg(10.6, 11.0, "world."), Seg(30.0, 30.5, "after")]
    out = words_mod.words_from_segments(segs, 10.0, 20.0)
    assert [(w.text, w.start, w.end) for w in out] == [("Hello", 0.2, 0.6), ("world.", 0.6, 1.0)]


def test_mark_emphasis_normalizes_case_and_punctuation():
    ws = words_mod.words_from_segments([Seg(0, 1, "It"), Seg(1, 2, "WORKED!")], 0, 5)
    marked = words_mod.mark_emphasis(ws, ["worked", "big idea"])
    assert [w.emphasis for w in marked] == [False, True]


def test_clip_words_slices_and_marks_emphasis():
    segs = [Seg(10.1, 10.4, "hey"), Seg(10.4, 10.9, "world")]
    out = words_mod.clip_words(segs, 10.0, 20.0, ["world"])
    assert [(w.text, w.start, w.emphasis) for w in out] == [("hey", 0.1, False), ("world", 0.4, True)]
