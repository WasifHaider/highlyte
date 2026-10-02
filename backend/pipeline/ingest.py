"""Ingest: download audio/video via yt-dlp and get basic metadata."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

import yt_dlp
from yt_dlp.utils import DownloadError

# YouTube blocks datacenter IPs like EC2's. YTDLP_PROXIES lists SOCKS5
# proxies (Tailscale sidecars that leave through teammates' home laptops)
# to try in order; unset means a direct connection, as in local development.
PROXIES_ENV = "YTDLP_PROXIES"

# Error text that means "this route can't reach YouTube right now" rather
# than "this video can't be downloaded", so the next route is worth trying.
_ROUTE_ERRORS = (
    "not a bot",
    "sign in to confirm",
    "http error 429",
    "too many requests",
    "unable to connect to proxy",
    "proxyerror",
    "socks",
    "connection refused",
    "connection reset",
    "timed out",
    "network is unreachable",
    "name resolution",
)

# A dead proxy should fail in seconds, not after yt-dlp's default retries.
_ROUTE_OPTS = {"socket_timeout": 20, "retries": 2, "extractor_retries": 1}


class NoDownloadRoute(RuntimeError):
    """Every configured route was blocked by YouTube or offline."""


def download_routes() -> list[str | None]:
    """Proxies from YTDLP_PROXIES in order, or [None] for a direct connection."""
    raw = os.environ.get(PROXIES_ENV) or ""
    routes = [p.strip() for p in raw.split(",") if p.strip()]
    return routes or [None]


def _is_route_error(e: Exception) -> bool:
    text = str(e).lower()
    return any(marker in text for marker in _ROUTE_ERRORS)


@dataclass
class VideoMeta:
    video_id: str
    title: str
    channel: str
    duration: float  # seconds
    audio_path: str
    video_path: str | None
    # yt-dlp's best thumbnail URL for the video, when it reports one.
    thumbnail_url: str | None = None


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _touch(path: str) -> None:
    try:
        os.utime(path)
    except OSError:
        pass


def _fetch(
    url: str, cache_dir: str, route: str | None, on_progress: "callable | None"
) -> tuple[dict, str]:
    """Read the video's info and download it (unless cached) over one route.
    Returns (info, path of the cached mp4)."""
    base = {"quiet": True, "noplaylist": True, **_ROUTE_OPTS}
    if route:
        base["proxy"] = route

    # First pass: extract info only, to get a stable video_id for caching.
    with yt_dlp.YoutubeDL({**base, "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    video_id = info["id"]
    out_template = os.path.join(cache_dir, f"{video_id}.%(ext)s")
    target_video = os.path.join(cache_dir, f"{video_id}.mp4")
    if os.path.exists(target_video):
        _touch(target_video)  # marks it as recently used for cache pruning
        return info, target_video

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
        **base,
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
    return info, target_video


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

    routes = download_routes()
    failures: list[str] = []
    for route in routes:
        try:
            info, target_video = _fetch(url, cache_dir, route, on_progress)
            break
        except DownloadError as e:
            if not _is_route_error(e):
                raise
            label = route or "direct"
            print(f"[ingest] route {label} failed: {e}")
            failures.append(label)
    else:
        if routes == [None]:
            raise NoDownloadRoute(
                "YouTube blocked the download from this server, and no download "
                "route (YTDLP_PROXIES) is set up."
            )
        raise NoDownloadRoute(
            f"YouTube download failed on all {len(routes)} route(s) "
            f"({', '.join(failures)}): YouTube blocked them or they are offline. "
            "Ask a teammate to switch on their laptop (Tailscale exit node), "
            "then try again."
        )
    video_id = info["id"]
    target_audio = os.path.join(cache_dir, f"{video_id}.m4a")

    if os.path.exists(target_audio):
        _touch(target_audio)
    else:
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
        thumbnail_url=info.get("thumbnail"),
    )


def duration_label(seconds: float) -> str:
    return _fmt_duration(seconds)
