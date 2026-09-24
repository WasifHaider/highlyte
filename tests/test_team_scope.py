import pytest

from backend import main
from tests.support import TEST_TEAM_ID, api_client

client = api_client()
OTHER = "team-other"


@pytest.fixture
def jobs():
    main.JOBS["aaaa00000001"] = main.Job(id="aaaa00000001", url="u", status="done", team_id=TEST_TEAM_ID)
    main.JOBS["bbbb00000001"] = main.Job(id="bbbb00000001", url="u", status="done", team_id=OTHER)
    yield
    main.JOBS.pop("aaaa00000001", None)
    main.JOBS.pop("bbbb00000001", None)


def test_project_list_only_shows_own_team(jobs, monkeypatch):
    seen = {}
    monkeypatch.setattr(main.db, "list_jobs", lambda team_id, limit=20: seen.setdefault("team", team_id) and [])
    monkeypatch.setattr(main.db, "count_clips_by_job", lambda ids: {})
    ids = [p["id"] for p in client.get("/api/jobs").json()]
    assert "aaaa00000001" in ids and "bbbb00000001" not in ids
    assert seen["team"] == TEST_TEAM_ID


def test_other_team_status_is_404(jobs):
    assert client.get("/api/status/aaaa00000001").status_code == 200
    assert client.get("/api/status/bbbb00000001").status_code == 404


def test_other_team_db_row_is_404(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: {"id": job_id, "status": "done", "team_id": OTHER})
    assert client.get("/api/status/cccc00000001").status_code == 404


def test_unowned_db_row_is_404(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: {"id": job_id, "status": "done", "team_id": None})
    assert client.get("/api/status/cccc00000002").status_code == 404


def test_other_team_clip_file_and_style_are_404(jobs):
    assert client.get("/api/clips/bbbb00000001/clip_0.mp4").status_code == 404
    style = {"layout": "fit", "captionPreset": "pop", "showHook": True, "hookTitle": None,
             "accent": "#FFD400", "captionPosition": "lower"}
    assert client.patch("/api/clips/bbbb00000001-0/style", json=style).status_code == 404


def test_generate_records_team_and_creator(monkeypatch):
    started = {}

    class NoThread:
        def __init__(self, target, args, daemon):
            started["job"] = args[0]

        def start(self):
            pass

    monkeypatch.setattr(main.threading, "Thread", NoThread)
    r = client.post("/api/generate", json={"url": "https://youtu.be/qt6YoGmksCc"})
    job = started["job"]
    try:
        assert r.status_code == 200
        assert job.team_id == TEST_TEAM_ID
        assert job.created_by == "00000000-0000-0000-0000-00000000test"
    finally:
        main.JOBS.pop(job.id, None)


def test_clip_list_is_team_filtered(monkeypatch):
    seen = {}
    monkeypatch.setattr(main.db, "list_clips", lambda team_id, limit=100: seen.setdefault("team", team_id) and [])
    assert client.get("/api/clips").status_code == 200
    assert seen["team"] == TEST_TEAM_ID
