from backend.pipeline import words as words_mod
from backend.pipeline.transcript import TranscriptSegment as Seg


def test_words_from_segments_slices_and_rebases():
    segs = [Seg(9.0, 9.8, "before"), Seg(10.2, 10.6, "Hello"), Seg(10.6, 11.0, "world."), Seg(30.0, 30.5, "after")]
    out = words_mod.words_from_segments(segs, 10.0, 20.0)
    assert [(w.text, w.start, w.end) for w in out] == [("Hello", 0.2, 0.6), ("world.", 0.6, 1.0)]


def test_spread_words_even_split_and_clamp():
    segs = [Seg(10.0, 12.0, "one two three four")]
    out = words_mod.spread_words(segs, 10.5, 20.0)
    # 0.5 s per word; "one" (10.0-10.5) ends exactly at the clip start and is dropped
    assert [(w.text, w.start, w.end) for w in out] == [("two", 0.0, 0.5), ("three", 0.5, 1.0), ("four", 1.0, 1.5)]


def test_mark_emphasis_normalizes_case_and_punctuation():
    ws = words_mod.words_from_segments([Seg(0, 1, "It"), Seg(1, 2, "WORKED!")], 0, 5)
    marked = words_mod.mark_emphasis(ws, ["worked", "big idea"])
    assert [w.emphasis for w in marked] == [False, True]


def test_clip_words_uses_transcript_words_for_whisper_sources():
    segs = [Seg(10.1, 10.4, "hey")]
    out, approx = words_mod.clip_words(segs, "groq", "a.m4a", 10.0, 20.0, [])
    assert approx is False
    assert out[0].text == "hey" and out[0].start == 0.1


def test_clip_words_calls_groq_for_caption_source(monkeypatch):
    monkeypatch.setattr(words_mod, "extract_audio_span", lambda *a, **k: None)
    calls = []

    def fake_transcribe(path, key, prompt):
        calls.append((key, prompt))
        return [(0.1, 0.5, "Hello"), (0.5, 0.9, "world")]

    segs = [Seg(10.0, 12.0, "hello world")]
    out, approx = words_mod.clip_words(
        segs, "captions", "a.m4a", 10.0, 20.0, ["world"],
        groq_key="k", prompt="p", transcribe=fake_transcribe,
    )
    assert calls == [("k", "p")]
    assert approx is False
    assert [(w.text, w.emphasis) for w in out] == [("Hello", False), ("world", True)]


def test_clip_words_falls_back_to_even_spread(monkeypatch):
    monkeypatch.setattr(words_mod, "extract_audio_span", lambda *a, **k: None)

    def boom(*a):
        raise RuntimeError("groq down")

    segs = [Seg(10.0, 11.0, "a b")]
    out, approx = words_mod.clip_words(segs, "captions", "a.m4a", 10.0, 20.0, [], groq_key="k", transcribe=boom)
    assert approx is True
    assert [(w.text, w.start, w.end) for w in out] == [("a", 0.0, 0.5), ("b", 0.5, 1.0)]


def test_clip_words_without_key_is_approx():
    out, approx = words_mod.clip_words([Seg(10.0, 11.0, "a")], "captions", "a.m4a", 10.0, 20.0, [])
    assert approx is True and out[0].text == "a"
