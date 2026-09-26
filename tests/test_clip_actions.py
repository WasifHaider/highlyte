import json
import os

import pytest

from backend import main
from backend.pipeline import clipprep, selection
from backend.pipeline.ingest import VideoMeta
from backend.spec import ClipSpec
from tests.support import TEST_TEAM_ID, api_client

client = api_client()
JOB = "ac7100000001"
FIXTURE_V2 = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec-v2.json")


def _record(idx, start, end):
    with open(FIXTURE_V2, encoding="utf-8") as f:
        spec = json.load(f)
    spec["clipId"] = f"{JOB}-{idx}"
    return {
        "id": f"{JOB}-{idx}", "start": start, "end": end, "text": "old", "tag": "Key insight", "score": 5.0,
        "hookTitle": None, "viralityScore": 5.0, "downloadUrl": f"/api/clips/{JOB}/clip_{idx}.mp4",
        "storageProvider": "local", "storageKey": None, "spec": spec,
        "style": {"layout": "fit", "captionPreset": "pop", "accent": "#123456", "captionPosition": "middle",
                  "showHook": False, "hookTitle": None},
        "qaFlags": [], "reason": "", "pendingAction": None, "actionError": None,
        "boundsOriginal": None, "boundsEdited": False, "revision": 0,
    }


@pytest.fixture
def env(monkeypatch):
    job = main.Job(id=JOB, url="https://youtu.be/x", status="done", team_id=TEST_TEAM_ID,
                   clips=[_record(0, 100.0, 120.0), _record(1, 300.0, 320.0)])
    job.alternates = [
        {"start": 305.0, "end": 325.0, "text": "clash", "score": 9.0, "tag": "Wild claim", "flags": [], "reason": "r1", "emphasis": []},
        {"start": 500.0, "end": 520.0, "text": "fresh", "score": 8.0, "tag": "Key insight", "flags": [], "reason": "r2", "emphasis": ["fresh"]},
    ]
    main.JOBS[JOB] = job
    writes, updates = [], []
    monkeypatch.setattr(main, "_start_thread", lambda target, *args: target(*args))
    monkeypatch.setattr(main.db, "get_transcript", lambda job_id: {"segments": [], "loudness": []})
    monkeypatch.setattr(main.db, "update_clip", lambda cid, f: updates.append((cid, f)))
    monkeypatch.setattr(main.db, "update_clip_checked", lambda cid, f: writes.append((cid, f)))
    monkeypatch.setattr(main.db, "upsert_job", lambda row: None)
    monkeypatch.setattr(main.ingest, "ingest", lambda url, cache_dir, on_progress=None: VideoMeta(
        video_id="x", title="t", channel="c", duration=900.0, audio_path="a", video_path="v", thumbnail_url=None))

    def fake_prepare(**kw):
        with open(FIXTURE_V2, encoding="utf-8") as f:
            spec = json.load(f)
        spec["clipId"] = f"{JOB}-{kw['idx']}"
        return clipprep.PreparedClip(spec=ClipSpec.model_validate(spec), storage_key=None, face_at_start=True)

    monkeypatch.setattr(main.clipprep, "prepare_clip", fake_prepare)
    yield job, writes, updates
    main.JOBS.pop(JOB, None)


def test_pick_alternate_skips_clashes():
    alts = [{"start": 305.0, "end": 325.0}, {"start": 500.0, "end": 520.0}]
    assert main.pick_alternate(alts, (100.0, 120.0), [(300.0, 320.0)]) == 1
    assert main.pick_alternate(alts[:1], (100.0, 120.0), [(300.0, 320.0)]) is None


def test_swap_replaces_clip_and_uses_up_the_alternate(env):
    job, writes, _ = env
    r = client.post(f"/api/clips/{JOB}-0/swap")
    assert r.status_code == 200 and r.json() == {"clipId": f"{JOB}-0", "pendingAction": "swap"}
    new = job.clips[0]
    assert (new["start"], new["end"], new["reason"]) == (500.0, 520.0, "r2")
    assert new["revision"] == 1 and new["pendingAction"] is None
    assert new["style"]["captionPreset"] == "pop" and new["style"]["accent"] == "#123456"
    assert [a["reason"] for a in job.alternates] == ["r1"]
    fields = writes[-1][1]
    assert fields["words_original"] is None and fields["bounds_original"] is None and fields["pending_action"] is None


def test_swap_with_nothing_left_is_409(env):
    job, _, _ = env
    job.alternates = job.alternates[:1]
    r = client.post(f"/api/clips/{JOB}-0/swap")
    assert r.status_code == 409 and r.json()["detail"] == "No other moments left to swap in."


def test_regenerate_replaces_clip(env, monkeypatch):
    job, _, _ = env
    monkeypatch.setattr(main.groq_llm, "build_chat", lambda: object())
    seen = {}

    def fake_regenerate(segs, loudness, current, avoid):
        seen["current"], seen["avoid"] = current, avoid
        return selection.Clip(start=130.0, end=150.0, text="new", score=8.0, tag="Key insight", reason="better")

    monkeypatch.setattr(main.selection, "regenerate", fake_regenerate)
    assert client.post(f"/api/clips/{JOB}-0/regenerate").status_code == 200
    assert seen == {"current": (100.0, 120.0), "avoid": [(300.0, 320.0)]}
    assert job.clips[0]["reason"] == "better"


def test_regenerate_failure_keeps_old_clip(env, monkeypatch):
    job, _, updates = env
    monkeypatch.setattr(main.groq_llm, "build_chat", lambda: object())
    monkeypatch.setattr(main.selection, "regenerate", lambda *a, **k: None)
    client.post(f"/api/clips/{JOB}-0/regenerate")
    rec = job.clips[0]
    assert rec["text"] == "old" and rec["pendingAction"] is None
    assert rec["actionError"] == "No better take found around this moment."
    assert updates[-1] == (f"{JOB}-0", {"pending_action": None, "action_error": "No better take found around this moment."})


def test_regenerate_needs_key(env, monkeypatch):
    monkeypatch.setattr(main.groq_llm, "build_chat", lambda: None)
    r = client.post(f"/api/clips/{JOB}-0/regenerate")
    assert r.status_code == 409 and r.json()["detail"] == "Regenerate needs GROQ_KEY."


def test_busy_clip_rejects_a_second_action(env, monkeypatch):
    job, _, _ = env
    job.clips[0]["pendingAction"] = "swap"
    assert client.post(f"/api/clips/{JOB}-0/swap").status_code == 409


def test_download_failure_is_reported(env, monkeypatch):
    job, _, _ = env

    def boom(*a, **k):
        raise RuntimeError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(main.ingest, "ingest", boom)
    client.post(f"/api/clips/{JOB}-0/swap")
    assert job.clips[0]["actionError"] == "Couldn't fetch the video again: Sign in to confirm you're not a bot."
