"""Supabase-backed persistence for job/clip metadata.

Reads SUPABASE_URL / SUPABASE_KEY from the environment (see .env.example).
If they aren't set, all functions here are no-ops so the app still runs
fully offline/local — Supabase is additive persistence, not a hard
dependency for the core pipeline to function.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


@lru_cache(maxsize=1)
def get_client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    from supabase import create_client

    return create_client(SUPABASE_URL, SUPABASE_KEY)


def is_enabled() -> bool:
    return get_client() is not None


def upsert_job(row: dict[str, Any]) -> None:
    client = get_client()
    if client is None:
        return
    try:
        client.table("jobs").upsert(row).execute()
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] upsert_job failed: {e}")


def insert_clips(rows: list[dict[str, Any]]) -> None:
    client = get_client()
    if client is None or not rows:
        return
    try:
        client.table("clips").insert(rows).execute()
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] insert_clips failed: {e}")


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("jobs")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] list_jobs failed: {e}")
        return []


def _first(res) -> dict[str, Any] | None:
    rows = res.data or []
    return rows[0] if rows else None


def get_job(job_id: str) -> dict[str, Any] | None:
    client = get_client()
    if client is None:
        return None
    try:
        return _first(client.table("jobs").select("*").eq("id", job_id).limit(1).execute())
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] get_job failed: {e}")
        return None


def list_clips_for_job(job_id: str) -> list[dict[str, Any]]:
    client = get_client()
    if client is None:
        return []
    try:
        res = client.table("clips").select("*").eq("job_id", job_id).order("idx").execute()
        return res.data or []
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] list_clips_for_job failed: {e}")
        return []


def get_clip(clip_id: str) -> dict[str, Any] | None:
    client = get_client()
    if client is None:
        return None
    try:
        return _first(client.table("clips").select("*").eq("id", clip_id).limit(1).execute())
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] get_clip failed: {e}")
        return None


def update_clip(clip_id: str, fields: dict[str, Any]) -> None:
    client = get_client()
    if client is None:
        return
    try:
        client.table("clips").update(fields).eq("id", clip_id).execute()
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] update_clip failed: {e}")


def list_clips(limit: int = 100) -> list[dict[str, Any]]:
    """All clips across every job, newest first, each with its parent
    job's video info embedded (PostgREST foreign-key embed via the
    clips.job_id -> jobs.id relationship) — this is what backs the
    Library tab, so a clip is never shown without knowing which video and
    which job it came from."""
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("clips")
            .select("*, jobs(url, video_title, video_channel, video_duration)")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] list_clips failed: {e}")
        return []


def upsert_render(row: dict[str, Any]) -> None:
    client = get_client()
    if client is None:
        return
    try:
        client.table("renders").upsert(row).execute()
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] upsert_render failed: {e}")


def get_render(render_id: str) -> dict[str, Any] | None:
    client = get_client()
    if client is None:
        return None
    try:
        return _first(client.table("renders").select("*").eq("id", render_id).limit(1).execute())
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] get_render failed: {e}")
        return None


def find_render(clip_id: str, style_hash: str) -> dict[str, Any] | None:
    """Newest live (queued/rendering/done) render of this clip in exactly
    this style, if any — failed renders are never reused."""
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("renders").select("*")
            .eq("clip_id", clip_id).eq("style_hash", style_hash)
            .in_("status", ["queued", "rendering", "done"])
            .order("created_at", desc=True).limit(1).execute()
        )
        return _first(res)
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] find_render failed: {e}")
        return None
