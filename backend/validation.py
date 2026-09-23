"""Strict validation for values that arrive in URL paths.

Job/clip/render ids and clip filenames are joined into local file paths
and object-store keys, so anything outside a tight allowlist (dots,
slashes, backslashes) is rejected before it gets near os.path.join —
otherwise "../" in a path parameter could read files outside data/clips.
"""
from __future__ import annotations

import re

from fastapi import HTTPException

ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")
CLIP_FILENAME_RE = re.compile(r"^clip_\d{1,3}\.mp4$")


def check_id(value: str, what: str = "id") -> str:
    if not ID_RE.fullmatch(value):
        raise HTTPException(400, f"invalid {what}")
    return value


def check_clip_filename(value: str) -> str:
    if not CLIP_FILENAME_RE.fullmatch(value):
        raise HTTPException(400, "invalid filename")
    return value
