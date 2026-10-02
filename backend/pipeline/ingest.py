"""Ingest: download audio/video via yt-dlp and get basic metadata."""
from __future__ import annotations

import os
from dataclasses import dataclass

import yt_dlp
from yt_dlp.utils import DownloadError, download_range_func

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
    "ffmpeg exited",
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


def _base_opts(route: str | None) -> dict:
    base = {"quiet": True, "noplaylist": True, **_ROUTE_OPTS}
    if route:
        base["proxy"] = route
    return base


def _find_audio(cache_dir: str, video_id: str) -> str | None:
    for name in sorted(os.listdir(cache_dir)):
        if name.startswith(f"{video_id}.audio.") and not name.endswith((".part", ".ytdl")):
            return os.path.join(cache_dir, name)
    return None


def _fetch_audio(
    url: str, cache_dir: str, route: str | None, on_progress: "callable | None"
) -> tuple[dict, str]:
    """Read the video's info and download its audio track only (unless
    cached) over one route. Returns (info, path of the cached audio)."""
    base = _base_opts(route)

    # First pass: extract info only, to get a stable video_id for caching.
    with yt_dlp.YoutubeDL({**base, "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    video_id = info["id"]
    cached = _find_audio(cache_dir, video_id)
    if cached:
        _touch(cached)  # marks it as recently used for cache pruning
        return info, cached

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
                on_progress("downloading", 100.0, "download complete")
        except Exception:
            pass  # progress reporting must never break the pipeline

    ydl_opts = {
        **base,
        # Audio only: transcription needs nothing else, and the video
        # for each clip is fetched later, just that clip's part of it.
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": os.path.join(cache_dir, f"{video_id}.audio.%(ext)s"),
        "progress_hooks": [_hook],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    audio = _find_audio(cache_dir, video_id)
    if audio is None:
        raise RuntimeError("audio download finished but no file was found")
    return info, audio


def _with_routes(action: "callable"):
    """Run action(route) over each configured route in order, moving on
    only when a route is blocked or offline."""
    routes = download_routes()
    failures: list[str] = []
    for route in routes:
        try:
            return action(route)
        except DownloadError as e:
            if not _is_route_error(e):
                raise
            label = route or "direct"
            print(f"[ingest] route {label} failed: {e}")
            failures.append(label)
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


def ingest(url: str, cache_dir: str, on_progress: "callable | None" = None) -> VideoMeta:
    """Download the video's audio track (for transcription) with yt-dlp.
    Results are cached by video ID so re-processing the same link is
    instant. The video itself is not downloaded here: each clip's part of
    it is fetched by fetch_section when the clip is prepared.

    If given, `on_progress(stage, percent, note)` is called during
    download (stage="downloading") — lets callers surface live progress
    instead of the caller staring at a silent status for minutes on a
    large podcast file.
    """
    os.makedirs(cache_dir, exist_ok=True)
    info, audio_path = _with_routes(lambda route: _fetch_audio(url, cache_dir, route, on_progress))
    return VideoMeta(
        video_id=info["id"],
        title=info.get("title") or "Untitled",
        channel=info.get("uploader") or info.get("channel") or "Unknown",
        duration=float(info.get("duration") or 0),
        audio_path=audio_path,
        thumbnail_url=info.get("thumbnail"),
    )


# Same preference as before: H.264 at 1080p or lower, which every browser
# can decode for the live preview.
_VIDEO_FORMAT = (
    "bestvideo[vcodec^=avc1][height<=1080][ext=mp4]+bestaudio[ext=m4a]"
    "/best[vcodec^=avc1][height<=1080][ext=mp4]"
    "/bestvideo[height<=1080]+bestaudio/best"
)


def _fetch_section(url: str, start: float, end: float, out_path: str, route: str | None) -> None:
    base = _base_opts(route)
    out_dir = os.path.dirname(out_path)
    stem = os.path.splitext(os.path.basename(out_path))[0]
    opts = {
        **base,
        "format": _VIDEO_FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(out_dir, f"{stem}.%(ext)s"),
        "download_ranges": download_range_func(None, [(start, end)]),
        # Re-encodes at the cut points, so the file starts exactly at
        # `start` (checked against the full audio: within 0.01 s). Without
        # it the cut snaps back to the previous keyframe and every caption
        # time in the clip's spec would be off by that much.
        "force_keyframes_at_cuts": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("section download finished but no file was found")


def fetch_section(url: str, start: float, end: float, out_path: str) -> str:
    """Download only seconds start..end of the video into out_path (an
    .mp4), failing over between download routes like ingest does."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    _with_routes(lambda route: _fetch_section(url, start, end, out_path, route))
    return out_path


def duration_label(seconds: float) -> str:
    return _fmt_duration(seconds)
