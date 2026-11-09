"""Uploaded videos: the fallback when YouTube blocks every download route.

The browser uploads the file straight to R2 in parts, using presigned
multipart URLs (Cloudflare Tunnel rejects request bodies over 100 MB, so a
long podcast can't go through the backend). The original stays in R2 at
uploads/{id}/source{.ext} until its project is deleted.

A job made from an upload has the source "upload:{id}" instead of a YouTube
link. ingest.ingest and ingest.SectionSource hand such sources to this
module, so the rest of the pipeline treats both the same way. Local copies
live in the download cache and are pulled from R2 again if the cache
sweeper removed them.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import threading
from urllib.parse import quote, unquote

from .. import storage
from .ingest import VideoMeta

PREFIX = "upload:"
MAX_BYTES = 5 * 1024 ** 3
PART_SIZE = 64 * 1024 ** 2
ALLOWED_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".m4v")
PART_URL_TTL_S = 6 * 3600
CHANNEL = "Uploaded video"

_ID_RE = re.compile(r"^[0-9a-f]{12}$")


class UploadError(ValueError):
    """The file can't be accepted (size or type). The message is user-facing."""


def check(filename: str, size: int) -> str:
    """Validate an upload before it starts. Returns its lowercase extension."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise UploadError("That file type isn't supported. Use MP4, MOV, MKV, WebM or M4V.")
    if size <= 0:
        raise UploadError("That file is empty.")
    if size > MAX_BYTES:
        raise UploadError("File is over 5 GB.")
    return ext


def is_upload(url: str | None) -> bool:
    return bool(url) and url.startswith(PREFIX)


def upload_id_of(url: str) -> str:
    if not is_upload(url) or not _ID_RE.match(url[len(PREFIX):]):
        raise ValueError(f"not an upload source: {url!r}")
    return url[len(PREFIX):]


def source_key(upload_id: str, ext: str) -> str:
    return f"uploads/{upload_id}/source{ext}"


def thumb_key(upload_id: str) -> str:
    return f"uploads/{upload_id}/thumb.jpg"


def thumb_url(upload_id: str) -> str:
    return f"/api/uploads/{upload_id}/thumb.jpg"


def _client():
    client = storage.get_client()
    if client is None:
        raise RuntimeError("Uploads need R2 storage, which isn't configured.")
    return client


# R2/S3 metadata must be ASCII, and filenames often aren't (Hindi titles).
def _encode(text: str) -> str:
    return quote(text, safe="")


def _decode(text: str) -> str:
    return unquote(text)


# --- multipart upload --------------------------------------------------------

def start(upload_id: str, filename: str, size: int, content_type: str | None, team_id: str) -> dict:
    """Start a multipart upload and presign one URL per part."""
    ext = check(filename, size)
    client = _client()
    key = source_key(upload_id, ext)
    created = client.create_multipart_upload(
        Bucket=storage.R2_BUCKET, Key=key,
        ContentType=content_type or "application/octet-stream",
        Metadata={"filename": _encode(filename), "team": team_id or ""},
    )
    r2_upload_id = created["UploadId"]
    parts = max(1, math.ceil(size / PART_SIZE))
    urls = [
        client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": storage.R2_BUCKET, "Key": key,
                    "UploadId": r2_upload_id, "PartNumber": n},
            ExpiresIn=PART_URL_TTL_S,
        )
        for n in range(1, parts + 1)
    ]
    return {"key": key, "r2UploadId": r2_upload_id, "partSize": PART_SIZE, "partUrls": urls}


def complete(key: str, r2_upload_id: str, parts: list[dict]) -> None:
    ordered = sorted(parts, key=lambda p: int(p["partNumber"]))
    _client().complete_multipart_upload(
        Bucket=storage.R2_BUCKET, Key=key, UploadId=r2_upload_id,
        MultipartUpload={"Parts": [
            {"PartNumber": int(p["partNumber"]), "ETag": str(p["etag"])} for p in ordered
        ]},
    )


def abort(key: str, r2_upload_id: str) -> None:
    _client().abort_multipart_upload(Bucket=storage.R2_BUCKET, Key=key, UploadId=r2_upload_id)


# --- local copies ------------------------------------------------------------

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(upload_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(upload_id, threading.Lock())


def _base(cache_dir: str, upload_id: str) -> str:
    return os.path.join(cache_dir, f"up-{upload_id}")


def _touch(path: str) -> None:
    try:
        os.utime(path)
    except OSError:
        pass


def _cached_source(cache_dir: str, upload_id: str) -> str | None:
    prefix = f"up-{upload_id}.source"
    if not os.path.isdir(cache_dir):
        return None
    for name in sorted(os.listdir(cache_dir)):
        if name.startswith(prefix) and not name.endswith(".part"):
            return os.path.join(cache_dir, name)
    return None


def _remote_source_key(upload_id: str) -> str:
    listed = _client().list_objects_v2(Bucket=storage.R2_BUCKET, Prefix=f"uploads/{upload_id}/source")
    keys = [o["Key"] for o in listed.get("Contents") or []]
    if not keys:
        raise RuntimeError("The uploaded video is missing from storage. Upload it again.")
    return keys[0]


def source_path(upload_id: str, cache_dir: str) -> str:
    """Local path of the uploaded original, pulled from R2 if not cached."""
    with _lock(upload_id):
        cached = _cached_source(cache_dir, upload_id)
        if cached:
            _touch(cached)
            return cached
        os.makedirs(cache_dir, exist_ok=True)
        key = _remote_source_key(upload_id)
        path = _base(cache_dir, upload_id) + ".source" + os.path.splitext(key)[1]
        part = path + ".part"
        _client().download_file(storage.R2_BUCKET, key, part)
        os.replace(part, path)
        return path


def _title(upload_id: str, cache_dir: str) -> str:
    """The original filename without its extension, from R2 metadata
    (cached next to the source so re-runs don't ask R2 again)."""
    meta_path = _base(cache_dir, upload_id) + ".meta.json"
    try:
        with open(meta_path, encoding="utf-8") as f:
            filename = json.load(f)["filename"]
        _touch(meta_path)
    except (OSError, ValueError, KeyError):
        head = _client().head_object(Bucket=storage.R2_BUCKET, Key=_remote_source_key(upload_id))
        filename = _decode((head.get("Metadata") or {}).get("filename") or "")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"filename": filename}, f)
    return os.path.splitext(filename)[0].strip() or "Uploaded video"


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='ignore')[-500:]}")
    return proc.stdout.decode(errors="ignore")


def _duration(path: str) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path])
    try:
        return float(out.strip())
    except ValueError as e:
        raise RuntimeError("Couldn't read this video's length. Is the file a valid video?") from e


def _audio(source: str, cache_dir: str, upload_id: str) -> str:
    path = _base(cache_dir, upload_id) + ".audio.m4a"
    if os.path.exists(path) and os.path.getsize(path) > 0:
        _touch(path)
        return path
    tmp = path + ".part.m4a"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", source, "-vn",
          "-ac", "1", "-c:a", "aac", "-b:a", "96k", tmp])
    os.replace(tmp, path)
    return path


def _ensure_thumb(source: str, duration: float, cache_dir: str, upload_id: str) -> None:
    key = thumb_key(upload_id)
    if storage.clip_exists(key):
        return
    local = _base(cache_dir, upload_id) + ".thumb.jpg"
    try:
        _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{duration * 0.1:.2f}", "-i", source,
              "-frames:v", "1", "-vf", "scale=640:-2", local])
        storage.upload_thumb(local, key)
    except Exception as e:  # noqa: BLE001  a missing poster must not fail the job
        print(f"[uploads] thumbnail failed for {upload_id}: {e}")
    finally:
        try:
            os.remove(local)
        except OSError:
            pass


def ingest_upload(upload_id: str, cache_dir: str) -> VideoMeta:
    source = source_path(upload_id, cache_dir)
    duration = _duration(source)
    audio = _audio(source, cache_dir, upload_id)
    _ensure_thumb(source, duration, cache_dir, upload_id)
    return VideoMeta(
        video_id=f"up-{upload_id}",
        title=_title(upload_id, cache_dir),
        channel=CHANNEL,
        duration=duration,
        audio_path=audio,
        thumbnail_url=thumb_url(upload_id),
    )


# --- cleanup and serving -----------------------------------------------------

def delete_upload(upload_id: str) -> None:
    """Delete the original and poster from R2 (best effort, like clip media)."""
    client = storage.get_client()
    if client is None:
        return
    try:
        listed = client.list_objects_v2(Bucket=storage.R2_BUCKET, Prefix=f"uploads/{upload_id}/")
        for obj in listed.get("Contents") or []:
            storage.delete_clip(obj["Key"])
    except Exception as e:  # noqa: BLE001
        print(f"[uploads] delete failed for {upload_id}: {e}")


def open_thumb(upload_id: str):
    return storage.open_object(thumb_key(upload_id))
