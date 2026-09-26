import json
import os

import pytest

from backend import main
from backend.spec import ClipSpec, default_style
from tests.support import TEST_TEAM_ID, api_client

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec.json")
JOB_ID = "cap123def456"
CLIP_ID = f"{JOB_ID}-0"
client = api_client()


@pytest.fixture
def env(monkeypatch):
    with open(FIXTURE, encoding="utf-8") as f:
        spec = ClipSpec.model_validate(json.load(f)).model_copy(update={"clipId": CLIP_ID})
    record = {"id": CLIP_ID, "spec": spec.model_dump(), "style": default_style(spec).model_dump(),
              "downloadUrl": f"/api/clips/{JOB_ID}/clip_0.mp4"}
    main.JOBS[JOB_ID] = main.Job(id=JOB_ID, url="u", status="done", clips=[record], team_id=TEST_TEAM_ID)
    updates = []
    monkeypatch.setattr(main.db, "update_clip", lambda clip_id, fields: updates.append((clip_id, fields)))
    yield record, updates
    main.JOBS.pop(JOB_ID, None)


def _edited(record):
    words = [dict(w) for w in record["spec"]["words"]]
    words[0]["text"] = "Honestly,"
    return words


def test_save_captions_stores_words_and_original_once(env):
    record, updates = env
    original = [dict(w) for w in record["spec"]["words"]]
    r = client.put(f"/api/clips/{CLIP_ID}/captions", json={"words": _edited(record)})
    assert r.status_code == 200 and r.json()["captionsEdited"] is True
    assert r.json()["words"][0]["text"] == "Honestly,"
    assert record["spec"]["words"][0]["text"] == "Honestly,"
    assert updates[-1][1]["words_original"] == original
    second = _edited(record)
    second[1]["text"] = "changed"
    client.put(f"/api/clips/{CLIP_ID}/captions", json={"words": second})
    assert updates[-1][1]["words_original"] == original  # first original kept


def test_reset_restores_original(env):
    record, updates = env
    original = [dict(w) for w in record["spec"]["words"]]
    client.put(f"/api/clips/{CLIP_ID}/captions", json={"words": _edited(record)})
    r = client.post(f"/api/clips/{CLIP_ID}/captions/reset")
    assert r.json() == {"words": original, "captionsEdited": False}
    assert record["spec"]["words"] == original
    assert updates[-1][1] == {"spec": record["spec"], "words_original": None}


def test_save_captions_validates(env):
    record, _ = env
    bad = _edited(record)
    bad[0]["text"] = ""
    r = client.put(f"/api/clips/{CLIP_ID}/captions", json={"words": bad})
    assert r.status_code == 422 and "empty" in r.json()["detail"]


def test_captions_need_a_spec(env):
    record, _ = env
    record["spec"] = None
    assert client.put(f"/api/clips/{CLIP_ID}/captions", json={"words": []}).status_code == 409


def test_captions_are_team_scoped(env, monkeypatch):
    main.JOBS[JOB_ID].team_id = "00000000-0000-0000-0000-0000000other"
    assert client.put(f"/api/clips/{CLIP_ID}/captions", json={"words": []}).status_code == 404


def test_clip_row_reports_captions_edited():
    row = {"id": "a-0", "job_id": "a", "start_s": 1, "end_s": 2, "words_original": [{"text": "x", "start": 0, "end": 1}]}
    assert main._clip_row_to_api(row)["captionsEdited"] is True
    assert main._clip_row_to_api({**row, "words_original": None})["captionsEdited"] is False
