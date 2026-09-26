import json
import os

import pytest

from backend import srt

CASES = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "paginate-cases.json")
FIXTURE_V2 = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec-v2.json")
FIXTURE_V1 = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec.json")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("case", _load(CASES), ids=lambda c: c["name"])
def test_paginate_matches_the_renderer(case):
    assert srt.paginate(case["words"], case["maxWords"], case["maxChars"]) == case["pages"]


def test_clip_words_uses_clip_time():
    words = srt.clip_words(_load(FIXTURE_V2))
    assert [w["text"] for w in words] == [w["text"] for w in _load(FIXTURE_V1)["words"]]
    assert words[0]["start"] == pytest.approx(_load(FIXTURE_V1)["words"][0]["start"], abs=1e-3)


def test_build_srt_format():
    text = srt.build_srt(_load(FIXTURE_V1))
    blocks = text.strip().split("\n\n")
    assert blocks[0].splitlines()[0] == "1"
    # 26 words over 8 s: step 8/26; the first sentence is 9 words, ending 9*step - 0.02 = 2.749
    assert blocks[0].splitlines()[1] == "00:00:00,000 --> 00:00:02,749"
    assert blocks[0].splitlines()[2] == "Honestly this was the moment everything changed for us."
    assert text.endswith("\n")


def test_build_srt_empty():
    assert srt.build_srt({"version": 1, "start": 0, "end": 5, "words": []}) == ""
