# Shot-Aware Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split screen shows the left person on top and the right person below only during wide two-person shots, and one person full-frame during close-ups, by detecting camera cuts and analysing faces per shot.

**Architecture:** Face sampling also keeps a tiny grayscale thumbnail per sample; `shots.py` turns thumbnail jumps into cut times and shot ranges; `reframe.analyze` builds face tracks per shot and records a `shots` list in the clip spec; the renderer picks the layout for each frame from the active shot through a pure `resolveView` function.

**Tech Stack:** Python 3.11, OpenCV, MediaPipe (existing), Pydantic; Remotion 4.0.527 + React 19 + zod 4 + vitest 5 in `renderer/`; Vue 3 frontend imports the renderer for the preview.

**Spec:** `docs/superpowers/specs/2026-09-26-shot-aware-layout-design.md`

## Global Constraints

- Branch `hinglish-v1`. Commit after every task. **Never push.** Never stage `renderer/package-lock.json`. Never run git stash/checkout of other commits/reset/amend. Never kill or stop any process.
- Every commit message ends with a blank line and exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Python tests: `./.venv/Scripts/python -m pytest -q` from the repo root (Git Bash); 202 pass before Task 1 plus one pre-existing starlette DeprecationWarning. Renderer tests: `cd renderer && npm test` and `npm run typecheck`.
- `CUT_THRESHOLD = 0.08` (mean absolute difference of 32×18 grayscale thumbnails, values 0–1). `MIN_SHOT_S = 0.6`. Thumbnail size 32 wide × 18 high.
- Shot kinds: `"two"` (faceIds ordered left to right), `"one"`, `"none"`. `Reframe.shots` defaults to an empty list; a spec without shots must render exactly as today.
- Auto layout: `split` when two-person shots cover ≥ 50 % of the clip; else `speaker` when the talker changes inside at least one two-person shot; else `follow`; the existing `fit` rules come first.
- Times in `shots`, face tracks and the speaker timeline are clip-relative seconds.
- Match surrounding style: module docstrings that say why, `from __future__ import annotations`, comments only where a reader would be surprised.

## File map

| File | Change |
|---|---|
| `backend/pipeline/shots.py` | new: `cut_times`, `split_shots` |
| `backend/spec.py` | `Shot`, `ShotKind`, `Reframe.shots` |
| `scripts/make_fixture_spec.py`, `renderer/src/__fixtures__/clip-spec.json` | fixture with two shots |
| `renderer/src/schema.ts`, `renderer/src/schema.test.ts` | `shotSchema`, `shots` default `[]` |
| `backend/pipeline/reframe.py` | per-shot analysis, `choose_auto` |
| `backend/pipeline/face_detect.py` | return thumbnails |
| `backend/pipeline/clipprep.py` | pass cuts into `analyze` |
| `renderer/src/lib/shots.ts`, `renderer/src/lib/view.ts` (+ tests) | `activeShot`, `resolveView` |
| `renderer/src/layouts/LayoutView.tsx` | render from `resolveView` |
| `README.md` | layout + redeploy note |

---

### Task 1: Cut detection and shot ranges

**Files:** Create `backend/pipeline/shots.py`, `tests/test_shots.py`.

**Interfaces — Produces:** `CUT_THRESHOLD = 0.08`, `MIN_SHOT_S = 0.6`, `cut_times(thumbs: list[np.ndarray], times: list[float], threshold: float = CUT_THRESHOLD) -> list[float]`, `split_shots(times: list[float], cuts: list[float], min_len_s: float = MIN_SHOT_S) -> list[tuple[int, int]]` (half-open sample index ranges covering all samples).

- [ ] **Step 1: Failing tests** — `tests/test_shots.py`:

```python
import numpy as np

from backend.pipeline import shots


def _thumbs(values):
    return [np.full((18, 32), v, dtype=np.float32) for v in values]


def _times(n, fps=5.0):
    return [round(i / fps, 3) for i in range(n)]


def test_cut_times_finds_hard_cut_only():
    rng = np.random.default_rng(0)
    base = [0.4 + rng.normal(0, 0.01, (18, 32)).astype(np.float32) for _ in range(10)]
    cut = [0.8 + rng.normal(0, 0.01, (18, 32)).astype(np.float32) for _ in range(10)]
    times = _times(20)
    assert shots.cut_times(base + cut, times) == [times[10]]


def test_cut_times_ignores_gradual_motion():
    assert shots.cut_times(_thumbs([0.40 + i * 0.01 for i in range(20)]), _times(20)) == []


def test_cut_times_empty():
    assert shots.cut_times([], []) == []


def test_split_shots_without_cuts_is_one_shot():
    assert shots.split_shots(_times(20), []) == [(0, 20)]


def test_split_shots_at_cuts():
    times = _times(40)
    assert shots.split_shots(times, [times[10], times[25]]) == [(0, 10), (10, 25), (25, 40)]


def test_split_shots_merges_too_short_shot_into_previous():
    times = _times(40)
    # 10..12 is 0.4 s long -> merged into the shot before it
    assert shots.split_shots(times, [times[10], times[12]]) == [(0, 12), (12, 40)]


def test_split_shots_merges_too_short_first_shot_into_next():
    times = _times(40)
    assert shots.split_shots(times, [times[2]]) == [(0, 40)]


def test_split_shots_empty():
    assert shots.split_shots([], []) == []
```

- [ ] **Step 2:** Run `./.venv/Scripts/python -m pytest -q tests/test_shots.py` → FAIL (ImportError).

- [ ] **Step 3: Implement** `backend/pipeline/shots.py`:

```python
"""Camera cuts and shots, from the tiny thumbnails kept during face sampling.

Podcasts cut between a wide two-person shot and single-person close-ups.
Face tracking and layout must restart at each cut, or a face track carries
on into a different shot and the crop lands on empty frame. Measured on a
real episode at 5 fps: ordinary movement changes a 32x18 grayscale
thumbnail by a mean of at most ~0.02, real cuts by 0.17-0.29.
"""
from __future__ import annotations

import numpy as np

CUT_THRESHOLD = 0.08
# Shorter shots (flash frames, transitions) join a neighbouring shot.
MIN_SHOT_S = 0.6


def cut_times(thumbs: list[np.ndarray], times: list[float], threshold: float = CUT_THRESHOLD) -> list[float]:
    """Times of the first sample of each new shot."""
    return [
        times[i] for i in range(1, len(thumbs))
        if float(np.abs(thumbs[i] - thumbs[i - 1]).mean()) > threshold
    ]


def _duration(times: list[float], start: int, end: int) -> float:
    step = times[1] - times[0] if len(times) > 1 else 0.0
    last = times[end] if end < len(times) else times[-1] + step
    return last - times[start]


def split_shots(times: list[float], cuts: list[float], min_len_s: float = MIN_SHOT_S) -> list[tuple[int, int]]:
    if not times:
        return []
    cut_set = set(cuts)
    starts = [0] + [i for i in range(1, len(times)) if times[i] in cut_set]
    ranges = list(zip(starts, starts[1:] + [len(times)]))
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if merged and _duration(times, start, end) < min_len_s:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    if len(merged) > 1 and _duration(times, *merged[0]) < min_len_s:
        merged[:2] = [(merged[0][0], merged[1][1])]
    return merged
```

- [ ] **Step 4:** Tests pass (8); full suite green.
- [ ] **Step 5:** Commit `Add camera cut detection and shot ranges` (+ trailer).

---

### Task 2: `shots` in the clip spec (Python + renderer schema + fixture)

**Files:** Modify `backend/spec.py`, `scripts/make_fixture_spec.py`, `renderer/src/schema.ts`, `renderer/src/schema.test.ts`; regenerate `renderer/src/__fixtures__/clip-spec.json`; test in `tests/test_spec.py`.

**Interfaces — Produces:** Python `ShotKind = Literal["two", "one", "none"]`, `class Shot(BaseModel): start: float; end: float; kind: ShotKind; faceIds: list[int]`, `Reframe.shots: list[Shot] = Field(default_factory=list)`. TS `shotSchema`, `type Shot`, `reframe.shots` = `z.array(shotSchema).default([])`.

- [ ] **Step 1: Failing tests.** Append to `tests/test_spec.py`:

```python
def test_reframe_shots_default_and_round_trip():
    from backend.spec import Reframe

    old = Reframe.model_validate({"auto": "follow", "faces": [], "speakerTimeline": []})
    assert old.shots == []
    new = Reframe.model_validate({
        "auto": "split", "faces": [], "speakerTimeline": [],
        "shots": [{"start": 0.0, "end": 4.0, "kind": "two", "faceIds": [0, 1]}],
    })
    assert new.model_dump()["shots"][0] == {"start": 0.0, "end": 4.0, "kind": "two", "faceIds": [0, 1]}
```

In `renderer/src/schema.test.ts`, inside `describe('schema', ...)`, add:

```ts
  it('reads shots from the fixture and defaults them for old specs', () => {
    expect(clipSpecSchema.parse(fixture).reframe.shots).toHaveLength(2)
    const old = structuredClone(fixture) as any
    delete old.reframe.shots
    expect(clipSpecSchema.parse(old).reframe.shots).toEqual([])
  })

  it('rejects an unknown shot kind', () => {
    const bad = structuredClone(fixture) as any
    bad.reframe.shots = [{ start: 0, end: 1, kind: 'three', faceIds: [] }]
    expect(clipSpecSchema.safeParse(bad).success).toBe(false)
  })
```

- [ ] **Step 2:** Run both suites → FAIL.

- [ ] **Step 3: Implement.** `backend/spec.py`, after `SpeakerTurn`:

```python
ShotKind = Literal["two", "one", "none"]


class Shot(BaseModel):
    """One camera shot of the clip. faceIds refer to Reframe.faces; for a
    "two" shot they are ordered left to right (top panel first in split)."""
    start: float
    end: float
    kind: ShotKind
    faceIds: list[int]
```

and in `Reframe` add after `speakerTimeline`:

```python
    # Empty for clips analysed before shots existed; they render as before.
    shots: list[Shot] = Field(default_factory=list)
```

`renderer/src/schema.ts`: add before `clipSpecSchema`

```ts
export const shotSchema = z.object({
  start: z.number(),
  end: z.number(),
  kind: z.enum(['two', 'one', 'none']),
  faceIds: z.array(z.number().int()),
})
```

add `shots: z.array(shotSchema).default([]),` as the last field of the `reframe` object, and `export type Shot = z.infer<typeof shotSchema>` with the other type exports.

`scripts/make_fixture_spec.py`: in the `reframe` dict add
`"shots": [{"start": 0.0, "end": 4.0, "kind": "two", "faceIds": [0, 1]}, {"start": 4.0, "end": 8.0, "kind": "one", "faceIds": [1]}],`
then run `./.venv/Scripts/python scripts/make_fixture_spec.py`.

- [ ] **Step 4:** Python suite green; `cd renderer && npm test && npm run typecheck` green.
- [ ] **Step 5:** Commit `Add camera shots to the clip spec` (+ trailer), including the regenerated fixture.

---

### Task 3: Per-shot face analysis

**Files:** Modify `backend/pipeline/reframe.py`; tests in `tests/test_reframe.py`.

**Interfaces — Consumes:** `shots.split_shots` (Task 1), `spec.Shot` (Task 2). **Produces:** `analyze(frames, times, cuts: list[float] | None = None) -> Reframe` — `cuts=None` is today's behaviour exactly with `shots=[]`; a list (even empty) runs per-shot analysis. `choose_auto(frames, tracks, shots, speaker_switches: bool) -> LayoutKind` (`speaker_switches`: the talker changes inside at least one two-person shot; per-shot timelines are concatenated, so every cut adds a turn and the whole-clip turn count is not a signal). `choose_layout` keeps working for existing tests.

- [ ] **Step 1: Failing tests** — append to `tests/test_reframe.py`:

```python
def _wide_then_closeup():
    times = _times(8)
    frames = []
    for t in times:
        if t < 4.0:
            frames.append([Detection(0.3, 0.4, 0.12, 0.25, 0.1), Detection(0.72, 0.4, 0.12, 0.25, 0.1)])
        else:
            frames.append([Detection(0.5, 0.4, 0.25, 0.45, 0.1)])  # close-up, centred
    return frames, times


def test_analyze_without_cuts_has_no_shots():
    frames, times = _wide_then_closeup()
    assert reframe.analyze(frames, times).shots == []


def test_analyze_per_shot_tracks_and_kinds():
    frames, times = _wide_then_closeup()
    result = reframe.analyze(frames, times, cuts=[4.0])
    assert [(s.start, s.kind) for s in result.shots] == [(0.0, "two"), (4.0, "one")]
    left, right = result.shots[0].faceIds
    by_id = {f.id: f for f in result.faces}
    assert by_id[left].track[0].cx < by_id[right].track[0].cx  # left face first -> top panel
    closeup = result.shots[1].faceIds[0]
    assert closeup not in (left, right)  # tracking restarts at the cut
    for face in result.faces:  # no track spans the cut
        ts = [p.t for p in face.track]
        assert max(ts) < 4.0 or min(ts) >= 4.0
    assert result.auto == "split"  # two-person shot covers >= 50 %


def test_analyze_with_empty_cuts_is_one_shot():
    frames, times = _wide_then_closeup()
    result = reframe.analyze(frames[:20], times[:20], cuts=[])
    assert [(s.start, s.kind) for s in result.shots] == [(0.0, "two")]


def test_choose_auto_prefers_follow_when_mostly_closeups():
    times = _times(10)
    frames = [[Detection(0.3, 0.4, 0.12, 0.25, 0.1), Detection(0.72, 0.4, 0.12, 0.25, 0.1)] if t < 2 else
              [Detection(0.5, 0.4, 0.25, 0.45, 0.1)] for t in times]
    assert reframe.analyze(frames, times, cuts=[2.0]).auto == "follow"


def test_speaker_timeline_starts_each_shot_at_its_start():
    frames, times = _wide_then_closeup()
    result = reframe.analyze(frames, times, cuts=[4.0])
    closeup = result.shots[1].faceIds[0]
    assert any(turn.t == 4.0 and turn.faceId == closeup for turn in result.speakerTimeline)
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Implement** in `reframe.py`. Import `from . import shots as shot_ranges` and `Shot` from `..spec`. Extract the fit check from `choose_layout` into `_needs_fit(frames, tracks) -> bool` and use it in both. Add:

```python
def _shot_kind(tracks: list[_Track], n_samples: int) -> tuple[str, list[int]]:
    frequent = [tr for tr in tracks if len(tr.points) / n_samples >= TWO_FACE_PRESENCE]
    if len(frequent) >= 2:
        pair = sorted(frequent[:2], key=lambda tr: statistics.median(d.cx for _, d in tr.points))
        return "two", [tr.id for tr in pair]
    if tracks:
        return "one", [(frequent or tracks)[0].id]
    return "none", []


def choose_auto(
    frames: list[list[Detection]], tracks: list[_Track], shots: list[Shot], speaker_switches: bool
) -> LayoutKind:
    if _needs_fit(frames, tracks):
        return "fit"
    total = sum(s.end - s.start for s in shots) or 1.0
    two = sum(s.end - s.start for s in shots if s.kind == "two")
    if two / total >= 0.5:
        return "split"
    if speaker_switches:
        return "speaker"
    return "follow"
```

and change `analyze`:

```python
def analyze(frames: list[list[Detection]], times: list[float], cuts: list[float] | None = None) -> Reframe:
    if cuts is None:
        tracks = keep_main_tracks(build_tracks(frames, times), len(times))
        timeline = speaker_timeline(tracks, times)
        return Reframe(
            auto=choose_layout(frames, tracks, timeline),
            faces=[FaceTrack(id=tr.id, track=smooth(tr.points)) for tr in tracks],
            speakerTimeline=timeline,
        )

    all_tracks: list[_Track] = []
    timeline: list[SpeakerTurn] = []
    shots: list[Shot] = []
    speaker_switches = False
    for k, (i0, i1) in enumerate(shot_ranges.split_shots(times, cuts)):
        ts = times[i0:i1]
        tracks = keep_main_tracks(build_tracks(frames[i0:i1], ts), len(ts))
        base = len(all_tracks)
        for tr in tracks:
            tr.id += base  # ids unique across the whole clip
        start = 0.0 if k == 0 else ts[0]
        end = times[i1] if i1 < len(times) else ts[-1]
        kind, face_ids = _shot_kind(tracks, len(ts))
        shots.append(Shot(start=round(start, 3), end=round(end, 3), kind=kind, faceIds=face_ids))
        turns = speaker_timeline(tracks, ts)
        if kind == "two" and len(turns) > 1:
            speaker_switches = True
        for turn in turns:
            t = start if turn.t == 0.0 else turn.t
            if not timeline or timeline[-1].faceId != turn.faceId:
                timeline.append(SpeakerTurn(t=round(t, 3), faceId=turn.faceId))
        all_tracks.extend(tracks)

    all_tracks.sort(key=lambda tr: len(tr.points), reverse=True)
    return Reframe(
        auto=choose_auto(frames, all_tracks, shots, speaker_switches),
        faces=[FaceTrack(id=tr.id, track=smooth(tr.points)) for tr in all_tracks],
        speakerTimeline=timeline,
        shots=shots,
    )
```

Update the module docstring's pipeline line to mention shots.

- [ ] **Step 4:** New and existing reframe tests pass; full suite green.
- [ ] **Step 5:** Commit `Analyse faces per camera shot` (+ trailer).

---

### Task 4: Thumbnails from face sampling, cuts into clip prep

**Files:** Modify `backend/pipeline/face_detect.py`, `backend/pipeline/clipprep.py`, `tests/test_clipprep.py`, `tests/test_face_detect.py`.

**Interfaces — Produces:** `face_detect.sample_detections(...) -> tuple[list[list[Detection]], list[float], list[np.ndarray]]` (third item: one 18×32 float32 thumbnail 0–1 per sample, same order as times). `face_detect.thumbnail(frame_bgr) -> np.ndarray`.

- [ ] **Step 1: Failing tests.** In `tests/test_clipprep.py`, change the stub in `test_prepare_clip_builds_spec` to return thumbnails and assert one shot:

```python
    thumbs = [np.zeros((18, 32), dtype=np.float32) for _ in times]
    _patch_media(monkeypatch, lambda path, model, sample_fps=5.0: (frames, times, thumbs))
    ...
    assert [s.kind for s in spec.reframe.shots] == ["one"]
```

(add `import numpy as np`), and add:

```python
def test_prepare_clip_detects_a_camera_cut(tmp_path, monkeypatch):
    times = [round(i / 5, 3) for i in range(80)]
    frames = [[Detection(0.3, 0.4, 0.12, 0.25, 0.1), Detection(0.72, 0.4, 0.12, 0.25, 0.1)] if t < 9 else
              [Detection(0.5, 0.4, 0.25, 0.45, 0.1)] for t in times]
    thumbs = [np.full((18, 32), 0.2 if t < 9 else 0.7, dtype=np.float32) for t in times]
    _patch_media(monkeypatch, lambda path, model, sample_fps=5.0: (frames, times, thumbs))
    shots = _prepare(tmp_path).spec.reframe.shots
    assert [s.kind for s in shots] == ["two", "one"]
    assert shots[1].start == 8.0  # segment time 9.0 minus the 1.0 s offset
```

In `tests/test_face_detect.py` (slow test) unpack three values and assert `len(thumbs) == len(times)` and `thumbs[0].shape == (18, 32)`.

- [ ] **Step 2:** Run `tests/test_clipprep.py` → FAIL.

- [ ] **Step 3: Implement.** `face_detect.py`: add

```python
THUMB_W, THUMB_H = 32, 18


def thumbnail(frame_bgr) -> "np.ndarray":
    """Tiny grayscale copy of a sampled frame, used to detect camera cuts."""
    import cv2
    import numpy as np

    small = cv2.resize(frame_bgr, (THUMB_W, THUMB_H), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
```

collect `thumbs.append(thumbnail(frame))` next to `times.append(...)`, and return `frames, times, thumbs`. Update the docstring of `sample_detections`.

`clipprep.py` (import `shots` from `.`):

```python
        frames, times, thumbs = face_detect.sample_detections(local_path, face_detect.ensure_model(models_dir))
        # Keep only samples inside the clip itself, re-based to its start.
        kept = [(round(t - offset, 3), f, th) for t, f, th in zip(times, frames, thumbs)
                if offset <= t <= offset + duration]
        kept_times = [t for t, _, _ in kept]
        cuts = shots.cut_times([th for _, _, th in kept], kept_times)
        reframe_result = reframe.analyze([f for _, f, _ in kept], kept_times, cuts)
```

- [ ] **Step 4:** Full suite green (slow test not required: `-m slow` is optional and downloads a model).
- [ ] **Step 5:** Commit `Detect camera cuts during face sampling` (+ trailer).

---

### Task 5: Renderer picks the layout per shot

**Files:** Create `renderer/src/lib/shots.ts`, `renderer/src/lib/shots.test.ts`, `renderer/src/lib/view.ts`, `renderer/src/lib/view.test.ts`; modify `renderer/src/layouts/LayoutView.tsx`.

**Interfaces — Consumes:** `Shot`, `ClipSpec`, `Layout` from `../schema`; `activeFace` from `./speaker`. **Produces:** `activeShot(shots: Shot[], t: number): Shot | null`; `resolveView(spec: ClipSpec, layout: Layout, t: number): View` where `type View = { kind: 'fit' } | { kind: 'one'; faceId: number } | { kind: 'two'; topId: number; bottomId: number }`.

- [ ] **Step 1: Failing tests.** `renderer/src/lib/shots.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { activeShot } from './shots'

const shots = [
  { start: 0, end: 4, kind: 'two' as const, faceIds: [0, 1] },
  { start: 4, end: 8, kind: 'one' as const, faceIds: [2] },
]

describe('activeShot', () => {
  it('picks the latest shot starting at or before t', () => {
    expect(activeShot(shots, 0)?.kind).toBe('two')
    expect(activeShot(shots, 3.99)?.kind).toBe('two')
    expect(activeShot(shots, 4)?.kind).toBe('one')
    expect(activeShot(shots, 99)?.kind).toBe('one')
  })
  it('handles no shots', () => {
    expect(activeShot([], 1)).toBeNull()
  })
})
```

`renderer/src/lib/view.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import fixture from '../__fixtures__/clip-spec.json'
import { clipSpecSchema } from '../schema'
import { resolveView } from './view'

const spec = clipSpecSchema.parse(fixture) // faces 0 (x .30) and 1 (x .70); shots: two [0,1] 0-4, one [1] 4-8
const noShots = clipSpecSchema.parse({ ...fixture, reframe: { ...fixture.reframe, shots: [] } })

describe('resolveView with shots', () => {
  it('splits a two-person shot, left face on top', () => {
    expect(resolveView(spec, 'split', 1)).toEqual({ kind: 'two', topId: 0, bottomId: 1 })
  })
  it('shows one person full-frame in a close-up even when split is chosen', () => {
    expect(resolveView(spec, 'split', 5)).toEqual({ kind: 'one', faceId: 1 })
  })
  it('follow uses the shot main face', () => {
    expect(resolveView(spec, 'follow', 5)).toEqual({ kind: 'one', faceId: 1 })
  })
  it('speaker falls back to the shot face when the speaker is not in the shot', () => {
    // fixture timeline: face 0 from 0 s, face 1 from 4 s
    expect(resolveView(spec, 'speaker', 1)).toEqual({ kind: 'one', faceId: 0 })
    expect(resolveView(spec, 'speaker', 5)).toEqual({ kind: 'one', faceId: 1 })
  })
  it('a shot without faces fits', () => {
    const none = clipSpecSchema.parse({ ...fixture, reframe: { ...fixture.reframe, shots: [{ start: 0, end: 8, kind: 'none', faceIds: [] }] } })
    expect(resolveView(none, 'split', 1)).toEqual({ kind: 'fit' })
  })
  it('fit stays fit', () => {
    expect(resolveView(spec, 'fit', 1)).toEqual({ kind: 'fit' })
  })
})

describe('resolveView without shots (clips analysed before shots existed)', () => {
  it('split orders the first two faces by their first position', () => {
    expect(resolveView(noShots, 'split', 1)).toEqual({ kind: 'two', topId: 0, bottomId: 1 })
  })
  it('follow uses the most present face', () => {
    expect(resolveView(noShots, 'follow', 1)).toEqual({ kind: 'one', faceId: 0 })
  })
  it('speaker follows the timeline', () => {
    expect(resolveView(noShots, 'speaker', 5)).toEqual({ kind: 'one', faceId: 1 })
  })
})
```

- [ ] **Step 2:** `cd renderer && npm test` → FAIL.

- [ ] **Step 3: Implement.** `renderer/src/lib/shots.ts`:

```ts
import type { Shot } from '../schema'

export function activeShot(shots: Shot[], t: number): Shot | null {
  let current: Shot | null = null
  for (const shot of shots) {
    if (shot.start <= t) current = shot
    else break
  }
  return current ?? shots[0] ?? null
}
```

`renderer/src/lib/view.ts`:

```ts
import type { ClipSpec, Layout } from '../schema'
import { activeShot } from './shots'
import { activeFace } from './speaker'

// What the frame shows at time t. Clips with shots switch at each camera
// cut; clips analysed before shots existed keep the old whole-clip rules.
export type View = { kind: 'fit' } | { kind: 'one'; faceId: number } | { kind: 'two'; topId: number; bottomId: number }

export function resolveView(spec: ClipSpec, layout: Layout, t: number): View {
  const { faces, speakerTimeline, shots } = spec.reframe
  if (faces.length === 0 || layout === 'fit') return { kind: 'fit' }

  const shot = activeShot(shots, t)
  if (shot) {
    if (shot.kind === 'none' || shot.faceIds.length === 0) return { kind: 'fit' }
    if (layout === 'split' && shot.kind === 'two') return { kind: 'two', topId: shot.faceIds[0], bottomId: shot.faceIds[1] }
    if (layout === 'speaker') {
      const speaking = activeFace(speakerTimeline, t)
      if (speaking !== null && shot.faceIds.includes(speaking)) return { kind: 'one', faceId: speaking }
    }
    return { kind: 'one', faceId: shot.faceIds[0] }
  }

  if (layout === 'split' && faces.length >= 2) {
    const [top, bottom] = [faces[0], faces[1]].sort((a, b) => (a.track[0]?.cx ?? 0.5) - (b.track[0]?.cx ?? 0.5))
    return { kind: 'two', topId: top.id, bottomId: bottom.id }
  }
  if (layout === 'speaker') return { kind: 'one', faceId: activeFace(speakerTimeline, t) ?? faces[0].id }
  return { kind: 'one', faceId: faces[0].id }
}
```

`LayoutView.tsx`: replace the `effective` logic and the three branches so that it computes `const view = resolveView(spec, layout, t)` and renders: `fit` → the existing blurred-background JSX; `two` → the existing split JSX with `top`/`bottom` looked up by id (`faces.find(f => f.id === view.topId)`), top panel with audio, bottom `muted`; `one` → the existing single-crop JSX for `faces.find(f => f.id === view.faceId) ?? faces[0]`. Keep `PANEL_H`, `cropWindow`, `sampleTrack` usage unchanged. Remove the now-unused `activeFace` import from LayoutView.

- [ ] **Step 4:** `cd renderer && npm test && npm run typecheck` green; `cd frontend && npm run build` succeeds; Python suite unaffected.
- [ ] **Step 5:** Commit `Switch the clip layout at each camera shot` (+ trailer).

---

### Task 6: README

**Files:** Modify `README.md` ("Vertical clips and rendering" section).

- [ ] **Step 1:** After the paragraph that lists the layouts, add:

```markdown
Layouts follow the camera: face analysis detects cuts (a jump in a tiny
grayscale thumbnail between samples) and tracks faces per shot. Split
shows the left person on top and the right person below only during
wide two-person shots; close-ups show one person full-frame. Clips made
before this change keep their old behaviour until the video is re-run.
After changing anything in `renderer/src`, re-run `npm run deploy:site`
so Lambda exports use the same layout as the preview.
```

- [ ] **Step 2:** Full Python suite green. Commit `Document shot-aware layouts` (+ trailer).

---

## Spec coverage

| Spec item | Task |
|---|---|
| Cut detection 0.08 on 32×18 thumbnails, no extra decode | 1, 4 |
| Shots, merge < 0.6 s | 1 |
| Tracks per shot, ids unique | 3 |
| Shot kinds, left-to-right faceIds | 3 |
| Speaker timeline per shot | 3 |
| Auto layout rule | 3 |
| Renderer per-shot split/follow/speaker/fit | 5 |
| Old clips unchanged | 2, 3 (`cuts=None`), 5 (no-shots path) |
| Data contract `shots` | 2 |
| Deploy note | 6 |
| Real-footage check | controller, after Task 6 |
