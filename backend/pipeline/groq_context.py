"""Which Groq key a pipeline call should use.

Each member can bring their own Groq key (team_members.groq_key). A request
handler resolves it once and either uses it directly or hands it to the
background thread it starts, which calls `set_groq_key` as its first line —
plain `threading.Thread` doesn't inherit a parent thread's contextvars, so
this has to happen explicitly on the worker side, not just at request time.
"""
from __future__ import annotations

import contextvars
import os

_key: contextvars.ContextVar[str | None] = contextvars.ContextVar("groq_key", default=None)


def set_groq_key(key: str | None) -> None:
    _key.set(key or None)


def get_groq_key() -> str | None:
    return _key.get() or os.environ.get("GROQ_KEY") or None
