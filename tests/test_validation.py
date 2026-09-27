import pytest
from fastapi import HTTPException

from backend import main
from backend.main import app
from backend.validation import check_clip_filename, check_id
from tests.support import TEST_TEAM_ID, api_client

client = api_client()


@pytest.mark.parametrize("value", ["abc123", "a1b2c3d4e5f6-0", "renders-1"])
def test_check_id_accepts(value):
    assert check_id(value) == value


@pytest.mark.parametrize("value", ["..", "../etc", "ABC", "a/b", "a\\b", "", "x" * 65])
def test_check_id_rejects(value):
    with pytest.raises(HTTPException) as exc:
        check_id(value)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("value", ["clip_0.mp4", "clip_12.mp4", "clip_0.jpg", "clip_3_r2.jpg"])
def test_check_clip_filename_accepts(value):
    assert check_clip_filename(value) == value


@pytest.mark.parametrize("value", ["secret.txt", "clip_0.mp4.exe", "../clip_0.mp4", "clip_a.mp4", "clip_0.png"])
def test_check_clip_filename_rejects(value):
    with pytest.raises(HTTPException):
        check_clip_filename(value)


def test_get_clip_rejects_traversal_job_id():
    assert client.get("/api/clips/..%2e/clip_0.mp4").status_code == 400


def test_get_clip_rejects_bad_filename():
    assert client.get("/api/clips/abc123/secret.txt").status_code == 400


def test_generate_rejects_unknown_language():
    r = client.post("/api/generate", json={"url": "https://youtu.be/x", "language": "french"})
    assert r.status_code == 422


def test_generate_accepts_language_and_defaults_to_hinglish(monkeypatch):
    started = []
    monkeypatch.setattr(main.threading, "Thread", lambda target, args, daemon: type(
        "T", (), {"start": lambda self: started.append(args[0])})())
    client.post("/api/generate", json={"url": "https://youtu.be/x"})
    client.post("/api/generate", json={"url": "https://youtu.be/y", "language": "english"})
    assert [j.language_requested for j in started] == ["hinglish", "english"]
    for j in started:
        main.JOBS.pop(j.id, None)


@pytest.mark.parametrize("value", ["clip_0_r1.mp4", "clip_12_r345.mp4"])
def test_check_clip_filename_accepts_revisions(value):
    assert check_clip_filename(value) == value


@pytest.mark.parametrize("value", ["clip_0_r.mp4", "clip_0_rx.mp4", "clip_0_r1.mp4/..", "clip_0-r1.mp4"])
def test_check_clip_filename_rejects_bad_revisions(value):
    with pytest.raises(HTTPException):
        check_clip_filename(value)


def test_get_clip_serves_a_local_poster_as_jpeg(tmp_path, monkeypatch):
    import os
    job_id = "feed0000000a"
    monkeypatch.setattr(main, "CLIPS_DIR", str(tmp_path))
    monkeypatch.setattr(main.storage, "is_enabled", lambda: False)
    os.makedirs(tmp_path / job_id)
    (tmp_path / job_id / "clip_0.jpg").write_bytes(b"jpg")
    main.JOBS[job_id] = main.Job(id=job_id, url="u", status="done", team_id=TEST_TEAM_ID)
    try:
        r = client.get(f"/api/clips/{job_id}/clip_0.jpg")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    finally:
        main.JOBS.pop(job_id, None)


def test_get_clip_redirect_is_briefly_cacheable(monkeypatch):
    # The browser can reuse the redirect instead of asking the API again
    # for every video element; shorter than a cached presigned URL's
    # minimum remaining life, so it never points at an expired one.
    job_id = "feed0000000b"
    monkeypatch.setattr(main.storage, "is_enabled", lambda: True)
    monkeypatch.setattr(main.storage, "clip_exists", lambda key: True)
    monkeypatch.setattr(main.storage, "clip_url", lambda key: "https://r2.example/x")
    main.JOBS[job_id] = main.Job(id=job_id, url="u", status="done", team_id=TEST_TEAM_ID)
    try:
        r = client.get(f"/api/clips/{job_id}/clip_0.mp4", follow_redirects=False)
        assert r.status_code == 307
        max_age = int(r.headers["cache-control"].split("max-age=")[1])
        assert 0 < max_age < main.storage.PRESIGNED_URL_MIN_LEFT_S
    finally:
        main.JOBS.pop(job_id, None)
