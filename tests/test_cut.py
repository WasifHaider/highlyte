import json
import subprocess

import pytest

from backend.pipeline import cut


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    """12 s test video whose only keyframe is its first frame, like a
    downloaded source with sparse keyframes."""
    path = tmp_path_factory.mktemp("src") / "src.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=12",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
        "-c:v", "libx264", "-g", "1000", "-c:a", "aac", "-shortest", str(path),
    ], check=True)
    return str(path)


def _keyframe_times(path: str) -> list[float]:
    out = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v", "-skip_frame", "nokey",
        "-show_entries", "frame=pts_time", "-of", "json", path,
    ], capture_output=True, check=True).stdout
    return [float(f["pts_time"]) for f in json.loads(out)["frames"]]


def _top_level_boxes(path: str) -> list[str]:
    boxes = []
    with open(path, "rb") as f:
        while header := f.read(8):
            size = int.from_bytes(header[:4], "big")
            boxes.append(header[4:8].decode("latin-1"))
            if size == 1:
                size = int.from_bytes(f.read(8), "big")
                f.seek(size - 16, 1)
            else:
                f.seek(size - 8, 1)
    return boxes


def test_cut_clip_puts_the_index_first(source, tmp_path):
    # The browser can start playing only once it has the moov box; at the
    # end of the file it has to fetch the whole segment first.
    out = cut.cut_clip(source, 1.0, 9.0, str(tmp_path / "c.mp4"))
    boxes = _top_level_boxes(out)
    assert boxes.index("moov") < boxes.index("mdat")


def test_cut_clip_adds_a_keyframe_every_second(source, tmp_path):
    out = cut.cut_clip(source, 1.0, 9.0, str(tmp_path / "c.mp4"))
    times = _keyframe_times(out)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert times[0] == 0.0 and len(times) >= 8
    assert max(gaps) <= 1.05


def test_reencode_segment_keeps_duration_and_fixes_layout(source, tmp_path):
    out = cut.reencode_segment(source, str(tmp_path / "r.mp4"))
    boxes = _top_level_boxes(out)
    assert boxes.index("moov") < boxes.index("mdat")
    times = _keyframe_times(out)
    assert max(b - a for a, b in zip(times, times[1:])) <= 1.05
    assert cut.probe_duration(out) == pytest.approx(cut.probe_duration(source), abs=0.1)


def test_make_thumbnail_writes_a_portrait_jpeg(source, tmp_path):
    out = cut.make_thumbnail(source, 2.0, str(tmp_path / "t.jpg"))
    w, h, _ = cut.probe_video(out)
    assert out.endswith(".jpg")
    assert h > w
