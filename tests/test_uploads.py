import os
import shutil
import subprocess

import pytest

from backend import storage
from backend.pipeline import ingest, uploads

UID = "abcdef012345"


class FakeR2:
    """In-memory stand-in for the boto3 S3 client pointed at R2."""

    def __init__(self):
        self.objects: dict[str, dict] = {}  # key -> {"data": bytes, "meta": dict}
        self.multipart: dict[str, dict] = {}  # upload id -> {"key", "meta", "parts"}
        self.downloads: list[str] = []
        self.aborted: list[str] = []
        self._n = 0

    def create_multipart_upload(self, Bucket, Key, ContentType=None, Metadata=None):
        self._n += 1
        uid = f"mp{self._n}"
        self.multipart[uid] = {"key": Key, "meta": Metadata or {}, "parts": {}}
        return {"UploadId": uid}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://r2.test/{op}/{Params['Key']}?part={Params.get('PartNumber')}&exp={ExpiresIn}"

    def put_part(self, uid, n, data):
        self.multipart[uid]["parts"][n] = data
        return f'"etag{n}"'

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload):
        mp = self.multipart.pop(UploadId)
        numbers = [p["PartNumber"] for p in MultipartUpload["Parts"]]
        assert numbers == sorted(numbers)
        data = b"".join(mp["parts"][n] for n in numbers)
        self.objects[Key] = {"data": data, "meta": mp["meta"]}

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self.aborted.append(UploadId)
        self.multipart.pop(UploadId, None)

    def list_objects_v2(self, Bucket, Prefix):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys]} if keys else {}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Metadata": self.objects[Key]["meta"]}

    def download_file(self, Bucket, Key, Filename):
        self.downloads.append(Key)
        with open(Filename, "wb") as f:
            f.write(self.objects[Key]["data"])

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
        with open(Filename, "rb") as f:
            self.objects[Key] = {"data": f.read(), "meta": {}}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(self.objects[Key]["data"])}


@pytest.fixture
def r2(monkeypatch):
    fake = FakeR2()
    monkeypatch.setattr(storage, "get_client", lambda: fake)
    return fake


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return path.read_bytes()


def put_upload(r2, data, filename="My Podcast Ep 4.mp4"):
    """Store an uploaded original the way a finished multipart upload would."""
    info = uploads.start(UID, filename, len(data), "video/mp4", "team-1")
    r2.put_part(info["r2UploadId"], 1, data)
    uploads.complete(info["key"], info["r2UploadId"], [{"partNumber": 1, "etag": '"etag1"'}])
    return info


# --- validation -------------------------------------------------------------

@pytest.mark.parametrize("name", ["a.mp4", "B.MOV", "c.mkv", "d.webm", "e.m4v"])
def test_check_accepts_video_types(name):
    assert uploads.check(name, 1000) == os.path.splitext(name)[1].lower()


def test_check_rejects_other_types():
    with pytest.raises(uploads.UploadError, match="isn't supported"):
        uploads.check("notes.pdf", 1000)


def test_check_rejects_empty_and_too_big():
    with pytest.raises(uploads.UploadError):
        uploads.check("a.mp4", 0)
    with pytest.raises(uploads.UploadError, match="over 5 GB"):
        uploads.check("a.mp4", uploads.MAX_BYTES + 1)
    assert uploads.check("a.mp4", uploads.MAX_BYTES) == ".mp4"


def test_upload_sources():
    assert uploads.is_upload(f"upload:{UID}")
    assert not uploads.is_upload("https://youtu.be/x")
    assert not uploads.is_upload(None)
    assert uploads.upload_id_of(f"upload:{UID}") == UID
    for bad in ["upload:../../etc", "upload:ABC", "https://youtu.be/x", f"upload:{UID}0"]:
        with pytest.raises(ValueError):
            uploads.upload_id_of(bad)


# --- multipart --------------------------------------------------------------

def test_start_presigns_one_url_per_part(r2):
    size = uploads.PART_SIZE * 2 + 1
    info = uploads.start(UID, "Ep 1.MOV", size, "video/quicktime", "team-1")
    assert info["key"] == f"uploads/{UID}/source.mov"
    assert info["partSize"] == uploads.PART_SIZE
    assert len(info["partUrls"]) == 3
    assert "part=3" in info["partUrls"][2]
    meta = r2.multipart[info["r2UploadId"]]["meta"]
    assert meta["team"] == "team-1"
    assert uploads._decode(meta["filename"]) == "Ep 1.MOV"


def test_complete_sorts_parts_and_abort_cancels(r2):
    info = uploads.start(UID, "a.mp4", 10, "video/mp4", "t")
    r2.put_part(info["r2UploadId"], 1, b"ab")
    r2.put_part(info["r2UploadId"], 2, b"cd")
    uploads.complete(info["key"], info["r2UploadId"],
                     [{"partNumber": 2, "etag": "e2"}, {"partNumber": 1, "etag": "e1"}])
    assert r2.objects[info["key"]]["data"] == b"abcd"

    other = uploads.start("bbbbbbbbbbbb", "b.mp4", 10, "video/mp4", "t")
    uploads.abort(other["key"], other["r2UploadId"])
    assert other["r2UploadId"] in r2.aborted


def test_non_ascii_filename_survives_metadata(r2):
    info = uploads.start(UID, "पॉडकास्ट — ep 2.mp4", 10, "video/mp4", "t")
    meta = r2.multipart[info["r2UploadId"]]["meta"]
    assert meta["filename"].isascii()
    assert uploads._decode(meta["filename"]) == "पॉडकास्ट — ep 2.mp4"


# --- ingest -----------------------------------------------------------------

def test_ingest_upload_builds_meta_audio_and_thumb(r2, sample_video, tmp_path):
    put_upload(r2, sample_video)
    meta = uploads.ingest_upload(UID, str(tmp_path))
    assert meta.video_id == f"up-{UID}"
    assert meta.title == "My Podcast Ep 4"
    assert meta.channel == "Uploaded video"
    assert 1.5 < meta.duration < 2.5
    assert os.path.getsize(meta.audio_path) > 0
    assert meta.audio_path.endswith(".m4a")
    assert meta.thumbnail_url == f"/api/uploads/{UID}/thumb.jpg"
    assert r2.objects[uploads.thumb_key(UID)]["data"][:2] == b"\xff\xd8"  # a JPEG


def test_ingest_upload_reuses_the_cache(r2, sample_video, tmp_path):
    put_upload(r2, sample_video)
    first = uploads.ingest_upload(UID, str(tmp_path))
    second = uploads.ingest_upload(UID, str(tmp_path))
    assert r2.downloads == [f"uploads/{UID}/source.mp4"]
    assert second.audio_path == first.audio_path
    assert second.title == "My Podcast Ep 4"


def test_source_path_downloads_again_after_the_sweeper(r2, sample_video, tmp_path):
    put_upload(r2, sample_video)
    path = uploads.source_path(UID, str(tmp_path))
    os.remove(path)
    assert uploads.source_path(UID, str(tmp_path)) == path
    assert os.path.exists(path)
    assert len(r2.downloads) == 2


def test_missing_upload_says_so(r2, tmp_path):
    with pytest.raises(RuntimeError, match="uploaded video"):
        uploads.source_path(UID, str(tmp_path))


def test_delete_upload_removes_source_and_thumb(r2, sample_video, tmp_path):
    put_upload(r2, sample_video)
    uploads.ingest_upload(UID, str(tmp_path))
    uploads.delete_upload(UID)
    assert not [k for k in r2.objects if k.startswith(f"uploads/{UID}/")]


# --- routed through ingest --------------------------------------------------

def test_ingest_hands_upload_sources_to_uploads(r2, sample_video, tmp_path, monkeypatch):
    put_upload(r2, sample_video)

    def no_ytdlp(*a, **k):
        raise AssertionError("yt-dlp must not be used for uploads")

    monkeypatch.setattr(ingest.yt_dlp, "YoutubeDL", no_ytdlp)
    meta = ingest.ingest(f"upload:{UID}", str(tmp_path))
    assert meta.video_id == f"up-{UID}"

    out = tmp_path / "clips" / "clip_0.mp4"
    ingest.SectionSource(f"upload:{UID}", str(tmp_path), meta.video_id)(0.5, 1.5, str(out))
    assert out.stat().st_size > 0
