# Pipeline Business-Logic Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the ten business-logic gaps found in the product audit (regenerate cost, dedup, self-rating, weak-pick honesty, podcast-only framing, no diarization, no independent self-containment check, no usage visibility, hard duration walls, caption occlusion) with the smallest change that actually fixes each one — without adding any rate limit, quota, or hard usage cap on any user or teammate.

**Architecture:** No new services. Every fix lands inside the existing `backend/pipeline/` modules (`scoring`, `ranker`, `selection`, `segments`, `transcript`), two new pure pipeline modules (`judge.py`, `diarize.py`), one new top-level `backend/usage.py` (telemetry only, mirrors `db.py`'s style), one new Supabase migration, and small, targeted edits in `backend/main.py`, the Vue clip card, and the Remotion renderer's view resolver.

**Tech Stack:** Python 3.11 / FastAPI / Supabase Postgres (existing), `pyannote.audio` (new dependency, diarization only), Vue 3 + Pinia, Remotion/TypeScript + Vitest, pytest.

**Spec:** This plan is self-contained; it implements the findings in the product audit pasted into this conversation on 2026-10-09 (no separate spec doc). Related prior plans: `docs/superpowers/plans/2026-09-26-clip-selection.md`, `2026-09-24-phase1-remotion-reframe-captions.md`, `2026-09-26-shot-aware-layout.md`.

## Global Constraints

- **Never add a rate limit, quota, cap, or any other block on how many times a user or teammate can run selection, Regenerate, Swap, or anything else.** Every fix below that touches cost (Task 1) is read-only telemetry: it records and displays, it never denies a request. If a task description below ever seems to imply a cap, the correct reading is "show the number, don't enforce it."
- Run Python tests with `./.venv/Scripts/python -m pytest -q` from the repo root (Git Bash). Record the baseline pass count before starting Task 1 and re-check it stays green (plus new tests) after every task.
- Frontend/renderer checks: `cd frontend && npm run build`; `cd renderer && npx vitest run`.
- Apply the new migration locally before exercising any usage-telemetry code: `npx supabase db push --db-url "$DBURL"` (user sets `DBURL`; never ask for or print it).
- Follow existing conventions: pipeline modules (`backend/pipeline/*.py`) stay pure / DB-free and are unit-testable with fakes; all Supabase I/O goes through `backend/db.py`-style wrappers that never raise (log and return a safe default); `backend/main.py` is the only place that wires pipeline output to persistence.
- `pyannote.audio` (Task 6) is the one approved new heavy dependency in this plan — it pulls in `torch`. It is optional at runtime (gated on an `HF_TOKEN` env var): a deployment that never sets `HF_TOKEN` behaves exactly as today (single speaker `"A"`, unchanged prompt), so shipping it carries no behavior-change risk for teams that don't opt in.
- Every commit message ends with a blank line then: `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`. Never push, never force anything, never amend.

## Audit Finding -> Task Map

| # | Audit finding | Task |
|---|---|---|
| 1 | Unbounded, unrated Regenerate — real cost exposure, zero guardrail | Task 1 (telemetry, **not** a cap) |
| 2 | No semantic dedup — only temporal overlap checked | Task 2 |
| 3 | Scoring is an ungrounded LLM self-rating, no calibration | Task 3 |
| 4 | Min-clip floor ships weak clips without honest signaling | Task 4 |
| 5 | No content-type detection; prompt hardcoded to "podcast" | Task 5 |
| 6 | No speaker diarization despite podcast/interview target | Task 6 |
| 7 | No independent self-containment verification | Task 3 |
| 8 | No usage/quota system — unit economics unenforceable | Task 1 (visibility only — see Global Constraints) |
| 9 | Hard duration walls (8–60 s) reject great off-band content | Task 7 |
| 10 | Caption position not layout-aware — occlusion risk | Task 8 (partially already fixed — see Task 8 for what's left) |

## File Map

| File | Status | Responsibility |
|---|---|---|
| `backend/pipeline/groq_llm.py` | modify | `GroqChat.usage_log` — every call's real token counts |
| `backend/usage.py` | create | Cost estimate + `record_many()` / `team_totals()`, DB-backed, never raises |
| `supabase/migrations/20261009000000_llm_usage.sql` | create | `llm_usage` table |
| `backend/db.py` | modify | `insert_usage()`, `sum_usage_for_team()` |
| `backend/main.py` | modify | Wire usage capture around `selection.select()` / `selection.regenerate()`; `GET /api/usage` |
| `frontend/src/services/highlyteApi.js` | modify | `getUsage()` |
| `frontend/src/components/ClipCard.vue` | modify | Show call count near Regenerate; QA flag tooltips; `needs_review` label |
| `backend/pipeline/scoring.py` | modify | Text-overlap dedup; soft duration band |
| `backend/pipeline/selection.py` | modify | Text-overlap check on alternates/swap; wire `judge.review()` |
| `backend/main.py` | modify | Text-overlap check in `pick_alternate()` |
| `backend/pipeline/judge.py` | create | Independent self-containment pass |
| `backend/pipeline/ranker.py` | modify | Drop "podcast"-only framing; speaker-tagged window text when diarized |
| `backend/pipeline/titles.py` | modify | Drop "podcast"-only framing |
| `backend/pipeline/diarize.py` | create | Optional `pyannote` diarization wrapper |
| `backend/pipeline/segments.py` | modify | `apply_speakers()` |
| `backend/pipeline/transcript.py` | modify | Run diarization, apply speaker labels |
| `requirements.txt` | modify | `pyannote.audio` |
| `renderer/src/lib/view.ts` | modify | Face-position-aware caption position for single-face close-ups |
| `renderer/src/lib/view.test.ts` | modify | New cases for the above |

---

## Task 1: Usage telemetry for LLM calls (findings #1, #8)

Read-only cost visibility. Every Groq call already reports `prompt_tokens`/`completion_tokens` in its response; today `groq_llm.py` only prints them. This task persists them per team/job/clip and surfaces them — nothing in this task ever blocks a call.

**Files:**
- Modify: `backend/pipeline/groq_llm.py:96-142` (`GroqChat`)
- Create: `backend/usage.py`
- Create: `supabase/migrations/20261009000000_llm_usage.sql`
- Modify: `backend/db.py`
- Modify: `backend/main.py:375-389` (`_select_and_prepare`), `backend/main.py:1024-1033` (`_run_clip_action` regenerate branch)
- Modify: `frontend/src/services/highlyteApi.js`, `frontend/src/components/ClipCard.vue`
- Test: `tests/test_groq_llm.py`, `tests/test_usage.py` (new)

**Interfaces:**
- Produces: `GroqChat.usage_log: list[tuple[int, int]]` (appended to on every `complete()` call, never cleared internally).
- Produces: `usage.record_many(team_id: str | None, job_id: str, clip_id: str | None, kind: str, calls: list[tuple[int, int]]) -> None`.
- Produces: `usage.team_totals(team_id: str) -> dict` with keys `prompt_tokens`, `completion_tokens`, `calls`, `estimated_usd`.
- Consumes (in `main.py`): `groq_llm.build_chat()` (existing, returns the process-wide singleton `GroqChat`).

- [ ] **Step 1: Write the failing test for `usage_log`**

```python
# tests/test_groq_llm.py (add)
def test_complete_records_usage(monkeypatch):
    from types import SimpleNamespace
    from backend.pipeline import groq_llm

    usage = SimpleNamespace(prompt_tokens=42, completion_tokens=7)
    raw = FakeRaw(content="hi", usage=usage)
    client = FakeOpenAI([raw])
    chat = groq_llm.GroqChat(client, sleep=lambda s: None, clock=lambda: 0.0)
    chat.complete("prompt", max_tokens=100)
    assert chat.usage_log == [(42, 7)]
```

(`FakeRaw`/`FakeOpenAI` import from `tests.llm_fakes`, matching the existing `test_groq_llm.py` import block.)

- [ ] **Step 2: Run it, confirm it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_groq_llm.py::test_complete_records_usage -v`
Expected: FAIL — `AttributeError: 'GroqChat' object has no attribute 'usage_log'`.

- [ ] **Step 3: Add `usage_log` to `GroqChat`**

In `backend/pipeline/groq_llm.py`, add to `__init__` (after `self._lock = threading.Lock()`):

```python
        self.usage_log: list[tuple[int, int]] = []
```

In `complete()`, right after the existing usage `print(...)` block (after the `if usage:` block, before `choice = resp.choices[0]`):

```python
                self.usage_log.append((
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                ) if usage else (0, 0))
```

- [ ] **Step 4: Run it, confirm it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_groq_llm.py -v`
Expected: PASS, all existing `test_groq_llm.py` tests still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/groq_llm.py tests/test_groq_llm.py
git commit -m "$(cat <<'EOF'
Track real token usage per Groq call

GroqChat.usage_log records every call's prompt/completion tokens so
callers can bill it to a job and team, instead of only printing it.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Write the failing test for `usage.py`**

```python
# tests/test_usage.py (new)
from backend import usage


def test_estimate_cost_is_proportional_to_tokens():
    cheap = usage.estimate_cost(100, 50)
    expensive = usage.estimate_cost(1000, 500)
    assert expensive == pytest.approx(cheap * 10)
    assert cheap > 0


def test_record_many_skips_empty_calls(monkeypatch):
    inserted = []
    monkeypatch.setattr(usage.db, "insert_usage", lambda rows: inserted.extend(rows))
    usage.record_many("team-1", "job-1", None, "select", [])
    assert inserted == []


def test_record_many_builds_one_row_per_call(monkeypatch):
    inserted = []
    monkeypatch.setattr(usage.db, "insert_usage", lambda rows: inserted.extend(rows))
    usage.record_many("team-1", "job-1", "clip-1", "regenerate", [(10, 5), (20, 8)])
    assert inserted == [
        {"team_id": "team-1", "job_id": "job-1", "clip_id": "clip-1", "kind": "regenerate",
         "prompt_tokens": 10, "completion_tokens": 5},
        {"team_id": "team-1", "job_id": "job-1", "clip_id": "clip-1", "kind": "regenerate",
         "prompt_tokens": 20, "completion_tokens": 8},
    ]
```

Add `import pytest` at the top of the test file.

- [ ] **Step 7: Run it, confirm it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_usage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.usage'`.

- [ ] **Step 8: Write `backend/usage.py`**

```python
"""Read-only LLM usage telemetry. Nothing in this module ever blocks,
throttles, or denies a request — it only records and reports what a job
or clip action actually cost, so a team (and eventually pricing) has a
real number to look at. See docs/superpowers/plans/
2026-10-09-pipeline-business-logic-fixes.md, Global Constraints.
"""
from __future__ import annotations

from . import db

# Groq's published price for openai/gpt-oss-20b (checked 2026-10-09),
# USD per token. Informational only.
PRICE_PER_PROMPT_TOKEN = 0.10 / 1_000_000
PRICE_PER_COMPLETION_TOKEN = 0.50 / 1_000_000


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return prompt_tokens * PRICE_PER_PROMPT_TOKEN + completion_tokens * PRICE_PER_COMPLETION_TOKEN


def record_many(
    team_id: str | None, job_id: str, clip_id: str | None, kind: str,
    calls: list[tuple[int, int]],
) -> None:
    """One row per LLM call. `calls` is a slice of GroqChat.usage_log —
    the entries made since the caller's last checkpoint."""
    if not calls:
        return
    rows = [{
        "team_id": team_id, "job_id": job_id, "clip_id": clip_id, "kind": kind,
        "prompt_tokens": p, "completion_tokens": c,
    } for p, c in calls]
    db.insert_usage(rows)


def team_totals(team_id: str) -> dict:
    totals = db.sum_usage_for_team(team_id)
    return {
        **totals,
        "estimated_usd": round(estimate_cost(totals["prompt_tokens"], totals["completion_tokens"]), 4),
    }
```

- [ ] **Step 9: Add the DB wrappers**

In `backend/db.py`, add (after `insert_clips`, matching its style):

```python
def insert_usage(rows: list[dict[str, Any]]) -> None:
    client = get_client()
    if client is None or not rows:
        return
    try:
        client.table("llm_usage").insert(rows).execute()
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] insert_usage failed: {e}")


def sum_usage_for_team(team_id: str) -> dict[str, Any]:
    client = get_client()
    empty = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    if client is None:
        return empty
    try:
        res = client.table("llm_usage").select("prompt_tokens, completion_tokens").eq("team_id", team_id).execute()
        rows = res.data or []
        return {
            "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
            "completion_tokens": sum(r["completion_tokens"] for r in rows),
            "calls": len(rows),
        }
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] sum_usage_for_team failed: {e}")
        return empty
```

- [ ] **Step 10: Run it, confirm it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_usage.py -v`
Expected: PASS.

- [ ] **Step 11: Add the migration**

Create `supabase/migrations/20261009000000_llm_usage.sql`:

```sql
-- Read-only LLM usage telemetry (plan: 2026-10-09-pipeline-business-logic-fixes.md).
-- Informational only: nothing in the backend reads this table to block,
-- throttle, or deny a request. It exists so a team can see what a job
-- or a clip action actually cost.
create table if not exists llm_usage (
  id bigint generated always as identity primary key,
  team_id uuid references teams(id) on delete set null,
  job_id text references jobs(id) on delete cascade,
  clip_id text references clips(id) on delete cascade,
  kind text not null,  -- 'select' | 'regenerate' | 'titles' | 'judge'
  prompt_tokens integer not null default 0,
  completion_tokens integer not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists llm_usage_team_idx on llm_usage(team_id, created_at desc);
create index if not exists llm_usage_job_idx on llm_usage(job_id);

alter table llm_usage enable row level security;
```

- [ ] **Step 12: Wire usage capture into job selection**

In `backend/main.py`, change `_select_and_prepare` (around line 375-389):

```python
def _select_and_prepare(job: Job, meta: ingest.VideoMeta, segs: list[Segment], loudness: list[float]) -> None:
    job.status = "analyzing"
    job.progress = {"stage": "analyzing", "percent": None, "note": "picking clips…"}
    _persist_job(job)
    chat = groq_llm.build_chat()
    usage_start = len(chat.usage_log) if chat else 0
    try:
        result = selection.select(segs, loudness)
    except selection.SelectionFailed as e:
        job.status = "selection_failed"
        job.error = str(e)
        job.progress = {}
        _persist_job(job)
        return
    finally:
        if chat:
            usage.record_many(job.team_id, job.id, None, "select", chat.usage_log[usage_start:])
```

(Keep the rest of the function body unchanged below this point.) Add `from . import usage` to the import block near the top of `main.py` (alongside the existing `from . import db` style import — check the exact existing import line and add `usage` to it or as its own line).

- [ ] **Step 13: Wire usage capture into Regenerate**

In `backend/main.py`, inside `_run_clip_action` (around line 1024-1033), wrap the `selection.regenerate(...)` call:

```python
        else:
            chat = groq_llm.build_chat()
            usage_start = len(chat.usage_log) if chat else 0
            try:
                new_clip = selection.regenerate(segs, stored.get("loudness") or [], current, others)
            except selection.SelectionFailed as e:
                fail(str(e))
                return
            finally:
                if chat:
                    usage.record_many(job.team_id, job.id, clip_id, "regenerate", chat.usage_log[usage_start:])
            if new_clip is None:
                fail("No better take found around this moment.")
                return
```

- [ ] **Step 14: Add the read-only usage endpoint**

In `backend/main.py`, near the other `GET /api/...` routes:

```python
@app.get("/api/usage")
def get_usage(member: Member = Depends(current_member)) -> dict[str, Any]:
    return usage.team_totals(member.team_id)
```

- [ ] **Step 15: Frontend — fetch and show usage**

In `frontend/src/services/highlyteApi.js`, add (matching the file's existing fetch-wrapper style):

```js
export function getUsage() {
  return apiGet('/api/usage')
}
```

(Match the exact helper name used by neighboring GET calls in that file — e.g. if the file uses a shared `apiGet` wrapper, reuse it; otherwise mirror the nearest existing `GET` call's exact fetch call shape.)

In `frontend/src/components/ClipCard.vue`, add a small, purely informational line next to the Regenerate button (around line 60) — never disable or hide the button based on this number:

```html
<span v-if="usage" class="usage-hint" title="Informational only — Regenerate has no limit">
  {{ usage.calls }} AI calls so far (~${{ usage.estimated_usd.toFixed(2) }})
</span>
```

Fetch it once in the component (e.g. in the existing `onMounted`/setup block) via `getUsage()` and store in a `ref`; a failed fetch leaves `usage` `null` and the hint simply doesn't render (never blocks the button).

- [ ] **Step 16: Run full test suite**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass (baseline count + 4 new tests).

- [ ] **Step 17: Commit**

```bash
git add backend/usage.py backend/db.py backend/main.py supabase/migrations/20261009000000_llm_usage.sql tests/test_usage.py frontend/src/services/highlyteApi.js frontend/src/components/ClipCard.vue
git commit -m "$(cat <<'EOF'
Show LLM usage and estimated cost, with no cap

Every select/regenerate call is now logged to llm_usage and surfaced
via GET /api/usage and a hint next to Regenerate. This is visibility
only: Regenerate and selection remain uncapped and unthrottled.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Semantic (text) dedup on top of temporal overlap (finding #2)

`scoring.pack()` and `selection.pick_alternate()` today only reject a candidate for overlapping another kept clip's **time span** (`scoring.MAX_OVERLAP`). Two non-overlapping spans that restate the same point (the speaker says it twice, or two ranker windows pick near-duplicate paraphrases) ship side by side. Add a cheap lexical-overlap check — no new dependency, no embedding model.

**Files:**
- Modify: `backend/pipeline/scoring.py:134-156`
- Modify: `backend/pipeline/selection.py:101-116`
- Modify: `backend/main.py:889-902` (`pick_alternate`)
- Test: `tests/test_scoring.py`, `tests/test_selection.py`

**Interfaces:**
- Produces: `scoring.text_overlap(a: Candidate, b: Candidate) -> float` (Jaccard over lowercased word sets).
- Consumes (by `_fits`, `_alternates`, `pick_alternate`): `scoring.MAX_TEXT_OVERLAP: float`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scoring.py (add)
def test_text_overlap_is_jaccard_over_words():
    a = cand(0, 20)
    for w, t in zip(a.words, ("we", "shipped", "it", "anyway") * 5):
        w.t = t
    b = cand(100, 120)
    for w, t in zip(b.words, ("we", "shipped", "it", "anyway") * 5):
        w.t = t
    c = cand(200, 220)
    for w, t in zip(c.words, ("totally", "different", "words", "here") * 5):
        w.t = t
    assert scoring.text_overlap(a, b) == 1.0
    assert scoring.text_overlap(a, c) == 0.0


def test_pack_drops_text_duplicate_even_without_temporal_overlap():
    strong = cand(0, 20, total=0.9)
    for w, t in zip(strong.words, ("we", "shipped", "it", "anyway") * 5):
        w.t = t
    restated = cand(100, 120, total=0.85)  # far away in time, same content
    for w, t in zip(restated.words, ("we", "shipped", "it", "anyway") * 5):
        w.t = t
    other = cand(200, 220, total=0.7)
    kept = scoring.pack([strong, restated, other])
    assert strong in kept and other in kept and restated not in kept
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_scoring.py -k text_overlap -v`
Expected: FAIL — `AttributeError: module 'scoring' has no attribute 'text_overlap'`.

- [ ] **Step 3: Implement in `scoring.py`**

Add near `MAX_OVERLAP` (line 35):

```python
MAX_TEXT_OVERLAP = 0.6
```

Add near `span_overlap`/`overlap_ratio` (after line 135):

```python
def _word_set(c: Candidate) -> set[str]:
    return {w.t.lower() for w in c.words}


def text_overlap(a: Candidate, b: Candidate) -> float:
    """Jaccard similarity of the two clips' words — catches the same point
    restated at a different timestamp, which span_overlap never sees."""
    sa, sb = _word_set(a), _word_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
```

Change `_fits` (line 138-139):

```python
def _fits(c: Candidate, kept: list[Candidate]) -> bool:
    return all(overlap_ratio(c, k) < MAX_OVERLAP and text_overlap(c, k) < MAX_TEXT_OVERLAP for k in kept)
```

- [ ] **Step 4: Run it, confirm it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_scoring.py -v`
Expected: PASS, including all pre-existing `test_scoring.py` tests.

- [ ] **Step 5: Apply the same check to alternates (`selection.py`) and swap (`main.py`)**

In `backend/pipeline/selection.py`, `_alternates` (line 108):

```python
        if any(scoring.span_overlap(span, s) >= scoring.MAX_OVERLAP for s in chosen):
            continue
```

becomes:

```python
        if any(scoring.span_overlap(span, s) >= scoring.MAX_OVERLAP for s in chosen):
            continue
        if any(scoring.text_overlap(c, k) >= scoring.MAX_TEXT_OVERLAP for k in kept_candidates):
            continue
```

This needs the original `Candidate` objects for the already-kept clips in scope; `_alternates(candidates, kept)` already receives `kept: list[scoring.Candidate]` as its second argument, so rename the loop variable reference to use the existing `kept` parameter directly (no new argument needed) — i.e. the check reads `scoring.text_overlap(c, k) >= scoring.MAX_TEXT_OVERLAP for k in kept`.

In `backend/main.py`, `pick_alternate` (line 889-902), add the same check next to the existing overlap check:

```python
def pick_alternate(
    alternates: list[dict[str, Any]], current: tuple[float, float], others: list[tuple[float, float]],
    current_text: str = "", other_texts: list[str] | None = None,
) -> int | None:
    other_texts = other_texts or []
    for i, a in enumerate(alternates):
        span = (a["start"], a["end"])
        if scoring.span_overlap(span, current) >= selection.SAME_MOMENT_OVERLAP:
            continue
        if any(scoring.span_overlap(span, o) >= scoring.MAX_OVERLAP for o in others):
            continue
        words_a = set(a.get("text", "").lower().split())
        if words_a and current_text:
            words_c = set(current_text.lower().split())
            if words_a and words_c and len(words_a & words_c) / len(words_a | words_c) >= scoring.MAX_TEXT_OVERLAP:
                continue
        if other_texts and words_a:
            if any(
                len(words_a & set(t.lower().split())) / len(words_a | set(t.lower().split())) >= scoring.MAX_TEXT_OVERLAP
                for t in other_texts if t
            ):
                continue
        return i
    return None
```

Update both call sites of `pick_alternate` (`_start_clip_action` at line 943 and `_run_clip_action` at line 1013) to also pass `current_text=record["text"]` and `other_texts=[c["text"] for c in job.clips if c["id"] != clip_id]`.

- [ ] **Step 6: Run the full suite**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/pipeline/scoring.py backend/pipeline/selection.py backend/main.py tests/test_scoring.py
git commit -m "$(cat <<'EOF'
Reject text-duplicate clips, not just time-overlapping ones

pack(), the alternates list, and swap/regenerate's pick_alternate all
rejected only by timestamp overlap, so the same point restated at a
different moment could ship twice. Add a word-Jaccard check alongside
the existing span check.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Independent self-containment judge (findings #3, #7)

Today the only signal behind "is this clip self-contained and good" is the ranker's own `standalone`/`hook`/`payoff` self-rating from the same call that picked the clip — no second opinion, no calibration. Add one additional, independent LLM pass over the clips that were actually kept (small, bounded set — at most 8) that re-checks self-containment with zero visibility into the original score. A clip the judge flags is never dropped (avoids the old failure mode of one model's opinion silently discarding content); it's labeled `needs_review` so a human makes the call.

**Files:**
- Create: `backend/pipeline/judge.py`
- Modify: `backend/pipeline/selection.py:127-152` (`select`)
- Modify: `frontend/src/components/ClipCard.vue` (QA label)
- Test: `tests/test_judge.py` (new), `tests/test_selection.py`

**Interfaces:**
- Produces: `judge.Verdict(self_contained: bool, reason: str)`, `judge.review(chat, texts: list[str]) -> list[Verdict]` (one verdict per input text, in order; never raises — a parse failure returns all-permissive verdicts).
- Consumes: `chat.complete(prompt, *, max_tokens) -> ChatResult` (same `GroqChat`/`FakeChat` interface `ranker.py` already uses).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_judge.py (new)
from backend.pipeline import judge
from tests.llm_fakes import FakeChat


def test_review_parses_one_verdict_per_clip():
    chat = FakeChat(['[{"self_contained": true, "reason": "ok"}, {"self_contained": false, "reason": "no payoff"}]'])
    out = judge.review(chat, ["clip one text", "clip two text"])
    assert out == [judge.Verdict(True, "ok"), judge.Verdict(False, "no payoff")]


def test_review_is_permissive_on_empty_input():
    assert judge.review(FakeChat([]), []) == []


def test_review_falls_back_to_permissive_on_bad_answer():
    chat = FakeChat(["not json at all"])
    out = judge.review(chat, ["clip one", "clip two"])
    assert out == [judge.Verdict(True, ""), judge.Verdict(True, "")]


def test_review_falls_back_to_permissive_on_exception():
    chat = FakeChat([RuntimeError("boom")])
    out = judge.review(chat, ["clip one"])
    assert out == [judge.Verdict(True, "")]
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_judge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.pipeline.judge'`.

- [ ] **Step 3: Write `backend/pipeline/judge.py`**

```python
"""Second, independent LLM pass over the clips the ranker already picked.
The ranker's standalone/hook/payoff scores come from the same call that
chose the clip — never checked by anything else. This module asks a
fresh question with none of that context: does this text alone make
sense start to finish? A "no" never drops the clip (the ranker already
decided it was worth keeping); it adds a needs_review flag so a person
makes the final call, instead of trusting one model's self-grade twice.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

MAX_TOKENS = 600
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

PROMPT = """Below are short video clips, each given only by its own text — no other context. For each, answer: does it fully make sense on its own, with no missing setup and no dangling ending? Someone who has seen nothing else of this video must be able to follow it start to finish.

{clips}

Reply with ONLY a JSON array, one entry per clip in order:
[{{"self_contained": true, "reason": "at most 12 words"}}]
"""


@dataclass
class Verdict:
    self_contained: bool
    reason: str = ""


def _format(texts: list[str]) -> str:
    return "\n\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))


def review(chat, texts: list[str]) -> list[Verdict]:
    """One independent verdict per text, in the same order. Any failure to
    get or parse an answer returns an all-permissive verdict list rather
    than raising — a flaky judge must never fail a selection that already
    succeeded."""
    if not texts:
        return []
    prompt = PROMPT.format(clips=_format(texts))
    try:
        result = chat.complete(prompt, max_tokens=MAX_TOKENS)
        match = _JSON_ARRAY_RE.search(result.content or "")
        if not match:
            raise ValueError("no JSON array in judge answer")
        data = json.loads(match.group(0))
        if not isinstance(data, list):
            raise ValueError("judge answer was not a list")
    except Exception as e:  # noqa: BLE001
        print(f"[judge] review skipped: {e}")
        return [Verdict(True, "") for _ in texts]

    out: list[Verdict] = []
    for i in range(len(texts)):
        item = data[i] if i < len(data) and isinstance(data[i], dict) else {}
        out.append(Verdict(
            self_contained=item.get("self_contained", True) is not False,
            reason=str(item.get("reason", ""))[:120] if item.get("self_contained") is False else "",
        ))
    return out
```

- [ ] **Step 4: Run it, confirm it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_judge.py -v`
Expected: PASS.

- [ ] **Step 5: Wire into `selection.select()`**

In `backend/pipeline/selection.py`, add `judge` to the module import (line 10: `from . import groq_llm, judge, ranker, scoring, snap, titles`), add `from dataclasses import dataclass, field, replace` (line 8 — add `replace`), and change `select()` (lines 143-144):

```python
    clips = [_to_clip(c, m) for c, m in zip(kept, meta)]
```

to:

```python
    clips = [_to_clip(c, m) for c, m in zip(kept, meta)]
    verdicts = judge.review(chat, texts)
    clips = [
        c if v.self_contained else replace(c, flags=[*c.flags, "needs_review"], reason=v.reason or c.reason)
        for c, v in zip(clips, verdicts)
    ]
```

(`texts` is already computed two lines above as `texts = [_text(c) for c in kept]`.)

- [ ] **Step 6: Write the selection-level test**

```python
# tests/test_selection.py (add — match the file's existing fixture/fake style)
def test_select_flags_clips_the_judge_rejects(...):
    # Build a chat whose replies are: one ranker-window reply with one good
    # pick, one titles reply, one judge reply marking it not self-contained.
    # Assert the returned clip still appears in result.clips but carries
    # "needs_review" in its flags, and that its score/text are unchanged.
    ...
```

Implement this using the same `FakeChat`/segment-building helpers the rest of `tests/test_selection.py` already uses (reuse its existing transcript-building fixtures rather than inventing new ones — read the file's top-of-file helpers first).

- [ ] **Step 7: Run it, confirm it passes; run the full suite**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 8: Frontend — label the new flag**

In `frontend/src/components/ClipCard.vue`, extend `QA_LABELS` (line 106-110):

```js
const QA_LABELS = {
  low_confidence: 'Low confidence — check captions',
  weak_pick: 'Weaker pick',
  no_face_start: 'No face at start',
  needs_review: 'Needs a human check',
}
```

- [ ] **Step 9: Commit**

```bash
git add backend/pipeline/judge.py backend/pipeline/selection.py tests/test_judge.py tests/test_selection.py frontend/src/components/ClipCard.vue
git commit -m "$(cat <<'EOF'
Add an independent self-containment check after selection

The ranker's standalone/hook/payoff scores were the only signal behind
every pick — one model grading its own answer. judge.review() asks a
second, context-free question per kept clip; disagreement flags
needs_review instead of silently trusting (or silently discarding) the
first score.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

*(Note: this does not build an engagement-feedback calibration loop — there is no engagement data pipeline to calibrate against yet. Building one here would be speculative; a second independent signal is the fix that's actually buildable today.)*

---

## Task 4: Honest signaling for weak-pick backfill clips (finding #4)

`scoring.pack()` already flags backfilled clips `weak_pick` (line 155) and `ClipCard.vue` already renders a "Weaker pick" chip (line 108). What's missing: the chip doesn't say *why*, so "honest signaling" is only half done. Add the reason as a tooltip.

**Files:**
- Modify: `frontend/src/components/ClipCard.vue:42, 106-110`
- Test: manual (no new unit test — this is a template-only change to an existing, already-tested data flow)

**Interfaces:**
- Consumes: `clip.qaFlags` (existing), `clip.reason` (existing field, already populated by `scoring.Candidate.reason` / `ranker.Pick.reason` through `selection._to_clip`).

- [ ] **Step 1: Add a tooltip map next to `QA_LABELS`**

In `frontend/src/components/ClipCard.vue`, after the `QA_LABELS` block (line 110):

```js
const QA_TOOLTIPS = {
  weak_pick: 'Added to reach the minimum clip count — this moment scored below our normal bar for standalone sense or hook strength.',
  needs_review: 'An independent check could not confirm this clip fully makes sense on its own — worth a quick watch before posting.',
  low_confidence: 'Some words had low transcription confidence — check the captions match what was actually said.',
}
```

- [ ] **Step 2: Use it on the chip**

Change line 42 from:

```html
<span v-for="f in clip.qaFlags || []" :key="f" class="chip chip-warning">{{ QA_LABELS[f] || f }}</span>
```

to:

```html
<span v-for="f in clip.qaFlags || []" :key="f" class="chip chip-warning" :title="QA_TOOLTIPS[f] || ''">{{ QA_LABELS[f] || f }}</span>
```

- [ ] **Step 3: Verify in the browser**

Run the app (`run` skill or existing dev-server instructions), open a job whose result includes a weak-pick clip, hover the "Weaker pick" chip, confirm the tooltip text appears.

- [ ] **Step 4: Frontend build check**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ClipCard.vue
git commit -m "$(cat <<'EOF'
Explain weak-pick and needs-review chips on hover

The chips said a clip was weaker or needed review but never why. Add
tooltips so the signal is actually honest, not just present.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Drop the podcast-only framing from both prompts (finding #5)

Building real content-type detection (and a prompt-variant system) would be speculative without evidence of what other content types customers actually upload. The concrete, low-risk fix available today: the ranker and titles prompts currently say "podcast" explicitly, which is false advertising for any non-podcast upload (a solo tutorial, a vlog, a webinar) even though the actual selection logic (complete idea, standalone, hook, payoff) has nothing podcast-specific about it. Generalize the wording; keep the Hinglish-aware filler-word handling (harmless no-ops for English-only content).

**Files:**
- Modify: `backend/pipeline/ranker.py:20-36`
- Modify: `backend/pipeline/titles.py:32-43`
- Test: `tests/test_ranker.py`, `tests/test_titles.py`

**Interfaces:**
- No signature changes — `PROMPT` stays a module-level `.format()` template in both files.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ranker.py (add)
def test_prompt_does_not_assume_podcast_content():
    assert "podcast" not in ranker.PROMPT.lower()
```

```python
# tests/test_titles.py (add)
def test_prompt_does_not_assume_podcast_content():
    assert "podcast" not in titles.PROMPT.lower()
```

- [ ] **Step 2: Run them, confirm both fail**

Run: `./.venv/Scripts/python -m pytest tests/test_ranker.py tests/test_titles.py -k podcast -v`
Expected: both FAIL (current prompts contain "podcast").

- [ ] **Step 3: Edit `ranker.PROMPT`**

In `backend/pipeline/ranker.py`, change line 20:

```python
PROMPT = """You pick short-form clips from a podcast transcript. Each line is one utterance: "<id>: <text>". A blank line separates complete thoughts. The text mixes English with Roman-script Hindi/Urdu.
```

to:

```python
PROMPT = """You pick short-form clips from a video's transcript. Each line is one utterance: "<id>: <text>". A blank line separates complete thoughts. The text mixes English with Roman-script Hindi/Urdu.
```

and line 25:

```python
- makes sense to someone who has seen nothing else of this podcast;
```

to:

```python
- makes sense to someone who has seen nothing else of this video;
```

- [ ] **Step 4: Edit `titles.PROMPT`**

In `backend/pipeline/titles.py`, change line 32:

```python
PROMPT = """You write short-form video metadata for podcast clips. The text mixes English with Roman-script Hindi/Urdu.
```

to:

```python
PROMPT = """You write short-form video metadata for these clips. The text mixes English with Roman-script Hindi/Urdu.
```

- [ ] **Step 5: Run the tests, confirm they pass; run the full suite**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass (prompt wording isn't asserted elsewhere — confirmed by grep before this task started).

- [ ] **Step 6: Commit**

```bash
git add backend/pipeline/ranker.py backend/pipeline/titles.py tests/test_ranker.py tests/test_titles.py
git commit -m "$(cat <<'EOF'
Stop telling the model this is always a podcast

Selection logic (complete idea, standalone, hook, payoff) has nothing
podcast-specific in it, but both LLM prompts said "podcast" outright —
wrong framing for a tutorial, vlog, or webinar upload. Generalize the
wording; Hinglish-aware filler handling is unchanged and still a no-op
for English-only content.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

*(Full content-type-aware prompt variants are out of scope here — there's no evidence yet of which other content types customers actually upload, or what a "tutorial" vs. "vlog" prompt should say differently. Revisit once usage data (Task 1) shows what's actually being clipped.)*

---

## Task 6: Speaker diarization (finding #6)

`segments.py:57` hardcodes `speaker="A"` with the comment "no diarization in v1". The downstream machinery is already speaker-aware and waiting: `utterances.build_utterances()` already splits an utterance whenever `seg.speaker != speaker` (utterances.py:89), and `Utterance.speaker` already flows through to `ThoughtUnit`. This task only needs to supply real speaker labels.

**Files:**
- Create: `backend/pipeline/diarize.py`
- Modify: `backend/pipeline/segments.py:1-96` (`apply_speakers`)
- Modify: `backend/pipeline/transcript.py:79-124` (`transcribe`)
- Modify: `backend/pipeline/ranker.py:90-91` (`format_window`)
- Modify: `requirements.txt`
- Test: `tests/test_diarize.py` (new), `tests/test_segments.py`, `tests/test_transcript.py`, `tests/test_ranker.py`

**Interfaces:**
- Produces: `diarize.Turn(start: float, end: float, speaker: str)`, `diarize.available() -> bool`, `diarize.run(wav_path: str) -> list[Turn]` (returns `[]` when `HF_TOKEN` isn't set — zero behavior change for anyone who hasn't opted in).
- Produces: `segments.apply_speakers(segs: list[Segment], turns: list[tuple[float, float, str]]) -> list[Segment]`.
- Consumes (in `transcript.py`): the existing `wav` local variable already in scope in `transcribe()`.

- [ ] **Step 1: Write the failing test for `apply_speakers`**

```python
# tests/test_segments.py (add)
def test_apply_speakers_relabels_by_midpoint_overlap():
    segs = [
        segments._segment(1, words(0.0, 5.0), "en"),
        segments._segment(2, words(5.0, 10.0), "en"),
    ]
    turns = [(0.0, 6.0, "SPEAKER_00"), (6.0, 20.0, "SPEAKER_01")]
    out = segments.apply_speakers(segs, turns)
    assert out[0].speaker == "SPEAKER_00"
    assert out[1].speaker == "SPEAKER_01"


def test_apply_speakers_is_a_no_op_with_no_turns():
    segs = [segments._segment(1, words(0.0, 5.0), "en")]
    assert segments.apply_speakers(segs, [])[0].speaker == "A"
```

(Add a local `words(start, end)` helper to `test_segments.py` matching the one already used in `test_scoring.py` if the file doesn't already have one — check first.)

- [ ] **Step 2: Run it, confirm it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_segments.py -k apply_speakers -v`
Expected: FAIL — `AttributeError: module 'segments' has no attribute 'apply_speakers'`.

- [ ] **Step 3: Implement `apply_speakers` in `segments.py`**

Add `replace` to the existing import (line 9): `from dataclasses import asdict, dataclass, field, replace`. Add after `build()` (line 80):

```python
def apply_speakers(segs: list[Segment], turns: list[tuple[float, float, str]]) -> list[Segment]:
    """Relabels each segment by which diarization turn covers its
    midpoint. An empty `turns` (diarization unavailable or not
    configured) is a no-op: every segment keeps its existing "A" label,
    so this is exactly today's behaviour until HF_TOKEN is set."""
    if not turns:
        return segs
    out = []
    for s in segs:
        mid = (s.start + s.end) / 2
        speaker = next((spk for start, end, spk in turns if start <= mid < end), s.speaker)
        out.append(replace(s, speaker=speaker))
    return out
```

- [ ] **Step 4: Run it, confirm it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_segments.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing test for `diarize.py`**

```python
# tests/test_diarize.py (new)
import pytest

from backend.pipeline import diarize


def test_available_is_false_without_hf_token(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    diarize._pipeline.cache_clear()
    assert diarize.available() is False


def test_run_returns_empty_without_hf_token(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    diarize._pipeline.cache_clear()
    assert diarize.run("unused.wav") == []
```

- [ ] **Step 6: Run it, confirm it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_diarize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.pipeline.diarize'`.

- [ ] **Step 7: Write `backend/pipeline/diarize.py`**

```python
"""Optional speaker diarization. v1 hardcoded every segment's speaker to
"A" (segments.py); this fills that in for real using pyannote's
pretrained pipeline, gated on HF_TOKEN so a deployment that never sets
it behaves exactly as before — single speaker, unchanged prompts.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

MODEL = "pyannote/speaker-diarization-3.1"


@dataclass
class Turn:
    start: float
    end: float
    speaker: str  # "SPEAKER_00", "SPEAKER_01", ...


@lru_cache(maxsize=1)
def _pipeline():
    token = os.environ.get("HF_TOKEN")
    if not token:
        return None
    from pyannote.audio import Pipeline  # heavy import, deferred until actually needed

    return Pipeline.from_pretrained(MODEL, use_auth_token=token)


def available() -> bool:
    return _pipeline() is not None


def run(wav_path: str) -> list[Turn]:
    """Every speaker turn in the file, or [] if diarization isn't
    configured (no HF_TOKEN) or the pipeline itself fails — a diarization
    failure degrades to "no diarization", never to a hard job failure."""
    pipeline = _pipeline()
    if pipeline is None:
        return []
    try:
        annotation = pipeline(wav_path)
    except Exception as e:  # noqa: BLE001
        print(f"[diarize] run failed: {e}")
        return []
    return [
        Turn(start=round(turn.start, 3), end=round(turn.end, 3), speaker=label)
        for turn, _, label in annotation.itertracks(yield_label=True)
    ]
```

- [ ] **Step 8: Run it, confirm it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_diarize.py -v`
Expected: PASS.

- [ ] **Step 9: Add the dependency**

In `requirements.txt`, add:

```
pyannote.audio==3.1.1
```

Note in a comment above it (matching the file's existing comment style, e.g. above the `mediapipe` line):

```
# Speaker diarization (backend/pipeline/diarize.py). Pulls in torch; only
# activates when HF_TOKEN is set — see diarize.available().
pyannote.audio==3.1.1
```

- [ ] **Step 10: Wire into `transcript.transcribe()`**

In `backend/pipeline/transcript.py`, add `from . import diarize` to the imports. Change the return block (lines 116-121):

```python
        fixed = hinglish.fix(segments.from_asr(words), decision.used)
        return Transcript(
            segments=segments.build(fixed, LANGUAGE_CODES[decision.used]),
            language=decision.used, note=decision.note, source=source,
            loudness=loudness,
        )
```

to:

```python
        fixed = hinglish.fix(segments.from_asr(words), decision.used)
        built = segments.build(fixed, LANGUAGE_CODES[decision.used])
        turns = [(t.start, t.end, t.speaker) for t in diarize.run(wav)]
        return Transcript(
            segments=segments.apply_speakers(built, turns),
            language=decision.used, note=decision.note, source=source,
            loudness=loudness,
        )
```

(`wav` is the normalized mono WAV path already created at line 90, still on disk at this point — `shutil.rmtree(tmp_dir, ...)` only runs in the `finally` block afterward.)

- [ ] **Step 11: Speaker-tag the ranker's window text when more than one speaker is present**

In `backend/pipeline/ranker.py`, change `format_window` (lines 90-91):

```python
def format_window(units: list[ThoughtUnit], idxs: list[int]) -> str:
    return "\n\n".join("\n".join(f"{u.id}: {u.text}" for u in units[i].utterances) for i in idxs)
```

to:

```python
def format_window(units: list[ThoughtUnit], idxs: list[int]) -> str:
    speakers = {u.speaker for i in idxs for u in units[i].utterances}
    tag = (lambda u: f"{u.id} [{u.speaker}]") if len(speakers) > 1 else (lambda u: u.id)
    return "\n\n".join("\n".join(f"{tag(u)}: {u.text}" for u in units[i].utterances) for i in idxs)
```

- [ ] **Step 12: Test the speaker-tagging behavior**

```python
# tests/test_ranker.py (add — build two ThoughtUnits whose Utterances have
# differing .speaker values via the existing test helpers in this file;
# read the file's existing unit-building helper first and reuse it)
def test_format_window_tags_speakers_when_more_than_one_present():
    ...  # assert "[SPEAKER_00]" and "[SPEAKER_01]" appear in the output

def test_format_window_omits_tags_for_a_single_speaker():
    ...  # assert no "[" appears when every utterance has the same speaker
```

- [ ] **Step 13: Run the full suite**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass. (`pip install -r requirements.txt` first if `pyannote.audio` isn't yet installed in `.venv` — this is a real new dependency; confirm the install succeeds before relying on `diarize.py`'s import.)

- [ ] **Step 14: Commit**

```bash
git add backend/pipeline/diarize.py backend/pipeline/segments.py backend/pipeline/transcript.py backend/pipeline/ranker.py requirements.txt tests/test_diarize.py tests/test_segments.py tests/test_ranker.py
git commit -m "$(cat <<'EOF'
Add speaker diarization, gated on HF_TOKEN

segments.py hardcoded every speaker to "A" since v1, even though
utterances.py already splits on speaker changes and carries a speaker
field through to the ranker. diarize.py fills it in for real with
pyannote when HF_TOKEN is set; with no token, behavior is unchanged.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Soft duration band instead of a hard reject wall (finding #9)

`scoring.structural_reject()` hard-rejects anything under 8 s or over 60 s, even a single genuinely great complete idea that runs 65 s. `duration_fit()` already soft-scores the 12–35 s ideal band and tapers toward the outer bounds — the fix is widening the hard outer bounds (so tapering, not rejection, handles the extremes) rather than removing the wall entirely (a 2-second or 10-minute "clip" is never a usable short-form clip regardless of content).

**Files:**
- Modify: `backend/pipeline/scoring.py:18-21, 61-68, 94-100`
- Modify: `backend/main.py:32-33` (duplicate constants — keep them in sync)
- Test: `tests/test_scoring.py`

**Interfaces:**
- No signature changes — only the `MIN_CLIP_S`/`MAX_CLIP_S` constants and `duration_fit()`'s anchors move.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scoring.py (add)
def test_duration_wall_allows_a_great_clip_past_the_old_60s_cap():
    long_clip = cand(0, 65, prob=0.9)  # was hard-rejected before this change
    assert scoring.structural_reject(long_clip) is None
    assert scoring.duration_fit(65) > 0.0  # tapered, not zeroed


def test_duration_wall_still_rejects_genuinely_unusable_lengths():
    assert scoring.structural_reject(cand(0, 3)) == "too_short"
    assert scoring.structural_reject(cand(0, 95)) == "too_long"
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_scoring.py -k duration_wall -v`
Expected: FAIL — 65 s still rejected under the old `MAX_CLIP_S = 60.0`.

- [ ] **Step 3: Widen the outer bounds**

In `backend/pipeline/scoring.py`, change lines 18-21:

```python
MIN_CLIP_S = 8.0
MAX_CLIP_S = 60.0
FIT_LOW_S = 12.0
FIT_HIGH_S = 35.0
```

to:

```python
MIN_CLIP_S = 4.0
MAX_CLIP_S = 90.0
FIT_LOW_S = 12.0
FIT_HIGH_S = 35.0
```

(`duration_fit()` and `structural_reject()` already read these constants — no other code change needed in this file.)

- [ ] **Step 4: Keep `main.py`'s duplicate constants in sync**

In `backend/main.py`, lines 32-33, change the matching `MIN_CLIP_S`/`MAX_CLIP_S` values to `4.0`/`90.0` to match.

- [ ] **Step 5: Run it, confirm it passes; run the full suite**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass. Check `test_duration_fit` (existing, line 20-25 of `test_scoring.py`) still holds — its assertions (`duration_fit(20) == 1.0`, `duration_fit(10) == 0.5`, `duration_fit(8) == 0.0`, `duration_fit(47.5) == 0.5`, `duration_fit(61) == 0.0`) depend on the **old** `MIN_CLIP_S`/`MAX_CLIP_S`; with the new bounds, `duration_fit(8)` and `duration_fit(61)` are no longer `0.0` (8 s and 61 s are now inside the widened band). Update those two assertions in the existing test to match the new anchors:

```python
def test_duration_fit():
    assert scoring.duration_fit(20) == 1.0
    assert scoring.duration_fit(10) == 0.5
    assert scoring.duration_fit(4) == 0.0
    assert scoring.duration_fit(47.5) == 0.5
    assert scoring.duration_fit(90) == 0.0
```

- [ ] **Step 6: Commit**

```bash
git add backend/pipeline/scoring.py backend/main.py tests/test_scoring.py
git commit -m "$(cat <<'EOF'
Widen the hard duration wall; let tapering handle the extremes

8-60s hard-rejected a genuinely great complete idea running a few
seconds past either edge. duration_fit() already tapers score toward
the ideal 12-35s band, so widen the reject wall to 4-90s and let
scoring, not a hard cutoff, deprioritize the extremes.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Face-aware caption position for single-face close-ups (finding #10)

Split-layout captions are **already** handled: `renderer/src/lib/view.ts:36-40` (`captionPositionAt`) already puts captions at the seam (`middle`) during a genuine two-person split and respects the user's setting during a close-up within a split clip. What's still missing: a close-up in **any** layout (`follow`/`speaker`, not just `split`) can have the active face sitting low in frame (chin near the bottom third) while the user's chosen `captionPosition` is `'lower'` (the app default — see `renderer/src/Root.tsx:15`), which puts the caption band right over the mouth/chin. Extend the existing occlusion-awareness to that case using face-track position data that's already computed and stored (`FaceTrack.track[].cy`).

**Files:**
- Modify: `renderer/src/lib/view.ts:33-40`
- Modify: `renderer/src/lib/view.test.ts`

**Interfaces:**
- Modifies: `captionPositionAt(spec, style, t)` (same signature, same return type `'lower' | 'middle'`).
- Produces (internal): `faceCyAt(faces, faceId, t) -> number | null`.

- [ ] **Step 1: Write the failing test**

```typescript
// renderer/src/lib/view.test.ts (add, after the existing `describe('captionPositionAt', ...)` block)
describe('captionPositionAt avoids a low face in a single-face close-up', () => {
  const lowFaceSpec = structuredClone(fixture)
  lowFaceSpec.reframe.faces[1].track = lowFaceSpec.reframe.faces[1].track.map(p => ({ ...p, cy: 0.8 }))
  const parsedLow = clipSpecSchema.parse(lowFaceSpec)

  it('switches a low face in a non-split close-up to middle', () => {
    // t=5 is inside the fixture's second shot: kind "one", faceIds [1]
    expect(captionPositionAt(parsedLow, style('follow', 'lower'), 5)).toBe('middle')
  })

  it('leaves a high-enough face on the configured position', () => {
    expect(captionPositionAt(spec, style('follow', 'lower'), 5)).toBe('lower')
  })

  it('an explicit middle setting is untouched either way', () => {
    expect(captionPositionAt(parsedLow, style('follow', 'middle'), 5)).toBe('middle')
  })
})
```

- [ ] **Step 2: Run it, confirm the first case fails**

Run: `cd renderer && npx vitest run src/lib/view.test.ts`
Expected: FAIL on "switches a low face in a non-split close-up to middle" (currently returns `'lower'`, the unmodified `style.captionPosition`).

- [ ] **Step 3: Implement in `view.ts`**

In `renderer/src/lib/view.ts`, after the imports (line 3), add:

```typescript
// A close-up whose face sits in the lower part of the frame risks the
// caption band (captionPosition 'lower') landing on the mouth/chin.
// 0.62 is a heuristic: the 'lower' band starts at 70% of frame height
// (Captions.tsx), so a face centred near or past 62% is close enough to
// risk it.
const FACE_LOW_CY = 0.62

function faceCyAt(faces: ClipSpec['reframe']['faces'], faceId: number, t: number): number | null {
  const track = faces.find(f => f.id === faceId)?.track
  if (!track || track.length === 0) return null
  let point = track[0]
  for (const p of track) {
    if (p.t <= t) point = p
    else break
  }
  return point.cy
}
```

Change `captionPositionAt` (lines 36-40):

```typescript
export function captionPositionAt(spec: ClipSpec, style: ClipStyle, t: number): 'lower' | 'middle' {
  if (resolveView(spec, style.layout, t).kind === 'two') return 'middle'
  if (style.layout === 'split') return 'lower'
  return style.captionPosition
}
```

to:

```typescript
export function captionPositionAt(spec: ClipSpec, style: ClipStyle, t: number): 'lower' | 'middle' {
  const view = resolveView(spec, style.layout, t)
  if (view.kind === 'two') return 'middle'
  if (style.layout === 'split') return 'lower'
  if (view.kind === 'one' && style.captionPosition === 'lower') {
    const cy = faceCyAt(spec.reframe.faces, view.faceId, t)
    if (cy !== null && cy >= FACE_LOW_CY) return 'middle'
  }
  return style.captionPosition
}
```

- [ ] **Step 4: Run it, confirm it passes**

Run: `cd renderer && npx vitest run src/lib/view.test.ts`
Expected: all cases pass, including every pre-existing `captionPositionAt`/`resolveView` test (the fixture's real face `cy` values are `0.4`/`0.42`, both under `0.62`, so none of the existing assertions change behavior).

- [ ] **Step 5: Full renderer check**

Run: `cd renderer && npx vitest run`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add renderer/src/lib/view.ts renderer/src/lib/view.test.ts
git commit -m "$(cat <<'EOF'
Avoid caption occlusion on a low face in non-split close-ups too

captionPositionAt already protected the split-layout seam case. Extend
the same idea to any single-face close-up (follow/speaker) whose face
sits low enough in frame that a 'lower' caption band would land on the
mouth or chin, using the face track's own cy data.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Notes

- **Coverage:** all 10 audit findings map to a task above (see the map table); #3/#7 are intentionally one task (both are "the self-rating has no second check"), #1/#8 are intentionally one task (both are "no cost visibility" — resolved as visibility, explicitly not as a cap, per the user's constraint).
- **No caps added:** re-read every task above — Task 1 only records and displays; Tasks 2, 3, 5, 6, 7, 8 change selection/rendering quality, not request volume; Task 4 is a UI label. Nothing here rejects a user's or teammate's request based on how many times they've made it.
- **New dependency called out:** `pyannote.audio` (Task 6) is flagged in Global Constraints as the one approved heavy addition, with its opt-in gate (`HF_TOKEN`) stated explicitly so it can't silently become a required install.
- **Type/name consistency check:** `scoring.text_overlap`, `scoring.MAX_TEXT_OVERLAP`, `judge.Verdict`/`judge.review`, `diarize.Turn`/`diarize.run`/`diarize.available`, `segments.apply_speakers`, `usage.record_many`/`usage.team_totals`, and `view.faceCyAt` are each defined once (Task 2/3/6/1/8 respectively) and referenced with the same names everywhere they're used later in the same task — no renames across steps.
