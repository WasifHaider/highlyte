"""Cutting: use ffmpeg to extract identified segments from the source audio.

Always re-encodes rather than stream-copying (-c copy). Stream copy can only
cut on a keyframe, so `-ss` snaps backward to the nearest one before the
requested start — on sources with sparse keyframes (e.g. downloaded
webm/vp9, keyframes every several seconds) that can make a clip start up to
multiple seconds before its intended highlight. Re-encoding is
frame-accurate; clips here are short (MIN_CLIP_S-MAX_CLIP_S), so the extra
CPU cost is small and worth the correctness.

Segments are streamed straight into the browser preview, so they are
encoded for that: the index (moov) goes at the front (+faststart), or the
browser has to fetch the whole file before it can show a frame, and a
keyframe every second, so seeking to the clip start (and every Lambda
render chunk's start) decodes at most a second of video.
"""
from __future__ import annotations

import json
import os
import subprocess


# Shared by cut_clip and reencode_segment (for segments cut before these
# settings existed).
STREAM_VIDEO_ARGS = [
    "-c:v", "libx264", "-preset", "veryfast",
    "-force_key_frames", "expr:gte(t,n_forced*1)",
    "-movflags", "+faststart",
]

# Card posters: a centre 9:16 crop, small enough to load instantly.
THUMB_W = 360


def _run(cmd: list[str], out_path: str) -> str:
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='ignore')}")
    return out_path


def cut_clip(source_path: str, start: float, end: float, out_path: str) -> str:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    duration = max(end - start, 0.5)

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.2f}", "-i", source_path,
        "-t", f"{duration:.2f}",
        *STREAM_VIDEO_ARGS, "-c:a", "aac", "-b:a", "160k",
        out_path,
    ]
    return _run(cmd, out_path)


def reencode_segment(in_path: str, out_path: str) -> str:
    """Re-encode an existing segment with STREAM_VIDEO_ARGS. Audio is
    copied and no trim is applied, so every time in its spec stays valid."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", in_path,
        *STREAM_VIDEO_ARGS, "-c:a", "copy",
        out_path,
    ]
    return _run(cmd, out_path)


def make_thumbnail(video_path: str, at_s: float, out_path: str) -> str:
    """A small portrait JPEG of the frame at `at_s`, for the clip card."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{max(at_s, 0.0):.2f}", "-i", video_path, "-frames:v", "1",
        "-vf", rf"crop=min(iw\,ih*9/16):ih,scale={THUMB_W}:-2", "-q:v", "4",
        out_path,
    ]
    return _run(cmd, out_path)


def probe_duration(path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path]
    proc = subprocess.run(cmd, capture_output=True, check=True)
    return float(json.loads(proc.stdout)["format"]["duration"])


def probe_video(path: str) -> tuple[int, int, float]:
    """(width, height, fps) of the first video stream."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate", "-of", "json", path,
    ]
    proc = subprocess.run(cmd, capture_output=True, check=True)
    stream = json.loads(proc.stdout)["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    return int(stream["width"]), int(stream["height"]), float(num) / float(den or 1)
