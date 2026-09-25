"""Camera cuts and shots, from the tiny thumbnails kept during face sampling.

Podcasts cut between a wide two-person shot and single-person close-ups.
Face tracking and layout must restart at each cut, or a face track carries
on into a different shot and the crop lands on empty frame. Measured on a
real episode at 5 fps: ordinary movement changes a 32x18 grayscale
thumbnail by a mean of at most ~0.02, real cuts by 0.17-0.29.
"""
from __future__ import annotations

import numpy as np

CUT_THRESHOLD = 0.08
# Shorter shots (flash frames, transitions) join a neighbouring shot.
MIN_SHOT_S = 0.6


def cut_times(thumbs: list[np.ndarray], times: list[float], threshold: float = CUT_THRESHOLD) -> list[float]:
    """Times of the first sample of each new shot."""
    return [
        times[i] for i in range(1, len(thumbs))
        if float(np.abs(thumbs[i] - thumbs[i - 1]).mean()) > threshold
    ]


def _duration(times: list[float], start: int, end: int) -> float:
    step = times[1] - times[0] if len(times) > 1 else 0.0
    last = times[end] if end < len(times) else times[-1] + step
    return last - times[start]


def split_shots(times: list[float], cuts: list[float], min_len_s: float = MIN_SHOT_S) -> list[tuple[int, int]]:
    if not times:
        return []
    cut_set = set(cuts)
    starts = [0] + [i for i in range(1, len(times)) if times[i] in cut_set]
    ranges = list(zip(starts, starts[1:] + [len(times)]))
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if merged and _duration(times, start, end) < min_len_s:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    if len(merged) > 1 and _duration(times, *merged[0]) < min_len_s:
        merged[:2] = [(merged[0][0], merged[1][1])]
    return merged
