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
