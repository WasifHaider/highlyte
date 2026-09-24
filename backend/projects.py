"""The project list behind the Home and Projects pages: one entry per
submitted video, built from running jobs in memory (which carry live
progress) and saved jobs in Supabase (which survive restarts).
"""
from __future__ import annotations

import re
from typing import Any

from .pipeline import ingest

PROCESSING_STATUSES = {"queued", "transcribing", "analyzing", "preparing"}
INTERRUPTED_ERROR = "Processing was interrupted by a server restart. Please submit the video again."

# Matches the 11-character id in watch?v=, youtu.be/, /shorts/, /embed/ and /live/ URLs.
_YOUTUBE_ID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")


def youtube_id(url: str | None) -> str | None:
    if not url:
        return None
    match = _YOUTUBE_ID_RE.search(url)
    return match.group(1) if match else None


def thumbnail_url(video_id: str | None, stored: str | None) -> str | None:
    """yt-dlp's thumbnail when we saved one; otherwise YouTube's standard
    thumbnail address, which exists for every public video."""
    if stored:
        return stored
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None


def _status_group(status: str) -> str:
    return "processing" if status in PROCESSING_STATUSES else status


def from_job(job: Any) -> dict[str, Any]:
    meta = job.video_meta or {}
    video_id = meta.get("videoId") or youtube_id(job.url)
    return {
        "id": job.id,
        "url": job.url,
        "status": job.status,
        "error": job.error,
        "videoTitle": meta.get("title"),
        "videoChannel": meta.get("channel"),
        "durationLabel": meta.get("durationLabel"),
        "thumbnailUrl": thumbnail_url(video_id, meta.get("thumbnailUrl")),
        "clipCount": len(job.clips),
        "progress": job.progress,
        "createdAt": job.created_at,
    }


def from_row(row: dict[str, Any], clip_count: int) -> dict[str, Any]:
    status, error = row["status"], row.get("error")
    if status not in ("done", "error"):
        # Not in memory, so its worker thread died with an old process.
        status, error = "error", INTERRUPTED_ERROR
    video_id = row.get("video_id") or youtube_id(row.get("url"))
    duration = row.get("video_duration")
    return {
        "id": row["id"],
        "url": row.get("url"),
        "status": status,
        "error": error,
        "videoTitle": row.get("video_title"),
        "videoChannel": row.get("video_channel"),
        "durationLabel": ingest.duration_label(float(duration)) if duration else None,
        "thumbnailUrl": thumbnail_url(video_id, row.get("thumbnail_url")),
        "clipCount": clip_count,
        "progress": {},
        "createdAt": row.get("created_at"),
    }


def build_projects(
    memory: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    counts: dict[str, int],
    *,
    q: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    by_id = {row["id"]: from_row(row, counts.get(row["id"], 0)) for row in rows}
    for project in memory:
        by_id[project["id"]] = project  # live state beats the last saved snapshot
    items = sorted(by_id.values(), key=lambda p: p.get("createdAt") or "", reverse=True)
    if q:
        needle = q.strip().lower()
        items = [p for p in items if needle in (p.get("videoTitle") or "").lower()]
    if status:
        items = [p for p in items if _status_group(p["status"]) == status]
    return items[:limit]
