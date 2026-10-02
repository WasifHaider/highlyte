import os

from backend.pipeline import cache

DAY = 86400


def _make(tmp_path, name, size, age_s, now):
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    os.utime(p, (now - age_s, now - age_s))
    return p


def test_removes_files_past_ttl_only(tmp_path):
    now = 1_000_000_000.0
    old = _make(tmp_path, "old.mp4", 10, 8 * DAY, now)
    fresh = _make(tmp_path, "fresh.mp4", 10, 1 * DAY, now)
    removed = cache.prune(str(tmp_path), ttl_s=7 * DAY, max_bytes=1e9, now=now)
    assert removed == ["old.mp4"]
    assert not old.exists() and fresh.exists()


def test_evicts_least_recently_used_over_cap(tmp_path):
    now = 1_000_000_000.0
    a = _make(tmp_path, "a.mp4", 100, 3 * DAY, now)
    b = _make(tmp_path, "b.mp4", 100, 2 * DAY, now)
    c = _make(tmp_path, "c.mp4", 100, 1 * DAY, now)
    cache.prune(str(tmp_path), ttl_s=30 * DAY, max_bytes=150, now=now)
    assert not a.exists() and not b.exists() and c.exists()


def test_never_removes_recently_used(tmp_path):
    now = 1_000_000_000.0
    busy = _make(tmp_path, "busy.mp4", 1000, 60, now)
    cache.prune(str(tmp_path), ttl_s=0, max_bytes=0, now=now)
    assert busy.exists()


def test_missing_dir_is_fine(tmp_path):
    assert cache.prune(str(tmp_path / "nope"), ttl_s=1, max_bytes=1) == []
