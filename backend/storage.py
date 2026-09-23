"""Cloudflare R2 storage for cut clips.

R2 is S3-compatible, so this uses boto3's S3 client pointed at R2's
account-scoped endpoint. Reads R2_ACCOUNT_ID / R2_ACCESS_KEY_ID /
R2_SECRET_ACCESS_KEY / R2_BUCKET from the environment (see .env.example).

Additive like db.py's Supabase client: if the env vars aren't set, every
function here is a no-op / returns None, and main.py falls back to serving
clips straight off local disk exactly as before — R2 isn't a hard
dependency for the pipeline to run.

Clips are stored under the key `{job_id}/{filename}` (mirrors the local
data/clips/{job_id}/{filename} layout). Two ways to hand a client a URL for
that key:
  - R2_PUBLIC_BASE_URL set (a public bucket's r2.dev URL, or a custom
    domain mapped to the bucket): URLs are stable and cheap, no signing.
  - Otherwise: a presigned GET URL, time-limited (PRESIGNED_URL_TTL_S).
    Generated fresh per request by main.py's /api/clips route rather than
    stored, since a presigned URL expires and shouldn't be persisted as
    if it were permanent.
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.environ.get("R2_BUCKET")
# Optional. Leave unset to use presigned URLs instead.
R2_PUBLIC_BASE_URL = os.environ.get("R2_PUBLIC_BASE_URL")

PRESIGNED_URL_TTL_S = 3600  # 1 hour


@lru_cache(maxsize=1)
def get_client():
    if not (R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET):
        return None
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def is_enabled() -> bool:
    return get_client() is not None


def clip_key(job_id: str, filename: str) -> str:
    return f"{job_id}/{filename}"


def upload_clip(local_path: str, key: str) -> None:
    """Upload `local_path` to the bucket at `key`. Raises on failure —
    caller decides whether to keep the local file as a fallback (see
    main.py, which only deletes the local copy once this succeeds).

    Sets Content-Disposition: attachment on the object itself. The
    frontend's download links point at our own /api/clips route, which
    307-redirects here — and browsers drop an <a download> hint across a
    cross-origin redirect (R2's domain isn't ours), so clicking "download"
    just opened the clip in a new tab instead of saving it. Baking
    Content-Disposition into the object means R2's actual response tells
    the browser to save it, which survives the redirect regardless of the
    HTML attribute."""
    filename = key.rsplit("/", 1)[-1]
    client = get_client()
    if client is None:
        return
    client.upload_file(
        local_path, R2_BUCKET, key,
        ExtraArgs={
            "ContentType": "video/mp4",
            "ContentDisposition": f'attachment; filename="{filename}"',
        },
    )


def clip_exists(key: str) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.head_object(Bucket=R2_BUCKET, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def clip_url(key: str) -> str | None:
    """A URL a client can GET the clip from, or None if R2 isn't
    configured. Public base URL if set; otherwise a fresh presigned URL."""
    if R2_PUBLIC_BASE_URL:
        return f"{R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"
    client = get_client()
    if client is None:
        return None
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": R2_BUCKET, "Key": key},
        ExpiresIn=PRESIGNED_URL_TTL_S,
    )


def delete_clip(key: str) -> None:
    client = get_client()
    if client is None:
        return
    try:
        client.delete_object(Bucket=R2_BUCKET, Key=key)
    except Exception as e:  # noqa: BLE001
        print(f"[r2] delete_object failed for {key}: {e}")
