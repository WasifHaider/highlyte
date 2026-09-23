# Phase 1 — Vertical Reframe + Remotion Captions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn HighLyte clips into 9:16 face-following shorts with animated captions, previewed live in the browser and rendered on AWS Lambda with Remotion.

**Architecture:** Python stops producing final video. For each highlight it cuts a padded 16:9 source segment, computes word timings and face tracks, and stores a `ClipSpec` (JSON). A Remotion composition in the new `renderer/` package draws `{spec, style}`. The Vue app mounts that same composition in a Remotion `<Player>` (React island) for live preview, and FastAPI renders it on Lambda via the `remotion-lambda` Python client, copying the output to R2.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, MediaPipe 1.0.1 (FaceLandmarker task), OpenCV, ffmpeg, Groq Whisper, remotion-lambda 4.0.527, boto3; Remotion 4.0.527, React 19.3, zod 4.5.4, TypeScript, vitest 5; Vue 3 + Vite 8 with `@vitejs/plugin-react`.

**Spec:** `docs/superpowers/specs/2026-09-24-phase1-remotion-reframe-captions-design.md`

## Global Constraints

- Remotion npm packages (`remotion`, `@remotion/*`) and the Python `remotion-lambda` client are pinned to exactly `4.0.527`, and installed with `--save-exact` / `==`.
- `zod` is pinned to `4.5.4` (the version Remotion 4.0.527 itself depends on).
- Output composition: id `Clip`, 1080x1920, 30 fps.
- Layout values: `follow | speaker | split | fit`. Caption presets: `karaoke | pop | clean`. Caption position: `lower | middle`.
- Default accent colour: `#FFD400`. Hook title: at most 8 words, shown for the first 2.5 s.
- Face sampling: 5 fps. Speaker minimum hold: 1.5 s. Segment padding: 1 s each side.
- Automatic layout: faces in < 40% of frames, or main-face median area < 3% of the frame, gives `fit`; two tracks each present in ≥ 50% of frames gives `speaker` (if the speaker timeline has a switch) or `split`; otherwise `follow`.
- Word-timing fallback spreads words evenly and sets `wordsApprox: true`.
- At most 2 Lambda renders run at once; a render `rendering` for more than 30 min becomes `error: timed out`.
- Path-parameter ids must match `^[a-z0-9-]{1,64}$`. `whisper_model` must be one of `tiny|base|small|medium`.
- The app must keep starting and running (analysis + preview) with Supabase, R2 and AWS all unset; only Export needs Lambda + R2.
- Code comments and docstrings follow the existing style: explain *why*, in full sentences.

## Deviations from the spec (intentional, decided while planning)

- The padded 16:9 segment **is** the existing clip file (`clip_{i}.mp4`, R2 key `{job_id}/clip_{i}.mp4`). This reuses `storage_key`, `/api/clips/{job}/{file}` and the Library tab unchanged, so no new `segment_key` column is needed. `spec.source.url` is served as that clip's `downloadUrl` for preview, and as a presigned R2 URL for Lambda.
- Preview also works without R2 (the clip is then served from local disk); only rendering requires R2.
- The Remotion S3 output is deleted explicitly after the copy to R2; the 1-day S3 lifecycle rule is documented as a manual backstop in the README.

## File Structure

```
backend/
  validation.py            NEW  id / filename validators for URL path params
  spec.py                  NEW  ClipSpec / ClipStyle Pydantic models, defaults, style hash
  render.py                NEW  render queue + Lambda wrapper + version check
  db.py                    MOD  job/clip/render lookups and writes
  storage.py               MOD  render keys, fileobj upload, object streaming
  main.py                  MOD  pipeline stage "preparing", status fallback, style + render endpoints
  pipeline/
    ingest.py              MOD  H.264 ≤1080p format selection
    highlight.py           MOD  hook_title, virality_score, emphasis words
    cut.py                 MOD  probe_video()
    words.py               NEW  per-clip word timings
    reframe.py             NEW  pure face-track logic (tracks, smoothing, speaker, layout)
    face_detect.py         NEW  MediaPipe FaceLandmarker sampling
    clipprep.py            NEW  per-clip preparation: segment, words, reframe, upload, spec
tests/                     NEW  pytest suite (conftest blanks all external services)
scripts/make_fixture_spec.py NEW writes renderer/src/__fixtures__/clip-spec.json
renderer/                  NEW  Remotion package (compositions, schema, lib, stills, deploy scripts)
frontend/
  vite.config.js           MOD  React plugin, @renderer alias, dedupe
  src/components/RemotionPreview.vue NEW React island hosting <Player>
  src/components/ClipCard.vue        NEW replaces ClipRow.vue
  src/components/ClipList.vue        MOD uses ClipCard
  src/components/ExportBar.vue       MOD render + zip flow
  src/components/ProcessingSteps.vue MOD "preparing" stage
  src/views/JobView.vue              MOD status notes, health load
  src/stores/jobStore.js             MOD styles, renders, health
  src/services/highlyteApi.js        MOD new endpoints
supabase/schema.sql        MOD  clip columns + renders table
requirements.txt           MOD  mediapipe, remotion-lambda
requirements-dev.txt       NEW  pytest, httpx
pytest.ini                 NEW
```

---

### Task 0: Pre-flight (commit existing work)

The working tree has uncommitted changes the plan depends on (for example `backend/storage.py` is untracked, and `backend/main.py` already imports it). A worktree created from `HEAD` would not contain them.

- [ ] **Step 1: Ask the user** to commit their current work (or give explicit permission to commit it as "WIP: R2 storage and library view"). Do not commit it without that permission.
- [ ] **Step 2: After the user's work is committed**, create the feature branch or worktree (`superpowers:using-git-worktrees`), branch name `feat/phase1-reframe-captions`.
- [ ] **Step 3: Confirm tools:** `ffmpeg -version`, `ffprobe -version`, `node -v` (expect v22), `.venv/Scripts/python --version` (expect 3.11).

---

### Task 1: Test harness and input validation

**Files:**
- Create: `pytest.ini`, `requirements-dev.txt`, `tests/conftest.py`, `tests/test_validation.py`, `backend/validation.py`
- Modify: `backend/main.py` (`GenerateRequest`, `get_clip`)

**Interfaces:**
- Produces: `backend.validation.check_id(value: str, what: str = "id") -> str` (raises `HTTPException(400)`), `backend.validation.check_clip_filename(value: str) -> str`.

- [ ] **Step 1: Add test tooling**

`requirements-dev.txt`:
```
-r requirements.txt
pytest==8.3.4
httpx==0.28.1
```

`pytest.ini`:
```ini
[pytest]
pythonpath = .
testpaths = tests
markers =
    slow: needs network, model downloads or heavy ffmpeg work
addopts = -m "not slow"
```

`tests/conftest.py`:
```python
"""Blank out every external service before any backend module is imported.

backend.db / backend.storage read their settings at import time (after
load_dotenv, which never overrides a variable that is already set, even
to ""). Setting them to "" here means tests never touch the real
Supabase project, R2 bucket, Groq or AWS account configured in .env.
"""
import os

for _key in [
    "SUPABASE_URL", "SUPABASE_KEY",
    "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL",
    "GROQ_KEY",
    "REMOTION_AWS_ACCESS_KEY_ID", "REMOTION_AWS_SECRET_ACCESS_KEY", "REMOTION_AWS_REGION",
    "REMOTION_FUNCTION_NAME", "REMOTION_SERVE_URL",
]:
    os.environ[_key] = ""
```

Run: `./.venv/Scripts/pip install -r requirements-dev.txt`

- [ ] **Step 2: Write the failing tests** — `tests/test_validation.py`:
```python
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import app
from backend.validation import check_clip_filename, check_id

client = TestClient(app)


@pytest.mark.parametrize("value", ["abc123", "a1b2c3d4e5f6-0", "renders-1"])
def test_check_id_accepts(value):
    assert check_id(value) == value


@pytest.mark.parametrize("value", ["..", "../etc", "ABC", "a/b", "a\\b", "", "x" * 65])
def test_check_id_rejects(value):
    with pytest.raises(HTTPException) as exc:
        check_id(value)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("value", ["clip_0.mp4", "clip_12.mp4"])
def test_check_clip_filename_accepts(value):
    assert check_clip_filename(value) == value


@pytest.mark.parametrize("value", ["secret.txt", "clip_0.mp4.exe", "../clip_0.mp4", "clip_a.mp4"])
def test_check_clip_filename_rejects(value):
    with pytest.raises(HTTPException):
        check_clip_filename(value)


def test_get_clip_rejects_traversal_job_id():
    assert client.get("/api/clips/..%2e/clip_0.mp4").status_code == 400


def test_get_clip_rejects_bad_filename():
    assert client.get("/api/clips/abc123/secret.txt").status_code == 400


def test_generate_rejects_unknown_whisper_model():
    r = client.post("/api/generate", json={"url": "https://youtu.be/x", "whisper_model": "large-v3"})
    assert r.status_code == 422
```

- [ ] **Step 3: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.validation'`.

- [ ] **Step 4: Implement** — `backend/validation.py`:
```python
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
```

In `backend/main.py`:
- add `from typing import Any, Literal` (replace the existing `from typing import Any`) and `from .validation import check_clip_filename, check_id`.
- change `GenerateRequest`:
```python
class GenerateRequest(BaseModel):
    url: str
    # Allowlisted: this is passed straight to faster-whisper, which would
    # otherwise download whatever model name a client sends.
    whisper_model: Literal["tiny", "base", "small", "medium"] = "small"
```
- at the top of `get_clip`, before `path = ...`:
```python
    check_id(job_id, "job id")
    check_clip_filename(filename)
```

- [ ] **Step 5: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest -v`
Expected: all tests in `tests/test_validation.py` PASS.

- [ ] **Step 6: Commit**
```bash
git add pytest.ini requirements-dev.txt tests/conftest.py tests/test_validation.py backend/validation.py backend/main.py
git commit -m "Add pytest harness and validate path params and whisper model"
```

---

### Task 2: ClipSpec / ClipStyle contract and shared fixture

**Files:**
- Create: `backend/spec.py`, `tests/test_spec.py`, `scripts/make_fixture_spec.py`, `renderer/src/__fixtures__/clip-spec.json` (generated)

**Interfaces:**
- Produces (in `backend/spec.py`): `LayoutKind`, `CaptionPreset` (Literal types); models `Word(text, start, end, emphasis=False)`, `Source(url, width, height, fps)`, `TrackPoint(t, cx, cy, w, h)`, `FaceTrack(id, track)`, `SpeakerTurn(t, faceId)`, `Reframe(auto, faces, speakerTimeline)`, `ClipSpec(version=1, clipId, source, start, end, words, wordsApprox, hookTitle, viralityScore, reframe)`, `ClipStyle(layout, captionPreset="karaoke", showHook=True, hookTitle=None, accent="#FFD400", captionPosition="lower")`; functions `default_style(spec: ClipSpec) -> ClipStyle`, `style_hash(style: ClipStyle) -> str` (16 hex chars).
- Produces: `renderer/src/__fixtures__/clip-spec.json` — a valid `ClipSpec` with `source.url = "fixture.mp4"`, 1920x1080 @ 30 fps, `start = 1.0`, `end = 9.0`.

- [ ] **Step 1: Write the failing tests** — `tests/test_spec.py`:
```python
import json
import os

import pytest
from pydantic import ValidationError

from backend.spec import ClipSpec, ClipStyle, default_style, style_hash

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec.json")


def _spec(**overrides) -> ClipSpec:
    base = {
        "clipId": "abc123def456-0",
        "source": {"url": "", "width": 1920, "height": 1080, "fps": 30},
        "start": 1.0,
        "end": 9.0,
        "words": [{"text": "hello", "start": 0.0, "end": 0.4}],
        "wordsApprox": False,
        "hookTitle": "Big claim",
        "viralityScore": 7.5,
        "reframe": {"auto": "split", "faces": [], "speakerTimeline": []},
    }
    base.update(overrides)
    return ClipSpec.model_validate(base)


def test_spec_defaults_version_and_emphasis():
    spec = _spec()
    assert spec.version == 1
    assert spec.words[0].emphasis is False


def test_spec_rejects_out_of_range_virality():
    with pytest.raises(ValidationError):
        _spec(viralityScore=11)


def test_spec_rejects_unknown_layout():
    with pytest.raises(ValidationError):
        _spec(reframe={"auto": "zoom", "faces": [], "speakerTimeline": []})


def test_default_style_follows_spec():
    style = default_style(_spec())
    assert style.layout == "split"
    assert style.captionPosition == "middle"  # split always puts captions on the seam
    assert style.showHook is True
    assert style.hookTitle == "Big claim"
    assert style.accent == "#FFD400"
    assert style.captionPreset == "karaoke"


def test_default_style_hides_hook_when_missing():
    style = default_style(_spec(hookTitle=None, reframe={"auto": "follow", "faces": [], "speakerTimeline": []}))
    assert style.showHook is False
    assert style.captionPosition == "lower"


def test_style_rejects_bad_accent():
    with pytest.raises(ValidationError):
        ClipStyle(layout="fit", accent="yellow")


def test_style_hash_is_stable_and_sensitive():
    a = ClipStyle(layout="fit")
    b = ClipStyle(layout="fit")
    c = ClipStyle(layout="fit", captionPreset="pop")
    assert style_hash(a) == style_hash(b)
    assert style_hash(a) != style_hash(c)
    assert len(style_hash(a)) == 16


def test_fixture_is_a_valid_spec():
    with open(FIXTURE, encoding="utf-8") as f:
        spec = ClipSpec.model_validate(json.load(f))
    assert spec.source.url == "fixture.mp4"
    assert len(spec.reframe.faces) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_spec.py -v`
Expected: FAIL — `No module named 'backend.spec'`.

- [ ] **Step 3: Implement** — `backend/spec.py`:
```python
"""The ClipSpec contract between the Python analysis pipeline and the
Remotion renderer (renderer/src/schema.ts mirrors these models in zod).

A spec holds what analysis measured about one clip and is written once.
A style holds what the team chose for it and changes freely. Remotion
receives both as {spec, style} input props, so the browser preview and
the Lambda render draw exactly the same thing.

All times are seconds. `start`/`end` are positions inside the padded
source segment; word and face-track times are relative to the clip's
own start (i.e. to `start`).
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

LayoutKind = Literal["follow", "speaker", "split", "fit"]
CaptionPreset = Literal["karaoke", "pop", "clean"]


class Word(BaseModel):
    text: str
    start: float
    end: float
    emphasis: bool = False


class Source(BaseModel):
    # Empty in stored specs: a fresh URL is filled in whenever the spec is
    # served (presigned R2 URLs expire, so they are never persisted).
    url: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)


class TrackPoint(BaseModel):
    """One smoothed face sample. Coordinates are normalized 0-1 of the
    source frame: (cx, cy) is the face centre, (w, h) its box size."""
    t: float
    cx: float
    cy: float
    w: float
    h: float


class FaceTrack(BaseModel):
    id: int
    track: list[TrackPoint]


class SpeakerTurn(BaseModel):
    t: float
    faceId: int


class Reframe(BaseModel):
    auto: LayoutKind
    # Sorted by how often each face is present, most present first.
    faces: list[FaceTrack]
    speakerTimeline: list[SpeakerTurn]


class ClipSpec(BaseModel):
    version: Literal[1] = 1
    clipId: str
    source: Source
    start: float = Field(ge=0)
    end: float
    words: list[Word]
    wordsApprox: bool
    hookTitle: str | None
    viralityScore: float = Field(ge=0, le=10)
    reframe: Reframe


class ClipStyle(BaseModel):
    layout: LayoutKind
    captionPreset: CaptionPreset = "karaoke"
    showHook: bool = True
    hookTitle: str | None = None
    accent: str = Field("#FFD400", pattern=r"^#[0-9A-Fa-f]{6}$")
    captionPosition: Literal["lower", "middle"] = "lower"


def default_style(spec: ClipSpec) -> ClipStyle:
    return ClipStyle(
        layout=spec.reframe.auto,
        showHook=spec.hookTitle is not None,
        hookTitle=spec.hookTitle,
        captionPosition="middle" if spec.reframe.auto == "split" else "lower",
    )


def style_hash(style: ClipStyle) -> str:
    """Stable fingerprint of a style, used to reuse an existing render
    instead of paying for an identical one again."""
    payload = json.dumps(style.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
```

`scripts/make_fixture_spec.py`:
```python
"""Write renderer/src/__fixtures__/clip-spec.json: a hand-built ClipSpec
used by the renderer's zod tests, Remotion Studio's default props and the
still-image smoke test. Generated from the Pydantic models so the two
schemas can't drift apart silently.

Run: ./.venv/Scripts/python scripts/make_fixture_spec.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.spec import ClipSpec  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec.json")

TEXT = (
    "Honestly this was the moment everything changed for us. "
    "Yaar sach yeh hai ke hum ready nahi thay. "
    "But we shipped it anyway and it worked!"
)
EMPHASIS = {"changed", "ready", "worked!"}


def build() -> ClipSpec:
    tokens = TEXT.split()
    step = 8.0 / len(tokens)
    words = [
        {
            "text": tok,
            "start": round(i * step, 3),
            "end": round((i + 1) * step - 0.02, 3),
            "emphasis": tok.lower() in EMPHASIS,
        }
        for i, tok in enumerate(tokens)
    ]
    left = [{"t": t / 5, "cx": 0.30, "cy": 0.42, "w": 0.12, "h": 0.22} for t in range(0, 41)]
    right = [{"t": t / 5, "cx": 0.70, "cy": 0.40, "w": 0.11, "h": 0.21} for t in range(0, 41)]
    return ClipSpec.model_validate({
        "clipId": "fixture0000-0",
        "source": {"url": "fixture.mp4", "width": 1920, "height": 1080, "fps": 30},
        "start": 1.0,
        "end": 9.0,
        "words": words,
        "wordsApprox": False,
        "hookTitle": "The moment everything changed",
        "viralityScore": 8.2,
        "reframe": {
            "auto": "speaker",
            "faces": [{"id": 0, "track": left}, {"id": 1, "track": right}],
            "speakerTimeline": [{"t": 0.0, "faceId": 0}, {"t": 4.0, "faceId": 1}],
        },
    })


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(build().model_dump(), f, indent=2)
        f.write("\n")
    print(f"wrote {OUT}")
```

Run: `./.venv/Scripts/python scripts/make_fixture_spec.py`

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest tests/test_spec.py -v`
Expected: 8 PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/spec.py tests/test_spec.py scripts/make_fixture_spec.py renderer/src/__fixtures__/clip-spec.json
git commit -m "Add ClipSpec/ClipStyle contract and shared renderer fixture"
```

---

### Task 3: LLM hook title, virality score, emphasis words; H.264 ingest

**Files:**
- Modify: `backend/pipeline/highlight.py` (`Clip`, `_llm_score_window` prompt + parsing, `_select_clips`)
- Modify: `backend/pipeline/ingest.py` (yt-dlp `format`)
- Test: `tests/test_highlight.py`

**Interfaces:**
- Produces: `highlight.Clip` gains `hook_title: str | None = None` and `emphasis: list[str] = field(default_factory=list)`. For LLM clips `Clip.score` is the virality score (0-10). Heuristic clips keep `hook_title=None`, `emphasis=[]`.

- [ ] **Step 1: Write the failing tests** — `tests/test_highlight.py`:
```python
import json
from types import SimpleNamespace

from backend.pipeline import highlight
from backend.pipeline.highlight import Clip, Sentence


def _client(content: str):
    completions = SimpleNamespace(
        create=lambda **kw: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
    )
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def _sentences():
    return [Sentence(start=i * 5.0, end=i * 5.0 + 4.8, text=f"Sentence number {i}.", idx=i) for i in range(6)]


def test_llm_window_reads_hook_title_virality_and_emphasis():
    sents = _sentences()
    content = json.dumps([{
        "start_idx": 0, "end_idx": 3, "virality_score": 8.5,
        "hook_title": "one two three four five six seven eight nine ten",
        "emphasis": ["number", "Sentence", 5, "a", "b", "c", "d"],
        "reason": "x", "tag": "Key insight",
    }])
    clips = highlight._llm_score_window(_client(content), sents, {s.idx: s for s in sents})
    assert len(clips) == 1
    c = clips[0]
    assert c.score == 8.5
    assert c.hook_title == "one two three four five six seven eight"  # capped at 8 words
    assert c.emphasis == ["number", "Sentence", "a", "b", "c"]  # strings only, max 5
    assert c.tag == "Key insight"


def test_llm_window_falls_back_to_hook_score_and_no_title():
    sents = _sentences()
    content = json.dumps([{"start_idx": 1, "end_idx": 4, "hook_score": 6, "tag": "Wild claim"}])
    c = highlight._llm_score_window(_client(content), sents, {s.idx: s for s in sents})[0]
    assert c.score == 6.0
    assert c.hook_title is None
    assert c.emphasis == []


def test_select_clips_keeps_hook_title_and_emphasis():
    sents = _sentences()
    cand = Clip(start=0.0, end=19.8, text="t", score=9.0, tag="Key insight", hook_title="Hook", emphasis=["x"])
    picked = highlight._select_clips([cand], sents)
    assert picked[0].hook_title == "Hook"
    assert picked[0].emphasis == ["x"]
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_highlight.py -v`
Expected: FAIL — `TypeError: Clip.__init__() got an unexpected keyword argument 'hook_title'`.

- [ ] **Step 3: Implement in `backend/pipeline/highlight.py`**

Imports: change `from dataclasses import dataclass` to `from dataclasses import dataclass, field, replace`.

Add near the other constants:
```python
HOOK_TITLE_MAX_WORDS = 8
MAX_EMPHASIS_WORDS = 5
```

`Clip`:
```python
@dataclass
class Clip:
    start: float
    end: float
    text: str
    score: float
    tag: str
    # LLM path only: a short hook overlay for the first seconds of the
    # short, and words from the span to highlight in captions.
    hook_title: str | None = None
    emphasis: list[str] = field(default_factory=list)
```

In `_llm_score_window`, replace the prompt text from `"should be roughly 15-90 seconds long. ...` through the JSON shape with:
```python
        "should be roughly 15-90 seconds long. end_idx must be the payoff/"
        "answer/punchline sentence, not a filler line before it. Rate each "
        "span's virality_score 0-10: how likely it is to perform as a "
        "standalone short, weighing most heavily how hard its first 2-3 "
        "seconds would grab a scrolling viewer with zero context. Write a "
        "hook_title of at most 8 words, punchy, in the same language mix the "
        "speakers use, that makes someone want to watch. List up to 5 "
        "emphasis words: single words copied from the span's own text that "
        "carry its meaning (they get highlighted in captions).\n\n"
        "Reply with ONLY a JSON array, no prose, in this exact shape:\n"
        '[{"start_idx": <int>, "end_idx": <int>, "virality_score": <0-10 number>, '
        '"hook_title": "<at most 8 words>", "emphasis": ["<word>", ...], '
        '"reason": "<short phrase>", "tag": "<one of: Strong opinion, Key '
        'insight, Funny moment, Actionable advice, Contrarian take, Wild '
        'claim>"}]\n'
        "If nothing in this window is worth clipping, reply with []."
```

In the parsing loop replace the `try` block and the `clips.append(...)`:
```python
        try:
            start_idx = int(span["start_idx"])
            end_idx = int(span["end_idx"])
            # hook_score was the field name before virality_score existed.
            virality = float(span.get("virality_score", span.get("hook_score", 0)))
        except (KeyError, TypeError, ValueError):
            continue
```
```python
        raw_title = span.get("hook_title")
        hook_title = None
        if isinstance(raw_title, str) and raw_title.strip():
            hook_title = " ".join(raw_title.split()[:HOOK_TITLE_MAX_WORDS])
        raw_emphasis = span.get("emphasis") if isinstance(span.get("emphasis"), list) else []
        emphasis = [w for w in raw_emphasis if isinstance(w, str) and w.strip()][:MAX_EMPHASIS_WORDS]
        clips.append(Clip(
            start=start_sent.start,
            end=end_sent.end,
            text=text,
            score=virality,
            tag=tag,
            hook_title=hook_title,
            emphasis=emphasis,
        ))
```

In `_select_clips`, replace
`picked.append(Clip(start=start, end=end, text=text, score=c.score, tag=c.tag))`
with
```python
        picked.append(replace(c, start=start, end=end, text=text))
```

Update the module docstring's LLM bullet: after "it isn't just scoring pre-cut slabs." add "It also returns a hook title, a 0-10 virality score and caption emphasis words per span."

- [ ] **Step 4: H.264 ingest** — in `backend/pipeline/ingest.py` replace the `"format"` entry:
```python
            # Prefer H.264 at 1080p or lower: every browser can decode it for
            # the live preview, and face analysis/cutting stay fast. Falls
            # back to anything available rather than failing the download.
            "format": (
                "bestvideo[vcodec^=avc1][height<=1080][ext=mp4]+bestaudio[ext=m4a]"
                "/best[vcodec^=avc1][height<=1080][ext=mp4]"
                "/bestvideo[height<=1080]+bestaudio/best"
            ),
```
(No test: it's a yt-dlp selector string. Segments are re-encoded to H.264 by `cut.cut_clip` anyway, so an older cached VP9 file still works.)

- [ ] **Step 5: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest -v`
Expected: all PASS.

- [ ] **Step 6: Commit**
```bash
git add backend/pipeline/highlight.py backend/pipeline/ingest.py tests/test_highlight.py
git commit -m "Return hook title, virality score and emphasis words from LLM; prefer H.264 downloads"
```

---

### Task 4: Per-clip word timings

**Files:**
- Create: `backend/pipeline/words.py`, `tests/test_words.py`

**Interfaces:**
- Consumes: `transcript.TranscriptSegment(start, end, text)`, `transcript._transcribe_chunk_groq(path, api_key, prompt) -> list[tuple[float, float, str]]`, `spec.Word`.
- Produces:
  - `words_from_segments(segments, clip_start, clip_end) -> list[Word]`
  - `spread_words(segments, clip_start, clip_end) -> list[Word]`
  - `mark_emphasis(words, keywords) -> list[Word]`
  - `extract_audio_span(audio_path, start, end, out_path) -> None`
  - `clip_words(segments, source, audio_path, clip_start, clip_end, emphasis, *, groq_key=None, prompt=None, transcribe=_transcribe_chunk_groq) -> tuple[list[Word], bool]` — returns `(words relative to clip_start, approx)`.

- [ ] **Step 1: Write the failing tests** — `tests/test_words.py`:
```python
from backend.pipeline import words as words_mod
from backend.pipeline.transcript import TranscriptSegment as Seg


def test_words_from_segments_slices_and_rebases():
    segs = [Seg(9.0, 9.8, "before"), Seg(10.2, 10.6, "Hello"), Seg(10.6, 11.0, "world."), Seg(30.0, 30.5, "after")]
    out = words_mod.words_from_segments(segs, 10.0, 20.0)
    assert [(w.text, w.start, w.end) for w in out] == [("Hello", 0.2, 0.6), ("world.", 0.6, 1.0)]


def test_spread_words_even_split_and_clamp():
    segs = [Seg(10.0, 12.0, "one two three four")]
    out = words_mod.spread_words(segs, 10.5, 20.0)
    # 0.5 s per word; "one" (10.0-10.5) ends exactly at the clip start and is dropped
    assert [(w.text, w.start, w.end) for w in out] == [("two", 0.0, 0.5), ("three", 0.5, 1.0), ("four", 1.0, 1.5)]


def test_mark_emphasis_normalizes_case_and_punctuation():
    ws = words_mod.words_from_segments([Seg(0, 1, "It"), Seg(1, 2, "WORKED!")], 0, 5)
    marked = words_mod.mark_emphasis(ws, ["worked", "big idea"])
    assert [w.emphasis for w in marked] == [False, True]


def test_clip_words_uses_transcript_words_for_whisper_sources():
    segs = [Seg(10.1, 10.4, "hey")]
    out, approx = words_mod.clip_words(segs, "groq", "a.m4a", 10.0, 20.0, [])
    assert approx is False
    assert out[0].text == "hey" and out[0].start == 0.1


def test_clip_words_calls_groq_for_caption_source(monkeypatch):
    monkeypatch.setattr(words_mod, "extract_audio_span", lambda *a, **k: None)
    calls = []

    def fake_transcribe(path, key, prompt):
        calls.append((key, prompt))
        return [(0.1, 0.5, "Hello"), (0.5, 0.9, "world")]

    segs = [Seg(10.0, 12.0, "hello world")]
    out, approx = words_mod.clip_words(
        segs, "captions", "a.m4a", 10.0, 20.0, ["world"],
        groq_key="k", prompt="p", transcribe=fake_transcribe,
    )
    assert calls == [("k", "p")]
    assert approx is False
    assert [(w.text, w.emphasis) for w in out] == [("Hello", False), ("world", True)]


def test_clip_words_falls_back_to_even_spread(monkeypatch):
    monkeypatch.setattr(words_mod, "extract_audio_span", lambda *a, **k: None)

    def boom(*a):
        raise RuntimeError("groq down")

    segs = [Seg(10.0, 11.0, "a b")]
    out, approx = words_mod.clip_words(segs, "captions", "a.m4a", 10.0, 20.0, [], groq_key="k", transcribe=boom)
    assert approx is True
    assert [(w.text, w.start, w.end) for w in out] == [("a", 0.0, 0.5), ("b", 0.5, 1.0)]


def test_clip_words_without_key_is_approx():
    out, approx = words_mod.clip_words([Seg(10.0, 11.0, "a")], "captions", "a.m4a", 10.0, 20.0, [])
    assert approx is True and out[0].text == "a"
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_words.py -v`
Expected: FAIL — `cannot import name 'words'`.

- [ ] **Step 3: Implement** — `backend/pipeline/words.py`:
```python
"""Word-level timings for one clip, relative to the clip's start.

Karaoke/pop captions need to know when each word is spoken. The Groq and
local Whisper transcript paths already produce word-level segments (see
transcript.py), so those are sliced directly. The YouTube-captions path
only has caption-line timing, so for those clips the clip's own audio
span is sent to Groq Whisper — a few seconds of audio per clip, not the
whole episode. If that isn't possible (no GROQ_KEY, or the call fails),
each caption line's duration is spread evenly across its words and the
result is flagged approximate so the UI can say so.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Callable

from ..spec import Word
from .transcript import TranscriptSegment, _transcribe_chunk_groq

# Transcript sources whose segments are already individual words.
WORD_LEVEL_SOURCES = {"groq", "whisper"}

_NON_WORD_RE = re.compile(r"[^\w']+", re.UNICODE)


def _norm(token: str) -> str:
    return _NON_WORD_RE.sub("", token.lower())


def _overlaps(start: float, end: float, clip_start: float, clip_end: float) -> bool:
    return end > clip_start and start < clip_end


def words_from_segments(
    segments: list[TranscriptSegment], clip_start: float, clip_end: float
) -> list[Word]:
    out: list[Word] = []
    for s in segments:
        text = s.text.strip()
        if not text or not _overlaps(s.start, s.end, clip_start, clip_end):
            continue
        start = max(s.start, clip_start) - clip_start
        end = min(s.end, clip_end) - clip_start
        out.append(Word(text=text, start=round(start, 3), end=round(max(end, start), 3)))
    return out


def spread_words(
    segments: list[TranscriptSegment], clip_start: float, clip_end: float
) -> list[Word]:
    out: list[Word] = []
    for s in segments:
        tokens = s.text.split()
        if not tokens or not _overlaps(s.start, s.end, clip_start, clip_end):
            continue
        step = (s.end - s.start) / len(tokens)
        for i, tok in enumerate(tokens):
            ws = s.start + i * step
            we = ws + step
            if not _overlaps(ws, we, clip_start, clip_end):
                continue
            out.append(Word(
                text=tok,
                start=round(max(ws, clip_start) - clip_start, 3),
                end=round(min(we, clip_end) - clip_start, 3),
            ))
    return out


def mark_emphasis(words: list[Word], keywords: list[str]) -> list[Word]:
    targets = {_norm(tok) for kw in keywords for tok in kw.split()} - {""}
    return [w.model_copy(update={"emphasis": _norm(w.text) in targets}) for w in words]


def extract_audio_span(audio_path: str, start: float, end: float, out_path: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.2f}", "-i", audio_path,
        "-t", f"{max(end - start, 0.5):.2f}",
        "-vn", "-c:a", "aac", "-b:a", "128k",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg audio span failed: {proc.stderr.decode(errors='ignore')}")


def clip_words(
    segments: list[TranscriptSegment],
    source: str,
    audio_path: str,
    clip_start: float,
    clip_end: float,
    emphasis: list[str],
    *,
    groq_key: str | None = None,
    prompt: str | None = None,
    transcribe: Callable[[str, str, str | None], list[tuple[float, float, str]]] = _transcribe_chunk_groq,
) -> tuple[list[Word], bool]:
    """Returns (words relative to clip_start, approx)."""
    if source in WORD_LEVEL_SOURCES:
        return mark_emphasis(words_from_segments(segments, clip_start, clip_end), emphasis), False

    words: list[Word] | None = None
    if groq_key:
        tmp_dir = tempfile.mkdtemp(prefix="highlyte_words_")
        try:
            span_path = os.path.join(tmp_dir, "span.m4a")
            extract_audio_span(audio_path, clip_start, clip_end, span_path)
            duration = clip_end - clip_start
            words = [
                Word(text=t.strip(), start=round(max(s, 0.0), 3), end=round(min(e, duration), 3))
                for s, e, t in transcribe(span_path, groq_key, prompt)
                if t.strip()
            ]
        except Exception as e:  # noqa: BLE001
            print(f"[words] groq word timing failed, spreading evenly: {e}")
            words = None
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    approx = words is None
    if words is None:
        words = spread_words(segments, clip_start, clip_end)
    return mark_emphasis(words, emphasis), approx
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest tests/test_words.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/pipeline/words.py tests/test_words.py
git commit -m "Add per-clip word timings with Groq and even-spread fallback"
```

---

### Task 5: Face-track logic (tracks, smoothing, speaker, auto layout)

**Files:**
- Create: `backend/pipeline/reframe.py`, `tests/test_reframe.py`

**Interfaces:**
- Consumes: `spec.Reframe`, `spec.FaceTrack`, `spec.TrackPoint`, `spec.SpeakerTurn`.
- Produces:
  - `Detection(cx, cy, w, h, jaw)` dataclass (normalized coords; `jaw` = MediaPipe `jawOpen` blendshape 0-1)
  - `build_tracks(frames: list[list[Detection]], times: list[float]) -> list[_Track]` (`_Track.id: int`, `_Track.points: list[tuple[float, Detection]]`)
  - `keep_main_tracks(tracks, n_samples) -> list[_Track]` — drops tracks present in < 10% of samples, sorts by presence, keeps 4, renumbers ids 0..
  - `smooth(points) -> list[TrackPoint]`
  - `speaker_timeline(tracks, times) -> list[SpeakerTurn]`
  - `choose_layout(frames, tracks, timeline) -> LayoutKind`
  - `analyze(frames, times) -> Reframe`
  - `fallback() -> Reframe` (`auto="fit"`, no faces)

- [ ] **Step 1: Write the failing tests** — `tests/test_reframe.py`:
```python
import math

from backend.pipeline import reframe
from backend.pipeline.reframe import Detection


def _times(seconds: float, fps: float = 5.0):
    return [round(i / fps, 3) for i in range(int(seconds * fps))]


def _talking(t: float, start: float, end: float) -> float:
    # jaw oscillates while talking, stays still otherwise
    return 0.3 + 0.25 * math.sin(t * 9) if start <= t < end else 0.05


def test_build_tracks_follows_two_faces_by_position():
    times = _times(2)
    frames = [[Detection(0.3, 0.4, 0.1, 0.2, 0.1), Detection(0.7, 0.4, 0.1, 0.2, 0.1)] for _ in times]
    tracks = reframe.build_tracks(frames, times)
    assert len(tracks) == 2
    assert all(len(t.points) == len(times) for t in tracks)
    assert {round(t.points[0][1].cx, 1) for t in tracks} == {0.3, 0.7}


def test_keep_main_tracks_drops_rare_faces_and_renumbers():
    times = _times(4)
    frames = [[Detection(0.5, 0.4, 0.1, 0.2, 0.1)] for _ in times]
    frames[0].append(Detection(0.1, 0.4, 0.05, 0.1, 0.0))  # a face seen in 1 of 20 samples
    kept = reframe.keep_main_tracks(reframe.build_tracks(frames, times), len(times))
    assert [t.id for t in kept] == [0]
    assert len(kept[0].points) == len(times)


def test_smooth_averages_and_applies_dead_zone():
    pts = [(i * 0.2, Detection(0.5 + (0.005 if i % 2 else 0.0), 0.4, 0.1, 0.2, 0.0)) for i in range(10)]
    out = reframe.smooth(pts)
    assert len(out) == 10
    assert len({p.cx for p in out}) == 1  # jitter below the dead zone never moves the crop


def test_speaker_timeline_switches_and_respects_min_hold():
    times = _times(9)
    frames = []
    for t in times:
        a_jaw = _talking(t, 0, 3) if t < 6 else _talking(t, 6, 6.6)  # A talks 0-3, blip at 6-6.6
        b_jaw = _talking(t, 3, 6) if t < 6 else _talking(t, 6.6, 9)
        frames.append([Detection(0.3, 0.4, 0.1, 0.2, a_jaw), Detection(0.7, 0.4, 0.1, 0.2, b_jaw)])
    tracks = reframe.keep_main_tracks(reframe.build_tracks(frames, times), len(times))
    timeline = reframe.speaker_timeline(tracks, times)
    a = next(t.id for t in tracks if t.points[0][1].cx < 0.5)
    b = next(t.id for t in tracks if t.points[0][1].cx > 0.5)
    assert timeline[0].t == 0.0 and timeline[0].faceId == a
    assert [turn.faceId for turn in timeline] == [a, b]  # the 0.6 s blip is absorbed
    assert 2.5 <= timeline[1].t <= 3.5


def test_choose_layout_rules():
    times = _times(4)
    solo = [[Detection(0.5, 0.4, 0.2, 0.3, 0.1)] for _ in times]
    pair = [[Detection(0.3, 0.4, 0.2, 0.3, 0.1), Detection(0.7, 0.4, 0.2, 0.3, 0.1)] for _ in times]
    tiny = [[Detection(0.9, 0.9, 0.05, 0.05, 0.1)] for _ in times]  # webcam corner in a screen share
    sparse = [([Detection(0.5, 0.4, 0.2, 0.3, 0.1)] if i < 5 else []) for i, _ in enumerate(times)]

    def layout(frames, timeline_len=1):
        tracks = reframe.keep_main_tracks(reframe.build_tracks(frames, times), len(times))
        timeline = [reframe.SpeakerTurn(t=float(i), faceId=0) for i in range(timeline_len)]
        return reframe.choose_layout(frames, tracks, timeline)

    assert layout(solo) == "follow"
    assert layout(pair, timeline_len=1) == "split"
    assert layout(pair, timeline_len=2) == "speaker"
    assert layout(tiny) == "fit"
    assert layout(sparse) == "fit"
    assert layout([[] for _ in times]) == "fit"


def test_analyze_returns_valid_reframe_and_fallback():
    times = _times(3)
    frames = [[Detection(0.5, 0.4, 0.2, 0.3, 0.1)] for _ in times]
    result = reframe.analyze(frames, times)
    assert result.auto == "follow"
    assert result.faces[0].id == 0 and len(result.faces[0].track) == len(times)
    assert reframe.fallback().auto == "fit" and reframe.fallback().faces == []
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_reframe.py -v`
Expected: FAIL — `cannot import name 'reframe'`.

- [ ] **Step 3: Implement** — `backend/pipeline/reframe.py`:
```python
"""Face-track logic for vertical reframing — pure functions, no video I/O
(face_detect.py produces the per-frame detections this module consumes).

Pipeline: per-sample face detections -> tracks (a face followed across
samples by horizontal position) -> keep the main tracks -> smooth them ->
work out who is talking when (jaw movement) -> pick an automatic layout.
Everything the renderer needs is stored for every layout, so the team
can switch layouts in the preview without re-running analysis.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..spec import FaceTrack, LayoutKind, Reframe, SpeakerTurn, TrackPoint

# A detection joins the track whose last position is within this much
# horizontal distance (fraction of frame width); otherwise it starts a new one.
MATCH_MAX_JUMP = 0.15
MIN_TRACK_PRESENCE = 0.10
MAX_TRACKS = 4
SMOOTH_WINDOW = 5  # samples (1 s at 5 fps)
# Crop centre only moves when the smoothed position shifts more than this,
# so small head movements don't make the frame wobble.
DEAD_ZONE = 0.02
ACTIVITY_WINDOW_S = 1.0
# Jaw-openness standard deviation below this counts as "not talking".
MIN_ACTIVITY = 0.01
MIN_HOLD_S = 1.5
FIT_MIN_FACE_FRACTION = 0.40
FIT_MIN_FACE_AREA = 0.03
TWO_FACE_PRESENCE = 0.50


@dataclass
class Detection:
    cx: float
    cy: float
    w: float
    h: float
    jaw: float


@dataclass
class _Track:
    id: int
    points: list[tuple[float, Detection]] = field(default_factory=list)


def build_tracks(frames: list[list[Detection]], times: list[float]) -> list[_Track]:
    tracks: list[_Track] = []
    next_id = 0
    for t, dets in zip(times, frames):
        used: set[int] = set()
        for d in sorted(dets, key=lambda d: -(d.w * d.h)):
            best: _Track | None = None
            best_dist = MATCH_MAX_JUMP
            for tr in tracks:
                if tr.id in used:
                    continue
                dist = abs(tr.points[-1][1].cx - d.cx)
                if dist <= best_dist:
                    best, best_dist = tr, dist
            if best is None:
                best = _Track(id=next_id)
                next_id += 1
                tracks.append(best)
            best.points.append((t, d))
            used.add(best.id)
    return tracks


def keep_main_tracks(tracks: list[_Track], n_samples: int) -> list[_Track]:
    if n_samples == 0:
        return []
    kept = [tr for tr in tracks if len(tr.points) / n_samples >= MIN_TRACK_PRESENCE]
    kept.sort(key=lambda tr: len(tr.points), reverse=True)
    kept = kept[:MAX_TRACKS]
    for new_id, tr in enumerate(kept):
        tr.id = new_id
    return kept


def smooth(points: list[tuple[float, Detection]]) -> list[TrackPoint]:
    out: list[TrackPoint] = []
    half = SMOOTH_WINDOW // 2
    last_cx: float | None = None
    for i, (t, _) in enumerate(points):
        window = [d for _, d in points[max(0, i - half): i + half + 1]]
        cx = sum(d.cx for d in window) / len(window)
        if last_cx is not None and abs(cx - last_cx) < DEAD_ZONE:
            cx = last_cx
        last_cx = cx
        out.append(TrackPoint(
            t=round(t, 3),
            cx=round(cx, 4),
            cy=round(sum(d.cy for d in window) / len(window), 4),
            w=round(sum(d.w for d in window) / len(window), 4),
            h=round(sum(d.h for d in window) / len(window), 4),
        ))
    return out


def speaker_timeline(tracks: list[_Track], times: list[float]) -> list[SpeakerTurn]:
    """Change points of who is talking, judged by how much each face's jaw
    moves in a 1 s window. Turns shorter than MIN_HOLD_S are absorbed into
    the previous turn so the crop doesn't flick between speakers."""
    if not tracks or not times:
        return []
    main = tracks[:2]
    if len(main) < 2:
        return [SpeakerTurn(t=0.0, faceId=main[0].id)]

    current = main[0].id
    raw: list[tuple[float, int]] = []
    for t in times:
        best_id, best_act = None, MIN_ACTIVITY
        for tr in main:
            jaws = [d.jaw for pt, d in tr.points if abs(pt - t) <= ACTIVITY_WINDOW_S / 2]
            if len(jaws) < 2:
                continue
            act = statistics.pstdev(jaws)
            if act > best_act:
                best_id, best_act = tr.id, act
        if best_id is not None:
            current = best_id
        raw.append((t, current))

    turns: list[tuple[float, int]] = []
    for t, fid in raw:
        if not turns or turns[-1][1] != fid:
            turns.append((t, fid))

    held: list[tuple[float, int]] = []
    for i, (t, fid) in enumerate(turns):
        next_t = turns[i + 1][0] if i + 1 < len(turns) else float("inf")
        if held and next_t - t < MIN_HOLD_S:
            continue  # too short: the previous speaker keeps the frame
        if held and held[-1][1] == fid:
            continue
        held.append((t, fid))

    return [SpeakerTurn(t=0.0 if i == 0 else round(t, 3), faceId=fid) for i, (t, fid) in enumerate(held)]


def choose_layout(
    frames: list[list[Detection]], tracks: list[_Track], timeline: list[SpeakerTurn]
) -> LayoutKind:
    n = len(frames)
    if n == 0 or not tracks:
        return "fit"
    face_fraction = sum(1 for dets in frames if dets) / n
    main_area = statistics.median(d.w * d.h for _, d in tracks[0].points)
    if face_fraction < FIT_MIN_FACE_FRACTION or main_area < FIT_MIN_FACE_AREA:
        return "fit"
    frequent = [tr for tr in tracks if len(tr.points) / n >= TWO_FACE_PRESENCE]
    if len(frequent) >= 2:
        return "speaker" if len(timeline) > 1 else "split"
    return "follow"


def analyze(frames: list[list[Detection]], times: list[float]) -> Reframe:
    tracks = keep_main_tracks(build_tracks(frames, times), len(times))
    timeline = speaker_timeline(tracks, times)
    return Reframe(
        auto=choose_layout(frames, tracks, timeline),
        faces=[FaceTrack(id=tr.id, track=smooth(tr.points)) for tr in tracks],
        speakerTimeline=timeline,
    )


def fallback() -> Reframe:
    return Reframe(auto="fit", faces=[], speakerTimeline=[])
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest tests/test_reframe.py -v`
Expected: 6 PASS. If `test_speaker_timeline_switches_and_respects_min_hold` fails on the switch time, print `timeline` and the per-sample activity; tune only `MIN_ACTIVITY` (not the test's talking pattern), and keep the value in the spec's spirit (below typical talking variance ≈ 0.15).

- [ ] **Step 5: Commit**
```bash
git add backend/pipeline/reframe.py tests/test_reframe.py
git commit -m "Add face tracking, smoothing, speaker timeline and auto layout logic"
```

---

### Task 6: MediaPipe face sampling and video probing

**Files:**
- Create: `backend/pipeline/face_detect.py`, `tests/test_face_detect.py`
- Modify: `backend/pipeline/cut.py` (add `probe_video`), `requirements.txt`, `.gitignore`

**Interfaces:**
- Consumes: `reframe.Detection`.
- Produces:
  - `face_detect.ensure_model(models_dir: str) -> str` (path to `face_landmarker.task`, downloads once)
  - `face_detect.sample_detections(video_path: str, model_path: str, sample_fps: float = 5.0) -> tuple[list[list[Detection]], list[float]]` (times are seconds from the start of `video_path`)
  - `cut.probe_video(path: str) -> tuple[int, int, float]` (width, height, fps)

- [ ] **Step 1: Dependencies**

Append to `requirements.txt`:
```
mediapipe==1.0.1
```
Run: `./.venv/Scripts/pip install -r requirements-dev.txt`

Append to `.gitignore`:
```
data/models/
```

- [ ] **Step 2: Write the failing tests** — `tests/test_face_detect.py`:
```python
import os
import subprocess

import pytest

from backend.pipeline import cut, face_detect

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "models")


def _make_video(path, seconds=3, size="320x240", rate=25):
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}",
        "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p", path,
    ], check=True)


def test_probe_video(tmp_path):
    path = str(tmp_path / "v.mp4")
    _make_video(path)
    assert cut.probe_video(path) == (320, 240, 25.0)


@pytest.mark.slow
def test_sample_detections_on_faceless_video(tmp_path):
    path = str(tmp_path / "v.mp4")
    _make_video(path, seconds=3)
    model = face_detect.ensure_model(MODELS_DIR)
    frames, times = face_detect.sample_detections(path, model, sample_fps=5.0)
    assert 14 <= len(times) <= 16
    assert times == sorted(times)
    assert all(dets == [] for dets in frames)
```

- [ ] **Step 3: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_face_detect.py -v -m "slow or not slow"`
Expected: FAIL — `cannot import name 'face_detect'`.

- [ ] **Step 4: Implement**

Add to `backend/pipeline/cut.py` (add `import json` to the imports):
```python
def probe_video(path: str) -> tuple[int, int, float]:
    """(width, height, fps) of the first video stream."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate", "-of", "json", path,
    ]
    proc = subprocess.run(cmd, capture_output=True, check=True)
    stream = json.loads(proc.stdout)["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    return int(stream["width"]), int(stream["height"]), float(num) / float(den or 1)
```

`backend/pipeline/face_detect.py`:
```python
"""Sample a video at a few frames per second and detect faces with
MediaPipe's FaceLandmarker task.

MediaPipe 1.0 removed the old `mediapipe.solutions` API; the Tasks API
needs a model file, downloaded once into data/models/. FaceLandmarker is
used (rather than the lighter FaceDetector) because its `jawOpen`
blendshape is what reframe.speaker_timeline uses to tell who is talking.
"""
from __future__ import annotations

import os
import urllib.request

from .reframe import Detection

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
MAX_FACES = 4


def ensure_model(models_dir: str) -> str:
    path = os.path.join(models_dir, "face_landmarker.task")
    if not os.path.exists(path):
        os.makedirs(models_dir, exist_ok=True)
        tmp = path + ".part"
        urllib.request.urlretrieve(MODEL_URL, tmp)
        os.replace(tmp, path)
    return path


def sample_detections(
    video_path: str, model_path: str, sample_fps: float = 5.0
) -> tuple[list[list[Detection]], list[float]]:
    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(src_fps / sample_fps))

    options = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=MAX_FACES,
        output_face_blendshapes=True,
    )
    frames: list[list[Detection]] = []
    times: list[float] = []
    try:
        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            idx = 0
            while True:
                # grab() skips decoding frames we don't sample, which is most of them.
                if not cap.grab():
                    break
                if idx % step == 0:
                    ok, frame = cap.retrieve()
                    if not ok:
                        break
                    t = idx / src_fps
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    result = landmarker.detect_for_video(image, int(t * 1000))
                    frames.append(_to_detections(result))
                    times.append(round(t, 3))
                idx += 1
    finally:
        cap.release()
    return frames, times


def _to_detections(result) -> list[Detection]:
    dets: list[Detection] = []
    for i, landmarks in enumerate(result.face_landmarks):
        xs = [p.x for p in landmarks]
        ys = [p.y for p in landmarks]
        x0, x1 = max(min(xs), 0.0), min(max(xs), 1.0)
        y0, y1 = max(min(ys), 0.0), min(max(ys), 1.0)
        jaw = 0.0
        if i < len(result.face_blendshapes):
            jaw = next((c.score for c in result.face_blendshapes[i] if c.category_name == "jawOpen"), 0.0)
        dets.append(Detection(cx=(x0 + x1) / 2, cy=(y0 + y1) / 2, w=x1 - x0, h=y1 - y0, jaw=float(jaw)))
    return dets
```

- [ ] **Step 5: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest tests/test_face_detect.py -v -m "slow or not slow"`
Expected: 2 PASS (the slow one downloads the ~3.7 MB model on first run).

- [ ] **Step 6: Manual sanity check on a real talking-head file** (the cached episode from any earlier job in `data/cache/*.mp4`):
```bash
./.venv/Scripts/python -c "from backend.pipeline import face_detect as f; fr,t=f.sample_detections(__import__('glob').glob('data/cache/*.mp4')[0], f.ensure_model('data/models')); print(len(t), sum(1 for d in fr if d), fr[len(fr)//2])"
```
Expected: most sampled frames have at least one `Detection` with `jaw` between 0 and 1. (This samples the whole cached video, so on a long podcast it takes a while; stop it with Ctrl+C once you see it working if needed.)

- [ ] **Step 7: Commit**
```bash
git add backend/pipeline/face_detect.py backend/pipeline/cut.py tests/test_face_detect.py requirements.txt .gitignore
git commit -m "Add MediaPipe face sampling and ffprobe video probing"
```

---

### Task 7: Storage helpers for renders

**Files:**
- Modify: `backend/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces: `storage.render_key(render_id: str) -> str` (`renders/{render_id}.mp4`), `storage.upload_fileobj(fileobj, key: str, download_name: str) -> None`, `storage.open_object(key: str)` (returns a readable stream; raises if R2 isn't configured).

- [ ] **Step 1: Write the failing tests** — `tests/test_storage.py`:
```python
import io
from unittest.mock import MagicMock

import pytest

from backend import storage


@pytest.fixture
def fake_r2(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(storage, "get_client", lambda: client)
    monkeypatch.setattr(storage, "R2_BUCKET", "bucket")
    return client


def test_render_key():
    assert storage.render_key("abc") == "renders/abc.mp4"


def test_upload_fileobj_sets_attachment_headers(fake_r2):
    body = io.BytesIO(b"data")
    storage.upload_fileobj(body, "renders/abc.mp4", "highlyte-clip.mp4")
    fake_r2.upload_fileobj.assert_called_once_with(
        body, "bucket", "renders/abc.mp4",
        ExtraArgs={"ContentType": "video/mp4", "ContentDisposition": 'attachment; filename="highlyte-clip.mp4"'},
    )


def test_open_object_returns_body(fake_r2):
    fake_r2.get_object.return_value = {"Body": "stream"}
    assert storage.open_object("renders/abc.mp4") == "stream"
    fake_r2.get_object.assert_called_once_with(Bucket="bucket", Key="renders/abc.mp4")


def test_open_object_requires_r2(monkeypatch):
    monkeypatch.setattr(storage, "get_client", lambda: None)
    with pytest.raises(RuntimeError):
        storage.open_object("renders/abc.mp4")
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_storage.py -v`
Expected: FAIL — `module 'backend.storage' has no attribute 'render_key'`.

- [ ] **Step 3: Implement** — append to `backend/storage.py`:
```python
def render_key(render_id: str) -> str:
    return f"renders/{render_id}.mp4"


def upload_fileobj(fileobj, key: str, download_name: str) -> None:
    """Stream a file-like object (e.g. an S3 GetObject body from a
    finished Lambda render) into the bucket without writing it to local
    disk first. Same attachment disposition as upload_clip, for the same
    cross-origin-redirect reason."""
    client = get_client()
    if client is None:
        raise RuntimeError("R2 is not configured")
    client.upload_fileobj(
        fileobj, R2_BUCKET, key,
        ExtraArgs={
            "ContentType": "video/mp4",
            "ContentDisposition": f'attachment; filename="{download_name}"',
        },
    )


def open_object(key: str):
    """Readable stream of an object's bytes (used to build zip downloads)."""
    client = get_client()
    if client is None:
        raise RuntimeError("R2 is not configured")
    return client.get_object(Bucket=R2_BUCKET, Key=key)["Body"]
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest tests/test_storage.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/storage.py tests/test_storage.py
git commit -m "Add R2 helpers for render uploads and streaming reads"
```

---

### Task 8: Per-clip preparation, pipeline integration and status fallback

**Files:**
- Create: `backend/pipeline/clipprep.py`, `tests/test_clipprep.py`, `tests/test_status.py`
- Modify: `backend/main.py`, `backend/db.py`, `supabase/schema.sql`

**Interfaces:**
- Consumes: `cut.cut_clip`, `cut.probe_video`, `words.clip_words`, `face_detect.ensure_model`, `face_detect.sample_detections`, `reframe.analyze`, `reframe.fallback`, `storage.is_enabled`, `storage.clip_key`, `storage.upload_clip`, `spec.ClipSpec`, `spec.default_style`.
- Produces:
  - `clipprep.SEGMENT_PAD_S = 1.0`; `clipprep.segment_bounds(clip_start, clip_end, video_duration) -> tuple[float, float]`
  - `clipprep.PreparedClip(spec: ClipSpec, storage_key: str | None)`
  - `clipprep.prepare_clip(*, job_id, idx, clip, video_path, video_duration, segments, transcript_source, audio_path, clips_dir, models_dir, groq_key, prompt, on_step) -> PreparedClip`
  - `db.get_job(job_id) -> dict | None`, `db.list_clips_for_job(job_id) -> list[dict]`, `db.get_clip(clip_id) -> dict | None`, `db.update_clip(clip_id, fields: dict) -> None`
  - In `main.py`: API clip records gain `hookTitle`, `viralityScore`, `spec` (dict or `None` for pre-Phase-1 clips), `style` (dict or `None`); `spec.source.url` in API responses equals the clip's `downloadUrl` path. Helpers `_clip_record`, `_clip_row`, `_clip_row_to_api`, `_with_source_url`, `_find_clip(clip_id) -> dict | None`. Job status `"preparing"` replaces `"cutting"`.

- [ ] **Step 1: Schema migration** — append to `supabase/schema.sql`:
```sql
-- Phase 1: vertical reframe + Remotion captions. The clip's padded 16:9
-- segment is still the file at storage_key / download_path; these columns
-- hold what the renderer needs to draw the 9:16 version of it.
alter table clips add column if not exists spec jsonb;           -- ClipSpec (backend/spec.py); source.url left empty
alter table clips add column if not exists style jsonb;          -- ClipStyle chosen by the team; null = defaults
alter table clips add column if not exists hook_title text;
alter table clips add column if not exists virality_score numeric;

create table if not exists renders (
  id text primary key,
  clip_id text not null references clips(id) on delete cascade,
  style jsonb not null,
  style_hash text not null,
  status text not null default 'queued',  -- queued|rendering|done|error
  progress numeric not null default 0,
  lambda_render_id text,
  lambda_bucket text,
  storage_key text,
  error text,
  started_epoch double precision,         -- unix seconds; used for the 30-minute stuck check
  attempts integer not null default 0,    -- Lambda throttling retries
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists renders_clip_style_idx on renders(clip_id, style_hash);

drop trigger if exists renders_set_updated_at on renders;
create trigger renders_set_updated_at
  before update on renders
  for each row execute function set_updated_at();
```

- [ ] **Step 2: Write the failing tests**

`tests/test_clipprep.py`:
```python
import os

from backend.pipeline import clipprep, cut, face_detect
from backend.pipeline.highlight import Clip
from backend.pipeline.reframe import Detection
from backend.pipeline.transcript import TranscriptSegment as Seg


def test_segment_bounds_pads_and_clamps():
    assert clipprep.segment_bounds(11.0, 40.0, 100.0) == (10.0, 41.0)
    assert clipprep.segment_bounds(0.4, 20.0, 20.5) == (0.0, 20.5)
    assert clipprep.segment_bounds(5.0, 20.0, 0.0) == (4.0, 21.0)  # unknown duration: no clamp


def _patch_media(monkeypatch, detect):
    def fake_cut(src, start, end, out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "wb").close()
        return out

    monkeypatch.setattr(cut, "cut_clip", fake_cut)
    monkeypatch.setattr(cut, "probe_video", lambda p: (1920, 1080, 30.0))
    monkeypatch.setattr(face_detect, "ensure_model", lambda d: "model")
    monkeypatch.setattr(face_detect, "sample_detections", detect)


def _prepare(tmp_path):
    clip = Clip(start=11.0, end=25.0, text="t", score=12.3, tag="Key insight", hook_title="Hook", emphasis=["hey"])
    return clipprep.prepare_clip(
        job_id="abc123def456", idx=0, clip=clip,
        video_path="v.mp4", video_duration=100.0,
        segments=[Seg(11.2, 11.5, "hey"), Seg(11.5, 11.9, "there")],
        transcript_source="groq", audio_path="a.m4a",
        clips_dir=str(tmp_path), models_dir=str(tmp_path),
        groq_key=None, prompt=None, on_step=lambda s: None,
    )


def test_prepare_clip_builds_spec(tmp_path, monkeypatch):
    # segment starts at 10.0, so the clip starts 1.0 s into it
    times = [round(i / 5, 3) for i in range(80)]  # 0-16 s of the segment
    frames = [[Detection(0.5, 0.4, 0.2, 0.3, 0.1)] for _ in times]
    _patch_media(monkeypatch, lambda path, model, sample_fps=5.0: (frames, times))

    prepared = _prepare(tmp_path)
    spec = prepared.spec
    assert spec.clipId == "abc123def456-0"
    assert (spec.start, spec.end) == (1.0, 15.0)
    assert spec.source.width == 1920 and spec.source.url == ""
    assert [(w.text, w.start, w.emphasis) for w in spec.words] == [("hey", 0.2, True), ("there", 0.5, False)]
    assert spec.wordsApprox is False
    assert spec.hookTitle == "Hook"
    assert spec.viralityScore == 10.0  # clamped
    assert spec.reframe.auto == "follow"
    track = spec.reframe.faces[0].track
    assert track[0].t == 0.0 and track[-1].t <= 14.0  # re-based to the clip start, trimmed to the clip
    assert prepared.storage_key is None  # R2 disabled in tests
    assert os.path.exists(os.path.join(tmp_path, "abc123def456", "clip_0.mp4"))


def test_prepare_clip_survives_face_detection_failure(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no mediapipe")

    _patch_media(monkeypatch, boom)
    assert _prepare(tmp_path).spec.reframe.auto == "fit"
```

`tests/test_status.py`:
```python
from fastapi.testclient import TestClient

from backend import main

client = TestClient(main.app)


def _job_row(status="done"):
    return {
        "id": "feed00000001", "url": "https://youtu.be/x", "status": status, "error": None,
        "video_title": "Ep 1", "video_channel": "Pod", "video_duration": 120,
        "transcript_source": "groq",
    }


def _clip_row():
    return {
        "id": "feed00000001-0", "job_id": "feed00000001", "idx": 0,
        "start_s": 10, "end_s": 25, "text": "t", "tag": "Key insight", "score": 7,
        "download_path": "/api/clips/feed00000001/clip_0.mp4",
        "storage_provider": "local", "storage_key": None,
        "hook_title": "Hook", "virality_score": 7,
        "spec": {"source": {"url": "", "width": 1920, "height": 1080, "fps": 30}},
        "style": {"layout": "fit"},
        "created_at": "2026-09-24T00:00:00Z",
    }


def test_status_falls_back_to_database(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _job_row())
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [_clip_row()])
    r = client.get("/api/status/feed00000001")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["videoMeta"]["title"] == "Ep 1"
    clip = body["clips"][0]
    assert clip["hookTitle"] == "Hook"
    assert clip["spec"]["source"]["url"] == "/api/clips/feed00000001/clip_0.mp4"
    assert clip["style"] == {"layout": "fit"}


def test_status_reports_interrupted_jobs(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _job_row(status="transcribing"))
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [])
    body = client.get("/api/status/feed00000001").json()
    assert body["status"] == "error"
    assert "restart" in body["error"]


def test_status_unknown_job(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: None)
    assert client.get("/api/status/feed00000002").status_code == 404
```

- [ ] **Step 3: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_clipprep.py tests/test_status.py -v`
Expected: FAIL — `cannot import name 'clipprep'` and 404s from the status endpoint.

- [ ] **Step 4: Implement `backend/pipeline/clipprep.py`**
```python
"""Everything that happens to one highlight after it's picked: cut its
padded 16:9 segment, time its words, analyse faces, upload the segment,
and describe the result as a ClipSpec. The renderer (Remotion) draws the
final 9:16 short from that spec; no finished video is made here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from .. import storage
from ..spec import ClipSpec, Source
from . import cut, face_detect, reframe, words
from .highlight import Clip
from .transcript import TranscriptSegment

# Extra source video kept either side of the clip, so the renderer and
# any later trim editing have a little room without re-cutting.
SEGMENT_PAD_S = 1.0


@dataclass
class PreparedClip:
    spec: ClipSpec
    storage_key: str | None


def segment_bounds(clip_start: float, clip_end: float, video_duration: float) -> tuple[float, float]:
    seg_start = max(0.0, clip_start - SEGMENT_PAD_S)
    seg_end = clip_end + SEGMENT_PAD_S
    if video_duration:
        seg_end = min(seg_end, video_duration)
    return seg_start, seg_end


def prepare_clip(
    *,
    job_id: str,
    idx: int,
    clip: Clip,
    video_path: str,
    video_duration: float,
    segments: list[TranscriptSegment],
    transcript_source: str,
    audio_path: str,
    clips_dir: str,
    models_dir: str,
    groq_key: str | None,
    prompt: str | None,
    on_step: Callable[[str], None],
) -> PreparedClip:
    clip_id = f"{job_id}-{idx}"
    filename = f"clip_{idx}.mp4"
    local_path = os.path.join(clips_dir, job_id, filename)
    seg_start, seg_end = segment_bounds(clip.start, clip.end, video_duration)
    offset = clip.start - seg_start
    duration = clip.end - clip.start

    on_step("cutting")
    cut.cut_clip(video_path, seg_start, seg_end, local_path)
    width, height, fps = cut.probe_video(local_path)

    on_step("timing captions")
    clip_word_list, approx = words.clip_words(
        segments, transcript_source, audio_path, clip.start, clip.end, clip.emphasis,
        groq_key=groq_key, prompt=prompt,
    )

    on_step("framing")
    try:
        frames, times = face_detect.sample_detections(local_path, face_detect.ensure_model(models_dir))
        # Keep only samples inside the clip itself, re-based to its start.
        kept = [(round(t - offset, 3), f) for t, f in zip(times, frames) if offset <= t <= offset + duration]
        reframe_result = reframe.analyze([f for _, f in kept], [t for t, _ in kept])
    except Exception as e:  # noqa: BLE001
        print(f"[reframe] face analysis failed for {clip_id}, using fit: {e}")
        reframe_result = reframe.fallback()

    on_step("uploading")
    storage_key = None
    if storage.is_enabled():
        try:
            key = storage.clip_key(job_id, filename)
            storage.upload_clip(local_path, key)
            os.remove(local_path)
            storage_key = key
        except Exception as e:  # noqa: BLE001
            print(f"[r2] upload failed for {job_id}/{filename}, keeping local copy: {e}")

    spec = ClipSpec(
        clipId=clip_id,
        source=Source(url="", width=width, height=height, fps=fps),
        start=round(offset, 3),
        end=round(offset + duration, 3),
        words=clip_word_list,
        wordsApprox=approx,
        hookTitle=clip.hook_title,
        viralityScore=max(0.0, min(10.0, round(clip.score, 1))),
        reframe=reframe_result,
    )
    return PreparedClip(spec=spec, storage_key=storage_key)
```

- [ ] **Step 5: Implement `backend/db.py` additions** (append):
```python
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
```

- [ ] **Step 6: Implement `backend/main.py` changes**

Imports: add `import copy`, and extend the pipeline import to `from .pipeline import clipprep, cut, highlight, ingest, transcript` and add `from .spec import default_style`. Add below `CLIPS_DIR`:
```python
MODELS_DIR = os.path.join(BASE_DIR, "data", "models")
```
Update the `Job.status` comment to `# queued|transcribing|analyzing|preparing|done|error`.

Add these helpers above `_run_pipeline`:
```python
def _clip_record(job_id: str, idx: int, clip: highlight.Clip, prepared: clipprep.PreparedClip) -> dict[str, Any]:
    spec = prepared.spec
    return {
        "id": spec.clipId,
        "start": clip.start,
        "end": clip.end,
        "startLabel": ingest.duration_label(clip.start),
        "endLabel": ingest.duration_label(clip.end),
        "durationLabel": ingest.duration_label(clip.end - clip.start),
        "text": clip.text,
        "tag": clip.tag,
        "score": clip.score,
        "hookTitle": spec.hookTitle,
        "viralityScore": spec.viralityScore,
        "downloadUrl": f"/api/clips/{job_id}/clip_{idx}.mp4",
        "storageProvider": "r2" if prepared.storage_key else "local",
        "storageKey": prepared.storage_key,
        "spec": spec.model_dump(),
        "style": default_style(spec).model_dump(),
    }


def _clip_row(job_id: str, idx: int, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "job_id": job_id,
        "idx": idx,
        "start_s": record["start"],
        "end_s": record["end"],
        "text": record["text"],
        "tag": record["tag"],
        "score": record["score"],
        "download_path": record["downloadUrl"],
        "storage_provider": record["storageProvider"],
        "storage_key": record["storageKey"],
        "hook_title": record["hookTitle"],
        "virality_score": record["viralityScore"],
        "spec": record["spec"],
        "style": record["style"],
    }


def _clip_row_to_api(r: dict[str, Any]) -> dict[str, Any]:
    start_s = float(r.get("start_s") or 0.0)
    end_s = float(r.get("end_s") or 0.0)
    return {
        "id": r["id"],
        "jobId": r["job_id"],
        "start": start_s,
        "end": end_s,
        "startLabel": ingest.duration_label(start_s),
        "endLabel": ingest.duration_label(end_s),
        "durationLabel": ingest.duration_label(end_s - start_s),
        "text": r.get("text"),
        "tag": r.get("tag"),
        "score": r.get("score"),
        "hookTitle": r.get("hook_title"),
        "viralityScore": r.get("virality_score"),
        "downloadUrl": r.get("download_path") or f"/api/clips/{r['job_id']}/clip_{r.get('idx', 0)}.mp4",
        "storageProvider": r.get("storage_provider", "local"),
        "storageKey": r.get("storage_key"),
        "createdAt": r.get("created_at"),
        "spec": r.get("spec"),
        "style": r.get("style"),
    }


def _with_source_url(record: dict[str, Any]) -> dict[str, Any]:
    """Copy of a clip record whose spec points the preview Player at the
    clip's own download path. That path proxies to R2 or local disk (see
    get_clip), so no expiring presigned URL ever reaches the client
    or the database."""
    out = dict(record)
    if out.get("spec"):
        out["spec"] = copy.deepcopy(out["spec"])
        out["spec"]["source"]["url"] = out["downloadUrl"]
    return out


def _find_clip(clip_id: str) -> dict[str, Any] | None:
    job_id = clip_id.rsplit("-", 1)[0]
    job = JOBS.get(job_id)
    if job is not None:
        for c in job.clips:
            if c["id"] == clip_id:
                return c
    row = db.get_clip(clip_id)
    return _clip_row_to_api(row) if row else None
```

In `_run_pipeline`, replace everything from `job.status = "cutting"` down to (and including) the `db.insert_clips([...])` block after `job.status = "done"` with:
```python
        job.status = "preparing"
        job.progress = {"stage": "preparing", "percent": 0, "note": f"0/{len(clips)} clips prepared"}
        _persist_job(job, whisper_model)

        groq_key = os.environ.get("GROQ_KEY") or None
        # The captions transcript has no word timings, so clip words come
        # from Groq; decide once per episode whether it needs the Roman
        # Urdu seed prompt (see transcript._detect_needs_roman_urdu_hint).
        prompt = None
        if tr.source == "captions" and groq_key:
            if transcript._detect_needs_roman_urdu_hint(meta.audio_path, groq_key):
                prompt = transcript.ROMAN_URDU_HINDI_SEED

        for i, c in enumerate(clips):
            def on_step(step: str, i: int = i) -> None:
                job.progress = {
                    "stage": "preparing",
                    "percent": i / len(clips) * 100.0,
                    "note": f"clip {i + 1}/{len(clips)}: {step}",
                }
                _persist_job(job, whisper_model, throttle=True)

            prepared = clipprep.prepare_clip(
                job_id=job.id, idx=i, clip=c,
                video_path=meta.video_path, video_duration=meta.duration,
                segments=tr.segments, transcript_source=tr.source, audio_path=meta.audio_path,
                clips_dir=CLIPS_DIR, models_dir=MODELS_DIR,
                groq_key=groq_key, prompt=prompt, on_step=on_step,
            )
            record = _clip_record(job.id, i, c, prepared)
            job.clips.append(record)
            # Saved per clip, so a failure later in the job doesn't lose
            # the clips already prepared.
            db.insert_clips([_clip_row(job.id, i, record)])

        job.status = "done"
        job.progress = {}
        _persist_job(job, whisper_model)
```

Replace the `status` endpoint:
```python
@app.get("/api/status/{job_id}")
def status(job_id: str) -> dict[str, Any]:
    check_id(job_id, "job id")
    job = JOBS.get(job_id)
    if job is not None:
        return {
            "id": job.id,
            "status": job.status,
            "error": job.error,
            "videoMeta": job.video_meta,
            "transcriptSource": job.transcript_source,
            "clips": [_with_source_url(c) for c in job.clips],
            "progress": job.progress,
        }

    # Not in memory (e.g. the backend restarted): rebuild it from Supabase.
    row = db.get_job(job_id)
    if row is None:
        raise HTTPException(404, "job not found")
    status_value, error = row["status"], row.get("error")
    if status_value not in ("done", "error"):
        # Its worker thread died with the old process; it will never finish.
        status_value, error = "error", "Processing was interrupted by a server restart. Please submit the video again."
    video_meta = None
    if row.get("video_title"):
        video_meta = {
            "title": row.get("video_title"),
            "channel": row.get("video_channel"),
            "duration": row.get("video_duration"),
            "durationLabel": ingest.duration_label(float(row.get("video_duration") or 0)),
        }
    return {
        "id": row["id"],
        "status": status_value,
        "error": error,
        "videoMeta": video_meta,
        "transcriptSource": row.get("transcript_source"),
        "clips": [_with_source_url(_clip_row_to_api(r)) for r in db.list_clips_for_job(job_id)],
        "progress": {},
    }
```

Replace the body of `list_all_clips` so it reuses the converter:
```python
    out = []
    for r in db.list_clips(limit):
        job_info = r.get("jobs") or {}
        record = _clip_row_to_api(r)
        record.update({
            "videoTitle": job_info.get("video_title"),
            "videoChannel": job_info.get("video_channel"),
            "videoUrl": job_info.get("url"),
        })
        out.append(record)
    return out
```
(keep its docstring.)

- [ ] **Step 7: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest -v`
Expected: all PASS.

- [ ] **Step 8: Apply the migration** — ask the user to run the new block of `supabase/schema.sql` in the Supabase SQL editor (it's idempotent). Don't run it yourself.

- [ ] **Step 9: Commit**
```bash
git add backend/pipeline/clipprep.py backend/main.py backend/db.py supabase/schema.sql tests/test_clipprep.py tests/test_status.py
git commit -m "Prepare per-clip specs in the pipeline and rebuild job status from Supabase"
```

---

### Task 9: Lambda render service

**Files:**
- Create: `backend/render.py`, `tests/test_render.py`
- Modify: `backend/db.py` (render persistence), `requirements.txt`

**Interfaces:**
- Consumes: `spec.ClipStyle`, `spec.style_hash`, `storage.render_key`, `db.upsert_render/get_render/find_render`.
- Produces:
  - `render.Render` dataclass with `.to_api() -> dict` (`{"id","clipId","status","progress","error","downloadUrl"}`), `.to_row()`, `Render.from_row(row)`
  - `render.RenderStore()` with `put(r)`, `get(id) -> Render | None`, `find(clip_id, style_hash) -> Render | None`, `by_status(status) -> list[Render]`
  - `render.RenderService(renderer, store, build_props, upload_output, now=time.time)` with `request(clip_id, style: ClipStyle) -> Render` and `refresh(render_id) -> Render | None`
    - `build_props(clip_id: str, style: dict) -> tuple[dict, float]` returns (`{"spec": ..., "style": ...}` input props, duration in seconds)
    - `upload_output(fileobj, key: str, download_name: str) -> None`
    - `renderer` duck type: `start(input_props: dict, duration_s: float) -> tuple[str, str]` (render id, bucket), `progress(render_id, bucket) -> dict` (`overallProgress`, `done`, `fatal`, `errors`, `outKey`), `fetch_output(bucket, key)`, `delete_output(bucket, key)`
  - `render.LambdaRenderer(region, serve_url, function_name, access_key, secret_key)`
  - `render.lambda_config() -> dict | None`, `render.build_service(build_props, upload_output) -> RenderService | None`, `render.check_versions(package_json_path: str, function_name: str | None) -> list[str]`
  - `db.upsert_render(row)`, `db.get_render(render_id) -> dict | None`, `db.find_render(clip_id, style_hash) -> dict | None`

- [ ] **Step 1: Dependency** — append to `requirements.txt`:
```
# Must stay exactly equal to the remotion/@remotion/* versions in renderer/package.json.
remotion-lambda==4.0.527
```
Run: `./.venv/Scripts/pip install -r requirements-dev.txt`

- [ ] **Step 2: Write the failing tests** — `tests/test_render.py`:
```python
import io
import json

import pytest

from backend import render
from backend.spec import ClipStyle


class FakeRenderer:
    def __init__(self):
        self.started = []
        self.progress_value = {"overallProgress": 0.4, "done": False, "fatal": False, "errors": [], "outKey": None}
        self.start_error = None
        self.deleted = []

    def start(self, input_props, duration_s):
        if self.start_error:
            raise self.start_error
        self.started.append((input_props, duration_s))
        return f"lambda-{len(self.started)}", "remotionlambda-bucket"

    def progress(self, render_id, bucket):
        return self.progress_value

    def fetch_output(self, bucket, key):
        return io.BytesIO(b"mp4")

    def delete_output(self, bucket, key):
        self.deleted.append((bucket, key))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def setup():
    fake = FakeRenderer()
    uploads = []
    clock = Clock()
    svc = render.RenderService(
        fake, render.RenderStore(),
        build_props=lambda clip_id, style: ({"spec": {"clipId": clip_id}, "style": style}, 12.0),
        upload_output=lambda body, key, name: uploads.append((key, name, body.read())),
        now=clock,
    )
    return svc, fake, uploads, clock


def test_request_starts_render(setup):
    svc, fake, _, _ = setup
    r = svc.request("job1-0", ClipStyle(layout="fit"))
    assert r.status == "rendering"
    assert fake.started[0][1] == 12.0
    assert fake.started[0][0]["style"]["layout"] == "fit"


def test_identical_style_reuses_render(setup):
    svc, fake, _, _ = setup
    a = svc.request("job1-0", ClipStyle(layout="fit"))
    b = svc.request("job1-0", ClipStyle(layout="fit"))
    c = svc.request("job1-0", ClipStyle(layout="fit", captionPreset="pop"))
    assert a.id == b.id
    assert c.id != a.id
    assert len(fake.started) == 2


def test_at_most_two_active(setup):
    svc, fake, _, _ = setup
    renders = [svc.request(f"job1-{i}", ClipStyle(layout="fit")) for i in range(3)]
    assert [r.status for r in renders] == ["rendering", "rendering", "queued"]
    fake.progress_value = {"overallProgress": 1.0, "done": True, "fatal": False, "errors": [], "outKey": "renders/x/out.mp4"}
    svc.refresh(renders[0].id)  # finishing one frees a slot
    assert renders[2].status == "rendering"


def test_done_copies_to_r2_and_deletes_s3(setup):
    svc, fake, uploads, _ = setup
    r = svc.request("job1-0", ClipStyle(layout="fit"))
    assert svc.refresh(r.id).progress == 40.0
    fake.progress_value = {"overallProgress": 1.0, "done": True, "fatal": False, "errors": [], "outKey": "renders/x/out.mp4"}
    r = svc.refresh(r.id)
    assert r.status == "done" and r.progress == 100.0
    assert r.storage_key == f"renders/{r.id}.mp4"
    assert uploads == [(f"renders/{r.id}.mp4", "highlyte-job1-0.mp4", b"mp4")]
    assert fake.deleted == [("remotionlambda-bucket", "renders/x/out.mp4")]
    assert r.to_api()["downloadUrl"] == f"/api/renders/{r.id}/file"


def test_fatal_error_is_reported(setup):
    svc, fake, _, _ = setup
    r = svc.request("job1-0", ClipStyle(layout="fit"))
    fake.progress_value = {"overallProgress": 0.2, "done": False, "fatal": True,
                           "errors": [{"message": "Video could not be decoded"}], "outKey": None}
    r = svc.refresh(r.id)
    assert r.status == "error" and "could not be decoded" in r.error


def test_stuck_render_times_out(setup):
    svc, _, _, clock = setup
    r = svc.request("job1-0", ClipStyle(layout="fit"))
    clock.t += render.STUCK_AFTER_S + 1
    r = svc.refresh(r.id)
    assert r.status == "error" and r.error == "timed out"


def test_throttled_start_stays_queued_then_retries(setup):
    svc, fake, _, clock = setup
    fake.start_error = RuntimeError("TooManyRequestsException: Rate Exceeded")
    r = svc.request("job1-0", ClipStyle(layout="fit"))
    assert r.status == "queued" and r.attempts == 1
    fake.start_error = None
    svc.refresh(r.id)
    assert r.status == "queued"  # still backing off
    clock.t += render.THROTTLE_BACKOFF_S + 1
    assert svc.refresh(r.id).status == "rendering"


def test_other_start_errors_fail(setup):
    svc, fake, _, _ = setup
    fake.start_error = RuntimeError("clip source is not in R2")
    r = svc.request("job1-0", ClipStyle(layout="fit"))
    assert r.status == "error" and "not in R2" in r.error


def test_lambda_config_requires_all_values(monkeypatch):
    assert render.lambda_config() is None
    for key, value in {
        "REMOTION_AWS_ACCESS_KEY_ID": "a", "REMOTION_AWS_SECRET_ACCESS_KEY": "b", "REMOTION_AWS_REGION": "ap-south-1",
        "REMOTION_FUNCTION_NAME": "remotion-render-4-0-527-mem2048mb-disk2048mb-240sec",
        "REMOTION_SERVE_URL": "https://example/sites/highlyte/index.html",
    }.items():
        monkeypatch.setenv(key, value)
    assert render.lambda_config()["region"] == "ap-south-1"


def test_check_versions(tmp_path):
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"dependencies": {"remotion": "4.0.527"}}))
    assert render.check_versions(str(pkg), "remotion-render-4-0-527-mem2048mb-disk2048mb-240sec") == []
    pkg.write_text(json.dumps({"dependencies": {"remotion": "4.0.500"}}))
    problems = render.check_versions(str(pkg), "remotion-render-4-0-400-mem2048mb")
    assert len(problems) == 2
```

- [ ] **Step 3: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_render.py -v`
Expected: FAIL — `cannot import name 'render'`.

- [ ] **Step 4: Implement `backend/db.py` render helpers** (append):
```python
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
```

- [ ] **Step 5: Implement `backend/render.py`**
```python
"""Rendering clips to mp4 on AWS Lambda with Remotion.

The Remotion composition lives in renderer/ and is deployed as a "site"
to S3; FastAPI starts renders with Remotion's Python client and polls
their progress. Finished files are copied into R2 (the permanent clip
library, free to download from) and the S3 copy is deleted.

There is no background worker: renders advance whenever someone polls
/api/renders/{id} (the frontend does, every 2 s, while a render is
running). At most MAX_ACTIVE renders run at once — new AWS accounts often
have a 10-concurrent-Lambda limit, and each render uses about 5.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from . import db, storage
from .spec import ClipStyle, style_hash

FPS = 30
MAX_ACTIVE = 2
STUCK_AFTER_S = 30 * 60
THROTTLE_MAX_ATTEMPTS = 5
THROTTLE_BACKOFF_S = 15
THROTTLE_MARKERS = ("TooManyRequests", "Rate Exceeded", "ConcurrentInvocationLimitExceeded", "Throttl")
LIVE_STATUSES = ("queued", "rendering", "done")


@dataclass
class Render:
    id: str
    clip_id: str
    style: dict[str, Any]
    style_hash: str
    status: str = "queued"  # queued|rendering|done|error
    progress: float = 0.0
    lambda_render_id: str | None = None
    lambda_bucket: str | None = None
    storage_key: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    attempts: int = 0
    retry_at: float = 0.0

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "clipId": self.clip_id,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "downloadUrl": f"/api/renders/{self.id}/file" if self.status == "done" else None,
        }

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "clip_id": self.clip_id,
            "style": self.style,
            "style_hash": self.style_hash,
            "status": self.status,
            "progress": self.progress,
            "lambda_render_id": self.lambda_render_id,
            "lambda_bucket": self.lambda_bucket,
            "storage_key": self.storage_key,
            "error": self.error,
            "started_epoch": self.started_at,
            "attempts": self.attempts,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Render":
        return cls(
            id=row["id"],
            clip_id=row["clip_id"],
            style=row["style"],
            style_hash=row["style_hash"],
            status=row["status"],
            progress=float(row.get("progress") or 0),
            lambda_render_id=row.get("lambda_render_id"),
            lambda_bucket=row.get("lambda_bucket"),
            storage_key=row.get("storage_key"),
            error=row.get("error"),
            started_at=row.get("started_epoch"),
            attempts=int(row.get("attempts") or 0),
        )


class RenderStore:
    """In-memory renders, written through to Supabase when configured, so
    the app works without Supabase and survives restarts with it."""

    def __init__(self) -> None:
        self._items: dict[str, Render] = {}

    def put(self, r: Render) -> None:
        self._items[r.id] = r
        db.upsert_render(r.to_row())

    def get(self, render_id: str) -> Render | None:
        r = self._items.get(render_id)
        if r is None:
            row = db.get_render(render_id)
            if row is not None:
                r = Render.from_row(row)
                self._items[r.id] = r
        return r

    def find(self, clip_id: str, hash_value: str) -> Render | None:
        for r in sorted(self._items.values(), key=lambda r: r.created_at, reverse=True):
            if r.clip_id == clip_id and r.style_hash == hash_value and r.status in LIVE_STATUSES:
                return r
        row = db.find_render(clip_id, hash_value)
        if row is None:
            return None
        r = Render.from_row(row)
        self._items[r.id] = r
        return r

    def by_status(self, status: str) -> list[Render]:
        return sorted((r for r in self._items.values() if r.status == status), key=lambda r: r.created_at)


class RenderService:
    def __init__(
        self,
        renderer: Any,
        store: RenderStore,
        build_props: Callable[[str, dict[str, Any]], tuple[dict[str, Any], float]],
        upload_output: Callable[[Any, str, str], None],
        now: Callable[[], float] = time.time,
    ) -> None:
        self.renderer = renderer
        self.store = store
        self.build_props = build_props
        self.upload_output = upload_output
        self.now = now
        self._lock = threading.Lock()

    def request(self, clip_id: str, style: ClipStyle) -> Render:
        hash_value = style_hash(style)
        with self._lock:
            existing = self.store.find(clip_id, hash_value)
            if existing is not None:
                return existing
            r = Render(
                id=uuid.uuid4().hex[:12], clip_id=clip_id, style=style.model_dump(),
                style_hash=hash_value, created_at=self.now(),
            )
            self.store.put(r)
            self._pump()
            return r

    def refresh(self, render_id: str) -> Render | None:
        with self._lock:
            r = self.store.get(render_id)
            if r is None:
                return None
            if r.status == "rendering":
                self._poll(r)
            self._pump()
            return r

    def _pump(self) -> None:
        active = len(self.store.by_status("rendering"))
        for r in self.store.by_status("queued"):
            if active >= MAX_ACTIVE:
                break
            if r.retry_at > self.now():
                continue
            if self._start(r):
                active += 1

    def _start(self, r: Render) -> bool:
        try:
            props, duration_s = self.build_props(r.clip_id, r.style)
            lambda_id, bucket = self.renderer.start(props, duration_s)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if any(m in msg for m in THROTTLE_MARKERS) and r.attempts + 1 < THROTTLE_MAX_ATTEMPTS:
                r.attempts += 1
                r.retry_at = self.now() + THROTTLE_BACKOFF_S * r.attempts
                self.store.put(r)
                return False
            r.status, r.error = "error", msg[:500]
            self.store.put(r)
            return False
        r.status = "rendering"
        r.lambda_render_id, r.lambda_bucket = lambda_id, bucket
        r.started_at = self.now()
        self.store.put(r)
        return True

    def _poll(self, r: Render) -> None:
        if r.started_at is not None and self.now() - r.started_at > STUCK_AFTER_S:
            r.status, r.error = "error", "timed out"
            self.store.put(r)
            return
        try:
            p = self.renderer.progress(r.lambda_render_id, r.lambda_bucket)
        except Exception as e:  # noqa: BLE001
            print(f"[render] progress check failed for {r.id}, will retry: {e}")
            return
        if p["fatal"]:
            messages = [str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in p["errors"]]
            r.status, r.error = "error", ("; ".join(messages) or "render failed")[:500]
            self.store.put(r)
            return
        r.progress = round(float(p["overallProgress"]) * 100, 1)
        if p["done"]:
            key = storage.render_key(r.id)
            body = self.renderer.fetch_output(r.lambda_bucket, p["outKey"])
            self.upload_output(body, key, f"highlyte-{r.clip_id}.mp4")
            self.renderer.delete_output(r.lambda_bucket, p["outKey"])
            r.status, r.progress, r.storage_key = "done", 100.0, key
        self.store.put(r)


class LambdaRenderer:
    """Thin wrapper over Remotion's Python client plus the S3 calls needed
    to move the output into R2."""

    def __init__(self, region: str, serve_url: str, function_name: str, access_key: str, secret_key: str) -> None:
        import boto3
        from remotion_lambda import RemotionClient

        self.session = boto3.Session(
            aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region,
        )
        self.client = RemotionClient(
            region=region, serve_url=serve_url, function_name=function_name, session=self.session,
        )
        self.s3 = self.session.client("s3")

    def start(self, input_props: dict[str, Any], duration_s: float) -> tuple[str, str]:
        from remotion_lambda import Privacy, RenderMediaParams

        frames = max(1, round(duration_s * FPS))
        params = RenderMediaParams(
            composition="Clip",
            input_props=input_props,
            codec="h264",
            crf=20,
            privacy=Privacy.PRIVATE,
            # About 4 renderer Lambdas per clip (plus the orchestrator), so
            # two concurrent renders fit a new account's 10-Lambda limit.
            frames_per_lambda=max(60, math.ceil(frames / 4)),
            max_retries=1,
        )
        resp = self.client.render_media_on_lambda(params)
        if resp is None:
            raise RuntimeError("Lambda returned no render id")
        return resp.render_id, resp.bucket_name

    def progress(self, render_id: str, bucket: str) -> dict[str, Any]:
        p = self.client.get_render_progress(render_id=render_id, bucket_name=bucket)
        if p is None:
            raise RuntimeError("no progress response")
        return {
            "overallProgress": p.overallProgress,
            "done": p.done,
            "fatal": p.fatalErrorEncountered,
            "errors": p.errors,
            "outKey": p.outKey,
        }

    def fetch_output(self, bucket: str, key: str):
        return self.s3.get_object(Bucket=bucket, Key=key)["Body"]

    def delete_output(self, bucket: str, key: str) -> None:
        self.s3.delete_object(Bucket=bucket, Key=key)


def lambda_config() -> dict[str, str] | None:
    values = {
        "access_key": os.environ.get("REMOTION_AWS_ACCESS_KEY_ID"),
        "secret_key": os.environ.get("REMOTION_AWS_SECRET_ACCESS_KEY"),
        "region": os.environ.get("REMOTION_AWS_REGION"),
        "function_name": os.environ.get("REMOTION_FUNCTION_NAME"),
        "serve_url": os.environ.get("REMOTION_SERVE_URL"),
    }
    if not all(values.values()):
        return None
    return values  # type: ignore[return-value]


def build_service(
    build_props: Callable[[str, dict[str, Any]], tuple[dict[str, Any], float]],
    upload_output: Callable[[Any, str, str], None],
) -> RenderService | None:
    """None unless both Lambda and R2 are configured — renders need R2 for
    their source segment and their output."""
    cfg = lambda_config()
    if cfg is None or not storage.is_enabled():
        return None
    return RenderService(LambdaRenderer(**cfg), RenderStore(), build_props, upload_output)


def check_versions(package_json_path: str, function_name: str | None) -> list[str]:
    """Remotion requires the Python client, the npm packages the site was
    built with, and the deployed function to be the exact same version."""
    from remotion_lambda import VERSION

    problems: list[str] = []
    try:
        with open(package_json_path, encoding="utf-8") as f:
            npm_version = json.load(f).get("dependencies", {}).get("remotion")
    except OSError:
        npm_version = None
    if npm_version != VERSION:
        problems.append(f"renderer/package.json remotion is {npm_version}, Python remotion-lambda is {VERSION}")
    if function_name and VERSION.replace(".", "-") not in function_name:
        problems.append(f"Lambda function {function_name} was not deployed with Remotion {VERSION}")
    return problems
```

- [ ] **Step 6: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest tests/test_render.py -v`
Expected: 10 PASS.

- [ ] **Step 7: Commit**
```bash
git add backend/render.py backend/db.py tests/test_render.py requirements.txt
git commit -m "Add Lambda render service with queueing, dedupe and R2 copy"
```

---

### Task 10: Style and render API endpoints

**Files:**
- Modify: `backend/main.py`
- Test: `tests/test_render_api.py`

**Interfaces:**
- Consumes: `render.build_service`, `render.check_versions`, `render.RenderService.request/refresh`, `storage.clip_url`, `storage.upload_fileobj`, `storage.open_object`, `spec.ClipStyle`, `main._find_clip`.
- Produces (HTTP):
  - `GET /api/health` → adds `"rendering": bool`
  - `PATCH /api/clips/{clip_id}/style` body `ClipStyle` → saved style dict
  - `POST /api/clips/{clip_id}/render` body `ClipStyle` → `Render.to_api()`; 404 unknown clip, 409 no spec or not in R2, 503 rendering not configured
  - `GET /api/renders/{render_id}` → `Render.to_api()`
  - `GET /api/renders/{render_id}/file` → 307 to R2
  - `GET /api/renders/zip?ids=a,b` → `application/zip`
  - `main.RENDER_SERVICE: RenderService | None`, `main._build_props(clip_id, style) -> tuple[dict, float]`

- [ ] **Step 1: Write the failing tests** — `tests/test_render_api.py`:
```python
import io
import json
import os
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend import main, render
from backend.spec import ClipSpec, default_style

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec.json")
JOB_ID = "abc123def456"
CLIP_ID = f"{JOB_ID}-0"

client = TestClient(main.app)


class FakeRenderer:
    def __init__(self):
        self.done = False
        self.props = None

    def start(self, input_props, duration_s):
        self.props = input_props
        return "lambda-1", "bucket"

    def progress(self, render_id, bucket):
        return {"overallProgress": 1.0 if self.done else 0.5, "done": self.done, "fatal": False,
                "errors": [], "outKey": "out.mp4"}

    def fetch_output(self, bucket, key):
        return io.BytesIO(b"mp4")

    def delete_output(self, bucket, key):
        pass


@pytest.fixture
def env(monkeypatch):
    with open(FIXTURE, encoding="utf-8") as f:
        spec = ClipSpec.model_validate(json.load(f)).model_copy(update={"clipId": CLIP_ID})
    record = {
        "id": CLIP_ID, "start": 10.0, "end": 18.0, "text": "t", "tag": "Key insight", "score": 8.2,
        "hookTitle": spec.hookTitle, "viralityScore": spec.viralityScore,
        "downloadUrl": f"/api/clips/{JOB_ID}/clip_0.mp4", "storageProvider": "r2",
        "storageKey": f"{JOB_ID}/clip_0.mp4",
        "spec": spec.model_dump(), "style": default_style(spec).model_dump(),
    }
    main.JOBS[JOB_ID] = main.Job(id=JOB_ID, url="u", status="done", clips=[record])
    fake = FakeRenderer()
    uploads = {}
    svc = render.RenderService(fake, render.RenderStore(), main._build_props,
                               lambda body, key, name: uploads.__setitem__(key, body.read()))
    monkeypatch.setattr(main, "RENDER_SERVICE", svc)
    monkeypatch.setattr(main.storage, "clip_url", lambda key: f"https://r2.example/{key}")
    monkeypatch.setattr(main.storage, "open_object", lambda key: io.BytesIO(uploads[key]))
    yield record, fake
    main.JOBS.pop(JOB_ID, None)


STYLE = {"layout": "follow", "captionPreset": "pop", "showHook": True, "hookTitle": "Edited",
         "accent": "#00FFAA", "captionPosition": "lower"}


def test_health_reports_rendering(env):
    assert client.get("/api/health").json()["rendering"] is True


def test_patch_style_saves(env):
    record, _ = env
    r = client.patch(f"/api/clips/{CLIP_ID}/style", json=STYLE)
    assert r.status_code == 200
    assert record["style"]["captionPreset"] == "pop"


def test_patch_style_validates(env):
    assert client.patch(f"/api/clips/{CLIP_ID}/style", json={**STYLE, "accent": "red"}).status_code == 422


def test_render_flow(env):
    _, fake = env
    r = client.post(f"/api/clips/{CLIP_ID}/render", json=STYLE)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rendering"
    assert fake.props["spec"]["source"]["url"] == f"https://r2.example/{JOB_ID}/clip_0.mp4"
    assert fake.props["style"]["hookTitle"] == "Edited"

    fake.done = True
    body = client.get(f"/api/renders/{body['id']}").json()
    assert body["status"] == "done"

    f = client.get(body["downloadUrl"], follow_redirects=False)
    assert f.status_code == 307
    assert f.headers["location"] == f"https://r2.example/renders/{body['id']}.mp4"

    z = client.get(f"/api/renders/zip?ids={body['id']}")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert names == [f"highlyte-{CLIP_ID}.mp4"]


def test_render_requires_r2_source(env):
    record, _ = env
    record["storageKey"] = None
    assert client.post(f"/api/clips/{CLIP_ID}/render", json=STYLE).status_code == 409


def test_render_unknown_clip(env):
    assert client.post("/api/clips/abc123def456-9/render", json=STYLE).status_code == 404


def test_render_not_configured(env, monkeypatch):
    monkeypatch.setattr(main, "RENDER_SERVICE", None)
    assert client.post(f"/api/clips/{CLIP_ID}/render", json=STYLE).status_code == 503


def test_zip_rejects_unfinished_and_bad_ids(env):
    assert client.get("/api/renders/zip?ids=../x").status_code == 400
    assert client.get("/api/renders/zip?ids=nope00000000").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_render_api.py -v`
Expected: FAIL — `module 'backend.main' has no attribute '_build_props'` (fixture error).

- [ ] **Step 3: Implement in `backend/main.py`**

Imports: add `import tempfile`, `import zipfile`; change the fastapi imports to
```python
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
```
and `from . import db, render, storage` and `from .spec import ClipStyle, default_style`.

Add after the `app.add_middleware(...)` call:
```python
RENDERER_PACKAGE_JSON = os.path.join(BASE_DIR, "renderer", "package.json")
MAX_ZIP_RENDERS = 20
```

Add after `_find_clip`:
```python
def _build_props(clip_id: str, style: dict[str, Any]) -> tuple[dict[str, Any], float]:
    """Remotion input props for a Lambda render. Lambda can't reach this
    machine, so the source must be a presigned R2 URL (fresh, since those
    expire)."""
    record = _find_clip(clip_id)
    if record is None or not record.get("spec"):
        raise RuntimeError("clip has no spec")
    if not record.get("storageKey"):
        raise RuntimeError("clip source is not in R2")
    spec = copy.deepcopy(record["spec"])
    spec["source"]["url"] = storage.clip_url(record["storageKey"])
    return {"spec": spec, "style": style}, spec["end"] - spec["start"]


RENDER_SERVICE = render.build_service(_build_props, storage.upload_fileobj)
if RENDER_SERVICE is not None:
    for _problem in render.check_versions(RENDERER_PACKAGE_JSON, os.environ.get("REMOTION_FUNCTION_NAME")):
        print(f"[render] VERSION MISMATCH: {_problem}")


def _clip_for_style(clip_id: str) -> dict[str, Any]:
    check_id(clip_id, "clip id")
    record = _find_clip(clip_id)
    if record is None:
        raise HTTPException(404, "clip not found")
    if not record.get("spec"):
        raise HTTPException(409, "This clip was made before vertical clips existed. Re-run the video to get one.")
    return record


def _save_style(record: dict[str, Any], style: ClipStyle) -> dict[str, Any]:
    record["style"] = style.model_dump()
    db.update_clip(record["id"], {"style": record["style"]})
    return record["style"]
```

Change `health`:
```python
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "supabase": db.is_enabled(), "rendering": RENDER_SERVICE is not None}
```

Add the endpoints (after `get_clip`):
```python
@app.patch("/api/clips/{clip_id}/style")
def update_style(clip_id: str, style: ClipStyle = Body(...)) -> dict[str, Any]:
    return _save_style(_clip_for_style(clip_id), style)


@app.post("/api/clips/{clip_id}/render")
def start_render(clip_id: str, style: ClipStyle = Body(...)) -> dict[str, Any]:
    record = _clip_for_style(clip_id)
    if RENDER_SERVICE is None:
        raise HTTPException(503, "Rendering not configured")
    if not record.get("storageKey"):
        raise HTTPException(409, "This clip's source isn't in R2, which Lambda rendering needs.")
    _save_style(record, style)
    return RENDER_SERVICE.request(clip_id, style).to_api()


def _get_render(render_id: str) -> render.Render:
    check_id(render_id, "render id")
    if RENDER_SERVICE is None:
        raise HTTPException(503, "Rendering not configured")
    r = RENDER_SERVICE.refresh(render_id)
    if r is None:
        raise HTTPException(404, "render not found")
    return r


# Declared before /api/renders/{render_id} so "zip" isn't taken as an id.
@app.get("/api/renders/zip")
def renders_zip(ids: str = Query(...)) -> StreamingResponse:
    render_ids = [i for i in ids.split(",") if i][:MAX_ZIP_RENDERS]
    renders = [_get_render(i) for i in render_ids]
    if not renders or any(r.status != "done" for r in renders):
        raise HTTPException(409, "all renders must be finished")
    # Spools to disk past 64 MB; mp4s are already compressed, so store them as-is.
    buf = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for r in renders:
            with zf.open(f"highlyte-{r.clip_id}.mp4", "w") as dest:
                src = storage.open_object(r.storage_key)
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    dest.write(chunk)
    buf.seek(0)

    def stream():
        try:
            yield from iter(lambda: buf.read(1024 * 1024), b"")
        finally:
            buf.close()

    return StreamingResponse(
        stream(), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="highlyte-clips.zip"'},
    )


@app.get("/api/renders/{render_id}")
def get_render(render_id: str) -> dict[str, Any]:
    return _get_render(render_id).to_api()


@app.get("/api/renders/{render_id}/file")
def get_render_file(render_id: str):
    r = _get_render(render_id)
    if r.status != "done" or not r.storage_key:
        raise HTTPException(409, "render not finished")
    url = storage.clip_url(r.storage_key)
    if url is None:
        raise HTTPException(503, "R2 not configured")
    return RedirectResponse(url)
```

Note `test_zip_rejects_unfinished_and_bad_ids` expects 404 for an unknown id: `_get_render` raises 404 before the "all finished" check. Good.

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest -v`
Expected: all PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/main.py tests/test_render_api.py
git commit -m "Add clip style, render, download and zip endpoints"
```

---

### Task 11: Renderer package scaffold and zod schema

**Files:**
- Create: `renderer/package.json` (via npm), `renderer/tsconfig.json`, `renderer/remotion.config.ts`, `renderer/src/index.ts`, `renderer/src/Root.tsx`, `renderer/src/constants.ts`, `renderer/src/schema.ts`, `renderer/src/schema.test.ts`, `renderer/src/ClipComposition.tsx` (placeholder body replaced in Task 13)
- Modify: `.gitignore`

**Interfaces:**
- Produces (TypeScript):
  - `constants.ts`: `FPS = 30`, `OUT_W = 1080`, `OUT_H = 1920`, `durationInFrames(spec: {start: number; end: number}): number`
  - `schema.ts`: `layoutSchema`, `wordSchema`, `trackPointSchema`, `clipSpecSchema`, `clipStyleSchema`, `clipPropsSchema`; types `Layout`, `Word`, `TrackPoint`, `ClipSpec`, `ClipStyle`, `ClipProps`
  - `ClipComposition.tsx`: `export const ClipComposition: React.FC<ClipProps>`
  - `Root.tsx`: composition id `Clip`

- [ ] **Step 1: Create the package**
```bash
mkdir -p renderer/src && cd renderer && npm init -y
npm install --save-exact remotion@4.0.527 @remotion/cli@4.0.527 @remotion/lambda@4.0.527 @remotion/google-fonts@4.0.527 react@19.3.0 react-dom@19.3.0 zod@4.5.4
npm install --save-dev --save-exact typescript vitest@5.0.1 @types/react @types/react-dom @types/node
```
Then edit `renderer/package.json` so it contains (keep the installed dependency blocks exactly as npm wrote them):
```json
{
  "name": "highlyte-renderer",
  "private": true,
  "type": "module",
  "scripts": {
    "studio": "remotion studio src/index.ts",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "fixture:video": "node scripts/make-fixture-video.mjs",
    "stills": "node scripts/stills.mjs",
    "deploy:functions": "remotion lambda functions deploy --memory=2048 --disk=2048 --timeout=240",
    "deploy:site": "remotion lambda sites create src/index.ts --site-name=highlyte"
  }
}
```
Remove the `main`, `keywords`, `author`, `license`, `description` fields `npm init` added.

Append to `.gitignore`:
```
renderer/node_modules/
renderer/out/
renderer/public/fixture.mp4
```

- [ ] **Step 2: Config files**

`renderer/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "esModuleInterop": true,
    "noEmit": true,
    "lib": ["DOM", "ES2022"]
  },
  "include": ["src", "remotion.config.ts"]
}
```

`renderer/remotion.config.ts`:
```ts
import { Config } from '@remotion/cli/config'

Config.setVideoImageFormat('jpeg')
Config.setOverwriteOutput(true)
```

- [ ] **Step 3: Write the failing test** — `renderer/src/schema.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import fixture from './__fixtures__/clip-spec.json'
import { clipPropsSchema, clipSpecSchema, clipStyleSchema } from './schema'
import { durationInFrames } from './constants'

const style = {
  layout: 'speaker', captionPreset: 'karaoke', showHook: true,
  hookTitle: 'Hook', accent: '#FFD400', captionPosition: 'lower',
}

describe('schema', () => {
  it('accepts the Python-generated fixture spec', () => {
    const spec = clipSpecSchema.parse(fixture)
    expect(spec.reframe.faces).toHaveLength(2)
  })

  it('accepts full props', () => {
    expect(clipPropsSchema.parse({ spec: fixture, style }).style.layout).toBe('speaker')
  })

  it('rejects a bad accent and an unknown preset', () => {
    expect(clipStyleSchema.safeParse({ ...style, accent: 'red' }).success).toBe(false)
    expect(clipStyleSchema.safeParse({ ...style, captionPreset: 'neon' }).success).toBe(false)
  })

  it('computes duration in frames', () => {
    expect(durationInFrames({ start: 1, end: 9 })).toBe(240)
    expect(durationInFrames({ start: 1, end: 1 })).toBe(1)
  })
})
```

- [ ] **Step 4: Run to verify failure**

Run: `cd renderer && npm test`
Expected: FAIL — cannot resolve `./schema`.

- [ ] **Step 5: Implement**

`renderer/src/constants.ts`:
```ts
export const FPS = 30
export const OUT_W = 1080
export const OUT_H = 1920

export const durationInFrames = (spec: { start: number; end: number }): number =>
  Math.max(1, Math.round((spec.end - spec.start) * FPS))
```

`renderer/src/schema.ts`:
```ts
// Mirrors backend/spec.py. The Python-generated fixture in __fixtures__ is
// parsed by schema.test.ts, so a change on one side that the other side
// doesn't know about fails a test instead of a render.
import { z } from 'zod'

export const layoutSchema = z.enum(['follow', 'speaker', 'split', 'fit'])

export const wordSchema = z.object({
  text: z.string(),
  start: z.number(),
  end: z.number(),
  emphasis: z.boolean().optional(),
})

export const trackPointSchema = z.object({
  t: z.number(),
  cx: z.number(),
  cy: z.number(),
  w: z.number(),
  h: z.number(),
})

export const clipSpecSchema = z.object({
  version: z.literal(1),
  clipId: z.string(),
  source: z.object({
    url: z.string(),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    fps: z.number().positive(),
  }),
  start: z.number().min(0),
  end: z.number(),
  words: z.array(wordSchema),
  wordsApprox: z.boolean(),
  hookTitle: z.string().nullable(),
  viralityScore: z.number().min(0).max(10),
  reframe: z.object({
    auto: layoutSchema,
    faces: z.array(z.object({ id: z.number().int(), track: z.array(trackPointSchema) })),
    speakerTimeline: z.array(z.object({ t: z.number(), faceId: z.number().int() })),
  }),
})

export const clipStyleSchema = z.object({
  layout: layoutSchema,
  captionPreset: z.enum(['karaoke', 'pop', 'clean']),
  showHook: z.boolean(),
  hookTitle: z.string().nullable(),
  accent: z.string().regex(/^#[0-9A-Fa-f]{6}$/),
  captionPosition: z.enum(['lower', 'middle']),
})

export const clipPropsSchema = z.object({ spec: clipSpecSchema, style: clipStyleSchema })

export type Layout = z.infer<typeof layoutSchema>
export type Word = z.infer<typeof wordSchema>
export type TrackPoint = z.infer<typeof trackPointSchema>
export type ClipSpec = z.infer<typeof clipSpecSchema>
export type ClipStyle = z.infer<typeof clipStyleSchema>
export type ClipProps = z.infer<typeof clipPropsSchema>
```

`renderer/src/ClipComposition.tsx` (placeholder; Task 13 replaces the body):
```tsx
import { AbsoluteFill } from 'remotion'
import type { ClipProps } from './schema'

export const ClipComposition: React.FC<ClipProps> = () => <AbsoluteFill style={{ backgroundColor: 'black' }} />
```

`renderer/src/Root.tsx`:
```tsx
import { Composition } from 'remotion'
import { ClipComposition } from './ClipComposition'
import { FPS, OUT_H, OUT_W, durationInFrames } from './constants'
import fixture from './__fixtures__/clip-spec.json'
import { clipPropsSchema, type ClipProps } from './schema'

const defaultProps = clipPropsSchema.parse({
  spec: fixture,
  style: {
    layout: fixture.reframe.auto,
    captionPreset: 'karaoke',
    showHook: true,
    hookTitle: fixture.hookTitle,
    accent: '#FFD400',
    captionPosition: 'lower',
  },
})

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Clip"
    component={ClipComposition}
    schema={clipPropsSchema}
    width={OUT_W}
    height={OUT_H}
    fps={FPS}
    durationInFrames={durationInFrames(defaultProps.spec)}
    defaultProps={defaultProps}
    calculateMetadata={({ props }: { props: ClipProps }) => ({ durationInFrames: durationInFrames(props.spec) })}
  />
)
```

`renderer/src/index.ts`:
```ts
import { registerRoot } from 'remotion'
import { RemotionRoot } from './Root'

registerRoot(RemotionRoot)
```

- [ ] **Step 6: Run to verify pass**

Run: `cd renderer && npm test && npm run typecheck`
Expected: 4 tests PASS; typecheck exits 0. If `schema={clipPropsSchema}` fails to typecheck against Remotion's zod types, switch `schema.ts` to `import { z } from 'zod/v3'` (Remotion 4.0.527 accepts both) and re-run.

- [ ] **Step 7: Commit**
```bash
git add renderer/package.json renderer/package-lock.json renderer/tsconfig.json renderer/remotion.config.ts renderer/src .gitignore
git commit -m "Scaffold Remotion renderer package with ClipSpec zod schema"
```

---

### Task 12: Renderer maths (track sampling, crops, speakers, caption pages)

**Files:**
- Create: `renderer/src/lib/track.ts`, `renderer/src/lib/crop.ts`, `renderer/src/lib/speaker.ts`, `renderer/src/captions/paginate.ts`, and their tests `renderer/src/lib/track.test.ts`, `renderer/src/lib/crop.test.ts`, `renderer/src/lib/speaker.test.ts`, `renderer/src/captions/paginate.test.ts`

**Interfaces:**
- Produces:
  - `track.ts`: `HOLD_S = 2`, `EASE_S = 0.5`, `sampleTrack(track: TrackPoint[], t: number): { cx: number; cy: number }`
  - `crop.ts`: `type Crop = { x: number; y: number; w: number; h: number }`, `cropWindow(srcW: number, srcH: number, cx: number, aspect: number): Crop` (source pixels; `aspect` = output width / height)
  - `speaker.ts`: `activeFace(timeline: { t: number; faceId: number }[], t: number): number | null`
  - `paginate.ts`: `PAUSE_BREAK_S = 0.4`, `type Page = { start: number; end: number; words: Word[] }`, `paginate(words: Word[], maxWords: number, maxChars?: number): Page[]`, `pageAt(pages: Page[], t: number, linger?: number): Page | null`

- [ ] **Step 1: Write the failing tests**

`renderer/src/lib/track.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { sampleTrack } from './track'

const pt = (t: number, cx: number) => ({ t, cx, cy: 0.4, w: 0.1, h: 0.2 })

describe('sampleTrack', () => {
  it('returns centre for an empty track', () => {
    expect(sampleTrack([], 3)).toEqual({ cx: 0.5, cy: 0.5 })
  })
  it('interpolates between close samples', () => {
    expect(sampleTrack([pt(0, 0.2), pt(1, 0.4)], 0.5).cx).toBeCloseTo(0.3)
  })
  it('holds the last position during a short gap, then eases to centre', () => {
    const track = [pt(0, 0.2), pt(10, 0.8)]
    expect(sampleTrack(track, 1.5).cx).toBeCloseTo(0.2)
    expect(sampleTrack(track, 2.25).cx).toBeCloseTo(0.35)
    expect(sampleTrack(track, 5).cx).toBeCloseTo(0.5)
    expect(sampleTrack(track, 10).cx).toBeCloseTo(0.8)
  })
  it('uses the first sample shortly before the track starts', () => {
    expect(sampleTrack([pt(1, 0.3)], 0).cx).toBeCloseTo(0.3)
    expect(sampleTrack([pt(5, 0.3)], 0).cx).toBeCloseTo(0.5)
  })
})
```

`renderer/src/lib/crop.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { cropWindow } from './crop'

describe('cropWindow', () => {
  it('makes a 9:16 window centred on the face', () => {
    const c = cropWindow(1920, 1080, 0.5, 1080 / 1920)
    expect(c.w).toBeCloseTo(607.5)
    expect(c.h).toBe(1080)
    expect(c.x).toBeCloseTo(656.25)
    expect(c.y).toBe(0)
  })
  it('clamps to the frame edges', () => {
    expect(cropWindow(1920, 1080, 0.0, 1080 / 1920).x).toBe(0)
    expect(cropWindow(1920, 1080, 1.0, 1080 / 1920).x).toBeCloseTo(1920 - 607.5)
  })
  it('shrinks height when the window would be wider than the source', () => {
    const c = cropWindow(1000, 1000, 0.5, 2)
    expect(c.w).toBe(1000)
    expect(c.h).toBe(500)
    expect(c.y).toBe(250)
  })
})
```

`renderer/src/lib/speaker.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { activeFace } from './speaker'

describe('activeFace', () => {
  const timeline = [{ t: 0, faceId: 1 }, { t: 4, faceId: 0 }]
  it('picks the latest turn at or before t', () => {
    expect(activeFace(timeline, 0)).toBe(1)
    expect(activeFace(timeline, 3.99)).toBe(1)
    expect(activeFace(timeline, 4)).toBe(0)
  })
  it('handles an empty timeline', () => {
    expect(activeFace([], 2)).toBeNull()
  })
})
```

`renderer/src/captions/paginate.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { pageAt, paginate } from './paginate'

const w = (text: string, start: number, end: number) => ({ text, start, end })

describe('paginate', () => {
  it('breaks at the word limit', () => {
    const words = [w('a', 0, 0.2), w('b', 0.2, 0.4), w('c', 0.4, 0.6), w('d', 0.6, 0.8), w('e', 0.8, 1)]
    expect(paginate(words, 2).map(p => p.words.map(x => x.text).join(' '))).toEqual(['a b', 'c d', 'e'])
  })
  it('breaks at sentence ends and pauses', () => {
    const words = [w('Hi.', 0, 0.3), w('So', 0.3, 0.5), w('then', 0.5, 0.7), w('later', 1.5, 1.8)]
    expect(paginate(words, 10).map(p => p.words.length)).toEqual([1, 2, 1])
  })
  it('breaks before exceeding the character limit', () => {
    const words = [w('abcdef', 0, 0.2), w('ghijkl', 0.2, 0.4), w('m', 0.4, 0.6)]
    expect(paginate(words, 10, 10).map(p => p.words.length)).toEqual([1, 2])
  })
  it('page times come from its words', () => {
    const [p] = paginate([w('a', 1, 1.2), w('b', 1.2, 1.5)], 5)
    expect([p.start, p.end]).toEqual([1, 1.5])
  })
})

describe('pageAt', () => {
  const pages = paginate([w('a', 0, 0.5), w('b.', 0.5, 1), w('c', 3, 3.5)], 5)
  it('shows a page from its start until the next page or a short linger', () => {
    expect(pageAt(pages, 0.2)?.words[0].text).toBe('a')
    expect(pageAt(pages, 1.2)?.words[0].text).toBe('a')
    expect(pageAt(pages, 2)).toBeNull()
    expect(pageAt(pages, 3.1)?.words[0].text).toBe('c')
  })
  it('shows nothing before the first word', () => {
    expect(paginate([w('a', 1, 2)], 5).length).toBe(1)
    expect(pageAt(paginate([w('a', 1, 2)], 5), 0.5)).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd renderer && npm test`
Expected: FAIL — cannot resolve `./track`, `./crop`, `./speaker`, `./paginate`.

- [ ] **Step 3: Implement**

`renderer/src/lib/track.ts`:
```ts
import type { TrackPoint } from '../schema'

// Face tracks come pre-smoothed from Python; here we only interpolate.
// When a face disappears the crop holds its last position for HOLD_S,
// then eases back to centre over EASE_S.
export const HOLD_S = 2
export const EASE_S = 0.5

const lerp = (a: number, b: number, k: number) => a + (b - a) * k

export function sampleTrack(track: TrackPoint[], t: number): { cx: number; cy: number } {
  if (track.length === 0) return { cx: 0.5, cy: 0.5 }
  let i = -1
  for (let k = 0; k < track.length; k++) {
    if (track[k].t <= t) i = k
    else break
  }
  if (i === -1) {
    const first = track[0]
    return first.t - t <= HOLD_S ? { cx: first.cx, cy: first.cy } : { cx: 0.5, cy: 0.5 }
  }
  const prev = track[i]
  const next = track[i + 1]
  if (next && next.t - prev.t <= HOLD_S) {
    const k = (t - prev.t) / (next.t - prev.t)
    return { cx: lerp(prev.cx, next.cx, k), cy: lerp(prev.cy, next.cy, k) }
  }
  const since = t - prev.t
  if (since <= HOLD_S) return { cx: prev.cx, cy: prev.cy }
  const k = Math.min(1, (since - HOLD_S) / EASE_S)
  return { cx: lerp(prev.cx, 0.5, k), cy: lerp(prev.cy, 0.5, k) }
}
```

`renderer/src/lib/crop.ts`:
```ts
// A window of the source frame (in source pixels) with the output's aspect
// ratio, centred horizontally on cx (0-1) and clamped inside the frame.
export type Crop = { x: number; y: number; w: number; h: number }

export function cropWindow(srcW: number, srcH: number, cx: number, aspect: number): Crop {
  let h = srcH
  let w = h * aspect
  if (w > srcW) {
    w = srcW
    h = w / aspect
  }
  const x = Math.min(Math.max(cx * srcW - w / 2, 0), srcW - w)
  return { x, y: (srcH - h) / 2, w, h }
}
```

`renderer/src/lib/speaker.ts`:
```ts
export function activeFace(timeline: { t: number; faceId: number }[], t: number): number | null {
  let id: number | null = null
  for (const turn of timeline) {
    if (turn.t <= t) id = turn.faceId
    else break
  }
  return id ?? timeline[0]?.faceId ?? null
}
```

`renderer/src/captions/paginate.ts`:
```ts
import type { Word } from '../schema'

// Captions show a "page" of a few words at a time. A page ends at the
// preset's word or character limit, at the end of a sentence, or at a
// pause, so pages follow the rhythm of speech.
export const PAUSE_BREAK_S = 0.4
const ENDS_SENTENCE = /[.!?…]["')\]]?$/

export type Page = { start: number; end: number; words: Word[] }

export function paginate(words: Word[], maxWords: number, maxChars = Infinity): Page[] {
  const pages: Page[] = []
  let cur: Word[] = []
  const flush = () => {
    if (cur.length) {
      pages.push({ start: cur[0].start, end: cur[cur.length - 1].end, words: cur })
      cur = []
    }
  }
  words.forEach((word, i) => {
    const chars = cur.reduce((n, x) => n + x.text.length + 1, 0) + word.text.length
    if (cur.length && chars > maxChars) flush()
    cur.push(word)
    const next = words[i + 1]
    const pause = next ? next.start - word.end > PAUSE_BREAK_S : false
    if (cur.length >= maxWords || ENDS_SENTENCE.test(word.text) || pause) flush()
  })
  flush()
  return pages
}

export function pageAt(pages: Page[], t: number, linger = 0.3): Page | null {
  for (let i = pages.length - 1; i >= 0; i--) {
    const p = pages[i]
    if (t >= p.start) {
      const next = pages[i + 1]
      const until = next ? Math.min(next.start, p.end + linger) : p.end + linger
      return t < until ? p : null
    }
  }
  return null
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd renderer && npm test`
Expected: all PASS (schema tests + 15 new).

- [ ] **Step 5: Commit**
```bash
git add renderer/src/lib renderer/src/captions/paginate.ts renderer/src/captions/paginate.test.ts
git commit -m "Add renderer track sampling, crop, speaker and caption pagination logic"
```

---

### Task 13: Remotion layouts, caption presets, hook title and still smoke test

**Files:**
- Create: `renderer/src/fonts.ts`, `renderer/src/source.ts`, `renderer/src/layouts/CroppedVideo.tsx`, `renderer/src/layouts/LayoutView.tsx`, `renderer/src/captions/Captions.tsx`, `renderer/src/HookTitle.tsx`, `renderer/scripts/make-fixture-video.mjs`, `renderer/scripts/stills.mjs`
- Modify: `renderer/src/ClipComposition.tsx`

**Interfaces:**
- Consumes: Task 12 functions, `schema.ts` types, `constants.ts`.
- Produces: `ClipComposition` drawing `LayoutView` + `Captions` + `HookTitle`; `fontFamily` from `fonts.ts`; `resolveSrc(url)` from `source.ts`; `HOOK_S = 2.5`.

- [ ] **Step 1: Shared helpers**

`renderer/src/fonts.ts`:
```ts
import { loadFont } from '@remotion/google-fonts/Montserrat'

// Loaded through Remotion so the browser preview and Lambda render wait
// for the same font before drawing a frame.
export const { fontFamily } = loadFont('normal', { weights: ['700', '800', '900'], subsets: ['latin'] })
```

`renderer/src/source.ts`:
```ts
import { staticFile } from 'remotion'

// Real specs carry an absolute URL (R2 or the API); the fixture uses a
// file in renderer/public for Studio and still renders.
export const resolveSrc = (url: string): string => (/^(https?:|blob:|\/)/.test(url) ? url : staticFile(url))
```

- [ ] **Step 2: Layouts**

`renderer/src/layouts/CroppedVideo.tsx`:
```tsx
import { OffthreadVideo } from 'remotion'
import type { Crop } from '../lib/crop'

type Props = {
  src: string
  trimBefore: number
  srcW: number
  srcH: number
  crop: Crop
  boxW: number
  boxH: number
  muted?: boolean
}

// Shows `crop` (source pixels) scaled to fill a boxW x boxH area. The crop
// has the box's aspect ratio, so one scale factor fits both dimensions.
export const CroppedVideo: React.FC<Props> = ({ src, trimBefore, srcW, srcH, crop, boxW, boxH, muted }) => {
  const scale = boxW / crop.w
  return (
    <div style={{ position: 'relative', width: boxW, height: boxH, overflow: 'hidden' }}>
      <OffthreadVideo
        src={src}
        trimBefore={trimBefore}
        muted={muted}
        style={{
          position: 'absolute',
          width: srcW * scale,
          height: srcH * scale,
          left: -crop.x * scale,
          top: -crop.y * scale,
          maxWidth: 'none',
        }}
      />
    </div>
  )
}
```

`renderer/src/layouts/LayoutView.tsx`:
```tsx
import { AbsoluteFill, OffthreadVideo, useCurrentFrame, useVideoConfig } from 'remotion'
import { OUT_H, OUT_W } from '../constants'
import { cropWindow } from '../lib/crop'
import { activeFace } from '../lib/speaker'
import { sampleTrack } from '../lib/track'
import type { ClipSpec, Layout } from '../schema'
import { resolveSrc } from '../source'
import { CroppedVideo } from './CroppedVideo'

const PANEL_H = OUT_H / 2

export const LayoutView: React.FC<{ spec: ClipSpec; layout: Layout }> = ({ spec, layout }) => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const t = frame / fps
  const src = resolveSrc(spec.source.url)
  const trimBefore = Math.round(spec.start * fps)
  const { width: srcW, height: srcH } = spec.source
  const faces = spec.reframe.faces

  // Layouts that need faces fall back gracefully when analysis found none.
  const effective: Layout = faces.length === 0 ? 'fit' : layout === 'split' && faces.length < 2 ? 'follow' : layout

  if (effective === 'fit') {
    return (
      <AbsoluteFill style={{ backgroundColor: 'black' }}>
        <AbsoluteFill style={{ filter: 'blur(40px)', transform: 'scale(1.15)' }}>
          <OffthreadVideo src={src} trimBefore={trimBefore} muted style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        </AbsoluteFill>
        <AbsoluteFill style={{ justifyContent: 'center' }}>
          <OffthreadVideo src={src} trimBefore={trimBefore} style={{ width: OUT_W, height: (OUT_W * srcH) / srcW }} />
        </AbsoluteFill>
      </AbsoluteFill>
    )
  }

  if (effective === 'split') {
    // Order panels by where each person sits at the start, so they never swap mid-clip.
    const [top, bottom] = [faces[0], faces[1]].sort((a, b) => (a.track[0]?.cx ?? 0.5) - (b.track[0]?.cx ?? 0.5))
    const aspect = OUT_W / PANEL_H
    return (
      <AbsoluteFill style={{ backgroundColor: 'black' }}>
        <CroppedVideo src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={OUT_W} boxH={PANEL_H}
          crop={cropWindow(srcW, srcH, sampleTrack(top.track, t).cx, aspect)} />
        <CroppedVideo src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={OUT_W} boxH={PANEL_H} muted
          crop={cropWindow(srcW, srcH, sampleTrack(bottom.track, t).cx, aspect)} />
      </AbsoluteFill>
    )
  }

  const faceId = effective === 'speaker' ? activeFace(spec.reframe.speakerTimeline, t) ?? faces[0].id : faces[0].id
  const face = faces.find(f => f.id === faceId) ?? faces[0]
  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      <CroppedVideo src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={OUT_W} boxH={OUT_H}
        crop={cropWindow(srcW, srcH, sampleTrack(face.track, t).cx, OUT_W / OUT_H)} />
    </AbsoluteFill>
  )
}
```

- [ ] **Step 3: Captions and hook title**

`renderer/src/captions/Captions.tsx`:
```tsx
import { useMemo } from 'react'
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { OUT_H } from '../constants'
import { fontFamily } from '../fonts'
import type { ClipStyle, Word } from '../schema'
import { pageAt, paginate, type Page } from './paginate'

const PRESETS = {
  karaoke: { maxWords: 4, maxChars: 28 },
  pop: { maxWords: 2, maxChars: 18 },
  clean: { maxWords: 14, maxChars: 84 },
} as const

type Props = {
  words: Word[]
  preset: ClipStyle['captionPreset']
  accent: string
  position: ClipStyle['captionPosition']
}

const OUTLINE = { WebkitTextStroke: '12px black', paintOrder: 'stroke fill' } as const

export const Captions: React.FC<Props> = ({ words, preset, accent, position }) => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const t = frame / fps
  const { maxWords, maxChars } = PRESETS[preset]
  const pages = useMemo(() => paginate(words, maxWords, maxChars), [words, maxWords, maxChars])
  const page = pageAt(pages, t)
  if (!page) return null

  const top = position === 'middle' ? OUT_H / 2 : OUT_H * 0.7
  return (
    <AbsoluteFill>
      <div style={{
        position: 'absolute', top, left: 60, right: 60, transform: 'translateY(-50%)',
        display: 'flex', justifyContent: 'center', textAlign: 'center', fontFamily,
      }}>
        {preset === 'karaoke' && <Karaoke page={page} t={t} accent={accent} />}
        {preset === 'pop' && <Pop page={page} frame={frame} fps={fps} accent={accent} />}
        {preset === 'clean' && <Clean page={page} t={t} />}
      </div>
    </AbsoluteFill>
  )
}

const Karaoke: React.FC<{ page: Page; t: number; accent: string }> = ({ page, t, accent }) => (
  <div style={{ fontSize: 84, fontWeight: 900, lineHeight: 1.1, textTransform: 'uppercase', color: 'white', ...OUTLINE }}>
    {page.words.map((w, i) => (
      <span key={i} style={{ color: t >= w.start && t < w.end ? accent : 'white' }}>
        {w.text}{i < page.words.length - 1 ? ' ' : ''}
      </span>
    ))}
  </div>
)

const Pop: React.FC<{ page: Page; frame: number; fps: number; accent: string }> = ({ page, frame, fps, accent }) => {
  const s = spring({ frame: frame - Math.round(page.start * fps), fps, config: { damping: 12, stiffness: 200 } })
  return (
    <div style={{
      fontSize: 120, fontWeight: 900, lineHeight: 1.05, textTransform: 'uppercase',
      transform: `scale(${0.8 + 0.2 * s})`, ...OUTLINE, WebkitTextStroke: '14px black',
    }}>
      {page.words.map((w, i) => (
        <span key={i} style={{ color: w.emphasis ? accent : 'white' }}>
          {w.text}{i < page.words.length - 1 ? ' ' : ''}
        </span>
      ))}
    </div>
  )
}

const Clean: React.FC<{ page: Page; t: number }> = ({ page, t }) => {
  const opacity = interpolate(t, [page.start, page.start + 0.15, page.end + 0.15, page.end + 0.3], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  })
  return (
    <div style={{
      maxWidth: 900, fontSize: 56, fontWeight: 700, lineHeight: 1.25, color: 'white', opacity,
      textShadow: '0 4px 16px rgba(0,0,0,0.85)',
    }}>
      {page.words.map(w => w.text).join(' ')}
    </div>
  )
}
```

`renderer/src/HookTitle.tsx`:
```tsx
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { fontFamily } from './fonts'

export const HOOK_S = 2.5

export const HookTitle: React.FC<{ text: string }> = ({ text }) => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const endFrame = HOOK_S * fps
  if (frame > endFrame) return null
  const enter = spring({ frame, fps, config: { damping: 14 } })
  const exit = interpolate(frame, [endFrame - 8, endFrame], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  return (
    <AbsoluteFill>
      <div style={{
        position: 'absolute', top: 200, left: 80, right: 80, display: 'flex', justifyContent: 'center',
        opacity: exit, transform: `translateY(${(1 - enter) * -40}px)`,
      }}>
        <div style={{
          background: 'white', color: '#111', borderRadius: 24, padding: '22px 34px', fontFamily,
          fontWeight: 800, fontSize: 60, lineHeight: 1.15, textAlign: 'center',
          boxShadow: '0 10px 30px rgba(0,0,0,0.35)',
        }}>
          {text}
        </div>
      </div>
    </AbsoluteFill>
  )
}
```

`renderer/src/ClipComposition.tsx` (replace):
```tsx
import { AbsoluteFill } from 'remotion'
import { Captions } from './captions/Captions'
import { HookTitle } from './HookTitle'
import { LayoutView } from './layouts/LayoutView'
import type { ClipProps } from './schema'

export const ClipComposition: React.FC<ClipProps> = ({ spec, style }) => {
  // Split layout puts captions on the seam between the two panels.
  const position = style.layout === 'split' ? 'middle' : style.captionPosition
  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      <LayoutView spec={spec} layout={style.layout} />
      <Captions words={spec.words} preset={style.captionPreset} accent={style.accent} position={position} />
      {style.showHook && style.hookTitle ? <HookTitle text={style.hookTitle} /> : null}
    </AbsoluteFill>
  )
}
```

- [ ] **Step 4: Fixture video and stills scripts**

`renderer/scripts/make-fixture-video.mjs`:
```js
// 12 s 1920x1080 test pattern with a tone, used as spec.source for the
// fixture in Studio and still renders (fixture.mp4 is git-ignored).
import { execFileSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'

mkdirSync('public', { recursive: true })
execFileSync('ffmpeg', [
  '-y', '-loglevel', 'error',
  '-f', 'lavfi', '-i', 'testsrc2=size=1920x1080:rate=30',
  '-f', 'lavfi', '-i', 'sine=frequency=440',
  '-t', '12', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest',
  'public/fixture.mp4',
], { stdio: 'inherit' })
console.log('wrote public/fixture.mp4')
```

`renderer/scripts/stills.mjs`:
```js
// One still per layout x caption preset from the fixture spec, at 1.5 s
// (hook title and captions both visible). Review out/stills by eye.
import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'

const spec = JSON.parse(readFileSync('src/__fixtures__/clip-spec.json', 'utf8'))
mkdirSync('out/stills', { recursive: true })
for (const layout of ['follow', 'speaker', 'split', 'fit']) {
  for (const captionPreset of ['karaoke', 'pop', 'clean']) {
    const props = {
      spec,
      style: { layout, captionPreset, showHook: true, hookTitle: spec.hookTitle, accent: '#FFD400', captionPosition: 'lower' },
    }
    const propsFile = `out/stills/props-${layout}-${captionPreset}.json`
    writeFileSync(propsFile, JSON.stringify(props))
    execFileSync('npx', ['remotion', 'still', 'src/index.ts', 'Clip', `out/stills/${layout}-${captionPreset}.png`,
      `--props=${propsFile}`, '--frame=45'], { stdio: 'inherit', shell: true })
  }
}
```

- [ ] **Step 5: Verify**

Run: `cd renderer && npm run typecheck && npm test && npm run fixture:video && npm run stills`
Expected: typecheck exits 0, tests PASS, 12 PNGs in `renderer/out/stills/`. Open at least `follow-karaoke.png`, `split-pop.png`, `fit-clean.png` with the Read tool and check:
- 1080x1920 frame; follow/speaker show a vertical slice of the test pattern; split shows two stacked panels; fit shows the full pattern on a blurred background.
- Hook title box near the top reading "The moment everything changed".
- Karaoke: 3-4 uppercase outlined words, one in yellow. Pop: 1-2 big words. Clean: a white sentence line.

Fix any visual problem before committing. Also run `npm run studio` briefly to confirm the composition plays with audio and switching props in the right panel updates it; stop it afterwards.

- [ ] **Step 6: Commit**
```bash
git add renderer/src renderer/scripts
git commit -m "Add Remotion layouts, caption presets, hook title and still smoke test"
```

---

### Task 14: Frontend — live preview, style controls, render and export

**Files:**
- Modify: `frontend/package.json` (via npm), `frontend/vite.config.js`, `frontend/src/services/highlyteApi.js`, `frontend/src/stores/jobStore.js`, `frontend/src/components/ClipList.vue`, `frontend/src/components/ExportBar.vue`, `frontend/src/components/ProcessingSteps.vue`, `frontend/src/views/JobView.vue`, `.claude/launch.json`
- Create: `frontend/src/components/RemotionPreview.vue`, `frontend/src/components/ClipCard.vue`
- Delete: `frontend/src/components/ClipRow.vue`

**Interfaces:**
- Consumes: `@renderer/ClipComposition` (`ClipComposition`), `@renderer/constants` (`FPS`, `OUT_W`, `OUT_H`, `durationInFrames`); API from Task 10.
- Produces: `highlyteApi.js` functions `getHealth()`, `saveClipStyle(clipId, style)`, `startRender(clipId, style)`, `getRender(renderId)`, `rendersZipUrl(renderIds)`; store state `renders` (clipId → render), `renderingEnabled`; actions `loadHealth()`, `updateStyle(clipId, patch)`, `exportSelected()`, `retryRender(clipId)`.

- [ ] **Step 1: Dependencies**
```bash
cd frontend
npm install --save-exact react@19.3.0 react-dom@19.3.0 remotion@4.0.527 @remotion/player@4.0.527 @remotion/google-fonts@4.0.527 zod@4.5.4
npm install --save-dev --save-exact @vitejs/plugin-react@6.1.1
```

- [ ] **Step 2: `frontend/vite.config.js`**
```js
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    // Only the Remotion composition (renderer/src, .tsx) is React; the app itself stays Vue.
    react({ include: /\.(jsx|tsx)$/ }),
  ],
  resolve: {
    alias: {
      '@renderer': fileURLToPath(new URL('../renderer/src', import.meta.url)),
    },
    // renderer/ has its own node_modules. Without dedupe the composition
    // would import a second copy of remotion/react, and the Player's
    // context wouldn't reach it.
    dedupe: ['react', 'react-dom', 'remotion', '@remotion/player', '@remotion/google-fonts', 'zod'],
  },
  server: {
    port: 6100,
    strictPort: true,
    fs: { allow: ['..'] },
  },
  preview: {
    port: 6100,
    strictPort: true,
  },
})
```

- [ ] **Step 3: API client** — append to `frontend/src/services/highlyteApi.js`:
```js
export function getHealth() {
  return api.get('/api/health').then(r => r.data)
}

export function saveClipStyle(clipId, style) {
  return api.patch(`/api/clips/${clipId}/style`, style).then(r => r.data)
}

export function startRender(clipId, style) {
  return api.post(`/api/clips/${clipId}/render`, style).then(r => r.data)
}

export function getRender(renderId) {
  return api.get(`/api/renders/${renderId}`).then(r => r.data)
}

export function rendersZipUrl(renderIds) {
  return `${baseURL}/api/renders/zip?ids=${renderIds.join(',')}`
}
```

- [ ] **Step 4: Store** — in `frontend/src/stores/jobStore.js`:

Update the import:
```js
import {
  clipDownloadUrl, createJob, getHealth, getJobStatus, getRender, listJobs, saveClipStyle, startRender,
} from '../services/highlyteApi'
```
Add constants under `POLL_INTERVAL_MS`:
```js
const RENDER_POLL_MS = 2000
const STYLE_SAVE_DELAY_MS = 500
```
Add to `state`:
```js
    renders: {}, // clipId -> render {id, status, progress, error, downloadUrl}
    renderingEnabled: false,
    _renderTimer: null,
    _styleTimers: {},
```
In `refresh()`, right after `const data = await getJobStatus(this.currentJobId)`, add:
```js
        // The Player needs an absolute URL; the API returns its own path.
        for (const c of data.clips || []) {
          if (c.spec?.source?.url?.startsWith('/')) c.spec.source.url = clipDownloadUrl(c.spec.source.url)
        }
```
Add actions:
```js
    async loadHealth() {
      try {
        this.renderingEnabled = !!(await getHealth()).rendering
      } catch {
        this.renderingEnabled = false
      }
    },
    updateStyle(clipId, patch) {
      const clip = this.clips.find(c => c.id === clipId)
      if (!clip) return
      clip.style = { ...clip.style, ...patch }
      // Saving is debounced so typing in the hook title isn't a request per key.
      clearTimeout(this._styleTimers[clipId])
      this._styleTimers[clipId] = setTimeout(() => {
        saveClipStyle(clipId, clip.style).catch(e => {
          this.error = e?.response?.data?.detail || 'Failed to save clip style'
        })
      }, STYLE_SAVE_DELAY_MS)
    },
    async exportSelected() {
      const clips = this.clips.filter(c => this.selected[c.id] && c.spec)
      for (const c of clips) await this._render(c)
      this._pollRenders()
    },
    async retryRender(clipId) {
      const clip = this.clips.find(c => c.id === clipId)
      if (!clip) return
      await this._render(clip)
      this._pollRenders()
    },
    async _render(clip) {
      try {
        this.renders[clip.id] = await startRender(clip.id, clip.style)
      } catch (e) {
        this.renders[clip.id] = { status: 'error', error: e?.response?.data?.detail || e.message }
      }
    },
    _pollRenders() {
      if (this._renderTimer) return
      this._renderTimer = setInterval(async () => {
        const pending = Object.entries(this.renders).filter(([, r]) => r.id && ['queued', 'rendering'].includes(r.status))
        if (pending.length === 0) {
          clearInterval(this._renderTimer)
          this._renderTimer = null
          return
        }
        for (const [clipId, r] of pending) {
          try {
            this.renders[clipId] = await getRender(r.id)
          } catch {
            // transient; try again next tick
          }
        }
      }, RENDER_POLL_MS)
    },
```
Add getters:
```js
    selectedRenders: (state) => (state.job?.clips || [])
      .filter(c => state.selected[c.id])
      .map(c => state.renders[c.id])
      .filter(Boolean),
```
In `submitUrl`, also reset `this.renders = {}`.

- [ ] **Step 5: `frontend/src/components/RemotionPreview.vue`**
```vue
<template>
  <div ref="host" class="remotion-preview"></div>
</template>

<script setup>
// Hosts the Remotion Player (React) inside this Vue app. The composition
// is imported straight from renderer/src, so the preview is the exact
// code Lambda renders.
import { onBeforeUnmount, onMounted, ref, toRaw, watch } from 'vue'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { Player } from '@remotion/player'
import { ClipComposition } from '@renderer/ClipComposition'
import { FPS, OUT_H, OUT_W, durationInFrames } from '@renderer/constants'

const props = defineProps({
  spec: { type: Object, required: true },
  clipStyle: { type: Object, required: true },
})

const host = ref(null)
let root = null

// React must receive plain objects, not Vue's reactive proxies.
const plain = (value) => JSON.parse(JSON.stringify(toRaw(value)))

function draw() {
  if (!root) return
  const spec = plain(props.spec)
  root.render(createElement(Player, {
    component: ClipComposition,
    inputProps: { spec, style: plain(props.clipStyle) },
    durationInFrames: durationInFrames(spec),
    fps: FPS,
    compositionWidth: OUT_W,
    compositionHeight: OUT_H,
    controls: true,
    acknowledgeRemotionLicense: true,
    style: { width: '100%' },
  }))
}

onMounted(() => {
  root = createRoot(host.value)
  draw()
})
watch(() => [props.spec, props.clipStyle], draw, { deep: true })
onBeforeUnmount(() => {
  root?.unmount()
  root = null
})
</script>

<style scoped>
.remotion-preview { width: 100%; aspect-ratio: 9 / 16; background: #000; border-radius: 10px; overflow: hidden; }
</style>
```

- [ ] **Step 6: `frontend/src/components/ClipCard.vue`**
```vue
<template>
  <div class="clip-card">
    <div class="preview">
      <RemotionPreview v-if="clip.spec" :spec="clip.spec" :clip-style="clip.style" />
      <div v-else class="no-preview">No vertical preview for this clip. Re-run the video to generate one.</div>
    </div>

    <div class="details">
      <div class="meta-row">
        <div class="checkbox" :class="{ checked: isSelected }" @click="$emit('toggle')">
          <span v-if="isSelected">✓</span>
        </div>
        <span class="clip-range">{{ clip.startLabel }} – {{ clip.endLabel }}</span>
        <span class="clip-duration">{{ clip.durationLabel }}</span>
        <span class="clip-tag">{{ clip.tag }}</span>
        <span v-if="clip.viralityScore != null" class="virality" title="Virality score">{{ Number(clip.viralityScore).toFixed(1) }}/10</span>
      </div>

      <template v-if="clip.spec">
        <label class="field">
          <span>Hook title</span>
          <input type="text" :value="clip.style.hookTitle || ''" maxlength="80"
            @input="set({ hookTitle: $event.target.value || null })" />
        </label>
        <label class="check">
          <input type="checkbox" :checked="clip.style.showHook" @change="set({ showHook: $event.target.checked })" />
          Show hook title
        </label>
        <div class="field-row">
          <label class="field">
            <span>Layout</span>
            <select :value="clip.style.layout" @change="set({ layout: $event.target.value })">
              <option v-for="l in LAYOUTS" :key="l.value" :value="l.value" :disabled="l.minFaces > faceCount">
                {{ l.label }}{{ l.value === clip.spec.reframe.auto ? ' (auto)' : '' }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>Captions</span>
            <select :value="clip.style.captionPreset" @change="set({ captionPreset: $event.target.value })">
              <option v-for="p in PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </label>
        </div>
        <div class="field-row">
          <label class="field">
            <span>Caption position</span>
            <select :value="clip.style.captionPosition" :disabled="clip.style.layout === 'split'"
              @change="set({ captionPosition: $event.target.value })">
              <option value="lower">Lower third</option>
              <option value="middle">Middle</option>
            </select>
          </label>
          <label class="field">
            <span>Accent colour</span>
            <input type="color" :value="clip.style.accent" @input="set({ accent: $event.target.value })" />
          </label>
        </div>
        <div v-if="clip.spec.wordsApprox" class="note">Approximate caption sync</div>
      </template>

      <div class="clip-snippet">"{{ snippet }}"</div>

      <div v-if="render" class="render-status" :class="render.status">
        <template v-if="render.status === 'queued'">Waiting to render…</template>
        <template v-else-if="render.status === 'rendering'">
          Rendering {{ Math.round(render.progress || 0) }}%
          <div class="progress-bar"><div class="progress-bar-fill" :style="{ width: (render.progress || 0) + '%' }"></div></div>
        </template>
        <template v-else-if="render.status === 'done'">
          <a :href="clipDownloadUrl(render.downloadUrl)">Download mp4</a>
        </template>
        <template v-else>
          Render failed: {{ render.error }}
          <button class="retry" @click="jobStore.retryRender(clip.id)">Retry</button>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useJobStore } from '../stores/jobStore'
import { clipDownloadUrl } from '../services/highlyteApi'
import RemotionPreview from './RemotionPreview.vue'

const LAYOUTS = [
  { value: 'follow', label: 'Follow face', minFaces: 1 },
  { value: 'speaker', label: 'Follow speaker', minFaces: 1 },
  { value: 'split', label: 'Split screen', minFaces: 2 },
  { value: 'fit', label: 'Fit with blur', minFaces: 0 },
]
const PRESETS = [
  { value: 'karaoke', label: 'Karaoke highlight' },
  { value: 'pop', label: 'Pop word-by-word' },
  { value: 'clean', label: 'Clean subtitle' },
]

const props = defineProps({
  clip: { type: Object, required: true },
  isSelected: { type: Boolean, default: false },
})
defineEmits(['toggle'])

const jobStore = useJobStore()
const faceCount = computed(() => props.clip.spec?.reframe.faces.length || 0)
const render = computed(() => jobStore.renders[props.clip.id])
const snippet = computed(() => {
  const t = props.clip.text || ''
  return t.length > 220 ? t.slice(0, 217) + '…' : t
})

function set(patch) {
  jobStore.updateStyle(props.clip.id, patch)
}
</script>

<style scoped>
.clip-card {
  display: grid; grid-template-columns: 220px 1fr; gap: 20px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px;
}
@media (max-width: 640px) { .clip-card { grid-template-columns: 1fr; } }
.no-preview {
  aspect-ratio: 9 / 16; display: flex; align-items: center; justify-content: center; text-align: center;
  padding: 16px; border-radius: 10px; background: var(--accent-soft); color: var(--ink-soft); font-size: 13px;
}
.details { min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.meta-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.checkbox {
  width: 20px; height: 20px; border-radius: 6px; flex-shrink: 0; cursor: pointer;
  display: flex; align-items: center; justify-content: center; font-size: 13px; color: #fff;
  background: #fff; border: 1.5px solid var(--border);
}
.checkbox.checked { background: var(--accent); border-color: var(--accent); }
.clip-range { font-family: monospace; font-size: 12.5px; color: var(--ink-soft); }
.clip-duration { font-size: 11px; color: var(--ink-faint); }
.clip-tag, .virality {
  background: var(--accent-soft); color: var(--accent-text); font-size: 11.5px; font-weight: 600;
  padding: 3px 10px; border-radius: 999px;
}
.field-row { display: flex; gap: 12px; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-soft); flex: 1; min-width: 140px; }
.field input[type="text"], .field select {
  font-family: var(--font-sans); font-size: 13.5px; color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 9px; background: #fff;
}
.field input[type="color"] { width: 48px; height: 32px; border: 1px solid var(--border); border-radius: 8px; padding: 2px; background: #fff; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-soft); }
.note { font-size: 12px; color: var(--ink-faint); }
.clip-snippet { font-family: var(--font-serif); font-style: italic; font-size: 14.5px; line-height: 1.5; }
.render-status { font-size: 13px; color: var(--ink-soft); }
.render-status.error { color: #9C3B14; }
.render-status a { color: var(--accent); font-weight: 600; }
.retry { margin-left: 8px; border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 3px 10px; cursor: pointer; }
.progress-bar { margin-top: 6px; height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--accent); transition: width .3s ease; }
</style>
```

- [ ] **Step 7: Wire it up**

`frontend/src/components/ClipList.vue` — replace the `<ClipRow .../>` element with:
```vue
      <ClipCard
        v-for="clip in jobStore.clips"
        :key="clip.id"
        :clip="clip"
        :is-selected="!!jobStore.selected[clip.id]"
        @toggle="jobStore.toggleClip(clip.id)"
      />
```
and change the import to `import ClipCard from './ClipCard.vue'`.

Delete `frontend/src/components/ClipRow.vue` (`git rm`). Remove `playingClipId` from the store state and the `setPlaying` action (nothing uses them any more).

`frontend/src/components/ExportBar.vue` — replace the template and script:
```vue
<template>
  <div class="bottombar">
    <div class="bottombar-inner">
      <span class="selection-label">{{ label }}</span>
      <div class="actions">
        <a v-if="zipUrl" class="zip-link" :href="zipUrl">Download all (zip)</a>
        <button
          class="export-btn"
          :class="{ active: canExport }"
          :disabled="!canExport"
          :title="jobStore.renderingEnabled ? '' : 'Rendering not configured'"
          @click="jobStore.exportSelected()"
        >
          {{ jobStore.renderingEnabled ? 'Render & export selected' : 'Rendering not configured' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useJobStore } from '../stores/jobStore'
import { rendersZipUrl } from '../services/highlyteApi'

const jobStore = useJobStore()

const label = computed(() => {
  const n = jobStore.selectedCount
  if (n === 0) return 'Select clips to export'
  const renders = jobStore.selectedRenders
  const done = renders.filter(r => r.status === 'done').length
  const busy = renders.filter(r => ['queued', 'rendering'].includes(r.status)).length
  if (busy) return `Rendering ${busy} of ${n} clips… (${done} done)`
  return `${n} of ${jobStore.clips.length} clips selected`
})

const canExport = computed(() => jobStore.renderingEnabled && jobStore.selectedCount > 0)

const zipUrl = computed(() => {
  const renders = jobStore.selectedRenders
  if (renders.length === 0 || renders.length !== jobStore.selectedCount) return null
  if (!renders.every(r => r.status === 'done')) return null
  return rendersZipUrl(renders.map(r => r.id))
})
</script>
```
Keep the existing `<style scoped>` block, remove the `.toast` rule, and add:
```css
.actions { display: flex; align-items: center; gap: 14px; }
.zip-link { font-size: 13.5px; font-weight: 600; color: var(--accent); }
```

`frontend/src/components/ProcessingSteps.vue`:
```js
  status: { type: String, required: true }, // queued|transcribing|analyzing|preparing|done|error
```
```js
const ORDER = ['transcribing', 'analyzing', 'preparing']
const LABELS = {
  transcribing: 'Transcribing audio',
  analyzing: 'Analyzing for highlights',
  preparing: 'Preparing clips (captions and framing)',
}
```
Change the hint text to: `This takes a few minutes on CPU: every clip gets word-timed captions and face tracking.`

`frontend/src/views/JobView.vue`: in `STATUS_NOTES` replace `cutting: 'Cutting clips…'` with `preparing: 'Preparing clips…'`, and change `onMounted(() => startForId(props.id))` to:
```js
onMounted(() => {
  jobStore.loadHealth()
  startForId(props.id)
})
```

- [ ] **Step 8: Launch config** — `.claude/launch.json` add a backend entry (keep `frontend`):
```json
    {
      "name": "backend",
      "runtimeExecutable": ".venv/Scripts/python.exe",
      "runtimeArgs": ["-m", "uvicorn", "backend.main:app", "--port", "7000"],
      "port": 7000
    }
```
Confirm `frontend/.env` (or the environment) sets `VITE_API_BASE_URL=http://127.0.0.1:7000`; if not, create `frontend/.env.local` with that line.

- [ ] **Step 9: Build check**

Run: `cd frontend && npm run build`
Expected: build succeeds with no unresolved-import errors (a chunk-size warning is fine).

- [ ] **Step 10: Browser verification**

1. `preview_start` `backend` and `frontend`.
2. Ask the user for a short (2-5 min) public YouTube video, ideally with two people on camera, and submit it on the home page.
3. Watch the stages reach "Preparing clips" and then done; check `preview_logs` for backend errors.
4. On the job page: `read_console_messages` has no errors (in particular no "multiple versions of remotion" or React context errors); each card shows a 9:16 Player; pressing play shows moving captions with audio.
5. Change layout, caption preset, accent and hook title on one card; the preview updates immediately; `read_network_requests` shows one debounced `PATCH /api/clips/.../style` returning 200.
6. Without AWS configured: the Export button reads "Rendering not configured" and is disabled.
7. Screenshot one card for the user.

- [ ] **Step 11: Commit**
```bash
git add frontend .claude/launch.json
git rm frontend/src/components/ClipRow.vue
git commit -m "Add live Remotion preview, clip style controls and render export to the Vue app"
```

---

### Task 15: AWS deployment, docs and end-to-end render

**Files:**
- Modify: `README.md`, `.env.example`

- [ ] **Step 1: `.env.example`** — append:
```
# Phase 1 rendering: Remotion on AWS Lambda. All five are required to
# enable Export; analysis and the in-browser preview work without them.
# R2 (above) is also required for rendering: Lambda reads each clip's
# source from R2 and the finished mp4 is stored there.
# REMOTION_AWS_ACCESS_KEY_ID=
# REMOTION_AWS_SECRET_ACCESS_KEY=
# REMOTION_AWS_REGION=ap-south-1
# From `npm run deploy:functions` in renderer/ (e.g. remotion-render-4-0-527-mem2048mb-disk2048mb-240sec):
# REMOTION_FUNCTION_NAME=
# From `npm run deploy:site` in renderer/ (the "Serve URL" it prints):
# REMOTION_SERVE_URL=

# Groq (free tier): hosted Whisper for transcripts and per-clip caption
# timing, plus LLM highlight selection. Without it, local Whisper and the
# heuristic scorer are used and captions may be approximately timed.
# GROQ_KEY=
```
Also delete the stale `OPENAI_API_KEY` block (the code reads `GROQ_KEY`).

- [ ] **Step 2: README** — replace the "Open questions" section's first item with a checked one (`- [x] Output format: vertical 9:16 shorts (Phase 1)`), fix the "optional LLM scorer if `OPENAI_API_KEY` is set" wording to `GROQ_KEY`, and add this section before "How it works":
````markdown
## Vertical clips and rendering

Each highlight becomes a 9:16 short: the crop follows faces (or the
current speaker, or shows both people split-screen, or fits the whole
frame on a blurred background), with animated word-by-word captions and
an optional hook title. The clip page previews every change live in the
browser; the final mp4 is rendered on AWS Lambda with
[Remotion](https://www.remotion.dev) only when you export.

- `renderer/` — the Remotion composition (layouts, caption presets, hook
  title). The same code runs in the browser preview and on Lambda.
  `npm run studio` opens Remotion Studio for designing presets;
  `npm run fixture:video && npm run stills` renders a still for every
  layout × preset.
- Remotion's free license covers teams of 3 or fewer people.

### One-time AWS setup

1. `cd renderer && npm install`
2. In the AWS console create an IAM user for HighLyte. Attach the policy
   printed by `npx remotion lambda policies user` to the user, and create
   the role described by `npx remotion lambda policies role` (role name
   `remotion-lambda-role`). Create an access key for the user.
3. Put the key, secret and region in `.env` (`REMOTION_AWS_*`), and also
   export them as `REMOTION_AWS_ACCESS_KEY_ID` / `REMOTION_AWS_SECRET_ACCESS_KEY`
   in the shell for the next two commands.
4. `npm run deploy:functions` — copy the function name into `REMOTION_FUNCTION_NAME`.
5. `npm run deploy:site` — copy the Serve URL into `REMOTION_SERVE_URL`.
   Re-run this whenever anything in `renderer/src` changes.
6. Create an AWS Budget alert at $5/month (Billing → Budgets).
7. Backstop cleanup: add a lifecycle rule on the `remotionlambda-*` S3
   bucket deleting objects under `renders/` after 1 day (HighLyte deletes
   each output after copying it to R2; this catches anything missed).
8. If renders fail with throttling errors, request a Lambda concurrency
   increase (Service Quotas → Lambda → Concurrent executions).

Remotion npm packages and the Python `remotion-lambda` client must be
the exact same version (currently 4.0.527). When upgrading, change both,
then redeploy the functions and the site; the backend logs a VERSION
MISMATCH line at startup if they differ.

### Tests
```
./.venv/Scripts/pip install -r requirements-dev.txt
./.venv/Scripts/python -m pytest              # fast suite
./.venv/Scripts/python -m pytest -m slow      # downloads the face model, runs MediaPipe
cd renderer && npm test
```
````

- [ ] **Step 3: User does the AWS setup** — hand the user the README steps above. Wait for them to confirm `.env` has all five `REMOTION_*` values and R2 is configured. Don't create AWS resources or handle their keys yourself.

- [ ] **Step 4: End-to-end render**
1. Restart the backend; check the log has no `VERSION MISMATCH` line and `GET /api/health` returns `"rendering": true`.
2. Re-run the Task 14 test video (clips from before R2 was configured have no R2 source).
3. Select two clips with different layouts and presets; click "Render & export selected"; watch progress reach "Download mp4".
4. Download one render and check it:
```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -show_entries format=duration -of default=noprint_wrappers=1 downloaded.mp4
```
Expected: `width=1080`, `height=1920`, `r_frame_rate=30/1`, and a duration within 0.1 s of the clip's `end - start`.
5. Click "Download all (zip)" and confirm the zip holds both mp4s.
6. Check the S3 bucket's `renders/` prefix is empty afterwards (outputs deleted after copying).

- [ ] **Step 5: Full test run**

Run: `./.venv/Scripts/python -m pytest -m "slow or not slow" && (cd renderer && npm test && npm run typecheck) && (cd frontend && npm run build)`
Expected: everything passes.

- [ ] **Step 6: Commit**
```bash
git add README.md .env.example
git commit -m "Document Lambda rendering setup, tests and Phase 1 configuration"
```
