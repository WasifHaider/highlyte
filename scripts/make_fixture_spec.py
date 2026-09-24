"""Write renderer/src/__fixtures__/clip-spec.json: a hand-built ClipSpec
used by the renderer's zod tests, Remotion Studio's default props and the
still-image smoke test. Generated from the Pydantic models so the two
schemas can't drift apart silently.

Run: ./.venv/Scripts/python scripts/make_fixture_spec.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.spec import ClipSpec  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec.json")

TEXT = (
    "Honestly this was the moment everything changed for us. "
    "Yaar sach yeh hai ke hum ready nahi thay. "
    "But we shipped it anyway and it worked!"
)
EMPHASIS = {"changed", "ready", "worked!"}


def build() -> ClipSpec:
    tokens = TEXT.split()
    step = 8.0 / len(tokens)
    words = [
        {
            "text": tok,
            "start": round(i * step, 3),
            "end": round((i + 1) * step - 0.02, 3),
            "emphasis": tok.lower() in EMPHASIS,
        }
        for i, tok in enumerate(tokens)
    ]
    left = [{"t": t / 5, "cx": 0.30, "cy": 0.42, "w": 0.12, "h": 0.22} for t in range(0, 41)]
    right = [{"t": t / 5, "cx": 0.70, "cy": 0.40, "w": 0.11, "h": 0.21} for t in range(0, 41)]
    return ClipSpec.model_validate({
        "clipId": "fixture0000-0",
        "source": {"url": "fixture.mp4", "width": 1920, "height": 1080, "fps": 30},
        "start": 1.0,
        "end": 9.0,
        "words": words,
        "wordsApprox": False,
        "hookTitle": "The moment everything changed",
        "viralityScore": 8.2,
        "reframe": {
            "auto": "speaker",
            "faces": [{"id": 0, "track": left}, {"id": 1, "track": right}],
            "speakerTimeline": [{"t": 0.0, "faceId": 0}, {"t": 4.0, "faceId": 1}],
        },
    })


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(build().model_dump(), f, indent=2)
        f.write("\n")
    print(f"wrote {OUT}")
