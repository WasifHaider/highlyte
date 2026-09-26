import os

import numpy as np

from backend.pipeline import clipprep, cut, face_detect
from backend.pipeline.selection import Clip
from backend.pipeline.reframe import Detection
from backend.pipeline.transcript import TranscriptSegment as Seg


def test_segment_bounds_pads_and_clamps():
    assert clipprep.segment_bounds(11.0, 40.0, 100.0) == (3.0, 48.0)
    assert clipprep.segment_bounds(0.4, 20.0, 20.5) == (0.0, 20.5)
    assert clipprep.segment_bounds(5.0, 20.0, 0.0) == (0.0, 28.0)  # unknown duration: no clamp


def _patch_media(monkeypatch, detect):
    def fake_cut(src, start, end, out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "wb").close()
        return out

    monkeypatch.setattr(cut, "cut_clip", fake_cut)
    monkeypatch.setattr(cut, "probe_video", lambda p: (1920, 1080, 30.0))
    monkeypatch.setattr(face_detect, "ensure_model", lambda d: "model")
    monkeypatch.setattr(face_detect, "sample_detections", detect)


def _prepare(tmp_path):
    clip = Clip(start=11.0, end=25.0, text="t", score=12.3, tag="Key insight", hook_title="Hook", emphasis=["hey"])
    return clipprep.prepare_clip(
        job_id="abc123def456", idx=0, clip=clip,
        video_path="v.mp4", video_duration=100.0,
        segments=[Seg(11.2, 11.5, "hey"), Seg(11.5, 11.9, "there")],
        clips_dir=str(tmp_path), models_dir=str(tmp_path),
        on_step=lambda s: None,
    )


def test_prepare_clip_builds_spec(tmp_path, monkeypatch):
    # segment starts at 3.0, so the clip starts 8.0 s into it
    times = [round(i / 5, 3) for i in range(80)]  # 0-16 s of the segment
    frames = [[Detection(0.5, 0.4, 0.2, 0.3, 0.1)] for _ in times]
    thumbs = [np.zeros((18, 32), dtype=np.float32) for _ in times]
    _patch_media(monkeypatch, lambda path, model, sample_fps=5.0: (frames, times, thumbs))

    prepared = _prepare(tmp_path)
    spec = prepared.spec
    assert spec.clipId == "abc123def456-0"
    assert spec.version == 2
    assert (spec.start, spec.end) == (8.0, 22.0)
    assert spec.source.duration == 30.0          # segment 3.0-33.0
    assert spec.source.width == 1920 and spec.source.url == ""
    assert [(w.text, w.start, w.emphasis) for w in spec.words] == [("hey", 8.2, True), ("there", 8.5, False)]
    assert spec.wordsApprox is False
    assert spec.hookTitle == "Hook"
    assert spec.viralityScore == 10.0  # clamped
    assert spec.reframe.auto == "follow"
    track = spec.reframe.faces[0].track
    assert track[0].t == 0.0 and track[-1].t > 14.0  # whole window, file time (no longer trimmed to the clip)
    assert prepared.storage_key is None  # R2 disabled in tests
    assert os.path.exists(os.path.join(tmp_path, "abc123def456", "clip_0.mp4"))
    assert [s.kind for s in spec.reframe.shots] == ["one"]


def test_prepare_clip_detects_a_camera_cut(tmp_path, monkeypatch):
    times = [round(i / 5, 3) for i in range(80)]
    frames = [[Detection(0.3, 0.4, 0.12, 0.25, 0.1), Detection(0.72, 0.4, 0.12, 0.25, 0.1)] if t < 9 else
              [Detection(0.5, 0.4, 0.25, 0.45, 0.1)] for t in times]
    thumbs = [np.full((18, 32), 0.2 if t < 9 else 0.7, dtype=np.float32) for t in times]
    _patch_media(monkeypatch, lambda path, model, sample_fps=5.0: (frames, times, thumbs))
    shots = _prepare(tmp_path).spec.reframe.shots
    assert [s.kind for s in shots] == ["two", "one"]
    # cut sample at segment time 9.0, previous sample at 8.8 -> midpoint 8.9 (file time)
    assert shots[1].start == 8.9


def test_prepare_clip_survives_face_detection_failure(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no mediapipe")

    _patch_media(monkeypatch, boom)
    assert _prepare(tmp_path).spec.reframe.auto == "fit"


def test_prepare_clip_reports_a_face_at_the_start(tmp_path, monkeypatch):
    times = [round(i / 5, 3) for i in range(80)]
    frames = [[Detection(0.5, 0.4, 0.2, 0.3, 0.1)] for _ in times]
    thumbs = [np.zeros((18, 32), dtype=np.float32) for _ in times]
    _patch_media(monkeypatch, lambda path, model, sample_fps=5.0: (frames, times, thumbs))
    assert _prepare(tmp_path).face_at_start is True


def test_prepare_clip_reports_no_face_at_the_start(tmp_path, monkeypatch):
    # clip starts at segment time 8.0; no face until segment time 10.0
    times = [round(i / 5, 3) for i in range(80)]
    frames = [[] if t < 10.0 else [Detection(0.5, 0.4, 0.2, 0.3, 0.1)] for t in times]
    thumbs = [np.zeros((18, 32), dtype=np.float32) for _ in times]
    _patch_media(monkeypatch, lambda path, model, sample_fps=5.0: (frames, times, thumbs))
    assert _prepare(tmp_path).face_at_start is False


def test_prepare_clip_face_unknown_when_detection_fails(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no mediapipe")

    _patch_media(monkeypatch, boom)
    assert _prepare(tmp_path).face_at_start is None
