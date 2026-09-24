import os

from backend.pipeline import clipprep, cut, face_detect
from backend.pipeline.highlight import Clip
from backend.pipeline.reframe import Detection
from backend.pipeline.transcript import TranscriptSegment as Seg


def test_segment_bounds_pads_and_clamps():
    assert clipprep.segment_bounds(11.0, 40.0, 100.0) == (10.0, 41.0)
    assert clipprep.segment_bounds(0.4, 20.0, 20.5) == (0.0, 20.5)
    assert clipprep.segment_bounds(5.0, 20.0, 0.0) == (4.0, 21.0)  # unknown duration: no clamp


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
        transcript_source="groq", audio_path="a.m4a",
        clips_dir=str(tmp_path), models_dir=str(tmp_path),
        groq_key=None, prompt=None, on_step=lambda s: None,
    )


def test_prepare_clip_builds_spec(tmp_path, monkeypatch):
    # segment starts at 10.0, so the clip starts 1.0 s into it
    times = [round(i / 5, 3) for i in range(80)]  # 0-16 s of the segment
    frames = [[Detection(0.5, 0.4, 0.2, 0.3, 0.1)] for _ in times]
    _patch_media(monkeypatch, lambda path, model, sample_fps=5.0: (frames, times))

    prepared = _prepare(tmp_path)
    spec = prepared.spec
    assert spec.clipId == "abc123def456-0"
    assert (spec.start, spec.end) == (1.0, 15.0)
    assert spec.source.width == 1920 and spec.source.url == ""
    assert [(w.text, w.start, w.emphasis) for w in spec.words] == [("hey", 0.2, True), ("there", 0.5, False)]
    assert spec.wordsApprox is False
    assert spec.hookTitle == "Hook"
    assert spec.viralityScore == 10.0  # clamped
    assert spec.reframe.auto == "follow"
    track = spec.reframe.faces[0].track
    assert track[0].t == 0.0 and track[-1].t <= 14.0  # re-based to the clip start, trimmed to the clip
    assert prepared.storage_key is None  # R2 disabled in tests
    assert os.path.exists(os.path.join(tmp_path, "abc123def456", "clip_0.mp4"))


def test_prepare_clip_survives_face_detection_failure(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no mediapipe")

    _patch_media(monkeypatch, boom)
    assert _prepare(tmp_path).spec.reframe.auto == "fit"
