"""Face-track logic for vertical reframing — pure functions, no video I/O
(face_detect.py produces the per-frame detections this module consumes).

Pipeline: per-sample face detections -> tracks (a face followed across
samples by horizontal position) -> keep the main tracks -> smooth them ->
work out who is talking when (jaw movement) -> pick an automatic layout.
Everything the renderer needs is stored for every layout, so the team
can switch layouts in the preview without re-running analysis.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..spec import FaceTrack, LayoutKind, Reframe, SpeakerTurn, TrackPoint

# A detection joins the track whose last position is within this much
# horizontal distance (fraction of frame width); otherwise it starts a new one.
MATCH_MAX_JUMP = 0.15
MIN_TRACK_PRESENCE = 0.10
MAX_TRACKS = 4
SMOOTH_WINDOW = 5  # samples (1 s at 5 fps)
# Crop centre only moves when the smoothed position shifts more than this,
# so small head movements don't make the frame wobble.
DEAD_ZONE = 0.02
ACTIVITY_WINDOW_S = 1.0
# Jaw-openness standard deviation below this counts as "not talking".
MIN_ACTIVITY = 0.01
MIN_HOLD_S = 1.5
FIT_MIN_FACE_FRACTION = 0.40
FIT_MIN_FACE_AREA = 0.03
TWO_FACE_PRESENCE = 0.50


@dataclass
class Detection:
    cx: float
    cy: float
    w: float
    h: float
    jaw: float


@dataclass
class _Track:
    id: int
    points: list[tuple[float, Detection]] = field(default_factory=list)


def build_tracks(frames: list[list[Detection]], times: list[float]) -> list[_Track]:
    tracks: list[_Track] = []
    next_id = 0
    for t, dets in zip(times, frames):
        used: set[int] = set()
        for d in sorted(dets, key=lambda d: -(d.w * d.h)):
            best: _Track | None = None
            best_dist = MATCH_MAX_JUMP
            for tr in tracks:
                if tr.id in used:
                    continue
                dist = abs(tr.points[-1][1].cx - d.cx)
                if dist <= best_dist:
                    best, best_dist = tr, dist
            if best is None:
                best = _Track(id=next_id)
                next_id += 1
                tracks.append(best)
            best.points.append((t, d))
            used.add(best.id)
    return tracks


def keep_main_tracks(tracks: list[_Track], n_samples: int) -> list[_Track]:
    if n_samples == 0:
        return []
    kept = [tr for tr in tracks if len(tr.points) / n_samples >= MIN_TRACK_PRESENCE]
    kept.sort(key=lambda tr: len(tr.points), reverse=True)
    kept = kept[:MAX_TRACKS]
    for new_id, tr in enumerate(kept):
        tr.id = new_id
    return kept


def smooth(points: list[tuple[float, Detection]]) -> list[TrackPoint]:
    out: list[TrackPoint] = []
    half = SMOOTH_WINDOW // 2
    last_cx: float | None = None
    for i, (t, _) in enumerate(points):
        window = [d for _, d in points[max(0, i - half): i + half + 1]]
        cx = sum(d.cx for d in window) / len(window)
        if last_cx is not None and abs(cx - last_cx) < DEAD_ZONE:
            cx = last_cx
        last_cx = cx
        out.append(TrackPoint(
            t=round(t, 3),
            cx=round(cx, 4),
            cy=round(sum(d.cy for d in window) / len(window), 4),
            w=round(sum(d.w for d in window) / len(window), 4),
            h=round(sum(d.h for d in window) / len(window), 4),
        ))
    return out


def speaker_timeline(tracks: list[_Track], times: list[float]) -> list[SpeakerTurn]:
    """Change points of who is talking, judged by how much each face's jaw
    moves in a 1 s window. Turns shorter than MIN_HOLD_S are absorbed into
    the previous turn so the crop doesn't flick between speakers."""
    if not tracks or not times:
        return []
    main = tracks[:2]
    if len(main) < 2:
        return [SpeakerTurn(t=0.0, faceId=main[0].id)]

    current = main[0].id
    raw: list[tuple[float, int]] = []
    for t in times:
        best_id, best_act = None, MIN_ACTIVITY
        for tr in main:
            jaws = [d.jaw for pt, d in tr.points if abs(pt - t) <= ACTIVITY_WINDOW_S / 2]
            if len(jaws) < 2:
                continue
            act = statistics.pstdev(jaws)
            if act > best_act:
                best_id, best_act = tr.id, act
        if best_id is not None:
            current = best_id
        raw.append((t, current))

    turns: list[tuple[float, int]] = []
    for t, fid in raw:
        if not turns or turns[-1][1] != fid:
            turns.append((t, fid))

    held: list[tuple[float, int]] = []
    for i, (t, fid) in enumerate(turns):
        next_t = turns[i + 1][0] if i + 1 < len(turns) else float("inf")
        if held and next_t - t < MIN_HOLD_S:
            continue  # too short: the previous speaker keeps the frame
        if held and held[-1][1] == fid:
            continue
        held.append((t, fid))

    return [SpeakerTurn(t=0.0 if i == 0 else round(t, 3), faceId=fid) for i, (t, fid) in enumerate(held)]


def choose_layout(
    frames: list[list[Detection]], tracks: list[_Track], timeline: list[SpeakerTurn]
) -> LayoutKind:
    n = len(frames)
    if n == 0 or not tracks:
        return "fit"
    face_fraction = sum(1 for dets in frames if dets) / n
    main_area = statistics.median(d.w * d.h for _, d in tracks[0].points)
    if face_fraction < FIT_MIN_FACE_FRACTION or main_area < FIT_MIN_FACE_AREA:
        return "fit"
    frequent = [tr for tr in tracks if len(tr.points) / n >= TWO_FACE_PRESENCE]
    if len(frequent) >= 2:
        return "speaker" if len(timeline) > 1 else "split"
    return "follow"


def analyze(frames: list[list[Detection]], times: list[float]) -> Reframe:
    tracks = keep_main_tracks(build_tracks(frames, times), len(times))
    timeline = speaker_timeline(tracks, times)
    return Reframe(
        auto=choose_layout(frames, tracks, timeline),
        faces=[FaceTrack(id=tr.id, track=smooth(tr.points)) for tr in tracks],
        speakerTimeline=timeline,
    )


def fallback() -> Reframe:
    return Reframe(auto="fit", faces=[], speakerTimeline=[])
