# Piece 3a: Fix in Place Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user fix a clip without re-running the video: nudge its start/end instantly, grow or shrink it by a sentence, reset, swap it for a runner-up moment, regenerate it with one small LLM call, and download its captions as SRT.

**Architecture:** Clip prep cuts an 8 s spare window each side and stores words and face data for the whole window (spec v2, times from the file start). The renderer converts any spec to clip time in one place (`toClipTime`), so nudges only change `spec.start/end`. Shared TypeScript trim rules drive the UI; the backend enforces limits. Swap and Regenerate run in a background thread per clip and replace the clip in place.

**Tech Stack:** Python 3.11 / FastAPI / pytest; Remotion 4 (TypeScript, zod, vitest); Vue 3 + Pinia + Vite; Supabase migrations.

**Spec:** `docs/superpowers/specs/2026-09-27-fix-in-place-design.md`

## Global Constraints

- Branch `hinglish-v1`. **Never push.** Never `git stash`, `git reset` or `git commit --amend`. Never stage `renderer/package-lock.json`. Never kill or stop processes. Never enter passwords. Never call Groq, Supabase, R2 or AWS for real in tests or checks.
- Every commit message ends with a blank line then exactly: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- Python tests: `./.venv/Scripts/python -m pytest -q` from the repo root (baseline 336 passed). Renderer: `cd renderer && npm test && npm run typecheck`. Frontend: `cd frontend && npm run build`.
- Spare window: `SEGMENT_PAD_S = 8.0`. Clip length limits for nudges: 8–60 s. Nudge step 0.5 s. Sentence cuts: 0.22 s before the first word, 0.40 s after the last, never closer than 0.03 s to the previous word or 0.05 s to the next.
- Swap/Regenerate overlap rules: a new clip must overlap every *other* clip of the job by < 30 % (of the shorter one) and overlap the *current* clip by < 90 %. Regenerate looks 120 s either side of the clip.
- Caption presets stay `karaoke | pop | clean`.
- v1 specs keep working for preview, export, caption edits, SRT, swap and regenerate (which produce v2 clips), but cannot be trimmed.
- User-facing messages, verbatim: "No other moments left to swap in." / "No better take found around this moment." / "Re-run the video to trim this clip." / "Regenerate needs GROQ_KEY." / "Captions or trim changed after this export was requested. Export again."

## File map

| File | Status | Responsibility |
|---|---|---|
| `supabase/migrations/20260927120000_fix_in_place.sql` | create | new clip/job columns |
| `backend/pipeline/scoring.py` | modify | `span_overlap()` helper |
| `backend/pipeline/selection.py` | modify | `Clip.reason`, alternates, `regenerate()` |
| `backend/spec.py` | modify | spec v2 (`version` 1\|2, `source.duration`), `render_hash` bounds |
| `backend/pipeline/clipprep.py` | modify | 8 s window, whole-window words and faces |
| `scripts/make_fixture_spec.py`, `renderer/src/__fixtures__/clip-spec-v2.json` | modify/create | v2 fixture |
| `renderer/src/schema.ts` | modify | zod v2 |
| `renderer/src/lib/timeline.ts` | create | `toClipTime`, `fileDuration` |
| `renderer/src/ClipComposition.tsx` | modify | use `toClipTime` |
| `renderer/src/lib/trim.ts` | create | nudge / sentence rules |
| `renderer/src/__fixtures__/paginate-cases.json` | create | shared pagination cases |
| `backend/srt.py` | create | SRT builder (Python port of paginate) |
| `backend/captions.py` | modify | window-aware limit |
| `backend/render.py` | modify | bounds in the render hash check |
| `backend/main.py` | modify | bounds, swap, regenerate, SRT endpoints, status fields |
| `backend/db.py` | — | unchanged |
| `frontend/src/services/highlyteApi.js`, `stores/jobStore.js`, `components/ClipCard.vue`, `components/CaptionEditor.vue`, `components/TrimControls.vue` (create) | modify/create | UI |

---

### Task 1: Migration, selection alternates and regenerate

**Files:**
- Create: `supabase/migrations/20260927120000_fix_in_place.sql`
- Modify: `backend/pipeline/scoring.py`, `backend/pipeline/selection.py`
- Test: `tests/test_scoring.py`, `tests/test_selection.py`

**Interfaces:**
- Produces:
  - `scoring.span_overlap(a: tuple[float, float], b: tuple[float, float]) -> float` (shared length ÷ shorter length; 0 when disjoint or either is empty)
  - `selection.Clip.reason: str = ""`
  - `selection.Selection.alternates: list[dict]` (default `[]`), each `{"start","end","text","score","tag","flags","reason","emphasis"}`
  - `selection.alternate_to_clip(d: dict) -> Clip`
  - `selection.regenerate(segments, loudness, current: tuple[float, float], avoid: list[tuple[float, float]], *, chat=None) -> Clip | None` — raises `SelectionFailed` without a key or when every ranker window fails
  - constants `selection.MAX_ALTERNATES = 10`, `REGENERATE_MARGIN_S = 120.0`, `SAME_MOMENT_OVERLAP = 0.9`

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/20260927120000_fix_in_place.sql`:

```sql
-- Piece 3a, fix in place.
-- {start, end} of the clip before its first nudge, for Reset.
alter table clips add column if not exists bounds_original jsonb;
-- The ranker's one-line reason, shown on the clip card.
alter table clips add column if not exists reason text;
-- 'swap' | 'regenerate' while one runs in the background, else null.
alter table clips add column if not exists pending_action text;
-- The last swap/regenerate failure, shown on the clip card.
alter table clips add column if not exists action_error text;
-- Bumped when a clip is replaced, so browsers reload its file.
alter table clips add column if not exists revision integer not null default 0;
-- Runner-up moments from clip selection, for Swap scene.
alter table jobs add column if not exists alternates jsonb not null default '[]'::jsonb;
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_scoring.py`:

```python
def test_span_overlap():
    assert scoring.span_overlap((0, 20), (10, 20)) == 1.0
    assert scoring.span_overlap((0, 20), (15, 35)) == 0.25
    assert scoring.span_overlap((0, 20), (30, 50)) == 0.0
    assert scoring.span_overlap((0, 0), (0, 10)) == 0.0
```

Append to `tests/test_selection.py`:

```python
def test_select_keeps_reason_and_runner_ups():
    from tests.llm_fakes import FakeChat

    # 6 thoughts, all picked: packing keeps them all (max 8), so no runner-ups;
    # then a duplicate pick of u1 is the only runner-up candidate and is
    # dropped because it overlaps a kept clip.
    ranked = json.dumps([pick(f"u{i}", f"u{i}") for i in range(1, 7)] + [pick("u1", "u1", hook=0.6)])
    result = selection.select(transcript(6), [], chat=FakeChat([ranked, "[]"]))
    assert len(result.clips) == 6
    assert result.clips[0].reason == "r"
    assert result.alternates == []


def test_select_stores_runner_ups_best_first():
    from tests.llm_fakes import FakeChat

    ranked = json.dumps([pick(f"u{i}", f"u{i}", payoff=0.1 * i) for i in range(1, 11)])
    result = selection.select(transcript(10), [], chat=FakeChat([ranked, "[]"]))
    assert len(result.clips) == 8
    assert [round(a["start"]) for a in result.alternates] == [25, 0]
    alt = result.alternates[0]
    assert set(alt) == {"start", "end", "text", "score", "tag", "flags", "reason", "emphasis"}
    assert alt["reason"] == "r" and alt["emphasis"] == ["baat"]
    clip = selection.alternate_to_clip(alt)
    assert (clip.start, clip.end, clip.reason) == (alt["start"], alt["end"], "r")


def test_regenerate_picks_a_different_nearby_moment():
    from tests.llm_fakes import FakeChat

    segs = transcript(6)                        # thoughts at 0, 25, 50, 75, 100, 125 s
    ranked = json.dumps([pick("u3", "u3"), pick("u4", "u4", hook=0.9)])
    chat = FakeChat([ranked, json.dumps([{"id": "c1", "hook_title": "Naya", "emphasis": [], "tag": "Key insight"}])])
    clip = selection.regenerate(segs, [], current=(49.78, 70.35), avoid=[(99.78, 120.35)], chat=chat)
    assert clip is not None
    assert round(clip.start) == 75 and clip.hook_title == "Naya"   # u3 is the current moment
    # only units within 120 s of the clip are shown to the ranker
    assert "u1:" in chat.prompts[0] and "u6:" in chat.prompts[0]


def test_regenerate_returns_none_when_nothing_new():
    from tests.llm_fakes import FakeChat

    chat = FakeChat([json.dumps([pick("u3", "u3")])])
    assert selection.regenerate(transcript(6), [], current=(49.78, 70.35), avoid=[], chat=chat) is None


def test_regenerate_without_key(monkeypatch):
    monkeypatch.setenv("GROQ_KEY", "")
    with pytest.raises(selection.SelectionFailed):
        selection.regenerate(transcript(3), [], current=(0, 20), avoid=[])
```

`transcript(n)`, `pick(...)` and `thought(...)` already exist at the top of `tests/test_selection.py`. In `test_select_stores_runner_ups_best_first`, all ten picks pass the thresholds; totals rise with payoff, so packing keeps u3–u10 (8 clips) and u1/u2 are the runner-ups, best (u2, start 25) first.

- [ ] **Step 3: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest -q tests/test_scoring.py tests/test_selection.py`
Expected: FAIL (`span_overlap`, `reason`, `alternates`, `alternate_to_clip`, `regenerate` missing).

- [ ] **Step 4: Implement**

In `backend/pipeline/scoring.py`, add above `overlap_ratio` and make `overlap_ratio` use it:

```python
def span_overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Shared length of two time spans as a share of the shorter one."""
    shortest = min(a[1] - a[0], b[1] - b[0])
    shared = min(a[1], b[1]) - max(a[0], b[0])
    if shortest <= 0 or shared <= 0:
        return 0.0
    return shared / shortest


def overlap_ratio(a: Candidate, b: Candidate) -> float:
    return span_overlap((a.start, a.end), (b.start, b.end))
```

In `backend/pipeline/selection.py`:

1. Add constants after `TITLES_FAILED_NOTE` / `ZERO_CLIPS_NOTE`:

```python
MAX_ALTERNATES = 10
REGENERATE_MARGIN_S = 120.0
SAME_MOMENT_OVERLAP = 0.9
```

2. Add `reason: str = ""` as the last field of `Clip`, and `alternates: list[dict] = field(default_factory=list)` as the last field of `Selection`.

3. Extract the candidate loop in `select()` into a helper and use it there:

```python
def _candidates(words, units, picks, loudness) -> list[scoring.Candidate]:
    out: list[scoring.Candidate] = []
    for p in picks:
        first = units[p.first_unit].utterances[0].first
        last = units[p.last_unit].utterances[-1].last
        try:
            cut = snap.snap(words, first, last)
        except snap.Reject:
            continue
        c = scoring.Candidate(
            start=cut.start, end=cut.end, words=words[cut.first:cut.last + 1],
            standalone=p.standalone, hook=p.hook, payoff=p.payoff, reason=p.reason,
        )
        if scoring.structural_reject(c):
            continue
        out.append(scoring.score(c, loudness))
    return out


def _text(c: scoring.Candidate) -> str:
    return " ".join(w.t for w in c.words)


def _to_clip(c: scoring.Candidate, meta: titles.Titles) -> Clip:
    flags = [*scoring.qa_flags(c), *c.flags]
    if not scoring.passes_thresholds(c) and "weak_pick" not in flags:
        flags.append("weak_pick")
    return Clip(
        start=c.start, end=c.end, text=_text(c), score=round(c.total * 10, 1), tag=meta.tag,
        hook_title=meta.hook_title, emphasis=meta.emphasis, flags=flags,
        standalone=c.standalone, hook=c.hook, payoff=c.payoff,
        energy=c.energy, duration_fit=c.duration_fit, reason=c.reason,
    )


def _alternates(candidates: list[scoring.Candidate], kept: list[scoring.Candidate]) -> list[dict]:
    out: list[dict] = []
    chosen: list[tuple[float, float]] = [(k.start, k.end) for k in kept]
    for i, c in enumerate(sorted(candidates, key=lambda c: c.total, reverse=True)):
        if len(out) >= MAX_ALTERNATES:
            break
        span = (c.start, c.end)
        if any(scoring.span_overlap(span, s) >= scoring.MAX_OVERLAP for s in chosen):
            continue
        chosen.append(span)
        clip = _to_clip(c, titles.fallback(_text(c), i))
        out.append({
            "start": clip.start, "end": clip.end, "text": clip.text, "score": clip.score,
            "tag": clip.tag, "flags": clip.flags, "reason": clip.reason, "emphasis": clip.emphasis,
        })
    return out


def alternate_to_clip(d: dict) -> Clip:
    return Clip(
        start=float(d["start"]), end=float(d["end"]), text=d.get("text", ""), score=float(d.get("score", 0.0)),
        tag=d.get("tag") or titles.TAGS[0], emphasis=list(d.get("emphasis") or []),
        flags=list(d.get("flags") or []), reason=d.get("reason", ""),
    )
```

   In `select()`, replace the candidate loop with `candidates = _candidates(words, units, ranked.picks, loudness)`, keep `kept = scoring.pack(candidates)`, build clips with `[_to_clip(c, m) for c, m in zip(kept, meta)]` where `meta, titles_ok = titles.write_titles(chat, [_text(c) for c in kept])`, and return `Selection(clips, note, alternates=_alternates(candidates, kept))`. Keep the existing note logic exactly. Note `_to_clip` must not add `weak_pick` twice for near-miss fills (they already carry it) — the `not in flags` check handles that.

4. Add `regenerate()`:

```python
def regenerate(
    segments: list[Segment], loudness: list[float], current: tuple[float, float],
    avoid: list[tuple[float, float]], *, chat=None,
) -> Clip | None:
    """A fresh take on one clip: re-rank the transcript around it and pick
    the best candidate that is not the same moment and does not collide
    with the job's other clips."""
    if chat is None:
        chat = groq_llm.build_chat()
    if chat is None:
        raise SelectionFailed("Regenerate needs GROQ_KEY.")
    utterances = build_utterances(segments)
    if not utterances:
        return None
    units = [u for u in build_thought_units(utterances)
             if u.end >= current[0] - REGENERATE_MARGIN_S and u.start <= current[1] + REGENERATE_MARGIN_S]
    if not units:
        return None
    ranked = ranker.rank(chat, units)
    words = flat_words(utterances)
    fresh = [
        c for c in _candidates(words, units, ranked.picks, loudness)
        if scoring.span_overlap((c.start, c.end), current) < SAME_MOMENT_OVERLAP
        and all(scoring.span_overlap((c.start, c.end), a) < scoring.MAX_OVERLAP for a in avoid)
    ]
    usable = [c for c in fresh if scoring.passes_thresholds(c)] or [c for c in fresh if scoring.near_miss(c)]
    if not usable:
        return None
    best = max(usable, key=lambda c: c.total)
    meta, _ = titles.write_titles(chat, [_text(best)])
    return _to_clip(best, meta[0])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/20260927120000_fix_in_place.sql backend/pipeline/scoring.py backend/pipeline/selection.py tests/test_scoring.py tests/test_selection.py
git commit -m "Keep runner-up moments and add regenerate to clip selection

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Spec v2 in the backend and an 8 s window in clip prep

**Files:**
- Modify: `backend/spec.py`, `backend/pipeline/clipprep.py`, `scripts/make_fixture_spec.py`
- Create: `renderer/src/__fixtures__/clip-spec-v2.json` (generated)
- Test: `tests/test_clipprep.py`, `tests/test_spec.py`

**Interfaces:**
- Produces: `ClipSpec.version: Literal[1, 2]` (default `2`); `Source.duration: float | None = None`; `spec.window_duration(spec: dict) -> float | None` (v2: `source.duration`; v1: `None`); `spec.render_hash(style, words, bounds: tuple[float, float] | None = None)`; clip prep writes v2 specs; `clipprep.SEGMENT_PAD_S = 8.0`; fixture `clip-spec-v2.json`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_clipprep.py`:
- replace `test_segment_bounds_pads_and_clamps` with:

```python
def test_segment_bounds_pads_and_clamps():
    assert clipprep.segment_bounds(11.0, 40.0, 100.0) == (3.0, 48.0)
    assert clipprep.segment_bounds(0.4, 20.0, 20.5) == (0.0, 20.5)
    assert clipprep.segment_bounds(5.0, 20.0, 0.0) == (0.0, 28.0)  # unknown duration: no clamp
```

- in `test_prepare_clip_builds_spec`, change the comment to `# segment starts at 3.0, so the clip starts 8.0 s into it` and replace the assertions from `assert (spec.start, spec.end)` through `assert track[0].t == 0.0 ...` with:

```python
    assert spec.version == 2
    assert (spec.start, spec.end) == (8.0, 22.0)
    assert spec.source.duration == 30.0          # segment 3.0-33.0
    assert spec.source.width == 1920 and spec.source.url == ""
    assert [(w.text, w.start, w.emphasis) for w in spec.words] == [("hey", 8.2, True), ("there", 8.5, False)]
    assert spec.wordsApprox is False
    assert spec.hookTitle == "Hook"
    assert spec.viralityScore == 10.0  # clamped
    assert spec.reframe.auto == "follow"
    track = spec.reframe.faces[0].track
    assert track[0].t == 0.0 and track[-1].t > 14.0  # whole window, file time (no longer trimmed to the clip)
```

- in `test_prepare_clip_detects_a_camera_cut`, replace the last comment and assertion with:

```python
    # cut sample at segment time 9.0, previous sample at 8.8 -> midpoint 8.9 (file time)
    assert shots[1].start == 8.9
```

- in `test_prepare_clip_reports_no_face_at_the_start`, change the comment to `# clip starts at segment time 8.0; no face until segment time 10.0` and the frames line to `frames = [[] if t < 10.0 else [Detection(0.5, 0.4, 0.2, 0.3, 0.1)] for t in times]`.

Append to `tests/test_spec.py`:

```python
def test_v2_fixture_round_trips_and_has_window():
    import json, os
    from backend.spec import ClipSpec, window_duration

    path = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec-v2.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    spec = ClipSpec.model_validate(data)
    assert spec.version == 2 and spec.source.duration == 12.0
    assert window_duration(data) == 12.0
    assert window_duration({**data, "version": 1}) is None


def test_render_hash_changes_with_bounds():
    from backend.spec import ClipStyle, Word, render_hash

    style, words = ClipStyle(layout="fit"), [Word(text="a", start=0, end=1)]
    assert render_hash(style, words) == render_hash(style, words, None)
    assert render_hash(style, words, (1.0, 9.0)) != render_hash(style, words, (1.5, 9.0))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest -q tests/test_clipprep.py tests/test_spec.py`
Expected: FAIL.

- [ ] **Step 3: Implement spec.py**

- Update the module docstring's last paragraph to: `All times are seconds. start/end are positions inside the padded source segment (the cut file). In version 2, word, face-track, speaker and shot times are also positions inside the cut file and cover the whole file; in version 1 they covered only the clip and were relative to start. The renderer converts both to clip time (renderer/src/lib/timeline.ts).`
- `Source`: add `duration: float | None = Field(None, gt=0)  # seconds of the cut file; v2 only`.
- `ClipSpec.version`: `version: Literal[1, 2] = 2`.
- Add after `ClipSpec`:

```python
def window_duration(spec: dict) -> float | None:
    """Length of a v2 clip's cut file, which bounds nudges and caption
    times. None for v1 clips, which cannot be trimmed."""
    if spec.get("version") != 2:
        return None
    duration = (spec.get("source") or {}).get("duration")
    return float(duration) if duration else None
```

- Replace `render_hash`:

```python
def render_hash(style: ClipStyle, words: list[Word], bounds: tuple[float, float] | None = None) -> str:
    """Fingerprint of everything an export depends on that a user can
    change: the style, the caption words and (once clips can be trimmed)
    the clip's bounds. Editing any of them must not reuse the old mp4."""
    payload: dict = {"style": style.model_dump(), "words": [w.model_dump() for w in words]}
    if bounds is not None:
        payload["bounds"] = [round(bounds[0], 3), round(bounds[1], 3)]
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: Implement clipprep.py**

- `SEGMENT_PAD_S = 8.0` with comment `# Spare source video either side of the clip: nudges and "include the next sentence" stay inside it, so they never need a re-cut.`
- In `prepare_clip`:
  - `clip_word_list = words.clip_words(segments, seg_start, seg_end, clip.emphasis)` (words for the whole file, file time).
  - In the framing `try`, stop filtering and re-basing samples: use all `times`, `frames`, `thumbs` as returned (they are already file time). `face_at_start` checks samples with `offset <= t <= offset + FACE_START_S`:

```python
        frames, times, thumbs = face_detect.sample_detections(local_path, face_detect.ensure_model(models_dir))
        opening = [f for t, f in zip(times, frames) if offset <= t <= offset + FACE_START_S]
        face_at_start = any(len(f) > 0 for f in opening) if opening else None
        cuts = shots.cut_times(thumbs, times)
        reframe_result = reframe.analyze(frames, times, cuts)
```

  - `ClipSpec(...)`: add `version=2`, and `source=Source(url="", width=width, height=height, fps=fps, duration=round(seg_end - seg_start, 3))`.
- Update the module docstring's last sentence to mention the spare window.

- [ ] **Step 5: Regenerate fixtures**

In `scripts/make_fixture_spec.py`:
- In `build()`, pass `"version": 1` in the dict so the existing fixture stays v1 (its times are clip-relative).
- Add `OUT_V2` beside `OUT` (`clip-spec-v2.json`) and a `build_v2()` that returns the same clip as a v2 spec: every time shifted by `+2.0` (words, track `t`, speaker `t`, shot `start/end`), `"start": 2.0`, `"end": 10.0`, `"version": 2`, `source.duration = 12.0`, plus two extra words outside the clip: `{"text": "Pehle.", "start": 0.5, "end": 1.0}` at the front and `{"text": "Baad.", "start": 10.6, "end": 11.2}` at the end; tracks extended to cover 0–12 s (`t / 5` for `t in range(0, 61)`).
- `__main__` writes both files.

Run: `./.venv/Scripts/python scripts/make_fixture_spec.py`
Expected: prints two `wrote ...` lines; `git diff renderer/src/__fixtures__/clip-spec.json` shows only an added `"duration": null` under `source` (the new optional field) and `"version": 1` unchanged.

- [ ] **Step 6: Run tests**

Run: `./.venv/Scripts/python -m pytest -q` and `cd renderer && npm test`
Expected: all pass (the renderer still accepts the v1 fixture; the v2 fixture is not read by TS yet).

- [ ] **Step 7: Commit**

```bash
git add backend/spec.py backend/pipeline/clipprep.py scripts/make_fixture_spec.py renderer/src/__fixtures__/clip-spec.json renderer/src/__fixtures__/clip-spec-v2.json tests/test_clipprep.py tests/test_spec.py
git commit -m "Cut an 8 s spare window per clip and write spec v2

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Renderer: spec v2 and clip time

**Files:**
- Modify: `renderer/src/schema.ts`, `renderer/src/ClipComposition.tsx`
- Create: `renderer/src/lib/timeline.ts`, `renderer/src/lib/timeline.test.ts`
- Test: `renderer/src/schema.test.ts`

**Interfaces:**
- Consumes: `renderer/src/__fixtures__/clip-spec-v2.json` (Task 2).
- Produces: zod `version: 1 | 2`, `source.duration` optional; `toClipTime(spec: ClipSpec): ClipSpec` (v1 → unchanged; v2 → every time minus `start`, words limited to those overlapping `[start, end]`, shots clipped to `[0, end-start]`); `fileDuration(spec): number | null` (v2 `source.duration`, else null).

- [ ] **Step 1: Write the failing tests**

Create `renderer/src/lib/timeline.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import v1 from '../__fixtures__/clip-spec.json'
import v2 from '../__fixtures__/clip-spec-v2.json'
import { clipSpecSchema } from '../schema'
import { fileDuration, toClipTime } from './timeline'

const spec1 = clipSpecSchema.parse(v1)
const spec2 = clipSpecSchema.parse(v2)

describe('toClipTime', () => {
  it('leaves v1 specs alone', () => {
    expect(toClipTime(spec1)).toBe(spec1)
  })
  it('matches the v1 fixture once a v2 spec is converted', () => {
    const clip = toClipTime(spec2)
    expect(clip.words.map(w => w.text)).toEqual(spec1.words.map(w => w.text))
    expect(clip.words[0].start).toBeCloseTo(spec1.words[0].start, 3)
    expect(clip.reframe.speakerTimeline).toEqual(spec1.reframe.speakerTimeline)
    expect(clip.reframe.shots).toEqual(spec1.reframe.shots)
    expect(clip.reframe.faces[0].track.find(p => Math.abs(p.t) < 1e-9)?.cx).toBe(0.3)
  })
  it('drops words outside the clip', () => {
    const texts = toClipTime(spec2).words.map(w => w.text)
    expect(texts).not.toContain('Pehle.')
    expect(texts).not.toContain('Baad.')
  })
})

describe('fileDuration', () => {
  it('is known only for v2', () => {
    expect(fileDuration(spec2)).toBe(12)
    expect(fileDuration(spec1)).toBeNull()
  })
})
```

Append to `renderer/src/schema.test.ts`:

```ts
import v2fixture from './__fixtures__/clip-spec-v2.json'

describe('spec v2', () => {
  it('parses the Python-generated v2 fixture', () => {
    const parsed = clipSpecSchema.parse(v2fixture)
    expect(parsed.version).toBe(2)
    expect(parsed.source.duration).toBe(12)
  })
})
```

(Match the file's existing `describe`/`it` import style; add imports at the top.)

- [ ] **Step 2: Run to verify failure**

Run: `cd renderer && npm test`
Expected: FAIL (`timeline` missing; schema rejects `version: 2`).

- [ ] **Step 3: Implement**

In `renderer/src/schema.ts`: `version: z.union([z.literal(1), z.literal(2)])`, and `source` gains `duration: z.number().positive().nullable().optional()`. Update the header comment to mention v2.

Create `renderer/src/lib/timeline.ts`:

```ts
import type { ClipSpec } from '../schema'

// Spec v2 stores words and face data for the whole cut file (times from the
// file start) so a clip can be nudged without a re-cut. Everything that
// draws a clip works in clip time (0 = the clip's first frame), so v2 specs
// are converted here, in one place. v1 specs are already in clip time.
export function toClipTime(spec: ClipSpec): ClipSpec {
  if (spec.version !== 2) return spec
  const { start, end } = spec
  const length = end - start
  const shift = (t: number) => Math.round((t - start) * 1000) / 1000
  return {
    ...spec,
    words: spec.words
      .filter(w => w.end > start && w.start < end)
      .map(w => ({ ...w, start: shift(w.start), end: shift(w.end) })),
    reframe: {
      ...spec.reframe,
      faces: spec.reframe.faces.map(f => ({ ...f, track: f.track.map(p => ({ ...p, t: shift(p.t) })) })),
      speakerTimeline: spec.reframe.speakerTimeline.map(s => ({ ...s, t: shift(s.t) })),
      shots: (spec.reframe.shots ?? [])
        .filter(s => s.end > start && s.start < end)
        .map(s => ({ ...s, start: Math.max(0, shift(s.start)), end: Math.min(length, shift(s.end)) })),
    },
  }
}

export function fileDuration(spec: ClipSpec): number | null {
  return spec.version === 2 && spec.source.duration ? spec.source.duration : null
}
```

In `renderer/src/ClipComposition.tsx`: `const clip = toClipTime(spec)` at the top of the component (wrap in `useMemo(() => toClipTime(spec), [spec])`), and pass `clip` wherever `spec` is used for `captionPositionAt`, `Captions words` and `LayoutView`. `LayoutView` still needs `spec.start` for `trimBefore` — `toClipTime` keeps `start`/`end` unchanged, so passing `clip` is correct.

- [ ] **Step 4: Verify**

Run: `cd renderer && npm test && npm run typecheck`
Expected: all pass. Then `cd frontend && npm run build` (the preview imports the composition).

- [ ] **Step 5: Commit**

```bash
git add renderer/src/schema.ts renderer/src/schema.test.ts renderer/src/lib/timeline.ts renderer/src/lib/timeline.test.ts renderer/src/ClipComposition.tsx
git commit -m "Render spec v2 by converting it to clip time in one place

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Trim rules

**Files:**
- Create: `renderer/src/lib/trim.ts`, `renderer/src/lib/trim.test.ts`

**Interfaces:**
- Consumes: `fileDuration` (Task 3), `Word`/`ClipSpec` types.
- Produces:
  - `type Bounds = { start: number; end: number }`
  - `type Move = { ok: true; bounds: Bounds } | { ok: false; reason: string }`
  - `canTrim(spec): boolean` (v2 with a known file duration)
  - `nudge(spec, edge: 'start' | 'end', deltaS: number): Move`
  - `sentence(spec, edge: 'start' | 'end', dir: -1 | 1): Move` — moves that edge to the previous (−1) / next (+1) sentence boundary
  - constants `MIN_CLIP_S = 8`, `MAX_CLIP_S = 60`, `NUDGE_S = 0.5`, `LEAD_S = 0.22`, `AIR_S = 0.4`, `PREV_GUARD_S = 0.03`, `NEXT_GUARD_S = 0.05`

Rules:
- Both functions return `{ ok: false, reason: 'Re-run the video to trim this clip.' }` when `!canTrim(spec)`.
- Result must satisfy `0 ≤ start < end ≤ fileDuration` and `MIN_CLIP_S ≤ end − start ≤ MAX_CLIP_S`; otherwise `{ ok: false, reason }` with `'Clips must be at least 8 s.'`, `'Clips can be at most 60 s.'` or `'That is the edge of the spare video.'`.
- `nudge` rounds to 3 decimals and clamps into the file; if clamping leaves bounds unchanged it returns the edge reason.
- Sentence boundaries: a sentence ends at a word whose text ends in `.`, `?` or `!`; the next sentence starts at the following word. For `edge='start'`: candidate starts are words that begin a sentence (the first word of the file counts). `dir=-1` picks the nearest sentence start strictly before the word the clip currently starts on (the first word with `start >= spec.start - 1e-6`); `dir=+1` the nearest one strictly after it. The new start cut = `max(word.start − LEAD_S, prevWord.end + PREV_GUARD_S, 0)`, never after `word.start`. For `edge='end'`: candidates are sentence-ending words; the current last word is the last with `end <= spec.end + 1e-6`; `dir=+1` the nearest sentence end strictly after it, `dir=-1` strictly before it. New end = `min(word.end + AIR_S, nextWord.start − NEXT_GUARD_S, fileDuration)`, never before `word.end`. No candidate: `'No earlier sentence in the spare video.'` / `'No later sentence in the spare video.'`.

- [ ] **Step 1: Write the failing tests**

Create `renderer/src/lib/trim.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { ClipSpec, Word } from '../schema'
import { canTrim, nudge, sentence } from './trim'

// Three sentences in a 40 s file. Word i of a sentence starting at `from`
// runs from + 0.9*i to from + 0.9*i + 0.8, so S1 is 1.0-9.9, S2 11.0-19.9,
// S3 21.0-29.9. The clip is S2 cut the snap.py way: 10.78-20.3.
function words(): Word[] {
  const out: Word[] = []
  for (const [from, n] of [[1, 'a'], [11, 'b'], [21, 'c']] as const) {
    for (let i = 0; i < 10; i++) {
      const start = from + i * 0.9
      out.push({ text: i === 9 ? `${n}${i}.` : `${n}${i}`, start, end: start + 0.8 })
    }
  }
  return out
}

function spec(over: Partial<ClipSpec> = {}): ClipSpec {
  return {
    version: 2, clipId: 'x-0', source: { url: '', width: 1920, height: 1080, fps: 30, duration: 40 },
    start: 10.78, end: 20.3, words: words(), wordsApprox: false, hookTitle: null, viralityScore: 5,
    reframe: { auto: 'fit', faces: [], speakerTimeline: [], shots: [] },
    ...over,
  } as ClipSpec
}

describe('canTrim', () => {
  it('needs a v2 spec with a file duration', () => {
    expect(canTrim(spec())).toBe(true)
    expect(canTrim(spec({ version: 1 } as Partial<ClipSpec>))).toBe(false)
    expect(nudge(spec({ version: 1 } as Partial<ClipSpec>), 'start', 0.5)).toEqual({ ok: false, reason: 'Re-run the video to trim this clip.' })
  })
})

describe('nudge', () => {
  it('moves one edge by the step', () => {
    expect(nudge(spec(), 'end', 0.5)).toEqual({ ok: true, bounds: { start: 10.78, end: 20.8 } })
    expect(nudge(spec(), 'start', -0.5)).toEqual({ ok: true, bounds: { start: 10.28, end: 20.3 } })
  })
  it('refuses a clip under 8 s', () => {
    expect(nudge(spec({ start: 11, end: 19 }), 'start', 0.5)).toEqual({ ok: false, reason: 'Clips must be at least 8 s.' })
  })
  it('stops at the file edge', () => {
    expect(nudge(spec({ start: 0, end: 10 }), 'start', -0.5)).toEqual({ ok: false, reason: 'That is the edge of the spare video.' })
  })
})

describe('sentence', () => {
  it('includes the next sentence', () => {
    // S3's last word ends 29.9; +0.4 air, nothing after it
    expect(sentence(spec(), 'end', 1)).toEqual({ ok: true, bounds: { start: 10.78, end: 30.3 } })
  })
  it('includes the previous sentence', () => {
    // S1's first word starts 1.0; -0.22 lead
    expect(sentence(spec(), 'start', -1)).toEqual({ ok: true, bounds: { start: 0.78, end: 20.3 } })
  })
  it('drops the last sentence', () => {
    expect(sentence(spec({ start: 10.78, end: 30.3 }), 'end', -1)).toEqual({ ok: true, bounds: { start: 10.78, end: 20.3 } })
  })
  it('refuses when there is none', () => {
    expect(sentence(spec({ start: 0.78, end: 30.3 }), 'start', -1)).toEqual({ ok: false, reason: 'No earlier sentence in the spare video.' })
  })
})
```

Checks on "drops the last sentence": with end 30.3 the current last word is `c9.` (index 29); the nearest sentence end before it is `b9.` (index 19, ends 19.9); the next word starts 21.0, so end = min(19.9 + 0.4, 21.0 − 0.05) = 20.3.

- [ ] **Step 2: Run to verify failure**

Run: `cd renderer && npx vitest run src/lib/trim.test.ts`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `renderer/src/lib/trim.ts`**

```ts
import type { ClipSpec } from '../schema'
import { fileDuration } from './timeline'

export const MIN_CLIP_S = 8
export const MAX_CLIP_S = 60
export const NUDGE_S = 0.5
export const LEAD_S = 0.22
export const AIR_S = 0.4
export const PREV_GUARD_S = 0.03
export const NEXT_GUARD_S = 0.05

export type Bounds = { start: number; end: number }
export type Move = { ok: true; bounds: Bounds } | { ok: false; reason: string }

const EDGE = 'That is the edge of the spare video.'
const ENDS = /[.?!]["')\]]?$/
const r3 = (n: number) => Math.round(n * 1000) / 1000

export const canTrim = (spec: ClipSpec) => fileDuration(spec) !== null

function check(spec: ClipSpec, b: Bounds): Move {
  const file = fileDuration(spec) as number
  if (b.start < 0 || b.end > file + 1e-6) return { ok: false, reason: EDGE }
  if (b.end - b.start < MIN_CLIP_S - 1e-6) return { ok: false, reason: 'Clips must be at least 8 s.' }
  if (b.end - b.start > MAX_CLIP_S + 1e-6) return { ok: false, reason: 'Clips can be at most 60 s.' }
  return { ok: true, bounds: { start: r3(b.start), end: r3(b.end) } }
}

export function nudge(spec: ClipSpec, edge: 'start' | 'end', deltaS: number): Move {
  if (!canTrim(spec)) return { ok: false, reason: 'Re-run the video to trim this clip.' }
  const file = fileDuration(spec) as number
  const b = { start: spec.start, end: spec.end }
  if (edge === 'start') b.start = Math.min(Math.max(0, r3(b.start + deltaS)), b.end)
  else b.end = Math.max(Math.min(file, r3(b.end + deltaS)), b.start)
  if (b.start === spec.start && b.end === spec.end) return { ok: false, reason: EDGE }
  return check(spec, b)
}

export function sentence(spec: ClipSpec, edge: 'start' | 'end', dir: -1 | 1): Move {
  if (!canTrim(spec)) return { ok: false, reason: 'Re-run the video to trim this clip.' }
  const words = spec.words
  const file = fileDuration(spec) as number
  const none = dir < 0 ? 'No earlier sentence in the spare video.' : 'No later sentence in the spare video.'
  if (edge === 'start') {
    const starts = words.map((w, i) => i).filter(i => i === 0 || ENDS.test(words[i - 1].text))
    const current = words.findIndex(w => w.start >= spec.start - 1e-6)
    const pickI = dir < 0 ? [...starts].reverse().find(i => i < current) : starts.find(i => i > current)
    if (pickI === undefined || current < 0) return { ok: false, reason: none }
    const w = words[pickI]
    let t = w.start - LEAD_S
    if (pickI > 0) t = Math.max(t, words[pickI - 1].end + PREV_GUARD_S)
    return check(spec, { start: Math.min(Math.max(t, 0), w.start), end: spec.end })
  }
  const ends = words.map((w, i) => i).filter(i => ENDS.test(words[i].text))
  let current = -1
  words.forEach((w, i) => { if (w.end <= spec.end + 1e-6) current = i })
  const pickI = dir > 0 ? ends.find(i => i > current) : [...ends].reverse().find(i => i < current)
  if (pickI === undefined) return { ok: false, reason: none }
  const w = words[pickI]
  let t = w.end + AIR_S
  if (pickI < words.length - 1) t = Math.min(t, words[pickI + 1].start - NEXT_GUARD_S)
  return check(spec, { start: spec.start, end: Math.max(Math.min(t, file), w.end) })
}
```

- [ ] **Step 4: Verify**

Run: `cd renderer && npm test && npm run typecheck`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add renderer/src/lib/trim.ts renderer/src/lib/trim.test.ts
git commit -m "Add trim rules: nudges and sentence steps inside the spare window

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: SRT export builder

**Files:**
- Create: `backend/srt.py`, `renderer/src/__fixtures__/paginate-cases.json`, `tests/test_srt.py`
- Modify: `renderer/src/captions/paginate.test.ts`

**Interfaces:**
- Produces: `srt.paginate(words: list[dict], max_words: int, max_chars: float) -> list[list[int]]` (word index groups, mirroring `paginate.ts`); `srt.clip_words(spec: dict) -> list[dict]` (clip-time words; same rule as `toClipTime`); `srt.build_srt(spec: dict) -> str`; constants `LINE_MAX_WORDS = 14`, `LINE_MAX_CHARS = 84`, `PAUSE_BREAK_S = 0.4`.

- [ ] **Step 1: Write the shared fixture**

Create `renderer/src/__fixtures__/paginate-cases.json`:

```json
[
  {
    "name": "sentence end breaks a page",
    "maxWords": 14, "maxChars": 84,
    "words": [
      {"text": "hum", "start": 0.0, "end": 0.3}, {"text": "chalein.", "start": 0.3, "end": 0.7},
      {"text": "phir", "start": 0.75, "end": 1.0}, {"text": "dekho", "start": 1.0, "end": 1.3}
    ],
    "pages": [[0, 1], [2, 3]]
  },
  {
    "name": "pause breaks a page",
    "maxWords": 14, "maxChars": 84,
    "words": [
      {"text": "ek", "start": 0.0, "end": 0.3}, {"text": "do", "start": 1.0, "end": 1.3}
    ],
    "pages": [[0], [1]]
  },
  {
    "name": "word limit",
    "maxWords": 2, "maxChars": 84,
    "words": [
      {"text": "a", "start": 0.0, "end": 0.1}, {"text": "b", "start": 0.1, "end": 0.2},
      {"text": "c", "start": 0.2, "end": 0.3}
    ],
    "pages": [[0, 1], [2]]
  },
  {
    "name": "character limit",
    "maxWords": 14, "maxChars": 10,
    "words": [
      {"text": "abcdef", "start": 0.0, "end": 0.1}, {"text": "ghijk", "start": 0.1, "end": 0.2}
    ],
    "pages": [[0], [1]]
  }
]
```

- [ ] **Step 2: Write the failing tests**

Append to `renderer/src/captions/paginate.test.ts`:

```ts
import cases from '../__fixtures__/paginate-cases.json'

describe('shared pagination cases (also checked by tests/test_srt.py)', () => {
  for (const c of cases) {
    it(c.name, () => {
      const pages = paginate(c.words, c.maxWords, c.maxChars)
      const indexOf = new Map(c.words.map((w, i) => [w, i]))
      expect(pages.map(p => p.words.map(w => indexOf.get(w)))).toEqual(c.pages)
    })
  }
})
```

(Add `describe`/`it`/`expect` to the existing vitest import if missing.)

Create `tests/test_srt.py`:

```python
import json
import os

import pytest

from backend import srt

CASES = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "paginate-cases.json")
FIXTURE_V2 = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec-v2.json")
FIXTURE_V1 = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec.json")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("case", _load(CASES), ids=lambda c: c["name"])
def test_paginate_matches_the_renderer(case):
    assert srt.paginate(case["words"], case["maxWords"], case["maxChars"]) == case["pages"]


def test_clip_words_uses_clip_time():
    words = srt.clip_words(_load(FIXTURE_V2))
    assert [w["text"] for w in words] == [w["text"] for w in _load(FIXTURE_V1)["words"]]
    assert words[0]["start"] == pytest.approx(_load(FIXTURE_V1)["words"][0]["start"], abs=1e-3)


def test_build_srt_format():
    text = srt.build_srt(_load(FIXTURE_V1))
    blocks = text.strip().split("\n\n")
    assert blocks[0].splitlines()[0] == "1"
    # 26 words over 8 s: step 8/26; the first sentence is 9 words, ending 9*step - 0.02 = 2.749
    assert blocks[0].splitlines()[1] == "00:00:00,000 --> 00:00:02,749"
    assert blocks[0].splitlines()[2] == "Honestly this was the moment everything changed for us."
    assert text.endswith("\n")


def test_build_srt_empty():
    assert srt.build_srt({"version": 1, "start": 0, "end": 5, "words": []}) == ""
```

- [ ] **Step 3: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest -q tests/test_srt.py` and `cd renderer && npx vitest run src/captions/paginate.test.ts`
Expected: Python FAIL (no module); TS PASS (it checks the existing paginate, proving the fixture matches it).

- [ ] **Step 4: Implement `backend/srt.py`**

```python
"""SubRip captions for a clip. Pages follow the caption editor's lines
(renderer/src/captions/edit.ts: 14 words / 84 characters), built with a
Python port of renderer/src/captions/paginate.ts. Both sides are checked
against renderer/src/__fixtures__/paginate-cases.json so they can't drift.
"""
from __future__ import annotations

import re
from typing import Any

LINE_MAX_WORDS = 14
LINE_MAX_CHARS = 84
PAUSE_BREAK_S = 0.4
_ENDS_SENTENCE = re.compile(r"[.!?…][\"')\]]?$")


def paginate(words: list[dict[str, Any]], max_words: int, max_chars: float = float("inf")) -> list[list[int]]:
    pages: list[list[int]] = []
    cur: list[int] = []
    for i, word in enumerate(words):
        chars = sum(len(words[j]["text"]) + 1 for j in cur) + len(word["text"])
        if cur and chars > max_chars:
            pages.append(cur)
            cur = []
        cur.append(i)
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = nxt is not None and nxt["start"] - word["end"] > PAUSE_BREAK_S
        if len(cur) >= max_words or _ENDS_SENTENCE.search(word["text"]) or pause:
            pages.append(cur)
            cur = []
    if cur:
        pages.append(cur)
    return pages


def clip_words(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Words in clip time: v2 specs hold the whole cut file, so keep the
    words overlapping the clip and shift them (renderer toClipTime)."""
    words = spec.get("words") or []
    if spec.get("version") != 2:
        return list(words)
    start, end = float(spec["start"]), float(spec["end"])
    return [
        {**w, "start": round(w["start"] - start, 3), "end": round(w["end"] - start, 3)}
        for w in words if w["end"] > start and w["start"] < end
    ]


def _stamp(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(spec: dict[str, Any]) -> str:
    words = clip_words(spec)
    length = float(spec["end"]) - float(spec["start"])
    blocks = []
    for n, page in enumerate(paginate(words, LINE_MAX_WORDS, LINE_MAX_CHARS), start=1):
        first, last = words[page[0]], words[page[-1]]
        start = max(0.0, first["start"])
        end = min(length, max(last["end"], start))
        text = " ".join(words[i]["text"] for i in page)
        blocks.append(f"{n}\n{_stamp(start)} --> {_stamp(end)}\n{text}\n")
    return "\n".join(blocks)
```

- [ ] **Step 5: Verify**

Run: `./.venv/Scripts/python -m pytest -q` and `cd renderer && npm test`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/srt.py tests/test_srt.py renderer/src/__fixtures__/paginate-cases.json renderer/src/captions/paginate.test.ts
git commit -m "Build SRT captions with pagination shared with the renderer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Bounds endpoints, render invalidation, window-aware captions, SRT endpoints

**Files:**
- Modify: `backend/main.py`, `backend/render.py`, `backend/captions.py` (docstring only if needed)
- Test: `tests/test_bounds_api.py` (create), `tests/test_render.py`, `tests/test_captions_api.py`

**Interfaces:**
- Consumes: `spec.window_duration`, `spec.render_hash(..., bounds)`, `srt.build_srt`.
- Produces:
  - `PATCH /api/clips/{clip_id}/bounds` body `{start: float, end: float}` → `{start, end, boundsEdited: bool}`
  - `POST /api/clips/{clip_id}/bounds/reset` → same shape
  - `GET /api/clips/{clip_id}/captions.srt` → `text/plain; charset=utf-8` attachment `highlyte-<clipId>.srt`
  - renders zip includes `highlyte-<clipId>.srt` per render
  - clip JSON gains `reason`, `pendingAction`, `actionError`, `boundsEdited`, `revision`
  - `RenderService.request(clip_id, style, words=None, bounds=None)`
  - constants in main: `MIN_CLIP_S = 8.0`, `MAX_CLIP_S = 60.0`

Behaviour:
- Bounds PATCH: `_clip_for_style` (team check, spec required). 409 "Re-run the video to trim this clip." when `window_duration(spec)` is None. 409 "This clip is being replaced. Wait for it to finish." when `record.get("pendingAction")`. 422 unless both are finite, `0 <= start < end <= window + 1e-6`, and `8 <= end - start <= 60` (messages: "Clips must be at least 8 s." / "Clips can be at most 60 s." / "That is outside the spare video."). Round to 3 decimals. `bounds_original` = existing value or `{"start": spec.start, "end": spec.end}` on first change. New `spec` with the bounds; the record's source-time `start`/`end` move by the same deltas (`record.start += new_start - old_start`, same for end); labels (`startLabel`, `endLabel`, `durationLabel`) recomputed with `ingest.duration_label`. Persist with `db.update_clip_checked(id, {"spec", "bounds_original", "start_s", "end_s"})` (503 "Couldn't save the trim. Try again." on error). Mutate the record like `save_captions` does.
- Reset: if `boundsOriginal` set, restore it (spec + record start/end shift back), clear `bounds_original`; else no-op. Same reply.
- Caption save: the limit passed to `captions.validate_words` becomes `window_duration(spec) or (spec["end"] - spec["start"])`.
- Render: `start_render` passes `bounds=(spec["start"], spec["end"])` to `RENDER_SERVICE.request`. In `render.py`, `request` gains `bounds` and uses `render_hash(style, words, bounds)` when words are given. In `_start`, the "changed underneath" check recomputes with `bounds=(props["spec"]["start"], props["spec"]["end"])` and accepts the hash if it equals either `render_hash(style, words, bounds)` or `render_hash(style, words)` (renders queued before this change); otherwise error "Captions or trim changed after this export was requested. Export again."
- `_clip_record` adds `"reason": clip.reason, "pendingAction": None, "actionError": None, "boundsOriginal": None, "boundsEdited": False, "revision": 0`; `_clip_row` adds `"reason"`, `"revision"`; `_clip_row_to_api` adds `"reason": r.get("reason") or ""`, `"pendingAction": r.get("pending_action")`, `"actionError": r.get("action_error")`, `"boundsOriginal": r.get("bounds_original")`, `"boundsEdited": r.get("bounds_original") is not None`, `"revision": r.get("revision") or 0`.
- `_with_source_url`: when `revision > 0`, the served `spec.source.url` is `f"{downloadUrl}?r={revision}"` (browser cache-busting; `get_clip` ignores the query). Drop `boundsOriginal` from the served record like `wordsOriginal`.
- SRT endpoint: `check_id`, `_require_job`, record via `_find_clip` (404 if missing, 409 if no spec). Returns `Response(srt.build_srt(spec), media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="highlyte-{clip_id}.srt"'})`.
- Zip: after each mp4 entry, write `highlyte-<clipId>.srt` from `_find_clip(r.clip_id)`'s spec (skip if missing).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bounds_api.py`:

```python
import copy
import json
import os

import pytest

from backend import main
from tests.support import TEST_TEAM_ID, api_client

client = api_client()
FIXTURE_V2 = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec-v2.json")
FIXTURE_V1 = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec.json")
JOB = "b0und5000001"


def _spec(path=FIXTURE_V2):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def clip(monkeypatch):
    spec = _spec()
    spec["clipId"] = f"{JOB}-0"
    record = {
        "id": f"{JOB}-0", "start": 100.0, "end": 108.0, "startLabel": "1:40", "endLabel": "1:48",
        "durationLabel": "0:08", "text": "t", "tag": "Key insight", "score": 7.0, "hookTitle": None,
        "viralityScore": 7.0, "downloadUrl": f"/api/clips/{JOB}/clip_0.mp4", "storageProvider": "local",
        "storageKey": None, "spec": spec, "style": {"layout": "fit"}, "qaFlags": [], "reason": "",
        "pendingAction": None, "actionError": None, "boundsOriginal": None, "boundsEdited": False, "revision": 0,
    }
    job = main.Job(id=JOB, url="https://youtu.be/x", status="done", team_id=TEST_TEAM_ID, clips=[record])
    main.JOBS[JOB] = job
    writes = []
    monkeypatch.setattr(main.db, "update_clip_checked", lambda cid, fields: writes.append((cid, fields)))
    yield record, writes
    main.JOBS.pop(JOB, None)


def test_bounds_update_saves_original_and_moves_source_time(clip):
    record, writes = clip
    r = client.patch(f"/api/clips/{JOB}-0/bounds", json={"start": 1.5, "end": 10.3})
    assert r.status_code == 200
    assert r.json() == {"start": 1.5, "end": 10.3, "boundsEdited": True}
    assert record["spec"]["start"] == 1.5 and record["spec"]["end"] == 10.3
    assert record["boundsOriginal"] == {"start": 2.0, "end": 10.0}
    assert (record["start"], record["end"]) == (99.5, 108.3)
    fields = writes[-1][1]
    assert fields["bounds_original"] == {"start": 2.0, "end": 10.0}
    assert (fields["start_s"], fields["end_s"]) == (99.5, 108.3)


def test_second_nudge_keeps_first_original(clip):
    record, _ = clip
    client.patch(f"/api/clips/{JOB}-0/bounds", json={"start": 1.5, "end": 10.3})
    client.patch(f"/api/clips/{JOB}-0/bounds", json={"start": 1.0, "end": 10.3})
    assert record["boundsOriginal"] == {"start": 2.0, "end": 10.0}


@pytest.mark.parametrize("body,msg", [
    ({"start": 3.0, "end": 10.0}, "at least 8 s"),
    ({"start": -1.0, "end": 10.0}, "outside the spare video"),
    ({"start": 2.0, "end": 12.5}, "outside the spare video"),
])
def test_bounds_limits(clip, body, msg):
    r = client.patch(f"/api/clips/{JOB}-0/bounds", json=body)
    assert r.status_code == 422 and msg in r.json()["detail"]


def test_v1_clip_cannot_be_trimmed(clip):
    record, _ = clip
    record["spec"] = _spec(FIXTURE_V1)
    r = client.patch(f"/api/clips/{JOB}-0/bounds", json={"start": 1.5, "end": 9.5})
    assert r.status_code == 409 and r.json()["detail"] == "Re-run the video to trim this clip."


def test_busy_clip_cannot_be_trimmed(clip):
    record, _ = clip
    record["pendingAction"] = "swap"
    assert client.patch(f"/api/clips/{JOB}-0/bounds", json={"start": 1.5, "end": 10.3}).status_code == 409


def test_reset_restores_original(clip):
    record, _ = clip
    client.patch(f"/api/clips/{JOB}-0/bounds", json={"start": 1.5, "end": 10.3})
    r = client.post(f"/api/clips/{JOB}-0/bounds/reset")
    assert r.json() == {"start": 2.0, "end": 10.0, "boundsEdited": False}
    assert (record["start"], record["end"]) == (100.0, 108.0)
    assert record["boundsOriginal"] is None


def test_srt_download(clip):
    r = client.get(f"/api/clips/{JOB}-0/captions.srt")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == f'attachment; filename="highlyte-{JOB}-0.srt"'
    assert r.text.startswith("1\n00:00:00,")


def test_caption_save_accepts_times_across_the_window(clip):
    record, _ = clip
    words = record["spec"]["words"]
    r = client.put(f"/api/clips/{JOB}-0/captions", json={"words": words})
    assert r.status_code == 200   # the last word ends at 11.2 s, past the 8 s clip
```

Append to `tests/test_render.py` (reuse the file's existing service fixture/helpers; if it builds the service with a helper, use the same one):

```python
def test_request_with_bounds_hashes_differently(make_service):
    svc = make_service()
    words = [Word(text="a", start=0, end=1)]
    a = svc.request("job1-0", ClipStyle(layout="fit"), words, bounds=(1.0, 9.0))
    b = svc.request("job1-0", ClipStyle(layout="fit"), words, bounds=(1.5, 9.0))
    assert a.id != b.id
```

Before writing this, read `tests/test_render.py` to see how it constructs the service (fixture or helper) and adapt the first line to that; import `Word` from `backend.spec` if not already imported. Also add a test beside the existing "captions changed after this export" test that queues a render with bounds `(1.0, 9.0)`, changes the props' spec start to 1.5 before the pump runs, and asserts the error message "Captions or trim changed after this export was requested. Export again."; and update the existing captions-changed test's expected message to the new wording.

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest -q tests/test_bounds_api.py tests/test_render.py tests/test_captions_api.py`
Expected: FAIL.

- [ ] **Step 3: Implement** as described in Behaviour above. Keep new endpoint code next to the caption endpoints. Import `Response` from `fastapi.responses` and `srt` from `.`; import `window_duration` from `.spec`.

- [ ] **Step 4: Verify**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/render.py backend/captions.py tests/test_bounds_api.py tests/test_render.py tests/test_captions_api.py
git commit -m "Add clip bounds and SRT endpoints; exports follow trims

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Swap scene and Regenerate

**Files:**
- Modify: `backend/main.py`
- Test: `tests/test_clip_actions.py` (create), `tests/test_pipeline_run.py`, `tests/test_status.py`

**Interfaces:**
- Consumes: `selection.Selection.alternates`, `selection.alternate_to_clip`, `selection.regenerate`, `scoring.span_overlap`, `groq_llm.build_chat`, `clipprep.prepare_clip`, `transcript.word_segments`, `segments.from_dict`, `_start_thread`, `_SELECTION_LOCK`.
- Produces:
  - `Job.alternates: list[dict]` (persisted as `jobs.alternates`; `_job_from_row` reads it; `_select_and_prepare` stores `result.alternates`)
  - status JSON gains `alternatesLeft: int`
  - `POST /api/clips/{clip_id}/swap`, `POST /api/clips/{clip_id}/regenerate` → `{"clipId", "pendingAction"}`
  - `main.pick_alternate(alternates, current, others) -> int | None`
  - `main._run_clip_action(job, clip_id, kind)`
  - status DB fallback: a clip row with `pending_action` set on a job not in memory is reported with `pendingAction: None` and `actionError: "Interrupted by a server restart. Try again."`

Behaviour:
- Endpoint (shared helper `_start_clip_action(clip_id, kind, member)`): `check_id`; job id from clip id; `_require_job`. Under `_SELECTION_LOCK`: get the job from `JOBS`, or rebuild it (`_job_from_row(row)` plus `job.clips = [_clip_row_to_api(r) for r in db.list_clips_for_job(job_id)]`) and `JOBS.setdefault`; 409 "Clips can be changed once the video is done." unless `job.status == "done"`; find the record (404); 409 "This clip has no vertical version. Re-run the video." without spec; 409 "This clip is already being replaced." if `pendingAction`; for swap: 409 "No other moments left to swap in." when `pick_alternate(...)` is None; for regenerate: 409 "Regenerate needs GROQ_KEY." when `groq_llm.build_chat()` is None. Then set `record["pendingAction"] = kind`, `record["actionError"] = None` and release the lock. Persist `db.update_clip(clip_id, {"pending_action": kind, "action_error": None})`; `_start_thread(_run_clip_action, job, clip_id, kind)`.
- `pick_alternate(alternates, current, others)`: first index (list is best first) whose span overlaps `current` by < 0.9 and every span in `others` by < 0.3 (`scoring.span_overlap`).
- `_run_clip_action(job, clip_id, kind)`:
  1. `stored = db.get_transcript(job.id)`; missing → error "This video's transcript wasn't saved. Submit the video again."
  2. `segs = [segment_from_dict(d) for d in stored["segments"]]`; `current = (record["start"], record["end"])`; `others = [(c["start"], c["end"]) for c in job.clips if c["id"] != clip_id]`.
  3. swap: `i = pick_alternate(job.alternates, current, others)`; None → error "No other moments left to swap in."; `new_clip = selection.alternate_to_clip(job.alternates[i])`. regenerate: `new_clip = selection.regenerate(segs, stored.get("loudness") or [], current, others)`; None → error "No better take found around this moment."; `SelectionFailed` → its message.
  4. `meta = ingest.ingest(job.url, CACHE_DIR)`; failure → error `f"Couldn't fetch the video again: {e}."`.
  5. `prepared = clipprep.prepare_clip(job_id=job.id, idx=idx, clip=new_clip, video_path=meta.video_path, video_duration=meta.duration, segments=transcript.word_segments(segs), clips_dir=CLIPS_DIR, models_dir=MODELS_DIR, on_step=lambda s: None)` where `idx = int(clip_id.rsplit("-", 1)[1])`.
  6. `new_record = _clip_record(job.id, idx, new_clip, prepared)`; keep the old style's `captionPreset`, `accent`, `captionPosition` (layout, hook title and showHook come from the new spec's default style); `new_record["revision"] = (record.get("revision") or 0) + 1`.
  7. `db.update_clip_checked(clip_id, {k: v for k, v in _clip_row(job.id, idx, new_record).items() if k != "id"} | {"words_original": None, "bounds_original": None, "pending_action": None, "action_error": None})`.
  8. Replace the record in `job.clips` (same position); for swap, remove `job.alternates[i]` and `_persist_job(job)`.
  - Any error: `record["pendingAction"] = None`, `record["actionError"] = message` (unexpected exceptions: `f"Couldn't {'swap' if kind == 'swap' else 'regenerate'} this clip: {e}"`), `db.update_clip(clip_id, {"pending_action": None, "action_error": message})`. The old clip stays.
- `_clip_row` gains `"reason"`, `"revision"` (Task 6) — confirm they flow through step 7.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_clip_actions.py` covering, with `_start_thread` monkeypatched to run inline (`lambda target, *args: target(*args)`), `ingest.ingest`, `clipprep.prepare_clip` (returning a `PreparedClip` built from the v2 fixture via `ClipSpec.model_validate`), `db.get_transcript`, `db.update_clip`, `db.update_clip_checked`, `db.upsert_job` and `selection.regenerate` faked:

```python
import json
import os

import pytest

from backend import main
from backend.pipeline import clipprep, selection
from backend.pipeline.ingest import VideoMeta
from backend.spec import ClipSpec
from tests.support import TEST_TEAM_ID, api_client

client = api_client()
JOB = "ac7100000001"
FIXTURE_V2 = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec-v2.json")


def _record(idx, start, end):
    with open(FIXTURE_V2, encoding="utf-8") as f:
        spec = json.load(f)
    spec["clipId"] = f"{JOB}-{idx}"
    return {
        "id": f"{JOB}-{idx}", "start": start, "end": end, "text": "old", "tag": "Key insight", "score": 5.0,
        "hookTitle": None, "viralityScore": 5.0, "downloadUrl": f"/api/clips/{JOB}/clip_{idx}.mp4",
        "storageProvider": "local", "storageKey": None, "spec": spec,
        "style": {"layout": "fit", "captionPreset": "pop", "accent": "#123456", "captionPosition": "middle",
                  "showHook": False, "hookTitle": None},
        "qaFlags": [], "reason": "", "pendingAction": None, "actionError": None,
        "boundsOriginal": None, "boundsEdited": False, "revision": 0,
    }


@pytest.fixture
def env(monkeypatch):
    job = main.Job(id=JOB, url="https://youtu.be/x", status="done", team_id=TEST_TEAM_ID,
                   clips=[_record(0, 100.0, 120.0), _record(1, 300.0, 320.0)])
    job.alternates = [
        {"start": 305.0, "end": 325.0, "text": "clash", "score": 9.0, "tag": "Wild claim", "flags": [], "reason": "r1", "emphasis": []},
        {"start": 500.0, "end": 520.0, "text": "fresh", "score": 8.0, "tag": "Key insight", "flags": [], "reason": "r2", "emphasis": ["fresh"]},
    ]
    main.JOBS[JOB] = job
    writes, updates = [], []
    monkeypatch.setattr(main, "_start_thread", lambda target, *args: target(*args))
    monkeypatch.setattr(main.db, "get_transcript", lambda job_id: {"segments": [], "loudness": []})
    monkeypatch.setattr(main.db, "update_clip", lambda cid, f: updates.append((cid, f)))
    monkeypatch.setattr(main.db, "update_clip_checked", lambda cid, f: writes.append((cid, f)))
    monkeypatch.setattr(main.db, "upsert_job", lambda row: None)
    monkeypatch.setattr(main.ingest, "ingest", lambda url, cache_dir, on_progress=None: VideoMeta(
        video_id="x", title="t", channel="c", duration=900.0, audio_path="a", video_path="v", thumbnail_url=None))

    def fake_prepare(**kw):
        with open(FIXTURE_V2, encoding="utf-8") as f:
            spec = json.load(f)
        spec["clipId"] = f"{JOB}-{kw['idx']}"
        return clipprep.PreparedClip(spec=ClipSpec.model_validate(spec), storage_key=None, face_at_start=True)

    monkeypatch.setattr(main.clipprep, "prepare_clip", fake_prepare)
    yield job, writes, updates
    main.JOBS.pop(JOB, None)


def test_pick_alternate_skips_clashes():
    alts = [{"start": 305.0, "end": 325.0}, {"start": 500.0, "end": 520.0}]
    assert main.pick_alternate(alts, (100.0, 120.0), [(300.0, 320.0)]) == 1
    assert main.pick_alternate(alts[:1], (100.0, 120.0), [(300.0, 320.0)]) is None


def test_swap_replaces_clip_and_uses_up_the_alternate(env):
    job, writes, _ = env
    r = client.post(f"/api/clips/{JOB}-0/swap")
    assert r.status_code == 200 and r.json() == {"clipId": f"{JOB}-0", "pendingAction": "swap"}
    new = job.clips[0]
    assert (new["start"], new["end"], new["reason"]) == (500.0, 520.0, "r2")
    assert new["revision"] == 1 and new["pendingAction"] is None
    assert new["style"]["captionPreset"] == "pop" and new["style"]["accent"] == "#123456"
    assert [a["reason"] for a in job.alternates] == ["r1"]
    fields = writes[-1][1]
    assert fields["words_original"] is None and fields["bounds_original"] is None and fields["pending_action"] is None


def test_swap_with_nothing_left_is_409(env):
    job, _, _ = env
    job.alternates = job.alternates[:1]
    r = client.post(f"/api/clips/{JOB}-0/swap")
    assert r.status_code == 409 and r.json()["detail"] == "No other moments left to swap in."


def test_regenerate_replaces_clip(env, monkeypatch):
    job, _, _ = env
    monkeypatch.setattr(main.groq_llm, "build_chat", lambda: object())
    seen = {}

    def fake_regenerate(segs, loudness, current, avoid):
        seen["current"], seen["avoid"] = current, avoid
        return selection.Clip(start=130.0, end=150.0, text="new", score=8.0, tag="Key insight", reason="better")

    monkeypatch.setattr(main.selection, "regenerate", fake_regenerate)
    assert client.post(f"/api/clips/{JOB}-0/regenerate").status_code == 200
    assert seen == {"current": (100.0, 120.0), "avoid": [(300.0, 320.0)]}
    assert job.clips[0]["reason"] == "better"


def test_regenerate_failure_keeps_old_clip(env, monkeypatch):
    job, _, updates = env
    monkeypatch.setattr(main.groq_llm, "build_chat", lambda: object())
    monkeypatch.setattr(main.selection, "regenerate", lambda *a, **k: None)
    client.post(f"/api/clips/{JOB}-0/regenerate")
    rec = job.clips[0]
    assert rec["text"] == "old" and rec["pendingAction"] is None
    assert rec["actionError"] == "No better take found around this moment."
    assert updates[-1] == (f"{JOB}-0", {"pending_action": None, "action_error": "No better take found around this moment."})


def test_regenerate_needs_key(env, monkeypatch):
    monkeypatch.setattr(main.groq_llm, "build_chat", lambda: None)
    r = client.post(f"/api/clips/{JOB}-0/regenerate")
    assert r.status_code == 409 and r.json()["detail"] == "Regenerate needs GROQ_KEY."


def test_busy_clip_rejects_a_second_action(env, monkeypatch):
    job, _, _ = env
    job.clips[0]["pendingAction"] = "swap"
    assert client.post(f"/api/clips/{JOB}-0/swap").status_code == 409


def test_download_failure_is_reported(env, monkeypatch):
    job, _, _ = env

    def boom(*a, **k):
        raise RuntimeError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(main.ingest, "ingest", boom)
    client.post(f"/api/clips/{JOB}-0/swap")
    assert job.clips[0]["actionError"] == "Couldn't fetch the video again: Sign in to confirm you're not a bot."
```

Import `groq_llm` in `main.py` (`from .pipeline import ... groq_llm ...`) so `main.groq_llm` exists. Append to `tests/test_pipeline_run.py` a test that `_run_pipeline` stores `Selection([], None, alternates=[{...}])` into `job.alternates` and the persisted row's `alternates`. Append to `tests/test_status.py`: the DB fallback reports an orphaned `pending_action` as interrupted, and the status carries `alternatesLeft`.

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest -q tests/test_clip_actions.py tests/test_pipeline_run.py tests/test_status.py`
Expected: FAIL.

- [ ] **Step 3: Implement** as described in Behaviour. `Job` gains `alternates: list[dict] = field(default_factory=list)`; `_persist_job` sends `"alternates": job.alternates`.

- [ ] **Step 4: Verify**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_clip_actions.py tests/test_pipeline_run.py tests/test_status.py
git commit -m "Add Swap scene and Regenerate for a single clip

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Frontend: trim, swap, regenerate, SRT, card info

**Files:**
- Create: `frontend/src/components/TrimControls.vue`
- Modify: `frontend/src/services/highlyteApi.js`, `frontend/src/stores/jobStore.js`, `frontend/src/components/ClipCard.vue`, `frontend/src/components/CaptionEditor.vue`

**Interfaces:**
- Consumes: endpoints from Tasks 6–7; `@renderer/lib/trim` (`canTrim`, `nudge`, `sentence`, `NUDGE_S`); `@renderer/lib/timeline` (`toClipTime`); `@renderer/captions/edit` (`captionLines`, `lineText`).

Changes:
1. **API** (`highlyteApi.js`): `saveBounds(clipId, bounds)` → `PATCH /api/clips/${clipId}/bounds`; `resetBounds(clipId)` → `POST .../bounds/reset`; `swapClip(clipId)` → `POST .../swap`; `regenerateClip(clipId)` → `POST .../regenerate`; `clipSrtUrl(clipId)` → `${baseURL}/api/clips/${clipId}/captions.srt`.
2. **Store** (`jobStore.js`):
   - `updateBounds(clipId, bounds)`: sets `clip.spec = { ...clip.spec, ...bounds }` immediately and `clip.boundsEdited = true`; deletes `this.renders[clipId]`; debounces `saveBounds` 500 ms per clip (own timer map `_boundsTimers`), on error sets `this.error` from `apiErrorMessage(e, 'Failed to save the trim')`.
   - `resetBounds(clipId)`: calls the API, applies `{start, end}` from the reply, sets `boundsEdited` from the reply, deletes the render.
   - `swapClip(clipId)` / `regenerateClip(clipId)`: call the API; on success set `clip.pendingAction` from the reply and `startPolling()`; on error set `clip.actionError = apiErrorMessage(e, ...)`.
   - `refresh()`: in the `done` branch, keep polling while any clip has `pendingAction` (only call `stopPolling()` when none does); when a clip's `revision` changed since the last refresh, delete `this.renders[clip.id]`.
3. **TrimControls.vue** (new, props `clip`): if `!canTrim(clip.spec)` show one muted line "Re-run the video to trim this clip." Otherwise a compact row: `Start: ◀ Sentence | −0.5 s | +0.5 s | Sentence ▶`, `End: ◀ Sentence | −0.5 s | +0.5 s | Sentence ▶`, the length `27.4 s`, and a `Reset` link when `clip.boundsEdited`. Each button computes its move (`sentence(clip.spec, 'start', -1)` etc.; nudges use `NUDGE_S`) and is disabled with `title` = the move's reason when `!ok`; clicking calls `jobStore.updateBounds(clip.id, move.bounds)`. Everything disabled while `clip.pendingAction`.
4. **ClipCard.vue**:
   - Under the meta row: the first caption line (`captionLines(toClipTime(clip.spec).words)[0]`, via `lineText`) as a quoted one-liner, and `clip.reason` in muted text when non-empty.
   - `<TrimControls :clip="clip" />` right under the preview.
   - Actions row: `Swap scene` (disabled when `jobStore.job.alternatesLeft === 0`, title "No other moments left to swap in."), `Regenerate`, and a `Download SRT` link (`clipSrtUrl(clip.id)`, `download` attribute). While `clip.pendingAction`: a line "Swapping in another moment…" or "Regenerating this clip…" and all edit controls disabled. `clip.actionError` shows in the existing error style.
   - Pass `:start`/`:end` to `CaptionEditor` (`clip.spec.version === 2 ? clip.spec.start : null`, same for end).
5. **CaptionEditor.vue**: new optional props `start` and `end` (Number, default null). `lines` becomes `captionLines(props.words)` filtered to lines with `line.end > start && line.start < end` when both are set (keeps each line's global `from`, so `editLine` still works on the full word list). `texts` index the visible lines only; the draft loop iterates visible lines last-first. The line clock shows clip time: `clock(line.start - (props.start ?? 0))`.

Styling: current CSS variables; compact buttons like the existing `.check`/`select` controls. The redesign restyles later.

- [ ] **Step 1: Implement the five changes.**
- [ ] **Step 2: Build**

Run: `cd frontend && npm run build`
Expected: success, no new warnings besides the existing chunk-size notice.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/highlyteApi.js frontend/src/stores/jobStore.js frontend/src/components/TrimControls.vue frontend/src/components/ClipCard.vue frontend/src/components/CaptionEditor.vue
git commit -m "Trim, swap, regenerate and SRT on the clip card

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Docs and roadmap

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-09-25-hinglish-v1-roadmap.md`

- [ ] **Step 1:** README: a short "Fixing a clip" section (trim, sentence steps, reset, Swap scene uses saved runner-ups and no tokens, Regenerate uses one small Groq call, SRT download; v1 clips from before this change can't be trimmed). Deploy notes: apply `supabase/migrations/20260927120000_fix_in_place.sql` and run `npm run deploy:site` in `renderer/` before exports can draw spec v2.
- [ ] **Step 2:** Roadmap "Start" section: piece 3a is built (link the spec and plan); next are 3b (video upload) and the UI redesign.
- [ ] **Step 3:** Run `./.venv/Scripts/python -m pytest -q`, `cd renderer && npm test && npm run typecheck`, `cd frontend && npm run build`. All pass.
- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-09-25-hinglish-v1-roadmap.md
git commit -m "Document fixing clips in place and the 3a deploy steps

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After all tasks

- Final whole-branch review (most capable model) over this plan's range.
- Remind the user: apply the migration; `npm run deploy:site` in `renderer/`; re-run a video (only new clips are v2 and trimmable); browser checks for trim, sentence steps, reset, swap, regenerate (spends Groq tokens), SRT download and the zip.
