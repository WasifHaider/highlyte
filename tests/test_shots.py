import numpy as np

from backend.pipeline import shots


def _thumbs(values):
    return [np.full((18, 32), v, dtype=np.float32) for v in values]


def _times(n, fps=5.0):
    return [round(i / fps, 3) for i in range(n)]


def test_cut_times_finds_hard_cut_only():
    rng = np.random.default_rng(0)
    base = [0.4 + rng.normal(0, 0.01, (18, 32)).astype(np.float32) for _ in range(10)]
    cut = [0.8 + rng.normal(0, 0.01, (18, 32)).astype(np.float32) for _ in range(10)]
    times = _times(20)
    assert shots.cut_times(base + cut, times) == [times[10]]


def test_cut_times_ignores_gradual_motion():
    assert shots.cut_times(_thumbs([0.40 + i * 0.01 for i in range(20)]), _times(20)) == []


def test_cut_times_empty():
    assert shots.cut_times([], []) == []


def test_split_shots_without_cuts_is_one_shot():
    assert shots.split_shots(_times(20), []) == [(0, 20)]


def test_split_shots_at_cuts():
    times = _times(40)
    assert shots.split_shots(times, [times[10], times[25]]) == [(0, 10), (10, 25), (25, 40)]


def test_split_shots_merges_too_short_shot_into_previous():
    times = _times(40)
    # 10..12 is 0.4 s long -> merged into the shot before it
    assert shots.split_shots(times, [times[10], times[12]]) == [(0, 12), (12, 40)]


def test_split_shots_merges_too_short_first_shot_into_next():
    times = _times(40)
    assert shots.split_shots(times, [times[2]]) == [(0, 40)]


def test_split_shots_empty():
    assert shots.split_shots([], []) == []
