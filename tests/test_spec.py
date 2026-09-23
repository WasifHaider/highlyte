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
    assert spec.version == 1
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
