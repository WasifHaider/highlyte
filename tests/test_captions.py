import pytest

from backend import captions


def _w(text, start, end, emphasis=False):
    return {"text": text, "start": start, "end": end, "emphasis": emphasis}


def test_validate_words_accepts_and_trims():
    out = captions.validate_words([_w(" hum ", 0.0, 0.3), _w("hain.", 0.3, 0.8)], clip_length=10.0)
    assert [w.text for w in out] == ["hum", "hain."]


@pytest.mark.parametrize("words, message", [
    ([], "at least one"),
    ([_w("", 0, 1)], "empty"),
    ([_w("x" * 41, 0, 1)], "too long"),
    ([_w("a\nb", 0, 1)], "line break"),
    ([_w("a", -0.1, 1)], "time"),
    ([_w("a", 1.0, 0.5)], "time"),
    ([_w("a", 0, 10.6)], "time"),
    ([_w("a", float("nan"), 1.0)], "time"),
    ([_w("a", 0, float("inf"))], "time"),
    ([_w("a", 1.0, 1.2), _w("b", 0.5, 0.7)], "order"),
])
def test_validate_words_rejects(words, message):
    with pytest.raises(ValueError, match=message):
        captions.validate_words(words, clip_length=10.0)


def test_validate_words_rejects_too_many():
    with pytest.raises(ValueError, match="at most"):
        captions.validate_words([_w("a", 0, 0.01)] * 3001, clip_length=10.0)
