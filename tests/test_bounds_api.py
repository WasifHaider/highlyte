import copy
import json
import os

import pytest

from backend import main
from tests.support import TEST_TEAM_ID, api_client

client = api_client()
FIXTURE_V2 = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec-v2.json")
FIXTURE_V1 = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec.json")
JOB = "b0und5000001"


def _spec(path=FIXTURE_V2):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def clip(monkeypatch):
    spec = _spec()
    spec["clipId"] = f"{JOB}-0"
    record = {
        "id": f"{JOB}-0", "start": 100.0, "end": 108.0, "startLabel": "1:40", "endLabel": "1:48",
        "durationLabel": "0:08", "text": "t", "tag": "Key insight", "score": 7.0, "hookTitle": None,
        "viralityScore": 7.0, "downloadUrl": f"/api/clips/{JOB}/clip_0.mp4", "storageProvider": "local",
        "storageKey": None, "spec": spec, "style": {"layout": "fit"}, "qaFlags": [], "reason": "",
        "pendingAction": None, "actionError": None, "boundsOriginal": None, "boundsEdited": False, "revision": 0,
    }
    job = main.Job(id=JOB, url="https://youtu.be/x", status="done", team_id=TEST_TEAM_ID, clips=[record])
    main.JOBS[JOB] = job
    writes = []
    monkeypatch.setattr(main.db, "update_clip_checked", lambda cid, fields: writes.append((cid, fields)))
    yield record, writes
    main.JOBS.pop(JOB, None)


def test_bounds_update_saves_original_and_moves_source_time(clip):
    record, writes = clip
    r = client.patch(f"/api/clips/{JOB}-0/bounds", json={"start": 1.5, "end": 10.3})
    assert r.status_code == 200
    assert r.json() == {"start": 1.5, "end": 10.3, "boundsEdited": True}
    assert record["spec"]["start"] == 1.5 and record["spec"]["end"] == 10.3
    assert record["boundsOriginal"] == {"start": 2.0, "end": 10.0}
    assert (record["start"], record["end"]) == (99.5, 108.3)
    fields = writes[-1][1]
    assert fields["bounds_original"] == {"start": 2.0, "end": 10.0}
    assert (fields["start_s"], fields["end_s"]) == (99.5, 108.3)


def test_second_nudge_keeps_first_original(clip):
    record, _ = clip
    client.patch(f"/api/clips/{JOB}-0/bounds", json={"start": 1.5, "end": 10.3})
    client.patch(f"/api/clips/{JOB}-0/bounds", json={"start": 1.0, "end": 10.3})
    assert record["boundsOriginal"] == {"start": 2.0, "end": 10.0}


@pytest.mark.parametrize("body,msg", [
    ({"start": 3.0, "end": 10.0}, "at least 8 s"),
    ({"start": -1.0, "end": 10.0}, "outside the spare video"),
    ({"start": 2.0, "end": 12.5}, "outside the spare video"),
])
def test_bounds_limits(clip, body, msg):
    r = client.patch(f"/api/clips/{JOB}-0/bounds", json=body)
    assert r.status_code == 422 and msg in r.json()["detail"]


def test_v1_clip_cannot_be_trimmed(clip):
    record, _ = clip
    record["spec"] = _spec(FIXTURE_V1)
    r = client.patch(f"/api/clips/{JOB}-0/bounds", json={"start": 1.5, "end": 9.5})
    assert r.status_code == 409 and r.json()["detail"] == "Re-run the video to trim this clip."


def test_busy_clip_cannot_be_trimmed(clip):
    record, _ = clip
    record["pendingAction"] = "swap"
    assert client.patch(f"/api/clips/{JOB}-0/bounds", json={"start": 1.5, "end": 10.3}).status_code == 409


def test_reset_restores_original(clip):
    record, _ = clip
    client.patch(f"/api/clips/{JOB}-0/bounds", json={"start": 1.5, "end": 10.3})
    r = client.post(f"/api/clips/{JOB}-0/bounds/reset")
    assert r.json() == {"start": 2.0, "end": 10.0, "boundsEdited": False}
    assert (record["start"], record["end"]) == (100.0, 108.0)
    assert record["boundsOriginal"] is None


def test_srt_download(clip):
    r = client.get(f"/api/clips/{JOB}-0/captions.srt")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == f'attachment; filename="highlyte-{JOB}-0.srt"'
    assert r.text.startswith("1\n00:00:00,")


def test_caption_save_accepts_times_across_the_window(clip):
    record, _ = clip
    words = record["spec"]["words"]
    r = client.put(f"/api/clips/{JOB}-0/captions", json={"words": words})
    assert r.status_code == 200   # the last word ends at 11.2 s, past the 8 s clip
