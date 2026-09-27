"""The ClipSpec contract between the Python analysis pipeline and the
Remotion renderer (renderer/src/schema.ts mirrors these models in zod).

A spec holds what analysis measured about one clip and is written once.
A style holds what the team chose for it and changes freely. Remotion
receives both as {spec, style} input props, so the browser preview and
the Lambda render draw exactly the same thing.

All times are seconds. start/end are positions inside the padded source
segment (the cut file). In version 2, word, face-track, speaker and shot
times are also positions inside the cut file and cover the whole file;
in version 1 they covered only the clip and were relative to start. The
renderer converts both to clip time (renderer/src/lib/timeline.ts).
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
    duration: float | None = Field(None, gt=0)  # seconds of the cut file; v2 only


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


ShotKind = Literal["two", "one", "none"]


class Shot(BaseModel):
    """One camera shot of the clip. faceIds refer to Reframe.faces; for a
    "two" shot they are ordered left to right (top panel first in split)."""
    start: float
    end: float
    kind: ShotKind
    faceIds: list[int]


class Reframe(BaseModel):
    auto: LayoutKind
    # Sorted by how often each face is present, most present first.
    faces: list[FaceTrack]
    speakerTimeline: list[SpeakerTurn]
    # Empty for clips analysed before shots existed; they render as before.
    shots: list[Shot] = Field(default_factory=list)


class ClipSpec(BaseModel):
    version: Literal[1, 2] = 2
    clipId: str
    source: Source
    start: float = Field(ge=0)
    end: float
    words: list[Word]
    wordsApprox: bool
    hookTitle: str | None
    viralityScore: float = Field(ge=0, le=10)
    reframe: Reframe


def window_duration(spec: dict) -> float | None:
    """Length of a v2 clip's cut file, which bounds nudges and caption
    times. None for v1 clips, which cannot be trimmed."""
    if spec.get("version") != 2:
        return None
    duration = (spec.get("source") or {}).get("duration")
    return float(duration) if duration else None


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


def render_hash(style: ClipStyle, words: list[Word], bounds: tuple[float, float] | None = None) -> str:
    """Fingerprint of everything an export depends on that a user can
    change: the style, the caption words and (once clips can be trimmed)
    the clip's bounds. Editing any of them must not reuse the old mp4."""
    payload: dict = {"style": style.model_dump(), "words": [w.model_dump() for w in words]}
    if bounds is not None:
        payload["bounds"] = [round(bounds[0], 3), round(bounds[1], 3)]
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]
