"""Which Groq keys a pipeline call should use.

Each member can bring a main Groq key (team_members.groq_key) and a backup
key from a second Groq account (team_members.groq_backup_key); Groq limits
each account, so the backup adds a second free daily quota. A request
handler resolves them once and either uses them directly or hands them to
the background thread it starts, which calls `set_groq_keys` as its first
line — plain `threading.Thread` doesn't inherit a parent thread's
contextvars, so this has to happen explicitly on the worker side, not just
at request time.
"""
from __future__ import annotations

import contextvars
import os

_key: contextvars.ContextVar[str | None] = contextvars.ContextVar("groq_key", default=None)
_backup: contextvars.ContextVar[str | None] = contextvars.ContextVar("groq_backup_key", default=None)


def set_groq_key(key: str | None) -> None:
    _key.set(key or None)


def set_groq_backup_key(key: str | None) -> None:
    _backup.set(key or None)


def set_groq_keys(key: str | None, backup: str | None) -> None:
    set_groq_key(key)
    set_groq_backup_key(backup)


def get_groq_key() -> str | None:
    return _key.get() or os.environ.get("GROQ_KEY") or None


def get_groq_backup_key() -> str | None:
    return _backup.get() or os.environ.get("GROQ_BACKUP_KEY") or None
