"""Ingest: download audio/video via yt-dlp and get basic metadata."""
from __future__ import annotations

import os
import random
import socket
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import yt_dlp
from yt_dlp.utils import DownloadError

from . import cut

# YouTube blocks datacenter IPs like EC2's. YTDLP_PROXIES lists proxies
# (Tailscale sidecars that leave through teammates' home laptops) to use;
# unset means a direct connection, as in local development.
PROXIES_ENV = "YTDLP_PROXIES"

# Error text that means "this route is rate-limited by YouTube right now".
# Waiting (not switching IP faster) is what clears it.
_RATE_ERRORS = (
    "not a bot",
    "http error 429",
    "too many requests",
)

# Error text that means "this route can't reach YouTube at all right now"
# (a laptop asleep, Tailscale down, a dropped connection).
_OFFLINE_ERRORS = (
    "unable to connect to proxy",
    "proxyerror",
    "tunnel connection failed",
    "socks",
    "connection refused",
    "connection reset",
    "timed out",
    "network is unreachable",
    "name resolution",
)

# Errors that might pass on a retry but say nothing about the route itself.
_TRANSIENT_ERRORS = ("ffmpeg exited",)

# A dead proxy should fail in seconds, not after yt-dlp's default retries.
# remote_components lets yt-dlp fetch YouTube's challenge solver script when
# it is not bundled; without it formats go missing and requests multiply.
_ROUTE_OPTS = {
    "socket_timeout": 20,
    "retries": 2,
    "extractor_retries": 1,
    "remote_components": ["ejs:github"],
}

# How long a route is skipped after failing, by kind of failure (seconds).
RATE_COOLDOWN_S = 600.0
OFFLINE_COOLDOWN_S = 45.0
TRANSIENT_COOLDOWN_S = 30.0
# Pause before retrying a rate-limited route once, with jitter added.
RATE_BACKOFF_S = 45.0
# How long a job waits for any route to come back before giving up.
DEFAULT_WAIT_S = 900.0
WAIT_POLL_S = 15.0

# A proxy that answered a probe is trusted for this long.
_PROBE_TTL_S = 30.0
_PROBE_TIMEOUT_S = 8.0

WAITING_NOTE = "waiting for a download route to come back…"


class NoDownloadRoute(RuntimeError):
    """Every configured route was blocked by YouTube or offline."""


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def download_routes() -> list[str | None]:
    """Proxies from YTDLP_PROXIES in order, or [None] for a direct connection."""
    raw = os.environ.get(PROXIES_ENV) or ""
    routes = [p.strip() for p in raw.split(",") if p.strip()]
    return routes or [None]


def _classify(e: Exception) -> str | None:
    """"rate", "offline", "transient", or None when the video itself is the
    problem (private, removed, age-gated) and no other route would help."""
    text = str(e).lower()
    if any(m in text for m in _RATE_ERRORS):
        return "rate"
    if any(m in text for m in _OFFLINE_ERRORS):
        return "offline"
    if any(m in text for m in _TRANSIENT_ERRORS):
        return "transient"
    return None


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _label(route: str | None) -> str:
    return route or "direct"


class _RouteBoard:
    """Shared by every job: which routes are cooling down, and whose turn
    is next, so load spreads over the laptops instead of hitting the first
    one every time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until: dict[str | None, tuple[float, str]] = {}
        self._cursor = 0

    def reset(self) -> None:
        with self._lock:
            self._until.clear()
            self._cursor = 0

    def order(self, routes: list[str | None]) -> list[str | None]:
        """Routes not cooling down, starting from the next one in turn."""
        now = time.monotonic()
        with self._lock:
            start = self._cursor % len(routes)
            rotated = routes[start:] + routes[:start]
            return [r for r in rotated if self._until.get(r, (0.0, ""))[0] <= now]

    def used(self, routes: list[str | None], route: str | None) -> None:
        with self._lock:
            if route in routes:
                self._cursor = (routes.index(route) + 1) % len(routes)

    def penalize(self, route: str | None, kind: str) -> None:
        seconds = {
            "rate": _env_float("YTDLP_RATE_COOLDOWN_S", RATE_COOLDOWN_S),
            "offline": OFFLINE_COOLDOWN_S,
        }.get(kind, TRANSIENT_COOLDOWN_S)
        with self._lock:
            self._until[route] = (time.monotonic() + seconds, kind)

    def seconds_until_ready(self, routes: list[str | None]) -> float:
        now = time.monotonic()
        with self._lock:
            return max(0.0, min(self._until.get(r, (0.0, ""))[0] for r in routes) - now)

    def kinds(self, routes: list[str | None]) -> set[str]:
        with self._lock:
            return {self._until[r][1] for r in routes if r in self._until}


BOARD = _RouteBoard()

# Caps simultaneous YouTube downloads so two jobs never hammer one IP.
_DOWNLOAD_SLOTS = threading.BoundedSemaphore(max(1, int(_env_float("YTDLP_CONCURRENCY", 2))))

_probed: dict[str, float] = {}


def _probe(route: str | None) -> bool:
    """Cheap check that an HTTP proxy can reach YouTube right now: ask it to
    open a tunnel. A sleeping laptop fails this in seconds instead of
    costing yt-dlp's full timeout and retries."""
    if route is None:
        return True
    parsed = urlparse(route)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return True  # can't probe it (e.g. SOCKS); let the download decide
    if time.monotonic() - _probed.get(route, -1e9) < _PROBE_TTL_S:
        return True
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 80), _PROBE_TIMEOUT_S) as s:
            s.settimeout(_PROBE_TIMEOUT_S)
            s.sendall(b"CONNECT www.youtube.com:443 HTTP/1.1\r\nHost: www.youtube.com:443\r\n\r\n")
            status_line = s.recv(256).split(b"\r\n", 1)[0]
    except OSError:
        return False
    ok = b" 200" in status_line
    if ok:
        _probed[route] = time.monotonic()
    return ok


def _explain(kinds: set[str]) -> str:
    if kinds == {"rate"}:
        return (
            "YouTube is rate-limiting every download route right now. This "
            "usually clears within 10-15 minutes: try again then."
        )
    if "rate" in kinds:
        return (
            "YouTube is rate-limiting a download route and the other route(s) "
            "are offline. Try again in 10-15 minutes, and ask a teammate to "
            "check their laptop is awake with Tailscale running."
        )
    return (
        "No download route is reachable. Ask a teammate to wake their laptop "
        "and make sure Tailscale is running (exit node on), then try again."
    )


def _with_routes(action: "callable", on_progress: "callable | None" = None):
    """Run action(route) on the configured routes. Routes take turns, one
    that is rate-limited is retried once after a pause and then rested, one
    that is offline is skipped until it answers a probe. If none is usable,
    wait for one to return (up to YTDLP_WAIT_S) before giving up."""
    routes = download_routes()
    direct = routes == [None]
    deadline = time.monotonic() + _env_float("YTDLP_WAIT_S", DEFAULT_WAIT_S)
    while True:
        for route in BOARD.order(routes):
            label = _label(route)
            if not _probe(route):
                print(f"[ingest] route {label} is not answering, skipping it")
                BOARD.penalize(route, "offline")  # _probe only fails real proxies
                continue
            for attempt in range(2):
                try:
                    with _DOWNLOAD_SLOTS:
                        result = action(route)
                    BOARD.used(routes, route)
                    return result
                except DownloadError as e:
                    kind = _classify(e)
                    if kind is None:
                        raise
                    print(f"[ingest] route {label} failed ({kind}): {e}")
                    if kind == "rate" and attempt == 0:
                        _sleep(RATE_BACKOFF_S + random.uniform(0, 15))
                        continue
                    if not direct:  # a direct connection has nothing to rotate to
                        BOARD.penalize(route, kind)
                    break
        kinds = BOARD.kinds(routes)
        if direct:
            raise NoDownloadRoute(
                "YouTube blocked the download from this server, and no download "
                "route (YTDLP_PROXIES) is set up."
                if "rate" in kinds else
                "Couldn't reach YouTube from this server."
            )
        wait = BOARD.seconds_until_ready(routes)
        if time.monotonic() + wait > deadline:
            raise NoDownloadRoute(_explain(kinds))
        if on_progress is not None:
            try:
                on_progress("downloading", None, WAITING_NOTE)
            except Exception:
                pass
        _sleep(min(max(wait, 1.0), WAIT_POLL_S))


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


def _progress_hook(on_progress: "callable | None"):
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

    return _hook


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

    ydl_opts = {
        **base,
        # Audio only: transcription needs nothing else. The video for the
        # clips is fetched once later, by SectionSource.
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": os.path.join(cache_dir, f"{video_id}.audio.%(ext)s"),
        "progress_hooks": [_progress_hook(on_progress)],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    audio = _find_audio(cache_dir, video_id)
    if audio is None:
        raise RuntimeError("audio download finished but no file was found")
    return info, audio


def ingest(url: str, cache_dir: str, on_progress: "callable | None" = None) -> VideoMeta:
    """Download the video's audio track (for transcription) with yt-dlp.
    Results are cached by video ID so re-processing the same link is
    instant. The video itself is not downloaded here: SectionSource fetches
    it, once, when the first clip is prepared.

    If given, `on_progress(stage, percent, note)` is called during
    download (stage="downloading") — lets callers surface live progress
    instead of the caller staring at a silent status for minutes on a
    large podcast file.
    """
    os.makedirs(cache_dir, exist_ok=True)
    info, audio_path = _with_routes(
        lambda route: _fetch_audio(url, cache_dir, route, on_progress), on_progress
    )
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

_video_locks: dict[str, threading.Lock] = {}
_video_locks_guard = threading.Lock()


def _video_lock(video_id: str) -> threading.Lock:
    with _video_locks_guard:
        return _video_locks.setdefault(video_id, threading.Lock())


def _video_path(cache_dir: str, video_id: str) -> str:
    return os.path.join(cache_dir, f"{video_id}.video.mp4")


def _fetch_video(url: str, cache_dir: str, video_id: str, route: str | None,
                 on_progress: "callable | None") -> None:
    opts = {
        **_base_opts(route),
        "format": _VIDEO_FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(cache_dir, f"{video_id}.video.%(ext)s"),
        "progress_hooks": [_progress_hook(on_progress)],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


class SectionSource:
    """Gives clip sections of one video. The whole video is downloaded once
    (cached by video id), then every clip is cut out of it locally with
    ffmpeg, so a job makes one YouTube download no matter how many clips it
    has. Call it as source(start, end, out_path)."""

    def __init__(self, url: str, cache_dir: str, video_id: str,
                 on_progress: "callable | None" = None) -> None:
        self.url, self.cache_dir, self.video_id = url, cache_dir, video_id
        self.on_progress = on_progress

    def _video(self) -> str:
        path = _video_path(self.cache_dir, self.video_id)
        with _video_lock(self.video_id):  # one download even if clips run together
            if os.path.exists(path) and os.path.getsize(path) > 0:
                _touch(path)
                return path
            os.makedirs(self.cache_dir, exist_ok=True)
            _with_routes(
                lambda route: _fetch_video(self.url, self.cache_dir, self.video_id, route, self.on_progress),
                self.on_progress,
            )
            if not os.path.exists(path) or os.path.getsize(path) == 0:
                raise RuntimeError("video download finished but no file was found")
            return path

    def __call__(self, start: float, end: float, out_path: str) -> str:
        source = self._video()
        # Re-encodes at the cut points, so the file starts exactly at
        # `start` (every caption time in the clip's spec depends on it).
        return cut.cut_clip(source, start, end, out_path)


def duration_label(seconds: float) -> str:
    return _fmt_duration(seconds)
