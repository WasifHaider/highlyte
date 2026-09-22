"""Cutting: use ffmpeg to extract identified segments from the source audio.

Uses stream copy (-c copy) where possible for speed; falls back to
re-encoding if copy fails (e.g. non-keyframe-aligned cut points).
"""
from __future__ import annotations

import os
import subprocess


def cut_clip(source_path: str, start: float, end: float, out_path: str) -> str:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    duration = max(end - start, 0.5)

    # Try stream copy first (fast, no quality loss).
    copy_cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.2f}", "-i", source_path,
        "-t", f"{duration:.2f}",
        "-c", "copy",
        out_path,
    ]
    proc = subprocess.run(copy_cmd, capture_output=True)
    if proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return out_path

    # Fall back to re-encode.
    reencode_cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.2f}", "-i", source_path,
        "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-c:a", "aac", "-b:a", "160k",
        out_path,
    ]
    proc = subprocess.run(reencode_cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='ignore')}")
    return out_path
