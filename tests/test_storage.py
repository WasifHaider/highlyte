import io
from unittest.mock import MagicMock

import pytest

from backend import storage


@pytest.fixture
def fake_r2(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(storage, "get_client", lambda: client)
    monkeypatch.setattr(storage, "R2_BUCKET", "bucket")
    return client


def test_render_key():
    assert storage.render_key("abc") == "renders/abc.mp4"


def test_upload_fileobj_sets_attachment_headers(fake_r2):
    body = io.BytesIO(b"data")
    storage.upload_fileobj(body, "renders/abc.mp4", "highlyte-clip.mp4")
    fake_r2.upload_fileobj.assert_called_once_with(
        body, "bucket", "renders/abc.mp4",
        ExtraArgs={"ContentType": "video/mp4", "ContentDisposition": 'attachment; filename="highlyte-clip.mp4"'},
    )


def test_open_object_returns_body(fake_r2):
    fake_r2.get_object.return_value = {"Body": "stream"}
    assert storage.open_object("renders/abc.mp4") == "stream"
    fake_r2.get_object.assert_called_once_with(Bucket="bucket", Key="renders/abc.mp4")


def test_open_object_requires_r2(monkeypatch):
    monkeypatch.setattr(storage, "get_client", lambda: None)
    with pytest.raises(RuntimeError):
        storage.open_object("renders/abc.mp4")
