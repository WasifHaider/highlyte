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


def list_jobs(team_id: str, limit: int = 20) -> list[dict[str, Any]]:
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("jobs")
            .select("*")
            .eq("team_id", team_id)
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


def list_clips(team_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """All clips across the team's jobs, newest first, each with its parent
    job's video info embedded (PostgREST foreign-key embed via the
    clips.job_id -> jobs.id relationship), so a clip is never shown
    without knowing which video and which job it came from (kept for
    API consumers; the Library tab was replaced by Projects). The `!inner`
    join makes the team_id filter apply to the clips themselves, not just
    the embedded job (a plain embed would still return every clip)."""
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("clips")
            .select("*, jobs!inner(url, video_title, video_channel, video_duration, team_id)")
            .eq("jobs.team_id", team_id)
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


def count_clips_by_job(job_ids: list[str]) -> dict[str, int]:
    """Clip count per job for the project list, in one query. PostgREST caps
    a response at its max-rows setting (1000 by default), so with more clips
    than that across the listed jobs some counts come back low; the project
    list asks for at most 200 jobs of about 8 clips each, so this is rare."""
    client = get_client()
    if client is None or not job_ids:
        return {}
    try:
        res = client.table("clips").select("job_id").in_("job_id", job_ids).execute()
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] count_clips_by_job failed: {e}")
        return {}
    counts: dict[str, int] = {}
    for r in res.data or []:
        counts[r["job_id"]] = counts.get(r["job_id"], 0) + 1
    return counts


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


# Account and team writes raise instead of logging and carrying on like the
# helpers above: a half-created account is worse than an error the caller
# can clean up after.
def _require_client():
    client = get_client()
    if client is None:
        raise RuntimeError("Supabase is not configured")
    return client


def create_team(name: str) -> dict[str, Any]:
    return _require_client().table("teams").insert({"name": name}).execute().data[0]


def delete_team(team_id: str) -> None:
    _require_client().table("teams").delete().eq("id", team_id).execute()


def add_member(user_id: str, team_id: str, role: str, email: str) -> dict[str, Any]:
    row = {"user_id": user_id, "team_id": team_id, "role": role, "email": email}
    return _require_client().table("team_members").insert(row).execute().data[0]


def get_member(user_id: str) -> dict[str, Any] | None:
    res = _require_client().table("team_members").select("*, teams(name)").eq("user_id", user_id).limit(1).execute()
    return _first(res)


def list_members(team_id: str) -> list[dict[str, Any]]:
    return _require_client().table("team_members").select("*").eq("team_id", team_id).execute().data or []


def oldest_team_id() -> str | None:
    # Which team gets the pre-login jobs. Ordered by created_at then id so
    # ties (teams created in the same instant) still resolve consistently
    # instead of depending on whatever order Postgres happens to return.
    res = (
        _require_client().table("teams").select("id")
        .order("created_at", desc=False).order("id", desc=False).limit(1).execute()
    )
    row = _first(res)
    return row["id"] if row else None


def claim_unowned_jobs(team_id: str) -> None:
    _require_client().table("jobs").update({"team_id": team_id}).is_("team_id", "null").execute()
