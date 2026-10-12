import os

import pytest
from yt_dlp.utils import DownloadError

from backend.pipeline import ingest

BOT = "ERROR: [youtube] abc: Sign in to confirm you're not a bot. Use --cookies-from-browser"
RATE = "ERROR: [youtube] abc: HTTP Error 429: Too Many Requests"
OFFLINE = (
    "ERROR: Unable to download API page: ('Unable to connect to proxy', "
    "OSError('Tunnel connection failed: 500 Internal Server Error'))"
)
GONE = "ERROR: [youtube] abc: Video unavailable. This video is private"


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL. `outcomes` maps a proxy (None for a
    direct connection) to an error message to raise, or None to succeed.
    Every call is recorded as (proxy, "info" | "download")."""

    outcomes: dict = {}
    calls: list = []
    downloads: list = []

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
        FakeYDL.downloads.append(self.opts)
        with open(path, "wb") as f:
            f.write(b"video")


@pytest.fixture
def ydl(monkeypatch, tmp_path):
    FakeYDL.outcomes = {}
    FakeYDL.calls = []
    FakeYDL.downloads = []
    monkeypatch.setattr(ingest.yt_dlp, "YoutubeDL", FakeYDL)
    ingest.BOARD.reset()
    ingest._probed.clear()
    monkeypatch.setattr(ingest, "_probe", lambda route: True)
    monkeypatch.setattr(ingest, "_sleep", lambda seconds: None)
    monkeypatch.setenv("YTDLP_WAIT_S", "0")
    return FakeYDL


def test_routes_default_to_a_direct_connection(monkeypatch):
    monkeypatch.delenv("YTDLP_PROXIES", raising=False)
    assert ingest.download_routes() == [None]


def test_routes_come_from_env_in_order(monkeypatch):
    monkeypatch.setenv("YTDLP_PROXIES", " http://ts-a:1056 ,, http://ts-b:1056 ")
    assert ingest.download_routes() == ["http://ts-a:1056", "http://ts-b:1056"]


def test_direct_download_passes_no_proxy(monkeypatch, ydl, tmp_path):
    monkeypatch.delenv("YTDLP_PROXIES", raising=False)
    meta = ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert meta.video_id == "abc"
    assert ydl.calls == [(None, "info"), (None, "download")]


def test_challenge_solver_download_is_allowed(monkeypatch, ydl, tmp_path):
    monkeypatch.delenv("YTDLP_PROXIES", raising=False)
    ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert "ejs:github" in ydl.downloads[0]["remote_components"]


def test_offline_routes_fall_over_to_the_next(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056,http://b:1056,http://c:1056")
    ydl.outcomes = {"http://a:1056": OFFLINE, "http://b:1056": OFFLINE}
    meta = ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert os.path.exists(meta.audio_path)
    assert ydl.calls == [
        ("http://a:1056", "info"),
        ("http://b:1056", "info"),
        ("http://c:1056", "info"),
        ("http://c:1056", "download"),
    ]


def test_video_errors_are_not_retried_on_other_routes(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056,http://b:1056")
    ydl.outcomes = {"http://a:1056": GONE}
    with pytest.raises(DownloadError, match="Video unavailable"):
        ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert ydl.calls == [("http://a:1056", "info")]


def test_age_gate_is_a_video_error_not_a_route_error(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056,http://b:1056")
    ydl.outcomes = {"http://a:1056": "ERROR: [youtube] abc: Sign in to confirm your age"}
    with pytest.raises(DownloadError, match="your age"):
        ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert ydl.calls == [("http://a:1056", "info")]


def test_all_routes_offline_says_so(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056,http://b:1056")
    ydl.outcomes = {"http://a:1056": OFFLINE, "http://b:1056": OFFLINE}
    with pytest.raises(ingest.NoDownloadRoute, match="teammate"):
        ingest.ingest("https://youtu.be/abc", str(tmp_path))


def test_all_routes_rate_limited_says_so_not_tailscale(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056,http://b:1056")
    ydl.outcomes = {"http://a:1056": RATE, "http://b:1056": BOT}
    with pytest.raises(ingest.NoDownloadRoute, match="rate-limiting") as err:
        ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert "Tailscale" not in str(err.value)


def test_rate_limited_route_is_retried_once_after_a_pause(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056")
    pauses = []
    monkeypatch.setattr(ingest, "_sleep", pauses.append)
    attempts = {"n": 0}
    real_run = FakeYDL._run

    def flaky(self, kind):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise DownloadError(RATE)
        real_run(self, kind)

    monkeypatch.setattr(FakeYDL, "_run", flaky)
    ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert len(pauses) == 1 and pauses[0] >= ingest.RATE_BACKOFF_S


def test_a_cooling_route_is_skipped_by_the_next_job(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056,http://b:1056")
    ydl.outcomes = {"http://a:1056": RATE}
    ingest.ingest("https://youtu.be/abc", str(tmp_path))
    ydl.calls.clear()
    for f in tmp_path.glob("abc.audio.*"):
        f.unlink()
    ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert {c[0] for c in ydl.calls} == {"http://b:1056"}


def test_routes_take_turns(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056,http://b:1056")
    ingest.ingest("https://youtu.be/abc", str(tmp_path))
    for f in tmp_path.glob("abc.audio.*"):
        f.unlink()
    ingest.ingest("https://youtu.be/abc", str(tmp_path))
    used = [c[0] for c in ydl.calls if c[1] == "info"]
    assert used == ["http://a:1056", "http://b:1056"]


def test_unanswering_proxy_is_skipped_without_calling_yt_dlp(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056,http://b:1056")
    monkeypatch.setattr(ingest, "_probe", lambda route: route != "http://a:1056")
    ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert {c[0] for c in ydl.calls} == {"http://b:1056"}


def test_waits_for_a_route_to_come_back(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056")
    monkeypatch.setenv("YTDLP_WAIT_S", "600")
    state = {"up": False}
    monkeypatch.setattr(ingest, "_probe", lambda route: state["up"])
    notes = []

    def sleeper(seconds):
        state["up"] = True  # the laptop wakes up while we wait
        ingest.BOARD.reset()

    monkeypatch.setattr(ingest, "_sleep", sleeper)
    ingest.ingest("https://youtu.be/abc", str(tmp_path), on_progress=lambda *a: notes.append(a))
    assert any(n[2] == ingest.WAITING_NOTE for n in notes)
    assert ydl.calls[-1] == ("http://a:1056", "download")


def test_gives_up_after_the_wait_runs_out(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056")
    monkeypatch.setenv("YTDLP_WAIT_S", "0")
    monkeypatch.setattr(ingest, "_probe", lambda route: False)
    with pytest.raises(ingest.NoDownloadRoute):
        ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert ydl.calls == []


def test_audio_only_is_downloaded(monkeypatch, ydl, tmp_path):
    monkeypatch.delenv("YTDLP_PROXIES", raising=False)
    ingest.ingest("https://youtu.be/abc", str(tmp_path))
    opts = ydl.downloads[0]
    assert opts["format"].startswith("bestaudio")
    assert not (tmp_path / "abc.mp4").exists()


def test_cached_audio_only_fetches_info(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056")
    (tmp_path / "abc.audio.m4a").write_bytes(b"audio")
    ingest.ingest("https://youtu.be/abc", str(tmp_path))
    assert ydl.calls == [("http://a:1056", "info")]


def test_clips_share_one_video_download(monkeypatch, ydl, tmp_path):
    monkeypatch.delenv("YTDLP_PROXIES", raising=False)
    cuts = []
    monkeypatch.setattr(ingest.cut, "cut_clip", lambda src, s, e, out: cuts.append((src, s, e, out)) or out)
    source = ingest.SectionSource("https://youtu.be/abc", str(tmp_path), "abc")
    source(3.0, 33.0, str(tmp_path / "c0.mp4"))
    source(50.0, 80.0, str(tmp_path / "c1.mp4"))
    ingest.SectionSource("https://youtu.be/abc", str(tmp_path), "abc")(90.0, 99.0, str(tmp_path / "c2.mp4"))
    assert ydl.calls == [(None, "download")]
    assert [(c[1], c[2]) for c in cuts] == [(3.0, 33.0), (50.0, 80.0), (90.0, 99.0)]
    assert cuts[0][0].endswith("abc.video.mp4")
    assert "bestvideo" in ydl.downloads[0]["format"]


def test_video_download_fails_over_between_routes(monkeypatch, ydl, tmp_path):
    monkeypatch.setenv("YTDLP_PROXIES", "http://a:1056,http://b:1056")
    ydl.outcomes = {"http://a:1056": OFFLINE}
    monkeypatch.setattr(ingest.cut, "cut_clip", lambda src, s, e, out: out)
    ingest.SectionSource("https://youtu.be/abc", str(tmp_path), "abc")(3.0, 33.0, str(tmp_path / "s.mp4"))
    assert [c[0] for c in ydl.calls] == ["http://a:1056", "http://b:1056"]
