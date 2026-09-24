import pytest
from fastapi import HTTPException

from backend.main import app
from backend.validation import check_clip_filename, check_id
from tests.support import TEST_TEAM_ID, api_client

client = api_client()


@pytest.mark.parametrize("value", ["abc123", "a1b2c3d4e5f6-0", "renders-1"])
def test_check_id_accepts(value):
    assert check_id(value) == value


@pytest.mark.parametrize("value", ["..", "../etc", "ABC", "a/b", "a\\b", "", "x" * 65])
def test_check_id_rejects(value):
    with pytest.raises(HTTPException) as exc:
        check_id(value)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("value", ["clip_0.mp4", "clip_12.mp4"])
def test_check_clip_filename_accepts(value):
    assert check_clip_filename(value) == value


@pytest.mark.parametrize("value", ["secret.txt", "clip_0.mp4.exe", "../clip_0.mp4", "clip_a.mp4"])
def test_check_clip_filename_rejects(value):
    with pytest.raises(HTTPException):
        check_clip_filename(value)


def test_get_clip_rejects_traversal_job_id():
    assert client.get("/api/clips/..%2e/clip_0.mp4").status_code == 400


def test_get_clip_rejects_bad_filename():
    assert client.get("/api/clips/abc123/secret.txt").status_code == 400


def test_generate_rejects_unknown_whisper_model():
    r = client.post("/api/generate", json={"url": "https://youtu.be/x", "whisper_model": "large-v3"})
    assert r.status_code == 422
