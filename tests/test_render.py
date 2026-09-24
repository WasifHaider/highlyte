import io
import json

import pytest

from backend import render
from backend.spec import ClipStyle


class FakeRenderer:
    def __init__(self):
        self.started = []
        self.progress_value = {"overallProgress": 0.4, "done": False, "fatal": False, "errors": [], "outKey": None}
        self.start_error = None
        self.deleted = []

    def start(self, input_props, duration_s):
        if self.start_error:
            raise self.start_error
        self.started.append((input_props, duration_s))
        return f"lambda-{len(self.started)}", "remotionlambda-bucket"

    def progress(self, render_id, bucket):
        return self.progress_value

    def fetch_output(self, bucket, key):
        return io.BytesIO(b"mp4")

    def delete_output(self, bucket, key):
        self.deleted.append((bucket, key))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def setup():
    fake = FakeRenderer()
    uploads = []
    clock = Clock()
    svc = render.RenderService(
        fake, render.RenderStore(),
        build_props=lambda clip_id, style: ({"spec": {"clipId": clip_id}, "style": style}, 12.0),
        upload_output=lambda body, key, name: uploads.append((key, name, body.read())),
        now=clock,
    )
    return svc, fake, uploads, clock


def test_request_starts_render(setup):
    svc, fake, _, _ = setup
    r = svc.request("job1-0", ClipStyle(layout="fit"))
    assert r.status == "rendering"
    assert fake.started[0][1] == 12.0
    assert fake.started[0][0]["style"]["layout"] == "fit"


def test_identical_style_reuses_render(setup):
    svc, fake, _, _ = setup
    a = svc.request("job1-0", ClipStyle(layout="fit"))
    b = svc.request("job1-0", ClipStyle(layout="fit"))
    c = svc.request("job1-0", ClipStyle(layout="fit", captionPreset="pop"))
    assert a.id == b.id
    assert c.id != a.id
    assert len(fake.started) == 2


def test_at_most_two_active(setup):
    svc, fake, _, _ = setup
    renders = [svc.request(f"job1-{i}", ClipStyle(layout="fit")) for i in range(3)]
    assert [r.status for r in renders] == ["rendering", "rendering", "queued"]
    fake.progress_value = {"overallProgress": 1.0, "done": True, "fatal": False, "errors": [], "outKey": "renders/x/out.mp4"}
    svc.refresh(renders[0].id)  # finishing one frees a slot
    assert renders[2].status == "rendering"


def test_done_copies_to_r2_and_deletes_s3(setup):
    svc, fake, uploads, _ = setup
    r = svc.request("job1-0", ClipStyle(layout="fit"))
    assert svc.refresh(r.id).progress == 40.0
    fake.progress_value = {"overallProgress": 1.0, "done": True, "fatal": False, "errors": [], "outKey": "renders/x/out.mp4"}
    r = svc.refresh(r.id)
    assert r.status == "done" and r.progress == 100.0
    assert r.storage_key == f"renders/{r.id}.mp4"
    assert uploads == [(f"renders/{r.id}.mp4", "highlyte-job1-0.mp4", b"mp4")]
    assert fake.deleted == [("remotionlambda-bucket", "renders/x/out.mp4")]
    assert r.to_api()["downloadUrl"] == f"/api/renders/{r.id}/file"


def test_fatal_error_is_reported(setup):
    svc, fake, _, _ = setup
    r = svc.request("job1-0", ClipStyle(layout="fit"))
    fake.progress_value = {"overallProgress": 0.2, "done": False, "fatal": True,
                           "errors": [{"message": "Video could not be decoded"}], "outKey": None}
    r = svc.refresh(r.id)
    assert r.status == "error" and "could not be decoded" in r.error


def test_stuck_render_times_out(setup):
    svc, _, _, clock = setup
    r = svc.request("job1-0", ClipStyle(layout="fit"))
    clock.t += render.STUCK_AFTER_S + 1
    r = svc.refresh(r.id)
    assert r.status == "error" and r.error == "timed out"


def test_throttled_start_stays_queued_then_retries(setup):
    svc, fake, _, clock = setup
    fake.start_error = RuntimeError("TooManyRequestsException: Rate Exceeded")
    r = svc.request("job1-0", ClipStyle(layout="fit"))
    assert r.status == "queued" and r.attempts == 1
    fake.start_error = None
    svc.refresh(r.id)
    assert r.status == "queued"  # still backing off
    clock.t += render.THROTTLE_BACKOFF_S + 1
    assert svc.refresh(r.id).status == "rendering"


def test_other_start_errors_fail(setup):
    svc, fake, _, _ = setup
    fake.start_error = RuntimeError("clip source is not in R2")
    r = svc.request("job1-0", ClipStyle(layout="fit"))
    assert r.status == "error" and "not in R2" in r.error


def test_lambda_config_requires_all_values(monkeypatch):
    assert render.lambda_config() is None
    for key, value in {
        "REMOTION_AWS_ACCESS_KEY_ID": "a", "REMOTION_AWS_SECRET_ACCESS_KEY": "b", "REMOTION_AWS_REGION": "ap-south-1",
        "REMOTION_FUNCTION_NAME": "remotion-render-4-0-527-mem2048mb-disk2048mb-240sec",
        "REMOTION_SERVE_URL": "https://example/sites/highlyte/index.html",
    }.items():
        monkeypatch.setenv(key, value)
    assert render.lambda_config()["region"] == "ap-south-1"


def test_check_versions(tmp_path):
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"dependencies": {"remotion": "4.0.527"}}))
    assert render.check_versions(str(pkg), "remotion-render-4-0-527-mem2048mb-disk2048mb-240sec") == []
    pkg.write_text(json.dumps({"dependencies": {"remotion": "4.0.500"}}))
    problems = render.check_versions(str(pkg), "remotion-render-4-0-400-mem2048mb")
    assert len(problems) == 2
