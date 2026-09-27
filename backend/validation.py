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
# clip_{idx}.mp4 for a clip as first prepared (revision 0);
# clip_{idx}_r{revision}.mp4 for one replaced by Swap or Regenerate.
CLIP_FILENAME_RE = re.compile(r"^clip_\d{1,3}(_r\d{1,6})?\.mp4$")
# What /api/clips/{job}/{name} serves: a segment or its card poster (.jpg).
CLIP_MEDIA_RE = re.compile(r"^clip_\d{1,3}(_r\d{1,6})?\.(mp4|jpg)$")


def check_id(value: str, what: str = "id") -> str:
    if not ID_RE.fullmatch(value):
        raise HTTPException(400, f"invalid {what}")
    return value


def check_clip_filename(value: str) -> str:
    if not CLIP_MEDIA_RE.fullmatch(value):
        raise HTTPException(400, "invalid filename")
    return value
