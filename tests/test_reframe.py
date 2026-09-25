import math

from backend.pipeline import reframe
from backend.pipeline.reframe import Detection


def _times(seconds: float, fps: float = 5.0):
    return [round(i / fps, 3) for i in range(int(seconds * fps))]


def _talking(t: float, start: float, end: float) -> float:
    # jaw oscillates while talking, stays still otherwise
    return 0.3 + 0.25 * math.sin(t * 9) if start <= t < end else 0.05


def test_build_tracks_follows_two_faces_by_position():
    times = _times(2)
    frames = [[Detection(0.3, 0.4, 0.1, 0.2, 0.1), Detection(0.7, 0.4, 0.1, 0.2, 0.1)] for _ in times]
    tracks = reframe.build_tracks(frames, times)
    assert len(tracks) == 2
    assert all(len(t.points) == len(times) for t in tracks)
    assert {round(t.points[0][1].cx, 1) for t in tracks} == {0.3, 0.7}


def test_keep_main_tracks_drops_rare_faces_and_renumbers():
    times = _times(4)
    frames = [[Detection(0.5, 0.4, 0.1, 0.2, 0.1)] for _ in times]
    frames[0].append(Detection(0.1, 0.4, 0.05, 0.1, 0.0))  # a face seen in 1 of 20 samples
    kept = reframe.keep_main_tracks(reframe.build_tracks(frames, times), len(times))
    assert [t.id for t in kept] == [0]
    assert len(kept[0].points) == len(times)


def test_smooth_averages_and_applies_dead_zone():
    pts = [(i * 0.2, Detection(0.5 + (0.005 if i % 2 else 0.0), 0.4, 0.1, 0.2, 0.0)) for i in range(10)]
    out = reframe.smooth(pts)
    assert len(out) == 10
    assert len({p.cx for p in out}) == 1  # jitter below the dead zone never moves the crop


def test_speaker_timeline_switches_and_respects_min_hold():
    times = _times(9)
    frames = []
    for t in times:
        a_jaw = _talking(t, 0, 3) if t < 6 else _talking(t, 6, 6.6)  # A talks 0-3, blip at 6-6.6
        b_jaw = _talking(t, 3, 6) if t < 6 else _talking(t, 6.6, 9)
        frames.append([Detection(0.3, 0.4, 0.1, 0.2, a_jaw), Detection(0.7, 0.4, 0.1, 0.2, b_jaw)])
    tracks = reframe.keep_main_tracks(reframe.build_tracks(frames, times), len(times))
    timeline = reframe.speaker_timeline(tracks, times)
    a = next(t.id for t in tracks if t.points[0][1].cx < 0.5)
    b = next(t.id for t in tracks if t.points[0][1].cx > 0.5)
    assert timeline[0].t == 0.0 and timeline[0].faceId == a
    assert [turn.faceId for turn in timeline] == [a, b]  # the 0.6 s blip is absorbed
    assert 2.5 <= timeline[1].t <= 3.5


def test_choose_layout_rules():
    times = _times(4)
    solo = [[Detection(0.5, 0.4, 0.2, 0.3, 0.1)] for _ in times]
    pair = [[Detection(0.3, 0.4, 0.2, 0.3, 0.1), Detection(0.7, 0.4, 0.2, 0.3, 0.1)] for _ in times]
    tiny = [[Detection(0.9, 0.9, 0.05, 0.05, 0.1)] for _ in times]  # webcam corner in a screen share
    sparse = [([Detection(0.5, 0.4, 0.2, 0.3, 0.1)] if i < 5 else []) for i, _ in enumerate(times)]

    def layout(frames, timeline_len=1):
        tracks = reframe.keep_main_tracks(reframe.build_tracks(frames, times), len(times))
        timeline = [reframe.SpeakerTurn(t=float(i), faceId=0) for i in range(timeline_len)]
        return reframe.choose_layout(frames, tracks, timeline)

    assert layout(solo) == "follow"
    assert layout(pair, timeline_len=1) == "split"
    assert layout(pair, timeline_len=2) == "speaker"
    assert layout(tiny) == "fit"
    assert layout(sparse) == "fit"
    assert layout([[] for _ in times]) == "fit"


def test_analyze_returns_valid_reframe_and_fallback():
    times = _times(3)
    frames = [[Detection(0.5, 0.4, 0.2, 0.3, 0.1)] for _ in times]
    result = reframe.analyze(frames, times)
    assert result.auto == "follow"
    assert result.faces[0].id == 0 and len(result.faces[0].track) == len(times)
    assert reframe.fallback().auto == "fit" and reframe.fallback().faces == []


def _wide_then_closeup():
    times = _times(8)
    frames = []
    for t in times:
        if t < 4.0:
            frames.append([Detection(0.3, 0.4, 0.12, 0.25, 0.1), Detection(0.72, 0.4, 0.12, 0.25, 0.1)])
        else:
            frames.append([Detection(0.5, 0.4, 0.25, 0.45, 0.1)])  # close-up, centred
    return frames, times


def test_analyze_without_cuts_has_no_shots():
    frames, times = _wide_then_closeup()
    assert reframe.analyze(frames, times).shots == []


def test_shot_kind_is_none_when_the_largest_face_is_tiny():
    # A webcam corner in a screen-share shot: real track, but far below
    # FIT_MIN_FACE_AREA_SHOTS. Must be "none" rather than "one" on a tiny
    # face, so the renderer fits the shot instead of zooming onto it.
    times = _times(4)
    frames = [[Detection(0.9, 0.9, 0.05, 0.05, 0.1)] for _ in times]
    tracks = reframe.keep_main_tracks(reframe.build_tracks(frames, times), len(times))
    kind, face_ids = reframe._shot_kind(tracks, len(times))
    assert (kind, face_ids) == ("none", [])


def test_analyze_per_shot_tracks_and_kinds():
    frames, times = _wide_then_closeup()
    result = reframe.analyze(frames, times, cuts=[4.0])
    # 5 fps samples: the cut sample is at 4.0, the previous sample at 3.8, so
    # the new shot starts at their midpoint (3.9) rather than the cut sample
    # itself — that's up to 0.2 s of the old shot's layout bleeding past the
    # actual cut. The previous shot's end lines up with the same value.
    assert [(s.start, s.kind) for s in result.shots] == [(0.0, "two"), (3.9, "one")]
    assert result.shots[0].end == 3.9
    left, right = result.shots[0].faceIds
    by_id = {f.id: f for f in result.faces}
    assert by_id[left].track[0].cx < by_id[right].track[0].cx  # left face first -> top panel
    closeup = result.shots[1].faceIds[0]
    assert closeup not in (left, right)  # tracking restarts at the cut
    for face in result.faces:  # no track spans the cut
        ts = [p.t for p in face.track]
        assert max(ts) < 4.0 or min(ts) >= 4.0
    assert result.auto == "split"  # two-person shot covers >= 50 %


def test_analyze_with_empty_cuts_is_one_shot():
    frames, times = _wide_then_closeup()
    result = reframe.analyze(frames[:20], times[:20], cuts=[])
    assert [(s.start, s.kind) for s in result.shots] == [(0.0, "two")]


def test_choose_auto_prefers_follow_when_mostly_closeups():
    times = _times(10)
    frames = [[Detection(0.3, 0.4, 0.12, 0.25, 0.1), Detection(0.72, 0.4, 0.12, 0.25, 0.1)] if t < 2 else
              [Detection(0.5, 0.4, 0.25, 0.45, 0.1)] for t in times]
    assert reframe.analyze(frames, times, cuts=[2.0]).auto == "follow"


def test_speaker_timeline_starts_each_shot_at_its_start():
    frames, times = _wide_then_closeup()
    result = reframe.analyze(frames, times, cuts=[4.0])
    closeup = result.shots[1].faceIds[0]
    assert any(turn.t == 3.9 and turn.faceId == closeup for turn in result.speakerTimeline)


def _wide_shot_then_closeup_realistic():
    # 0.11 x 0.24 (area 0.0264) sits below the old FIT_MIN_FACE_AREA (0.03) but
    # above FIT_MIN_FACE_AREA_SHOTS (0.01), so these tests only pass under the
    # shot-aware threshold — the old 0.118 x 0.255 (0.03009) face already
    # cleared the old rule and didn't discriminate between the two.
    wide_times = _times(18.4)
    close_times = [round(t, 3) for t in _times(34.4) if t >= 18.4]
    times = wide_times + close_times
    frames = []
    for t in times:
        if t < 18.4:
            frames.append([Detection(0.3, 0.4, 0.11, 0.24, 0.1), Detection(0.72, 0.4, 0.11, 0.24, 0.1)])
        else:
            frames.append([Detection(0.5, 0.4, 0.25, 0.45, 0.1)])
    return frames, times


def test_analyze_real_footage_wide_shot_is_not_fit():
    frames, times = _wide_shot_then_closeup_realistic()
    result = reframe.analyze(frames, times, cuts=[18.4])
    assert result.auto == "split"


def test_analyze_wide_shot_alone_is_not_fit():
    frames, times = _wide_shot_then_closeup_realistic()
    wide_only_count = sum(1 for t in times if t < 18.4)
    result = reframe.analyze(frames[:wide_only_count], times[:wide_only_count], cuts=[])
    assert result.auto == "split"


def test_analyze_tiny_webcam_corner_is_fit():
    times = _times(4)
    frames = [[Detection(0.9, 0.9, 0.05, 0.05, 0.1)] for _ in times]
    result = reframe.analyze(frames, times, cuts=[])
    assert result.auto == "fit"


def test_choose_auto_uses_the_largest_track_not_just_the_most_present():
    # The most-present track (the long wide shot) has small faces (0.0264,
    # under the old FIT_MIN_FACE_AREA of 0.03); a less-present track (the
    # short close-up) has a large face (0.1125). auto must not be "fit" —
    # that only holds if the largest-area check looks across all tracks
    # instead of just the most-present one.
    wide_times = _times(10)
    close_times = [round(t, 3) for t in _times(12) if t >= 10]
    times = wide_times + close_times
    frames = []
    for t in times:
        if t < 10.0:
            frames.append([Detection(0.3, 0.4, 0.11, 0.24, 0.1), Detection(0.72, 0.4, 0.11, 0.24, 0.1)])
        else:
            frames.append([Detection(0.5, 0.4, 0.25, 0.45, 0.1)])
    result = reframe.analyze(frames, times, cuts=[10.0])
    assert result.auto != "fit"
