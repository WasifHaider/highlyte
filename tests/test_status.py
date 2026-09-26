from backend import main
from tests.support import TEST_TEAM_ID, api_client

client = api_client()


def _job_row(status="done"):
    return {
        "id": "feed00000001", "url": "https://youtu.be/x", "status": status, "error": None,
        "video_title": "Ep 1", "video_channel": "Pod", "video_duration": 120,
        "transcript_source": "groq", "team_id": TEST_TEAM_ID,
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


def test_list_all_clips_normalizes_source_url(monkeypatch):
    row = dict(_clip_row())
    row["jobs"] = {"url": "u", "video_title": "Ep 1", "video_channel": "Pod"}
    monkeypatch.setattr(main.db, "list_clips", lambda team_id, limit=100: [row])
    body = client.get("/api/clips").json()
    clip = body[0]
    assert clip["spec"]["source"]["url"] == "/api/clips/feed00000001/clip_0.mp4"
    assert clip["videoTitle"] == "Ep 1"


def _failed_row(**extra):
    return {**_job_row(status="selection_failed"),
            "error": "Clip selection hit Groq's daily limit. Try again later.", **extra}


def test_status_keeps_selection_failed_and_note(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _failed_row(selection_note="n"))
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [])
    body = client.get("/api/status/feed00000001").json()
    assert body["status"] == "selection_failed"
    assert body["error"].startswith("Clip selection hit")
    assert body["selectionNote"] == "n"


def test_status_clip_has_qa_flags(monkeypatch):
    row = {**_clip_row(), "qa_flags": ["low_confidence"]}
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _job_row())
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [row, _clip_row()])
    clips = client.get("/api/status/feed00000001").json()["clips"]
    assert clips[0]["qaFlags"] == ["low_confidence"] and clips[1]["qaFlags"] == []


def _start_inline(monkeypatch):
    ran = []
    monkeypatch.setattr(main, "_start_thread", lambda target, *args: ran.append((target, args)))
    return ran


def test_retry_selection_restarts_selection(monkeypatch):
    main.JOBS.pop("feed00000001", None)
    ran = _start_inline(monkeypatch)
    stored = {"segments": [{"id": "seg_0001"}], "loudness": [-20.0]}
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _failed_row())
    monkeypatch.setattr(main.db, "get_transcript", lambda job_id: stored)
    monkeypatch.setattr(main.db, "upsert_job", lambda row: None)
    r = client.post("/api/jobs/feed00000001/select")
    assert r.status_code == 200 and r.json() == {"job_id": "feed00000001"}
    job = main.JOBS.pop("feed00000001")
    assert job.status == "analyzing" and job.error is None
    assert ran == [(main._run_selection_retry, (job, stored))]


def test_retry_selection_second_call_conflicts_while_first_is_in_flight(monkeypatch):
    main.JOBS.pop("feed00000001", None)
    _start_inline(monkeypatch)  # the first call's thread never actually runs
    stored = {"segments": [{"id": "seg_0001"}], "loudness": [-20.0]}
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _failed_row())
    monkeypatch.setattr(main.db, "get_transcript", lambda job_id: stored)
    monkeypatch.setattr(main.db, "upsert_job", lambda row: None)
    first = client.post("/api/jobs/feed00000001/select")
    assert first.status_code == 200
    second = client.post("/api/jobs/feed00000001/select")
    assert second.status_code == 409
    main.JOBS.pop("feed00000001", None)


def test_retry_selection_only_after_it_failed(monkeypatch):
    main.JOBS.pop("feed00000001", None)
    _start_inline(monkeypatch)
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _job_row(status="done"))
    assert client.post("/api/jobs/feed00000001/select").status_code == 409


def test_retry_selection_needs_a_stored_transcript(monkeypatch):
    main.JOBS.pop("feed00000001", None)
    _start_inline(monkeypatch)
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _failed_row())
    monkeypatch.setattr(main.db, "get_transcript", lambda job_id: None)
    assert client.post("/api/jobs/feed00000001/select").status_code == 409


def test_retry_selection_other_team_is_not_found(monkeypatch):
    main.JOBS.pop("feed00000001", None)
    _start_inline(monkeypatch)
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _failed_row(team_id="someone-else"))
    assert client.post("/api/jobs/feed00000001/select").status_code == 404


def test_status_reports_alternates_left_in_memory():
    main.JOBS.pop("feed00000001", None)
    job = main.Job(id="feed00000001", url="https://youtu.be/x", status="done", team_id=TEST_TEAM_ID)
    job.alternates = [{"start": 1.0, "end": 2.0}]
    main.JOBS["feed00000001"] = job
    body = client.get("/api/status/feed00000001").json()
    main.JOBS.pop("feed00000001", None)
    assert body["alternatesLeft"] == 1


def test_status_db_fallback_reports_alternates_left(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: {**_job_row(), "alternates": [{"start": 1.0, "end": 2.0}]})
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [])
    body = client.get("/api/status/feed00000001").json()
    assert body["alternatesLeft"] == 1


def test_status_db_fallback_reports_orphaned_pending_action_as_interrupted(monkeypatch):
    row = {**_clip_row(), "pending_action": "swap", "action_error": None}
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _job_row())
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [row])
    body = client.get("/api/status/feed00000001").json()
    clip = body["clips"][0]
    assert clip["pendingAction"] is None
    assert clip["actionError"] == "Interrupted by a server restart. Try again."
