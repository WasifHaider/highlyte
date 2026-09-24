"""The ClipSpec contract between the Python analysis pipeline and the
Remotion renderer (renderer/src/schema.ts mirrors these models in zod).

A spec holds what analysis measured about one clip and is written once.
A style holds what the team chose for it and changes freely. Remotion
receives both as {spec, style} input props, so the browser preview and
the Lambda render draw exactly the same thing.

All times are seconds. `start`/`end` are positions inside the padded
source segment; word and face-track times are relative to the clip's
own start (i.e. to `start`).
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

LayoutKind = Literal["follow", "speaker", "split", "fit"]
CaptionPreset = Literal["karaoke", "pop", "clean"]


class Word(BaseModel):
    text: str
    start: float
    end: float
    emphasis: bool = False


class Source(BaseModel):
    # Empty in stored specs: a fresh URL is filled in whenever the spec is
    # served (presigned R2 URLs expire, so they are never persisted).
    url: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)


class TrackPoint(BaseModel):
    """One smoothed face sample. Coordinates are normalized 0-1 of the
    source frame: (cx, cy) is the face centre, (w, h) its box size."""
    t: float
    cx: float
    cy: float
    w: float
    h: float


class FaceTrack(BaseModel):
    id: int
    track: list[TrackPoint]


class SpeakerTurn(BaseModel):
    t: float
    faceId: int


class Reframe(BaseModel):
    auto: LayoutKind
    # Sorted by how often each face is present, most present first.
    faces: list[FaceTrack]
    speakerTimeline: list[SpeakerTurn]


class ClipSpec(BaseModel):
    version: Literal[1] = 1
    clipId: str
    source: Source
    start: float = Field(ge=0)
    end: float
    words: list[Word]
    wordsApprox: bool
    hookTitle: str | None
    viralityScore: float = Field(ge=0, le=10)
    reframe: Reframe


class ClipStyle(BaseModel):
    layout: LayoutKind
    captionPreset: CaptionPreset = "karaoke"
    showHook: bool = True
    hookTitle: str | None = Field(None, max_length=80)
    accent: str = Field("#FFD400", pattern=r"^#[0-9A-Fa-f]{6}$")
    captionPosition: Literal["lower", "middle"] = "lower"


def default_style(spec: ClipSpec) -> ClipStyle:
    return ClipStyle(
        layout=spec.reframe.auto,
        showHook=spec.hookTitle is not None,
        hookTitle=spec.hookTitle,
        captionPosition="middle" if spec.reframe.auto == "split" else "lower",
    )


def style_hash(style: ClipStyle) -> str:
    """Stable fingerprint of a style, used to reuse an existing render
    instead of paying for an identical one again."""
    payload = json.dumps(style.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
