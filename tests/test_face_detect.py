import os
import subprocess

import pytest

from backend.pipeline import cut, face_detect

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "models")


def _make_video(path, seconds=3, size="320x240", rate=25):
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}",
        "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p", path,
    ], check=True)


def test_probe_video(tmp_path):
    path = str(tmp_path / "v.mp4")
    _make_video(path)
    assert cut.probe_video(path) == (320, 240, 25.0)


@pytest.mark.slow
def test_sample_detections_on_faceless_video(tmp_path):
    path = str(tmp_path / "v.mp4")
    _make_video(path, seconds=3)
    model = face_detect.ensure_model(MODELS_DIR)
    frames, times = face_detect.sample_detections(path, model, sample_fps=5.0)
    assert 14 <= len(times) <= 16
    assert times == sorted(times)
    assert all(dets == [] for dets in frames)
