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


def test_other_clip_busy_rejects_action(env):
    job, _, _ = env
    job.clips[1]["pendingAction"] = "regenerate"
    r = client.post(f"/api/clips/{JOB}-0/swap")
    assert r.status_code == 409
    assert r.json()["detail"] == "Another clip is being replaced. Wait for it to finish."


def test_start_clip_action_rolls_back_pending_flag_on_db_failure(env, monkeypatch):
    job, _, _ = env

    def boom(cid, fields):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(main.db, "update_clip", boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/clips/{JOB}-0/swap")
    assert job.clips[0]["pendingAction"] is None


def _clip_row_for_rebuild(idx, start, end, pending_action=None):
    with open(FIXTURE_V2, encoding="utf-8") as f:
        spec = json.load(f)
    spec["clipId"] = f"{JOB}-{idx}"
    return {
        "id": f"{JOB}-{idx}", "job_id": JOB, "idx": idx, "start_s": start, "end_s": end,
        "text": "old", "tag": "Key insight", "score": 5.0,
        "download_path": f"/api/clips/{JOB}/clip_{idx}.mp4",
        "storage_provider": "local", "storage_key": None, "hook_title": None, "virality_score": 5.0,
        "spec": spec,
        "style": {"layout": "fit", "captionPreset": "pop", "accent": "#123456", "captionPosition": "middle",
                  "showHook": False, "hookTitle": None},
        "qa_flags": [], "reason": "", "pending_action": pending_action, "action_error": None,
        "bounds_original": None, "revision": 0,
    }


def test_swap_recovers_a_job_rebuilt_with_an_orphaned_pending_action(monkeypatch):
    main.JOBS.pop(JOB, None)
    updates = []
    monkeypatch.setattr(main, "_start_thread", lambda target, *args: target(*args))
    monkeypatch.setattr(main.db, "get_transcript", lambda job_id: {"segments": [], "loudness": []})
    monkeypatch.setattr(main.db, "update_clip", lambda cid, f: updates.append((cid, f)))
    monkeypatch.setattr(main.db, "update_clip_checked", lambda cid, f: None)
    monkeypatch.setattr(main.db, "upsert_job", lambda row: None)
    monkeypatch.setattr(main.ingest, "ingest", lambda url, cache_dir, on_progress=None: VideoMeta(
        video_id="x", title="t", channel="c", duration=900.0, audio_path="a", video_path="v", thumbnail_url=None))

    def fake_prepare(**kw):
        with open(FIXTURE_V2, encoding="utf-8") as f:
            spec = json.load(f)
        spec["clipId"] = f"{JOB}-{kw['idx']}"
        return clipprep.PreparedClip(spec=ClipSpec.model_validate(spec), storage_key=None, face_at_start=True)

    monkeypatch.setattr(main.clipprep, "prepare_clip", fake_prepare)
    monkeypatch.setattr(main.db, "get_job", lambda job_id: {
        "id": JOB, "url": "https://youtu.be/x", "status": "done", "team_id": TEST_TEAM_ID,
        "alternates": [{"start": 500.0, "end": 520.0, "text": "fresh", "score": 8.0, "tag": "Key insight",
                        "flags": [], "reason": "r2", "emphasis": []}],
    })
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [
        _clip_row_for_rebuild(0, 100.0, 120.0, pending_action="swap"),
        _clip_row_for_rebuild(1, 300.0, 320.0),
    ])

    r = client.post(f"/api/clips/{JOB}-0/swap")
    assert r.status_code == 200 and r.json() == {"clipId": f"{JOB}-0", "pendingAction": "swap"}
    # The orphaned pending_action was cleared (and reported) before the new
    # action's own pending_action write, so the rebuild's clearing write
    # comes before the final "swap done" write in the recorded updates.
    assert (f"{JOB}-0", {"pending_action": None, "action_error": "Interrupted by a server restart. Try again."}) in updates
    main.JOBS.pop(JOB, None)


def _media_env(monkeypatch, tmp_path, job):
    """Old clip 0 lives at clip_0.mp4 (local file and R2 key); the fake
    prepare_clip writes its replacement where the real one would."""
    monkeypatch.setattr(main, "CLIPS_DIR", str(tmp_path))
    job_dir = tmp_path / JOB
    job_dir.mkdir()
    (job_dir / "clip_0.mp4").write_bytes(b"old")
    rec = job.clips[0]
    rec["storageProvider"], rec["storageKey"] = "r2", f"{JOB}/clip_0.mp4"
    seen, deleted = {}, []

    def fake_prepare(**kw):
        seen.update(kw)
        name = clipprep.clip_filename(kw["idx"], kw["revision"])
        (job_dir / name).write_bytes(b"new")
        with open(FIXTURE_V2, encoding="utf-8") as f:
            spec = json.load(f)
        spec["clipId"] = f"{JOB}-{kw['idx']}"
        return clipprep.PreparedClip(spec=ClipSpec.model_validate(spec), storage_key=f"{JOB}/{name}",
                                     face_at_start=True, filename=name)

    monkeypatch.setattr(main.clipprep, "prepare_clip", fake_prepare)
    monkeypatch.setattr(main.storage, "delete_clip", lambda key: deleted.append(key))
    return job_dir, seen, deleted


def test_swap_writes_a_new_revision_and_drops_the_old_media(env, monkeypatch, tmp_path):
    job, writes, _ = env
    job_dir, seen, deleted = _media_env(monkeypatch, tmp_path, job)
    assert client.post(f"/api/clips/{JOB}-0/swap").status_code == 200
    assert seen["revision"] == 1
    new = job.clips[0]
    assert new["downloadUrl"] == f"/api/clips/{JOB}/clip_0_r1.mp4"
    assert new["storageKey"] == f"{JOB}/clip_0_r1.mp4" and new["revision"] == 1
    fields = writes[-1][1]
    assert fields["download_path"] == new["downloadUrl"] and fields["storage_key"] == new["storageKey"]
    assert fields["revision"] == 1
    assert (job_dir / "clip_0_r1.mp4").exists()
    assert not (job_dir / "clip_0.mp4").exists()
    assert deleted == [f"{JOB}/clip_0.mp4"]
    # The new name is served by the clip route.
    r = client.get(f"/api/clips/{JOB}/clip_0_r1.mp4")
    assert r.status_code == 200 and r.content == b"new"


def test_second_swap_replaces_revision_one_with_revision_two(env, monkeypatch, tmp_path):
    job, _, _ = env
    job_dir, seen, deleted = _media_env(monkeypatch, tmp_path, job)
    job.alternates.append({"start": 700.0, "end": 720.0, "text": "more", "score": 7.0, "tag": "Key insight",
                           "flags": [], "reason": "r3", "emphasis": []})
    assert client.post(f"/api/clips/{JOB}-0/swap").status_code == 200
    assert client.post(f"/api/clips/{JOB}-0/swap").status_code == 200
    assert seen["revision"] == 2
    assert job.clips[0]["downloadUrl"] == f"/api/clips/{JOB}/clip_0_r2.mp4"
    assert sorted(p.name for p in job_dir.iterdir()) == ["clip_0_r2.mp4"]
    assert deleted == [f"{JOB}/clip_0.mp4", f"{JOB}/clip_0_r1.mp4"]


def test_failure_after_prepare_keeps_the_old_media(env, monkeypatch, tmp_path):
    job, _, _ = env
    job_dir, _, deleted = _media_env(monkeypatch, tmp_path, job)

    def boom(cid, fields):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(main.db, "update_clip_checked", boom)
    client.post(f"/api/clips/{JOB}-0/swap")
    rec = job.clips[0]
    assert rec["revision"] == 0 and rec["text"] == "old" and rec["pendingAction"] is None
    assert rec["downloadUrl"] == f"/api/clips/{JOB}/clip_0.mp4"
    assert rec["storageKey"] == f"{JOB}/clip_0.mp4"
    assert rec["actionError"] == "Couldn't swap this clip: supabase down"
    assert (job_dir / "clip_0.mp4").read_bytes() == b"old"
    # The half-made replacement is cleaned up; the old object is not touched.
    assert not (job_dir / "clip_0_r1.mp4").exists()
    assert deleted == [f"{JOB}/clip_0_r1.mp4"]
    assert [a["reason"] for a in job.alternates] == ["r1", "r2"]


def test_old_media_delete_failure_does_not_fail_the_action(env, monkeypatch, tmp_path):
    job, _, _ = env
    _media_env(monkeypatch, tmp_path, job)

    def boom(key):
        raise RuntimeError("r2 down")

    monkeypatch.setattr(main.storage, "delete_clip", boom)
    assert client.post(f"/api/clips/{JOB}-0/swap").status_code == 200
    assert job.clips[0]["revision"] == 1 and job.clips[0]["actionError"] is None


def test_action_on_an_unfinished_rebuilt_job_does_not_install_it(monkeypatch):
    main.JOBS.pop(JOB, None)
    monkeypatch.setattr(main.db, "get_job", lambda job_id: {
        "id": JOB, "url": "https://youtu.be/x", "status": "transcribing", "team_id": TEST_TEAM_ID,
    })
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [])
    r = client.post(f"/api/clips/{JOB}-0/swap")
    assert r.status_code == 409 and r.json()["detail"] == "Clips can be changed once the video is done."
    assert JOB not in main.JOBS
    # The status fallback still reports it as interrupted.
    assert client.get(f"/api/status/{JOB}").json()["status"] == "error"
