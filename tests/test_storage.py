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


def test_upload_thumb_sets_image_headers(fake_r2):
    storage.upload_thumb("t.jpg", "job/clip_0.jpg")
    fake_r2.upload_file.assert_called_once_with(
        "t.jpg", "bucket", "job/clip_0.jpg",
        ExtraArgs={"ContentType": "image/jpeg", "CacheControl": storage.MEDIA_CACHE_CONTROL},
    )


def test_upload_clip_lets_browsers_cache_it(fake_r2):
    storage.upload_clip("c.mp4", "job/clip_0.mp4")
    assert fake_r2.upload_file.call_args.kwargs["ExtraArgs"]["CacheControl"] == storage.MEDIA_CACHE_CONTROL


def test_thumb_filename():
    assert storage.thumb_filename("clip_2.mp4") == "clip_2.jpg"
    assert storage.thumb_filename("clip_2_r3.mp4") == "clip_2_r3.jpg"


def test_clip_url_reuses_a_presigned_url_until_near_expiry(fake_r2, monkeypatch):
    # A fresh signature per request makes every URL look like a new file to
    # the browser, so nothing it already downloaded is reused.
    monkeypatch.setattr(storage, "R2_PUBLIC_BASE_URL", None)
    storage._presigned.clear()
    now = [1000.0]
    monkeypatch.setattr(storage.time, "time", lambda: now[0])
    fake_r2.generate_presigned_url.side_effect = lambda *a, **k: f"url-{now[0]}"

    first = storage.clip_url("job/clip_0.mp4")
    now[0] += storage.PRESIGNED_URL_TTL_S - storage.PRESIGNED_URL_MIN_LEFT_S - 1
    assert storage.clip_url("job/clip_0.mp4") == first
    now[0] += 2
    assert storage.clip_url("job/clip_0.mp4") != first
