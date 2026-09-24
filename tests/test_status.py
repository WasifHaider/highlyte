from fastapi.testclient import TestClient

from backend import main

client = TestClient(main.app)


def _job_row(status="done"):
    return {
        "id": "feed00000001", "url": "https://youtu.be/x", "status": status, "error": None,
        "video_title": "Ep 1", "video_channel": "Pod", "video_duration": 120,
        "transcript_source": "groq",
    }


def _clip_row():
    return {
        "id": "feed00000001-0", "job_id": "feed00000001", "idx": 0,
        "start_s": 10, "end_s": 25, "text": "t", "tag": "Key insight", "score": 7,
        "download_path": "/api/clips/feed00000001/clip_0.mp4",
        "storage_provider": "local", "storage_key": None,
        "hook_title": "Hook", "virality_score": 7,
        "spec": {"source": {"url": "", "width": 1920, "height": 1080, "fps": 30}},
        "style": {"layout": "fit"},
        "created_at": "2026-09-24T00:00:00Z",
    }


def test_status_falls_back_to_database(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _job_row())
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [_clip_row()])
    r = client.get("/api/status/feed00000001")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["videoMeta"]["title"] == "Ep 1"
    clip = body["clips"][0]
    assert clip["hookTitle"] == "Hook"
    assert clip["spec"]["source"]["url"] == "/api/clips/feed00000001/clip_0.mp4"
    assert clip["style"] == {"layout": "fit"}


def test_status_reports_interrupted_jobs(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _job_row(status="transcribing"))
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [])
    body = client.get("/api/status/feed00000001").json()
    assert body["status"] == "error"
    assert "restart" in body["error"]


def test_status_unknown_job(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: None)
    assert client.get("/api/status/feed00000002").status_code == 404
