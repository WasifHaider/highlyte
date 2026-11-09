import pytest

from backend import main, storage
from backend.pipeline import uploads
from tests.support import TEST_TEAM_ID, api_client
from tests.test_uploads import FakeR2

client = api_client()


@pytest.fixture
def r2(monkeypatch):
    fake = FakeR2()
    monkeypatch.setattr(storage, "get_client", lambda: fake)
    main.PENDING_UPLOADS.clear()
    yield fake
    main.PENDING_UPLOADS.clear()


@pytest.fixture
def started(monkeypatch):
    jobs = []
    monkeypatch.setattr(main, "_start_thread", lambda target, *args, **kw: jobs.append(args[0]))
    yield jobs
    for job in jobs:
        main.JOBS.pop(job.id, None)


def start_upload(size=1000, filename="Ep 7.mp4"):
    return client.post("/api/uploads", json={"filename": filename, "size": size, "contentType": "video/mp4"})


def test_create_returns_part_urls(r2):
    res = start_upload(size=uploads.PART_SIZE + 5)
    assert res.status_code == 200
    body = res.json()
    assert len(body["uploadId"]) == 12
    assert body["partSize"] == uploads.PART_SIZE
    assert len(body["partUrls"]) == 2
    assert main.PENDING_UPLOADS[body["uploadId"]]["team"] == TEST_TEAM_ID


def test_create_rejects_bad_files(r2):
    res = start_upload(filename="slides.pdf")
    assert res.status_code == 400
    assert "isn't supported" in res.json()["detail"]
    res = start_upload(size=uploads.MAX_BYTES + 1)
    assert res.status_code == 400
    assert res.json()["detail"] == "File is over 5 GB."


def test_uploads_need_r2(monkeypatch):
    monkeypatch.setattr(storage, "get_client", lambda: None)
    assert start_upload().status_code == 503
    assert client.get("/api/health").json()["uploads"] is False


def test_health_reports_uploads(r2):
    assert client.get("/api/health").json()["uploads"] is True


def test_complete_starts_a_job_from_the_upload(r2, started):
    body = start_upload().json()
    uid = body["uploadId"]
    r2.put_part(main.PENDING_UPLOADS[uid]["r2UploadId"], 1, b"video")
    res = client.post(f"/api/uploads/{uid}/complete",
                      json={"parts": [{"partNumber": 1, "etag": '"etag1"'}], "language": "english"})
    assert res.status_code == 200
    job = main.JOBS[res.json()["job_id"]]
    assert job.url == f"upload:{uid}"
    assert job.language_requested == "english"
    assert job.team_id == TEST_TEAM_ID
    assert started == [job]
    assert f"uploads/{uid}/source.mp4" in r2.objects
    assert uid not in main.PENDING_UPLOADS
    # Completing twice is refused.
    again = client.post(f"/api/uploads/{uid}/complete", json={"parts": [{"partNumber": 1, "etag": "x"}]})
    assert again.status_code == 404


def test_other_team_cannot_complete_or_abort(r2, started):
    uid = start_upload().json()["uploadId"]
    main.PENDING_UPLOADS[uid]["team"] = "someone-else"
    assert client.post(f"/api/uploads/{uid}/complete",
                       json={"parts": [{"partNumber": 1, "etag": "x"}]}).status_code == 404
    assert client.delete(f"/api/uploads/{uid}").status_code == 404
    assert started == []


def test_abort_cancels_the_upload(r2):
    uid = start_upload().json()["uploadId"]
    r2_id = main.PENDING_UPLOADS[uid]["r2UploadId"]
    assert client.delete(f"/api/uploads/{uid}").status_code == 204
    assert r2_id in r2.aborted
    assert uid not in main.PENDING_UPLOADS


def test_bad_upload_ids_are_rejected(r2):
    assert client.delete("/api/uploads/NOT-AN-ID").status_code in (404, 422)


def test_generate_refuses_upload_sources(started):
    for url in ["upload:abcdef012345", " UPLOAD:abcdef012345"]:
        assert client.post("/api/generate", json={"url": url}).status_code == 422
    assert started == []


def test_generate_still_takes_links_without_a_scheme(started):
    res = client.post("/api/generate", json={"url": "youtube.com/watch?v=qt6YoGmksCc"})
    assert res.status_code == 200
    assert started[0].url == "youtube.com/watch?v=qt6YoGmksCc"


def test_thumb_is_served_to_the_owning_team(r2):
    uid = "abcdef012345"
    r2.objects[uploads.thumb_key(uid)] = {"data": b"\xff\xd8jpeg", "meta": {}}
    main.JOBS["feed0000up01"] = main.Job(id="feed0000up01", url=f"upload:{uid}", team_id=TEST_TEAM_ID)
    try:
        res = client.get(f"/api/uploads/{uid}/thumb.jpg")
        assert res.status_code == 200
        assert res.content == b"\xff\xd8jpeg"
        assert res.headers["content-type"] == "image/jpeg"
        main.JOBS["feed0000up01"].team_id = "someone-else"
        assert client.get(f"/api/uploads/{uid}/thumb.jpg").status_code == 404
    finally:
        main.JOBS.pop("feed0000up01", None)


def _stub_db(monkeypatch, calls, url):
    row = {"id": "feed0000up01", "url": url, "status": "error", "team_id": TEST_TEAM_ID,
           "language_requested": "hinglish"}
    monkeypatch.setattr(main.db, "get_job", lambda job_id: row)
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [])
    monkeypatch.setattr(main.db, "list_render_keys_for_job", lambda job_id: [])
    monkeypatch.setattr(main.db, "delete_job", lambda job_id: calls.append(("job", job_id)))
    monkeypatch.setattr(main.uploads, "delete_upload", lambda uid: calls.append(("upload", uid)))


def test_deleting_an_upload_project_deletes_the_original(monkeypatch):
    calls = []
    _stub_db(monkeypatch, calls, "upload:abcdef012345")
    assert client.delete("/api/jobs/feed0000up01").status_code == 204
    assert calls == [("job", "feed0000up01"), ("upload", "abcdef012345")]


def test_deleting_a_youtube_project_touches_no_upload(monkeypatch):
    calls = []
    _stub_db(monkeypatch, calls, "https://youtu.be/x")
    assert client.delete("/api/jobs/feed0000up01").status_code == 204
    assert calls == [("job", "feed0000up01")]


def test_retrying_a_failed_upload_keeps_the_original(monkeypatch, started):
    calls = []
    _stub_db(monkeypatch, calls, "upload:abcdef012345")
    res = client.post("/api/jobs/feed0000up01/retry")
    assert res.status_code == 200
    assert main.JOBS[res.json()["job_id"]].url == "upload:abcdef012345"
    assert calls == [("job", "feed0000up01")]
