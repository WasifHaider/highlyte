import io
import json
import os
import zipfile

import pytest

from backend import main, render
from backend.spec import ClipSpec, default_style
from tests.support import TEST_TEAM_ID, api_client

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec.json")
JOB_ID = "abc123def456"
CLIP_ID = f"{JOB_ID}-0"

client = api_client()


class FakeRenderer:
    def __init__(self):
        self.done = False
        self.props = None

    def start(self, input_props, duration_s):
        self.props = input_props
        return "lambda-1", "bucket"

    def progress(self, render_id, bucket):
        return {"overallProgress": 1.0 if self.done else 0.5, "done": self.done, "fatal": False,
                "errors": [], "outKey": "out.mp4"}

    def fetch_output(self, bucket, key):
        return io.BytesIO(b"mp4")

    def delete_output(self, bucket, key):
        pass


@pytest.fixture
def env(monkeypatch):
    with open(FIXTURE, encoding="utf-8") as f:
        spec = ClipSpec.model_validate(json.load(f)).model_copy(update={"clipId": CLIP_ID})
    record = {
        "id": CLIP_ID, "start": 10.0, "end": 18.0, "text": "t", "tag": "Key insight", "score": 8.2,
        "hookTitle": spec.hookTitle, "viralityScore": spec.viralityScore,
        "downloadUrl": f"/api/clips/{JOB_ID}/clip_0.mp4", "storageProvider": "r2",
        "storageKey": f"{JOB_ID}/clip_0.mp4",
        "spec": spec.model_dump(), "style": default_style(spec).model_dump(),
    }
    main.JOBS[JOB_ID] = main.Job(id=JOB_ID, url="u", status="done", clips=[record], team_id=TEST_TEAM_ID)
    fake = FakeRenderer()
    uploads = {}
    svc = render.RenderService(fake, render.RenderStore(), main._build_props,
                               lambda body, key, name: uploads.__setitem__(key, body.read()))
    monkeypatch.setattr(main, "RENDER_SERVICE", svc)
    monkeypatch.setattr(main.storage, "clip_url", lambda key: f"https://r2.example/{key}")
    monkeypatch.setattr(main.storage, "open_object", lambda key: io.BytesIO(uploads[key]))
    yield record, fake
    main.JOBS.pop(JOB_ID, None)


STYLE = {"layout": "follow", "captionPreset": "pop", "showHook": True, "hookTitle": "Edited",
         "accent": "#00FFAA", "captionPosition": "lower"}


def test_health_reports_rendering(env):
    assert client.get("/api/health").json()["rendering"] is True


def test_patch_style_saves(env):
    record, _ = env
    r = client.patch(f"/api/clips/{CLIP_ID}/style", json=STYLE)
    assert r.status_code == 200
    assert record["style"]["captionPreset"] == "pop"


def test_patch_style_validates(env):
    assert client.patch(f"/api/clips/{CLIP_ID}/style", json={**STYLE, "accent": "red"}).status_code == 422


def test_render_flow(env):
    _, fake = env
    r = client.post(f"/api/clips/{CLIP_ID}/render", json=STYLE)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rendering"
    assert fake.props["spec"]["source"]["url"] == f"https://r2.example/{JOB_ID}/clip_0.mp4"
    assert fake.props["style"]["hookTitle"] == "Edited"

    fake.done = True
    body = client.get(f"/api/renders/{body['id']}").json()
    assert body["status"] == "done"

    f = client.get(body["downloadUrl"], follow_redirects=False)
    assert f.status_code == 307
    assert f.headers["location"] == f"https://r2.example/renders/{body['id']}.mp4"

    z = client.get(f"/api/renders/zip?ids={body['id']}")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert names == [f"highlyte-{CLIP_ID}.mp4"]


def test_render_requires_r2_source(env):
    record, _ = env
    record["storageKey"] = None
    assert client.post(f"/api/clips/{CLIP_ID}/render", json=STYLE).status_code == 409


def test_render_unknown_clip(env):
    assert client.post("/api/clips/abc123def456-9/render", json=STYLE).status_code == 404


def test_render_not_configured(env, monkeypatch):
    monkeypatch.setattr(main, "RENDER_SERVICE", None)
    assert client.post(f"/api/clips/{CLIP_ID}/render", json=STYLE).status_code == 503


def test_zip_rejects_unfinished_and_bad_ids(env):
    assert client.get("/api/renders/zip?ids=../x").status_code == 400
    assert client.get("/api/renders/zip?ids=nope00000000").status_code == 404
