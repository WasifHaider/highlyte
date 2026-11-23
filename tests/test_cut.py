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


@pytest.fixture(scope="module")
def quiet_burst(tmp_path_factory):
    """10 s video whose audio is silent except a quiet 440 Hz tone from 4 s
    to 7 s (about -30 LUFS), at 44.1 kHz."""
    path = tmp_path_factory.mktemp("burst") / "burst.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=10",
        "-f", "lavfi", "-i", "aevalsrc=if(between(t\,4\,7)\,0.03*sin(2*PI*440*t)\,0):s=44100:d=10",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
    ], check=True)
    return str(path)


def _integrated_lufs(path: str) -> float:
    err = subprocess.run(["ffmpeg", "-nostats", "-i", path, "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True).stderr.decode(errors="ignore")
    summary = err[err.rindex("Summary:"):]
    return float(summary.split("I:")[1].split("LUFS")[0])


def _audio_onset(path: str, rate: int = 48000) -> float:
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    import array
    samples = array.array("h", pcm)
    peak = max(abs(s) for s in samples)
    first = next(i for i, s in enumerate(samples) if abs(s) > peak * 0.2)
    return first / rate


def _sample_rate(path: str) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=sample_rate",
                          "-of", "csv=p=0", path], capture_output=True, check=True).stdout
    return int(out.decode().strip())


def test_reencode_segment_brings_speech_to_social_loudness(quiet_burst, tmp_path):
    out = cut.reencode_segment(quiet_burst, str(tmp_path / "loud.mp4"))
    assert _integrated_lufs(quiet_burst) < -25
    assert _integrated_lufs(out) == pytest.approx(cut.TARGET_LUFS, abs=1.5)
    assert _sample_rate(out) == 48000


def test_reencode_segment_keeps_audio_timing(quiet_burst, tmp_path):
    # Captions and the clip bounds are word times inside this file, so the
    # audio must not shift.
    out = cut.reencode_segment(quiet_burst, str(tmp_path / "timed.mp4"))
    assert _audio_onset(out) == pytest.approx(_audio_onset(quiet_burst), abs=0.03)
    assert cut.probe_duration(out) == pytest.approx(cut.probe_duration(quiet_burst), abs=0.1)


def test_reencode_segment_handles_silent_and_soundless_video(tmp_path):
    silent = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=3",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "3", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(silent)], check=True)
    mute = tmp_path / "mute.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=3",
                    "-c:v", "libx264", str(mute)], check=True)
    assert cut.voice_audio_args(str(silent))[0] == "-c:a"     # nothing to normalise
    assert cut.probe_duration(cut.reencode_segment(str(silent), str(tmp_path / "s.mp4"))) == pytest.approx(3, abs=0.1)
    assert cut.probe_duration(cut.reencode_segment(str(mute), str(tmp_path / "m.mp4"))) == pytest.approx(3, abs=0.1)
