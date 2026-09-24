"""Cutting: use ffmpeg to extract identified segments from the source audio.

Always re-encodes rather than stream-copying (-c copy). Stream copy can only
cut on a keyframe, so `-ss` snaps backward to the nearest one before the
requested start — on sources with sparse keyframes (e.g. downloaded
webm/vp9, keyframes every several seconds) that can make a clip start up to
multiple seconds before its intended highlight. Re-encoding is
frame-accurate; clips here are short (MIN_CLIP_S-MAX_CLIP_S), so the extra
CPU cost is small and worth the correctness.
"""
from __future__ import annotations

import json
import os
import subprocess


def cut_clip(source_path: str, start: float, end: float, out_path: str) -> str:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    duration = max(end - start, 0.5)

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.2f}", "-i", source_path,
        "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-b:a", "160k",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='ignore')}")
    return out_path


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
