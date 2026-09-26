from backend.pipeline import segments
from backend.pipeline.asr import AsrWord


def w(t, start, end, prob=0.9, raw=None):
    return segments.SegWord(t=t, raw=raw or t, start=start, end=end, kind="hinglish", prob=prob)


def test_from_asr_copies_text_to_raw():
    out = segments.from_asr([AsrWord("yar", 1.0, 1.2, 0.8)])
    assert (out[0].t, out[0].raw, out[0].kind) == ("yar", "yar", "")


def test_build_splits_on_pause_and_punctuation():
    words = [w("hum", 0.0, 0.3), w("chalein.", 0.3, 0.7), w("phir", 0.8, 1.0),
             w("dekho", 1.0, 1.3), w("yaar", 1.8, 2.0)]
    segs = segments.build(words, "hi-Latn-EN")
    assert [s.hinglish for s in segs] == ["hum chalein.", "phir dekho", "yaar"]
    assert [s.id for s in segs] == ["seg_0001", "seg_0002", "seg_0003"]
    assert segs[0].start == 0.0 and segs[0].end == 0.7


def test_build_splits_long_segments():
    words = [w(f"w{i}", i * 0.5, i * 0.5 + 0.45) for i in range(40)]  # 20s, no pauses
    for s in segments.build(words, "en"):
        assert s.end - s.start <= segments.MAX_SEGMENT_S


def test_segment_fields():
    seg = segments.build([w("yaar", 1.0, 1.5, prob=0.8, raw="yar"), w("sun", 1.5, 1.8, prob=0.6)], "hi-Latn-EN")[0]
    assert seg.raw == "yar sun" and seg.hinglish == "yaar sun"
    assert seg.speaker == "A" and seg.language == "hi-Latn-EN"
    assert seg.confidence == 0.7
    d = seg.to_dict()
    assert d["words"][0] == {"t": "yaar", "raw": "yar", "start": 1.0, "end": 1.5, "kind": "hinglish", "prob": 0.8}


def test_build_empty():
    assert segments.build([], "en") == []


def test_from_dict_round_trips_to_dict():
    seg = segments.build([w("yaar", 1.0, 1.5, prob=0.8, raw="yar"), w("sun.", 1.5, 1.8, prob=0.6)], "hi-Latn-EN")[0]
    back = segments.from_dict(seg.to_dict())
    assert back == seg


def test_from_dict_tolerates_missing_optional_fields():
    back = segments.from_dict({"id": "seg_0001", "start": 0.0, "end": 0.5,
                               "words": [{"t": "hi", "start": 0.0, "end": 0.5}]})
    assert back.speaker == "A" and back.words[0].raw == "hi" and back.words[0].prob == 0.0
