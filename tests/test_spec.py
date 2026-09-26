import json
import os

import pytest
from pydantic import ValidationError

from backend.spec import ClipSpec, ClipStyle, default_style, style_hash

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec.json")


def _spec(**overrides) -> ClipSpec:
    base = {
        "clipId": "abc123def456-0",
        "source": {"url": "", "width": 1920, "height": 1080, "fps": 30},
        "start": 1.0,
        "end": 9.0,
        "words": [{"text": "hello", "start": 0.0, "end": 0.4}],
        "wordsApprox": False,
        "hookTitle": "Big claim",
        "viralityScore": 7.5,
        "reframe": {"auto": "split", "faces": [], "speakerTimeline": []},
    }
    base.update(overrides)
    return ClipSpec.model_validate(base)


def test_spec_defaults_version_and_emphasis():
    spec = _spec()
    assert spec.version == 2
    assert spec.words[0].emphasis is False


def test_spec_rejects_out_of_range_virality():
    with pytest.raises(ValidationError):
        _spec(viralityScore=11)


def test_spec_rejects_unknown_layout():
    with pytest.raises(ValidationError):
        _spec(reframe={"auto": "zoom", "faces": [], "speakerTimeline": []})


def test_default_style_follows_spec():
    style = default_style(_spec())
    assert style.layout == "split"
    assert style.captionPosition == "middle"  # split always puts captions on the seam
    assert style.showHook is True
    assert style.hookTitle == "Big claim"
    assert style.accent == "#FFD400"
    assert style.captionPreset == "karaoke"


def test_default_style_hides_hook_when_missing():
    style = default_style(_spec(hookTitle=None, reframe={"auto": "follow", "faces": [], "speakerTimeline": []}))
    assert style.showHook is False
    assert style.captionPosition == "lower"


def test_style_rejects_bad_accent():
    with pytest.raises(ValidationError):
        ClipStyle(layout="fit", accent="yellow")


def test_style_rejects_hook_title_over_80_chars():
    with pytest.raises(ValidationError):
        ClipStyle(layout="fit", hookTitle="x" * 81)


def test_style_hash_is_stable_and_sensitive():
    a = ClipStyle(layout="fit")
    b = ClipStyle(layout="fit")
    c = ClipStyle(layout="fit", captionPreset="pop")
    assert style_hash(a) == style_hash(b)
    assert style_hash(a) != style_hash(c)
    assert len(style_hash(a)) == 16


def test_fixture_is_a_valid_spec():
    with open(FIXTURE, encoding="utf-8") as f:
        spec = ClipSpec.model_validate(json.load(f))
    assert spec.source.url == "fixture.mp4"
    assert len(spec.reframe.faces) == 2


def test_render_hash_depends_on_words_and_style():
    from backend.spec import ClipStyle, Word, render_hash

    s = ClipStyle(layout="fit")
    w1 = [Word(text="a", start=0.0, end=0.1)]
    assert render_hash(s, w1) == render_hash(s, list(w1))
    assert render_hash(s, w1) != render_hash(s, [Word(text="b", start=0.0, end=0.1)])
    assert render_hash(s, w1) != render_hash(ClipStyle(layout="follow"), w1)


def test_reframe_shots_default_and_round_trip():
    from backend.spec import Reframe

    old = Reframe.model_validate({"auto": "follow", "faces": [], "speakerTimeline": []})
    assert old.shots == []
    new = Reframe.model_validate({
        "auto": "split", "faces": [], "speakerTimeline": [],
        "shots": [{"start": 0.0, "end": 4.0, "kind": "two", "faceIds": [0, 1]}],
    })
    assert new.model_dump()["shots"][0] == {"start": 0.0, "end": 4.0, "kind": "two", "faceIds": [0, 1]}


def test_v2_fixture_round_trips_and_has_window():
    import json, os
    from backend.spec import ClipSpec, window_duration

    path = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec-v2.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    spec = ClipSpec.model_validate(data)
    assert spec.version == 2 and spec.source.duration == 12.0
    assert window_duration(data) == 12.0
    assert window_duration({**data, "version": 1}) is None


def test_render_hash_changes_with_bounds():
    from backend.spec import ClipStyle, Word, render_hash

    style, words = ClipStyle(layout="fit"), [Word(text="a", start=0, end=1)]
    assert render_hash(style, words) == render_hash(style, words, None)
    assert render_hash(style, words, (1.0, 9.0)) != render_hash(style, words, (1.5, 9.0))
