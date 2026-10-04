from backend import main
from tests.support import TEST_TEAM_ID, api_client

client = api_client()


def _row(**kw):
    base = {
        "id": "feed00000001", "url": "https://youtu.be/qt6YoGmksCc", "status": "done", "error": None,
        "video_title": "Ep 1", "video_channel": "Pod", "video_duration": 60,
        "video_id": "qt6YoGmksCc", "thumbnail_url": None, "transcript_source": "groq",
        "created_at": "2026-09-24T10:00:00+00:00", "team_id": TEST_TEAM_ID,
    }
    base.update(kw)
    return base


def test_jobs_endpoint_returns_projects(monkeypatch):
    seen = {}

    def fake_counts(ids):
        seen["ids"] = ids
        return {"feed00000001": 4}

    monkeypatch.setattr(main.db, "list_jobs", lambda team_id, limit=20: [_row()])
    monkeypatch.setattr(main.db, "count_clips_by_job", fake_counts)
    body = client.get("/api/jobs").json()
    assert seen["ids"] == ["feed00000001"]
    assert body[0]["clipCount"] == 4
    assert body[0]["thumbnailUrl"] == "https://i.ytimg.com/vi/qt6YoGmksCc/hqdefault.jpg"


def test_jobs_endpoint_filters(monkeypatch):
    monkeypatch.setattr(main.db, "list_jobs", lambda team_id, limit=20: [_row(), _row(id="feed00000002", video_title="Other", status="error")])
    monkeypatch.setattr(main.db, "count_clips_by_job", lambda ids: {})
    assert [p["id"] for p in client.get("/api/jobs?q=ep").json()] == ["feed00000001"]
    assert [p["id"] for p in client.get("/api/jobs?status=error").json()] == ["feed00000002"]
    assert client.get("/api/jobs?status=bogus").status_code == 422
    assert client.get("/api/jobs?limit=500").status_code == 422


def test_jobs_endpoint_includes_in_memory_jobs(monkeypatch):
    monkeypatch.setattr(main.db, "list_jobs", lambda team_id, limit=20: [])
    monkeypatch.setattr(main.db, "count_clips_by_job", lambda ids: {})
    main.JOBS["feed00000003"] = main.Job(id="feed00000003", url="https://youtu.be/_aw32rFL680", status="transcribing", team_id=TEST_TEAM_ID)
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


def test_status_includes_language_note_from_memory():
    main.JOBS["feed00000004"] = main.Job(
        id="feed00000004", url="https://youtu.be/_aw32rFL680", status="done", team_id=TEST_TEAM_ID,
        language_used="english", language_note="Detected English audio. Captions will be in English.",
    )
    try:
        body = client.get("/api/status/feed00000004").json()
        assert body["language"] == "english"
        assert body["languageNote"].startswith("Detected English")
    finally:
        main.JOBS.pop("feed00000004", None)


def test_status_fallback_includes_language(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _row(language_used="hinglish", language_note=None))
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [])
    body = client.get("/api/status/feed00000001").json()
    assert body["language"] == "hinglish" and body["languageNote"] is None


def test_project_list_includes_language(monkeypatch):
    monkeypatch.setattr(main.db, "list_jobs", lambda team_id, limit=20: [_row(language_used="english")])
    monkeypatch.setattr(main.db, "count_clips_by_job", lambda ids: {})
    assert client.get("/api/jobs").json()[0]["language"] == "english"


def _stub_delete(monkeypatch, calls):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _row())
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [{"id": "feed00000001-0", "storage_key": "feed00000001/clip_0.mp4"}])
    monkeypatch.setattr(main.db, "list_render_keys_for_job", lambda job_id: ["renders/r1.mp4"])
    monkeypatch.setattr(main.db, "delete_job", lambda job_id: calls.append(("job", job_id)))
    monkeypatch.setattr(main.storage, "delete_clip", lambda key: calls.append(("r2", key)))


def test_delete_project_removes_row_and_media(monkeypatch):
    calls = []
    _stub_delete(monkeypatch, calls)
    res = client.delete("/api/jobs/feed00000001")
    assert res.status_code == 204
    assert ("job", "feed00000001") in calls
    r2 = {k for kind, k in calls if kind == "r2"}
    assert {"feed00000001/clip_0.mp4", "renders/r1.mp4"} <= r2


def test_delete_project_refuses_while_processing(monkeypatch):
    calls = []
    _stub_delete(monkeypatch, calls)
    main.JOBS["feed00000001"] = main.Job(id="feed00000001", url="https://youtu.be/qt6YoGmksCc", status="transcribing", team_id=TEST_TEAM_ID)
    try:
        assert client.delete("/api/jobs/feed00000001").status_code == 409
        assert calls == []
    finally:
        main.JOBS.pop("feed00000001", None)


def test_delete_project_other_team_is_404(monkeypatch):
    calls = []
    _stub_delete(monkeypatch, calls)
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _row(team_id="someone-else"))
    assert client.delete("/api/jobs/feed00000001").status_code == 404
    assert calls == []


def test_delete_project_db_failure_keeps_media(monkeypatch):
    calls = []
    _stub_delete(monkeypatch, calls)

    def boom(job_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(main.db, "delete_job", boom)
    assert client.delete("/api/jobs/feed00000001").status_code == 500
    assert calls == []


def test_retry_failed_starts_new_job_and_removes_old(monkeypatch):
    calls = []
    _stub_delete(monkeypatch, calls)
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _row(status="error", language_requested="english"))
    started = []
    monkeypatch.setattr(main, "_run_pipeline", lambda job: started.append(job))
    res = client.post("/api/jobs/feed00000001/retry")
    assert res.status_code == 200
    new_id = res.json()["job_id"]
    try:
        assert new_id != "feed00000001"
        assert main.JOBS[new_id].url == "https://youtu.be/qt6YoGmksCc"
        assert main.JOBS[new_id].language_requested == "english"
        assert ("job", "feed00000001") in calls
    finally:
        main.JOBS.pop(new_id, None)


def test_retry_rejects_done_job(monkeypatch):
    calls = []
    _stub_delete(monkeypatch, calls)
    assert client.post("/api/jobs/feed00000001/retry").status_code == 409
    assert calls == []
