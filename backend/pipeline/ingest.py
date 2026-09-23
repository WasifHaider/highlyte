"""Ingest: download audio/video via yt-dlp and get basic metadata."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

import yt_dlp


@dataclass
class VideoMeta:
    video_id: str
    title: str
    channel: str
    duration: float  # seconds
    audio_path: str
    video_path: str | None


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def ingest(url: str, cache_dir: str, on_progress: "callable | None" = None) -> VideoMeta:
    """Download the video's audio (for transcription) and keep a reference
    to a downloadable video/audio file (for cutting). Uses yt-dlp; results
    are cached by video ID so re-processing the same link is instant.

    If given, `on_progress(stage, percent, note)` is called during
    download (stage="downloading") — lets callers surface live progress
    instead of the caller staring at a silent status for minutes on a
    large podcast file.
    """
    os.makedirs(cache_dir, exist_ok=True)

    # First pass: extract info only, to get a stable video_id for caching.
    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "noplaylist": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    video_id = info["id"]
    out_template = os.path.join(cache_dir, f"{video_id}.%(ext)s")
    target_video = os.path.join(cache_dir, f"{video_id}.mp4")
    target_audio = os.path.join(cache_dir, f"{video_id}.m4a")

    if not os.path.exists(target_video):
        def _hook(d: dict) -> None:
            if on_progress is None:
                return
            try:
                if d.get("status") == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    downloaded = d.get("downloaded_bytes") or 0
                    pct = (downloaded / total * 100.0) if total else None
                    speed = d.get("speed")
                    note = f"{pct:.1f}%" if pct is not None else f"{downloaded} bytes"
                    if speed:
                        note += f" @ {speed / 1024:.0f} KiB/s"
                    on_progress("downloading", pct, note)
                elif d.get("status") == "finished":
                    on_progress("downloading", 100.0, "download complete, muxing…")
            except Exception:
                pass  # progress reporting must never break the pipeline

        ydl_opts = {
            "quiet": True,
            "noplaylist": True,
            # Prefer H.264 at 1080p or lower: every browser can decode it for
            # the live preview, and face analysis/cutting stay fast. Falls
            # back to anything available rather than failing the download.
            "format": (
                "bestvideo[vcodec^=avc1][height<=1080][ext=mp4]+bestaudio[ext=m4a]"
                "/best[vcodec^=avc1][height<=1080][ext=mp4]"
                "/bestvideo[height<=1080]+bestaudio/best"
            ),
            "merge_output_format": "mp4",
            "outtmpl": out_template,
            "progress_hooks": [_hook],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    if not os.path.exists(target_audio):
        # Pull the audio track out of the downloaded video for transcription,
        # rather than a second yt-dlp download.
        extract_cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", target_video,
            "-vn", "-c:a", "aac", "-b:a", "160k",
            target_audio,
        ]
        proc = subprocess.run(extract_cmd, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg audio extraction failed: {proc.stderr.decode(errors='ignore')}")

    return VideoMeta(
        video_id=video_id,
        title=info.get("title") or "Untitled",
        channel=info.get("uploader") or info.get("channel") or "Unknown",
        duration=float(info.get("duration") or 0),
        audio_path=target_audio,
        video_path=target_video,
    )


def duration_label(seconds: float) -> str:
    return _fmt_duration(seconds)
