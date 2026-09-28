import os

import pytest
from yt_dlp.utils import DownloadError

from backend.pipeline import ingest

BOT = "ERROR: [youtube] abc: Sign in to confirm you're not a bot. Use --cookies-from-browser"
DEAD = "ERROR: Unable to download webpage: Unable to connect to proxy (caused by ProxyError)"
GONE = "ERROR: [youtube] abc: Video unavailable. This video is private"


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL. `outcomes` maps a proxy (None for a
    direct connection) to an error message to raise, or None to succeed.
    Every call is recorded as (proxy, "info" | "download")."""

    outcomes: dict = {}
    calls: list = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _run(self, kind):
        proxy = self.opts.get("proxy")
        FakeYDL.calls.append((proxy, kind))
        error = FakeYDL.outcomes.get(proxy)
        if error:
            raise DownloadError(error)

    def extract_info(self, url, download=False):
        self._run("info")
        return {"id": "abc", "title": "T", "uploader": "U", "duration": 60, "thumbnail": None}

    def download(self, urls):
        self._run("download")
        path = self.opts["outtmpl"].replace("%(ext)s", "mp4")
        with open(path, "wb") as f:
            f.write(b"video")


@pytest.fixture
def ydl(monkeypatch, tmp_path):
    FakeYDL.outcomes = {}
    FakeYDL.calls = []
    monkeypatch.setattr(ingest.yt_dlp, "YoutubeDL", FakeYDL)
    # The audio track already exists, so ingest never shells out to ffmpeg.
    (tmp_path / "abc.m4a").write_bytes(b"audio")
    return FakeYDL


def test_routes_default_to_a_direct_connection(monkeypatch):
    monkeypatch.delenv("YTDLP_PROXIES", raising=False)
    assert ingest.download_routes() == [None]


def test_routes_come_from_env_in_order(monkeypatch):
    monkeypatch.setenv("YTDLP_PROXIES", " socks5://ts-a:1055 ,, socks5://ts-b:1055 ")
    assert ingest.download_routes() == ["socks5://ts-a:1055", "socks5://ts-b:1055"]


def test_direct_download_passes_no_proxy(monkeypatch, ydl, tmp_path):
    monkeypatch.delenv("YTDLP_PROXIES", raising=False)
    meta = ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert meta.video_id == "abc"
    assert ydl.calls == [(None, "info"), (None, "download")]


def test_blocked_route_falls_over_to_the_next(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "socks5://a:1055,socks5://b:1055,socks5://c:1055")
    ydl.outcomes = {"socks5://a:1055": BOT, "socks5://b:1055": DEAD}
    meta = ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert os.path.exists(meta.video_path)
    assert ydl.calls == [
        ("socks5://a:1055", "info"),
        ("socks5://b:1055", "info"),
        ("socks5://c:1055", "info"),
        ("socks5://c:1055", "download"),
    ]


def test_video_errors_are_not_retried_on_other_routes(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "socks5://a:1055,socks5://b:1055")
    ydl.outcomes = {"socks5://a:1055": GONE}
    with pytest.raises(DownloadError, match="Video unavailable"):
        ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert ydl.calls == [("socks5://a:1055", "info")]


def test_all_routes_down_gives_a_plain_error(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "socks5://a:1055,socks5://b:1055")
    ydl.outcomes = {"socks5://a:1055": BOT, "socks5://b:1055": DEAD}
    with pytest.raises(ingest.NoDownloadRoute, match="teammate"):
        ingest.ingest("https://youtu.be/abc", str(tmp_path))


def test_cached_video_only_fetches_info(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "socks5://a:1055")
    (tmp_path / "abc.mp4").write_bytes(b"video")
    ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert ydl.calls == [("socks5://a:1055", "info")]
