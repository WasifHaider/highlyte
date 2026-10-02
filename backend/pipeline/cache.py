"""Housekeeping for the download cache (data/cache).

Every job caches the full source video plus its extracted audio, keyed by
video id, and nothing else ever removes them. prune() deletes files that
have not been used for a while, then the least recently used ones until the
folder fits under a size cap. ingest() touches a file each time it serves
it, so mtime means "last used". Files used within MIN_AGE_S are never
removed, which protects jobs in progress. A pruned video is simply
downloaded again if Retry selection, Swap or Regenerate needs it.
"""
from __future__ import annotations

import os
import threading
import time

MIN_AGE_S = 6 * 3600
DEFAULT_TTL_DAYS = 7.0
DEFAULT_MAX_GB = 20.0
SWEEP_INTERVAL_S = 3600


def _settings() -> tuple[float, float]:
    ttl_days = float(os.environ.get("CACHE_TTL_DAYS", DEFAULT_TTL_DAYS))
    max_gb = float(os.environ.get("CACHE_MAX_GB", DEFAULT_MAX_GB))
    return ttl_days * 86400, max_gb * 1024**3


def prune(
    cache_dir: str, *, ttl_s: float, max_bytes: float, min_age_s: float = MIN_AGE_S,
    now: float | None = None,
) -> list[str]:
    """Delete stale cache files; returns the names removed."""
    now = time.time() if now is None else now
    files: list[tuple[float, int, str]] = []
    try:
        entries = list(os.scandir(cache_dir))
    except OSError:
        return []
    for e in entries:
        try:
            if e.is_file():
                st = e.stat()
                files.append((st.st_mtime, st.st_size, e.path))
        except OSError:
            continue
    files.sort()  # least recently used first
    total = sum(size for _, size, _ in files)
    removed: list[str] = []
    for mtime, size, path in files:
        age = now - mtime
        if age < min_age_s:
            continue
        if age > ttl_s or total > max_bytes:
            try:
                os.remove(path)
            except OSError as e:
                print(f"[cache] couldn't delete {path}: {e}")
                continue
            total -= size
            removed.append(os.path.basename(path))
    return removed


def sweep(cache_dir: str) -> None:
    ttl_s, max_bytes = _settings()
    removed = prune(cache_dir, ttl_s=ttl_s, max_bytes=max_bytes)
    if removed:
        print(f"[cache] removed {len(removed)} stale file(s): {', '.join(removed)}")


def start_sweeper(cache_dir: str) -> None:
    """Sweep now and then hourly, in a daemon thread."""
    def loop() -> None:
        while True:
            try:
                sweep(cache_dir)
            except Exception as e:  # noqa: BLE001
                print(f"[cache] sweep failed: {e}")
            time.sleep(SWEEP_INTERVAL_S)

    threading.Thread(target=loop, daemon=True, name="cache-sweeper").start()
