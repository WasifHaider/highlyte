from fastapi.testclient import TestClient

from backend import main

client = TestClient(main.app)


def _row(**kw):
    base = {
        "id": "feed00000001", "url": "https://youtu.be/qt6YoGmksCc", "status": "done", "error": None,
        "video_title": "Ep 1", "video_channel": "Pod", "video_duration": 60,
        "video_id": "qt6YoGmksCc", "thumbnail_url": None, "transcript_source": "groq",
        "created_at": "2026-09-24T10:00:00+00:00",
    }
    base.update(kw)
    return base


def test_jobs_endpoint_returns_projects(monkeypatch):
    seen = {}

    def fake_counts(ids):
        seen["ids"] = ids
        return {"feed00000001": 4}

    monkeypatch.setattr(main.db, "list_jobs", lambda limit=20: [_row()])
    monkeypatch.setattr(main.db, "count_clips_by_job", fake_counts)
    body = client.get("/api/jobs").json()
    assert seen["ids"] == ["feed00000001"]
    assert body[0]["clipCount"] == 4
    assert body[0]["thumbnailUrl"] == "https://i.ytimg.com/vi/qt6YoGmksCc/hqdefault.jpg"


def test_jobs_endpoint_filters(monkeypatch):
    monkeypatch.setattr(main.db, "list_jobs", lambda limit=20: [_row(), _row(id="feed00000002", video_title="Other", status="error")])
    monkeypatch.setattr(main.db, "count_clips_by_job", lambda ids: {})
    assert [p["id"] for p in client.get("/api/jobs?q=ep").json()] == ["feed00000001"]
    assert [p["id"] for p in client.get("/api/jobs?status=error").json()] == ["feed00000002"]
    assert client.get("/api/jobs?status=bogus").status_code == 422
    assert client.get("/api/jobs?limit=500").status_code == 422


def test_jobs_endpoint_includes_in_memory_jobs(monkeypatch):
    monkeypatch.setattr(main.db, "list_jobs", lambda limit=20: [])
    monkeypatch.setattr(main.db, "count_clips_by_job", lambda ids: {})
    main.JOBS["feed00000003"] = main.Job(id="feed00000003", url="https://youtu.be/_aw32rFL680", status="transcribing")
    try:
        body = client.get("/api/jobs").json()
        assert body[0]["id"] == "feed00000003"
        assert body[0]["status"] == "transcribing"
        assert body[0]["createdAt"]
    finally:
        main.JOBS.pop("feed00000003", None)


def test_status_fallback_includes_thumbnail(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _row(thumbnail_url="https://x/t.jpg"))
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [])
    meta = client.get("/api/status/feed00000001").json()["videoMeta"]
    assert meta["videoId"] == "qt6YoGmksCc"
    assert meta["thumbnailUrl"] == "https://x/t.jpg"
