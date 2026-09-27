"""Run clip selection on a stored transcript and print what it picks.

Spends real Groq tokens (about 31k for a 74-minute episode). Usage, from
the repo root:
    ./.venv/Scripts/python scripts/select_dry_run.py <job_id | transcript.json>
A JSON file must hold {"segments": [...], "loudness": [...]} (loudness optional).
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import db  # noqa: E402  (loads .env, including GROQ_KEY)
from backend.pipeline import selection  # noqa: E402
from backend.pipeline.ingest import duration_label  # noqa: E402
from backend.pipeline.segments import from_dict  # noqa: E402


def _load(arg: str) -> dict:
    if os.path.isfile(arg):
        with open(arg, encoding="utf-8") as f:
            return json.load(f)
    stored = db.get_transcript(arg)
    if not stored:
        sys.exit(f"No stored transcript for job {arg!r}.")
    return stored


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    stored = _load(sys.argv[1])
    segs = [from_dict(d) for d in stored.get("segments") or []]
    try:
        result = selection.select(segs, stored.get("loudness") or [])
    except selection.SelectionFailed as e:
        sys.exit(f"Selection failed: {e}")
    for i, c in enumerate(result.clips, 1):
        print(f"#{i} {duration_label(c.start)}-{duration_label(c.end)} ({c.end - c.start:.1f}s) "
              f"score {c.score} [{c.tag}] flags={c.flags or '-'}")
        print(f"   standalone {c.standalone} hook {c.hook} payoff {c.payoff} "
              f"energy {c.energy} fit {c.duration_fit}")
        print(f"   title: {c.hook_title!r}  emphasis: {c.emphasis}")
        print(f"   {c.text}\n")
    if result.note:
        print(f"Note: {result.note}")


if __name__ == "__main__":
    main()
