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
