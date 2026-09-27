"""Bring clips cut before stream-friendly segments existed up to date:
re-encode each segment with cut.STREAM_VIDEO_ARGS (index first, a
keyframe every second) and give it a card poster.

Overwrites each segment in place (same R2 key or local file), so every
stored spec, style and render stays valid; the re-encode copies audio and
keeps the duration. A segment whose index is already first is only given
a poster if it lacks one. Usage, from the repo root:
    ./.venv/Scripts/python scripts/fix_clip_media.py [--dry-run] [job_id ...]
"""
from __future__ import annotations

import os
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import db, storage  # noqa: E402  (loads .env)
from backend.main import CLIPS_DIR  # noqa: E402
from backend.pipeline import cut  # noqa: E402


def index_first(path: str) -> bool:
    """True if the file's moov box comes before its mdat box."""
    with open(path, "rb") as f:
        while header := f.read(8):
            size = int.from_bytes(header[:4], "big")
            kind = header[4:8]
            if kind == b"moov":
                return True
            if kind == b"mdat":
                return False
            if size == 1:
                size = int.from_bytes(f.read(8), "big")
                f.seek(size - 16, 1)
            elif size == 0:
                return False
            else:
                f.seek(size - 8, 1)
    return False


def fix(row: dict, work: str, dry_run: bool) -> str:
    key = row.get("storage_key")
    filename = os.path.basename(row["download_path"])
    thumb_name = storage.thumb_filename(filename)
    start = float((row.get("spec") or {}).get("start") or 0.0)
    src = os.path.join(work, filename)

    if key:
        url = storage.clip_url(key)
        # The first boxes are enough to tell where the index is.
        req = urllib.request.Request(url, headers={"Range": "bytes=0-65535"})
        with urllib.request.urlopen(req) as resp, open(src, "wb") as f:
            f.write(resp.read())
        has_thumb = storage.clip_exists(storage.thumb_filename(key))
    else:
        local = os.path.join(CLIPS_DIR, row["job_id"], filename)
        if not os.path.exists(local):
            return "missing"
        src = local
        has_thumb = os.path.exists(os.path.join(CLIPS_DIR, row["job_id"], thumb_name))

    needs_encode = not index_first(src)
    if not needs_encode and has_thumb:
        return "ok already"
    if dry_run:
        return ("re-encode + " if needs_encode else "") + ("poster" if not has_thumb else "no poster needed")
    if key:
        urllib.request.urlretrieve(url, src)

    if needs_encode:
        out = os.path.join(work, "fixed_" + filename)
        cut.reencode_segment(src, out)
        before, after = cut.probe_duration(src), cut.probe_duration(out)
        if abs(before - after) > 0.1:
            return f"skipped: duration changed {before:.2f} -> {after:.2f}"
        if key:
            storage.upload_clip(out, key)
        else:
            os.replace(out, src)
            out = src
    else:
        out = src

    thumb = cut.make_thumbnail(out, start, os.path.join(work, thumb_name))
    if key:
        storage.upload_thumb(thumb, storage.thumb_filename(key))
    else:
        os.replace(thumb, os.path.join(CLIPS_DIR, row["job_id"], thumb_name))
    return ("re-encoded + " if needs_encode else "") + "poster"


def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    job_ids = [a for a in args if a != "--dry-run"]
    client = db.get_client()
    if client is None:
        sys.exit("Supabase is not configured.")
    query = client.table("clips").select("id,job_id,download_path,storage_key,spec")
    if job_ids:
        query = query.in_("job_id", job_ids)
    rows = query.execute().data or []
    print(f"{len(rows)} clips{' (dry run)' if dry_run else ''}")
    for row in rows:
        with tempfile.TemporaryDirectory() as work:
            try:
                result = fix(row, work, dry_run)
            except Exception as e:  # noqa: BLE001
                result = f"failed: {e}"
        print(f"{row['id']}: {result}", flush=True)


if __name__ == "__main__":
    main()
