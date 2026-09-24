import pytest
from fastapi.routing import APIRoute

from backend import accounts, main, render
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


class CountingRenderer:
    """Records every Lambda call so a test can prove another team's request
    never reached it."""

    def __init__(self):
        self.calls = []

    def start(self, input_props, duration_s):
        self.calls.append("start")
        return "lambda-1", "bucket"

    def progress(self, render_id, bucket):
        self.calls.append("progress")
        return {"overallProgress": 1.0, "done": True, "fatal": False, "errors": [], "outKey": "out.mp4"}

    def fetch_output(self, bucket, key):
        self.calls.append("fetch_output")

    def delete_output(self, bucket, key):
        self.calls.append("delete_output")


@pytest.fixture
def other_render(jobs, monkeypatch):
    fake = CountingRenderer()
    svc = render.RenderService(fake, render.RenderStore(), main._build_props, lambda body, key, name: None)
    svc.store.put(render.Render(
        id="rend00000001", clip_id="bbbb00000001-0", style={}, style_hash="h", status="rendering",
        lambda_render_id="lambda-1", lambda_bucket="bucket",
    ))
    monkeypatch.setattr(main, "RENDER_SERVICE", svc)
    monkeypatch.setattr(main.storage, "clip_url", lambda key: f"https://r2.example/{key}")
    return fake


def test_other_team_render_routes_are_404(other_render):
    style = {"layout": "fit", "captionPreset": "pop", "showHook": True, "hookTitle": None,
             "accent": "#FFD400", "captionPosition": "lower"}
    assert client.post("/api/clips/bbbb00000001-0/render", json=style).status_code == 404
    assert client.get("/api/renders/rend00000001").status_code == 404
    assert client.get("/api/renders/rend00000001/file", follow_redirects=False).status_code == 404
    assert client.get("/api/renders/zip?ids=rend00000001").status_code == 404
    # The ownership check runs before refresh(), so another team can't even
    # make us poll Lambda for its render.
    assert other_render.calls == []


def _dependency_calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _dependency_calls(dep)


PUBLIC_API_PATHS = {"/api/health", "/api/auth/login", "/api/auth/signup", "/api/auth/logout"}


def test_every_api_route_requires_login():
    # A new endpoint that forgets Depends(current_member) would be readable
    # by anyone; this makes that a test failure instead of a silent leak.
    checked = 0
    for route in main.app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/") or route.path in PUBLIC_API_PATHS:
            continue
        checked += 1
        assert accounts.current_member in set(_dependency_calls(route.dependant)), route.path
    assert checked > 10
