# Piece 2: Clip Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `backend/pipeline/highlight.py` with a clip selector that packs the stored transcript into utterances and thought units, asks a paced Groq LLM to pick utterance ranges, snaps every cut in code, scores and packs 5–8 clips, flags weak ones for QA, and fails into a retryable `selection_failed` state instead of failing silently.

**Architecture:** Seven small modules in `backend/pipeline/` (`utterances`, `snap`, `scoring`, `groq_llm`, `ranker`, `titles`, `selection`), each pure except the two LLM calls behind one paced client. `backend/main.py` runs selection from the transcript it just saved (or, on retry, from the stored one), stores QA flags and a selection note, and exposes `POST /api/jobs/{id}/select`. The Vue frontend shows the retry state, the note and QA chips.

**Tech Stack:** Python 3.11, FastAPI, `openai==1.57.4` client against Groq (`openai/gpt-oss-20b`), numpy, Supabase Postgres (CLI migrations), pytest; Vue 3 + Pinia + Vite.

**Spec:** `docs/superpowers/specs/2026-09-26-clip-selection-design.md`

## Global Constraints

- Branch `hinglish-v1`. **Never push.** Never `git stash`, `git reset` or `git commit --amend`. Never stage `renderer/package-lock.json`.
- Never kill or stop processes. Never enter passwords.
- Every commit message ends with a blank line then: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- Run Python tests with `./.venv/Scripts/python -m pytest -q` from the repo root (`D:\Personal\HighLyte`, Git Bash). Baseline before this plan: 249 passed.
- Frontend check: `cd frontend && npm run build`.
- Groq free tier for `openai/gpt-oss-20b`: 8k tokens/minute, 200k tokens/day. Every call stays near 6k tokens including reasoning; always `reasoning_effort: "low"` via `extra_body`.
- The ranker picks utterance ids only; LLM timestamps are never requested or read. Code owns every cut point.
- Score: `total = 0.40·standalone + 0.25·hook + 0.15·payoff + 0.10·energy + 0.10·duration_fit`; `viralityScore = round(total × 10, 1)`.
- Hard limits: clips 8–60 s, prefer 12–35 s, at most 8 clips, near-miss fill up to 5.
- QA flag ids and labels: `low_confidence` = "Low confidence — check captions", `weak_pick` = "Weaker pick", `no_face_start` = "No face at start".
- Selection must fail visibly: no key, daily limit or every window failing ends the job in `selection_failed` with a readable message; partial failure writes `selection_note`.
- The new migration must be applied locally before running the app: `npx supabase db push --db-url "$DBURL"` (the user sets `DBURL`; never ask for or print it).

## File map

| File | Status | Responsibility |
|---|---|---|
| `supabase/migrations/20260926180000_clip_selection.sql` | create | `transcripts.loudness`, `jobs.selection_note`, `clips.qa_flags` |
| `backend/pipeline/audio.py` | modify | `loudness_db()` |
| `backend/pipeline/segments.py` | modify | `from_dict()` |
| `backend/pipeline/transcript.py` | modify | `Transcript.loudness`, `word_segments()` |
| `backend/db.py` | modify | `save_transcript(..., loudness)` |
| `backend/pipeline/utterances.py` | create | utterances, thought units, `norm()` |
| `backend/pipeline/snap.py` | create | cut points, filler rules |
| `backend/pipeline/scoring.py` | create | `Candidate`, score, rejects, QA flags, packing |
| `backend/pipeline/groq_llm.py` | create | paced Groq client, rate-limit parsing, shared errors |
| `backend/pipeline/ranker.py` | create | windows, prompt, parsing, `rank()` |
| `backend/pipeline/titles.py` | create | hook titles, emphasis, tags, fallback |
| `backend/pipeline/selection.py` | create | `Clip`, `Selection`, `select()`, `skipped_note()` |
| `backend/pipeline/highlight.py` | delete | replaced |
| `backend/pipeline/clipprep.py` | modify | import `Clip` from selection; `face_at_start` |
| `backend/main.py` | modify | pipeline wiring, `selection_failed`, retry endpoint, QA flags, note |
| `backend/projects.py` | modify | keep `selection_failed` rows, group it under "error" |
| `frontend/src/services/highlyteApi.js` | modify | `retrySelection()` |
| `frontend/src/stores/jobStore.js` | modify | `selectionFailed`, `retrySelection()` |
| `frontend/src/views/JobView.vue` | modify | retry panel, selection note |
| `frontend/src/components/ClipCard.vue` | modify | QA chips |
| `frontend/src/components/ProjectCard.vue` | modify | "Needs retry" badge |
| `scripts/select_dry_run.py` | create | run selection on a stored transcript |
| `tests/llm_fakes.py` | create | fake OpenAI client and fake chat shared by LLM tests |
| `tests/test_utterances.py`, `test_snap.py`, `test_scoring.py`, `test_groq_llm.py`, `test_ranker.py`, `test_titles.py`, `test_selection.py` | create | unit tests |
| `tests/test_highlight.py` | delete | module deleted |
| `tests/test_transcript.py`, `test_transcript_store.py`, `test_segments.py`, `test_audio.py`, `test_clipprep.py`, `test_pipeline_run.py`, `test_status.py`, `test_projects.py` | modify | new behaviour |

---

### Task 1: Stored data: migration, loudness, segment round-trip

**Files:**
- Create: `supabase/migrations/20260926180000_clip_selection.sql`
- Modify: `backend/pipeline/audio.py`, `backend/pipeline/segments.py`, `backend/pipeline/transcript.py`, `backend/db.py:102-111`
- Test: `tests/test_audio.py`, `tests/test_segments.py`, `tests/test_transcript.py`, `tests/test_transcript_store.py`

**Interfaces:**
- Produces: `audio.loudness_db(samples: np.ndarray, step_s: float = 0.5) -> list[float]`; `audio.LOUDNESS_STEP_S = 0.5`; `segments.from_dict(d: dict) -> Segment`; `Transcript.loudness: list[float]` (default `[]`); `transcript.word_segments(segs: list[Segment]) -> list[TranscriptSegment]`; `db.save_transcript(job_id, language, source, segments, loudness: list[float] | None = None)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audio.py`:

```python
def test_loudness_db_one_value_per_half_second():
    import numpy as np
    from backend.pipeline import audio

    sr = audio.SR
    loud = np.full(sr // 2, 0.1, dtype=np.float32)     # RMS 0.1 -> -20 dB
    quiet = np.zeros(sr // 2, dtype=np.float32)        # silence -> floor
    tail = np.full(sr // 4, 0.1, dtype=np.float32)     # partial last block
    values = audio.loudness_db(np.concatenate([loud, quiet, tail]))
    assert values == [-20.0, -100.0, -20.0]
```

Append to `tests/test_segments.py`:

```python
def test_from_dict_round_trips_to_dict():
    seg = segments.build([w("yaar", 1.0, 1.5, prob=0.8, raw="yar"), w("sun.", 1.5, 1.8, prob=0.6)], "hi-Latn-EN")[0]
    back = segments.from_dict(seg.to_dict())
    assert back == seg


def test_from_dict_tolerates_missing_optional_fields():
    back = segments.from_dict({"id": "seg_0001", "start": 0.0, "end": 0.5,
                               "words": [{"t": "hi", "start": 0.0, "end": 0.5}]})
    assert back.speaker == "A" and back.words[0].raw == "hi" and back.words[0].prob == 0.0
```

Append to `tests/test_transcript.py`:

```python
def test_transcribe_returns_loudness(fake_audio):
    asr_ = FakeAsr([AsrWord("hello", 0.0, 0.5, 0.9)])
    t = transcript.transcribe("a.m4a", "english", detect=lambda p: "english", primary=asr_, fallback=asr_)
    assert len(t.loudness) == 120  # fake_audio is 60 s of silence: one value per 0.5 s
    assert set(t.loudness) == {-100.0}


def test_word_segments_flattens_segments(fake_audio):
    asr_ = FakeAsr([AsrWord("hello", 0.0, 0.5, 0.9), AsrWord("there", 0.5, 0.9, 0.9)])
    t = transcript.transcribe("a.m4a", "english", detect=lambda p: "english", primary=asr_, fallback=asr_)
    assert [(s.start, s.text) for s in transcript.word_segments(t.segments)] == [(0.0, "hello"), (0.5, "there")]
```

`FakeAsr` and the `fake_audio` fixture already exist at the top of `tests/test_transcript.py`.

Append to `tests/test_transcript_store.py`:

```python
def test_save_transcript_stores_loudness(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(db, "get_client", lambda: fake)
    db.save_transcript("job1", "hinglish", "groq", [], [-20.0, -18.5])
    assert db.get_transcript("job1")["loudness"] == [-20.0, -18.5]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest -q tests/test_audio.py tests/test_segments.py tests/test_transcript.py tests/test_transcript_store.py`
Expected: FAIL (`loudness_db`, `from_dict`, `loudness`, `word_segments` do not exist; `save_transcript` takes 4 arguments).

- [ ] **Step 3: Write the migration**

Create `supabase/migrations/20260926180000_clip_selection.sql`:

```sql
-- Piece 2, clip selection.
-- Loudness per 0.5 s (dB) so a retried selection needs no audio.
alter table transcripts add column if not exists loudness jsonb;
-- Partial-failure note shown above the clip grid, e.g. skipped time ranges.
alter table jobs add column if not exists selection_note text;
-- QA flags per clip: low_confidence, weak_pick, no_face_start.
alter table clips add column if not exists qa_flags jsonb not null default '[]'::jsonb;
```

`jobs.status` is already plain `text` (baseline migration line 14), so `selection_failed` needs no schema change.

- [ ] **Step 4: Implement loudness, from_dict, transcript fields, db column**

In `backend/pipeline/audio.py`, after `load()`:

```python
LOUDNESS_STEP_S = 0.5
# Floor for silence, so log10 never sees zero.
_SILENCE_DB = -100.0


def loudness_db(samples: np.ndarray, step_s: float = LOUDNESS_STEP_S) -> list[float]:
    """RMS loudness in dB for each step_s block, rounded to 0.1 dB. Clip
    selection compares a clip's loudness with the episode's median."""
    n = max(1, int(SR * step_s))
    out: list[float] = []
    for i in range(0, len(samples), n):
        block = samples[i:i + n].astype(np.float64)
        rms = float(np.sqrt(np.mean(block * block)))
        out.append(round(20 * np.log10(rms), 1) if rms > 1e-5 else _SILENCE_DB)
    return out
```

In `backend/pipeline/segments.py`, after `build()`:

```python
def from_dict(d: dict) -> Segment:
    """Inverse of Segment.to_dict, for transcripts read back from the
    database (a retried clip selection)."""
    words = [
        SegWord(t=w["t"], raw=w.get("raw", w["t"]), start=float(w["start"]), end=float(w["end"]),
                kind=w.get("kind", ""), prob=float(w.get("prob", 0.0)))
        for w in d.get("words") or []
    ]
    return Segment(
        id=d["id"], start=float(d["start"]), end=float(d["end"]), speaker=d.get("speaker", "A"),
        language=d.get("language", ""), raw=d.get("raw", ""), hinglish=d.get("hinglish", ""),
        words=words, confidence=float(d.get("confidence", 0.0)),
    )
```

In `backend/pipeline/transcript.py`:
- change the dataclass import to `from dataclasses import dataclass, field` (keep other imports as they are);
- add a last field to `Transcript`: `loudness: list[float] = field(default_factory=list)  # dB per 0.5 s`;
- in `transcribe()`, directly after `samples = audio.load(wav)`, add `loudness = audio.loudness_db(samples)`;
- pass `loudness=loudness` in the `Transcript(...)` return;
- replace `to_word_segments` with:

```python
def word_segments(segs: list[segments.Segment]) -> list[TranscriptSegment]:
    """One TranscriptSegment per word, the shape clip prep's caption
    timing reads."""
    return [TranscriptSegment(w.start, w.end, w.t) for s in segs for w in s.words]


def to_word_segments(t: Transcript) -> list[TranscriptSegment]:
    return word_segments(t.segments)
```

In `backend/db.py`, replace `save_transcript`:

```python
def save_transcript(
    job_id: str, language: str, source: str, segments: list[dict[str, Any]],
    loudness: list[float] | None = None,
) -> None:
    """Store a job's transcript. Unlike the job/clip writes above, a failure
    raises: nudging and regenerating clips later depends on this row, so a
    job without it must not be reported as done."""
    client = get_client()
    if client is None:
        return
    row: dict[str, Any] = {"job_id": job_id, "language": language, "source": source, "segments": segments}
    if loudness is not None:
        row["loudness"] = loudness
    client.table("transcripts").upsert(row).execute()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass (249 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/20260926180000_clip_selection.sql backend/pipeline/audio.py backend/pipeline/segments.py backend/pipeline/transcript.py backend/db.py tests/test_audio.py tests/test_segments.py tests/test_transcript.py tests/test_transcript_store.py
git commit -m "Store loudness with transcripts and add clip selection columns

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Utterances and thought units

**Files:**
- Create: `backend/pipeline/utterances.py`
- Test: `tests/test_utterances.py`

**Interfaces:**
- Consumes: `segments.Segment`, `segments.SegWord`.
- Produces:
  - `norm(word: str) -> str` (lowercase, edge punctuation stripped)
  - `Utterance(id: str, first: int, last: int, start: float, end: float, words: list[SegWord], speaker: str = "A")` with properties `text: str`, `confidence: float`, `ends_sentence: bool`. `first`/`last` are inclusive indices into `flat_words(utterances)`.
  - `ThoughtUnit(utterances: list[Utterance])` with properties `start`, `end`
  - `build_utterances(segments: list[Segment]) -> list[Utterance]`
  - `build_thought_units(utterances: list[Utterance]) -> list[ThoughtUnit]`
  - `flat_words(utterances: list[Utterance]) -> list[SegWord]`
  - constants `HANGING_END`, `CONTINUATION_START`, `CLOSING_PHRASES`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_utterances.py`:

```python
from backend.pipeline import segments
from backend.pipeline.utterances import (
    ThoughtUnit, Utterance, build_thought_units, build_utterances, flat_words, norm,
)


def w(t, start, end, prob=0.9):
    return segments.SegWord(t=t, raw=t, start=start, end=end, kind="hinglish", prob=prob)


def seg(words, speaker="A"):
    return segments.Segment(id="s", start=words[0].start, end=words[-1].end, speaker=speaker,
                            language="hi-Latn-EN", raw="", hinglish="", words=words, confidence=0.9)


def U(n, start, end, text):
    toks = text.split()
    step = (end - start) / len(toks)
    words = [w(t, start + i * step, start + (i + 1) * step) for i, t in enumerate(toks)]
    return Utterance(id=f"u{n}", first=0, last=0, start=start, end=end, words=words)


def texts(units):
    return [[u.id for u in unit.utterances] for unit in units]


def test_norm_strips_case_and_edge_punctuation():
    assert norm("Toh,") == "toh" and norm("hai?") == "hai" and norm("\"Yaar!\"") == "yaar"


def test_splits_on_pause_and_sentence_end():
    words = [w("hum", 0.0, 0.3), w("chalein.", 0.3, 0.7), w("phir", 0.75, 1.0),
             w("dekho", 1.0, 1.3), w("yaar", 1.7, 2.0)]
    utts = build_utterances([seg(words)])
    assert [u.text for u in utts] == ["hum chalein.", "phir dekho", "yaar"]
    assert [u.id for u in utts] == ["u1", "u2", "u3"]
    assert [(u.first, u.last) for u in utts] == [(0, 1), (2, 3), (4, 4)]
    assert flat_words(utts)[2].t == "phir"


def test_joins_across_segments_split_mid_sentence():
    utts = build_utterances([seg([w("a", 0.0, 0.3), w("b", 0.3, 0.6)]), seg([w("c", 0.6, 0.9)])])
    assert [u.text for u in utts] == ["a b c"]


def test_speaker_change_splits():
    utts = build_utterances([seg([w("a", 0.0, 0.3)], "A"), seg([w("b", 0.3, 0.6)], "B")])
    assert [(u.text, u.speaker) for u in utts] == [("a", "A"), ("b", "B")]


def test_long_utterance_split_at_longest_gap():
    words = []
    for i in range(50):
        shift = 0.15 if i >= 20 else 0.0
        words.append(w(f"w{i}", i * 0.5 + shift, i * 0.5 + 0.45 + shift))
    utts = build_utterances([seg(words)])
    assert len(utts) == 2
    assert utts[0].words[-1].t == "w19" and utts[1].words[0].t == "w20"
    assert all(u.end - u.start <= 20.0 for u in utts)


def test_confidence_and_sentence_end():
    u = build_utterances([seg([w("kya", 0.0, 0.3, prob=0.8), w("hua?", 0.3, 0.6, prob=0.6)])])[0]
    assert u.confidence == 0.7 and u.ends_sentence is True


def test_short_gaps_join_one_unit():
    assert texts(build_thought_units([U(1, 0, 3, "ek do teen"), U(2, 3.5, 6, "char paanch")])) == [["u1", "u2"]]


def test_long_pause_without_connector_splits():
    assert texts(build_thought_units([U(1, 0, 3, "ek do teen"), U(2, 4, 6, "char paanch")])) == [["u1"], ["u2"]]


def test_question_bridges_a_pause():
    units = build_thought_units([U(1, 0, 3, "kya scene hai?"), U(2, 4.5, 8, "scene ye hai")])
    assert texts(units) == [["u1", "u2"]]


def test_hanging_end_bridges_a_pause():
    assert texts(build_thought_units([U(1, 0, 3, "main gaya lekin"), U(2, 4, 6, "woh nahi aaya")])) == [["u1", "u2"]]


def test_continuation_start_bridges_a_pause():
    assert texts(build_thought_units([U(1, 0, 3, "main nahi gaya"), U(2, 4, 6, "kyunki barish thi")])) == [["u1", "u2"]]


def test_bridge_never_crosses_more_than_two_seconds():
    assert texts(build_thought_units([U(1, 0, 3, "kya hua?"), U(2, 5.5, 8, "kuch nahi")])) == [["u1"], ["u2"]]


def test_bridges_pull_in_at_most_twelve_seconds():
    units = build_thought_units([
        U(1, 0, 2, "sawal kya hai?"),
        U(2, 3, 10, "jawab ye hai lekin"),   # bridged: 8 s extra
        U(3, 11, 16, "aur phir kya"),        # would make 14 s extra
    ])
    assert texts(units) == [["u1", "u2"], ["u3"]]


def test_unit_capped_at_45_seconds():
    utts = [U(i + 1, i * 10.2, i * 10.2 + 10, "baat chal rahi hai") for i in range(5)]
    assert texts(build_thought_units(utts)) == [["u1", "u2", "u3", "u4"], ["u5"]]


def test_closing_phrase_starts_a_new_unit():
    units = build_thought_units([U(1, 0, 3, "ye baat khatam"), U(2, 3.2, 5, "chalo next sawal")])
    assert texts(units) == [["u1"], ["u2"]]
    assert isinstance(units[0], ThoughtUnit) and units[0].start == 0 and units[1].end == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest -q tests/test_utterances.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.utterances'`.

- [ ] **Step 3: Implement**

Create `backend/pipeline/utterances.py`:

```python
"""Utterances and thought units: what the clip ranker picks from (spec
2026-09-26-clip-selection-design.md, section 2).

An utterance is a run of words ended by a pause, a sentence end or a
speaker change. A thought unit groups utterances that belong together (a
question and its answer, a claim and its "kyunki ..."), so a pick widened
to whole units never ends mid-thought.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .segments import Segment, SegWord

PAUSE_S = 0.35
MAX_UTTERANCE_S = 20.0
UNIT_PAUSE_S = 0.8
BRIDGE_MAX_GAP_S = 2.0
BRIDGE_MAX_EXTRA_S = 12.0
MAX_UNIT_S = 45.0

HANGING_END = {"lekin", "kyunki", "aur", "toh", "but", "because", "and", "so"}
CONTINUATION_START = {"kyunki", "lekin", "matlab", "yaani", "isliye", "because", "but", "so"}
CLOSING_PHRASES = ("chalo next", "chalo aage", "moving on", "next question")

_SENTENCE_END = (".", "?", "!")
_EDGE_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)


def norm(word: str) -> str:
    return _EDGE_RE.sub("", word.lower())


@dataclass
class Utterance:
    id: str
    first: int   # index of the first word in flat_words(...)
    last: int    # index of the last word, inclusive
    start: float
    end: float
    words: list[SegWord]
    speaker: str = "A"

    @property
    def text(self) -> str:
        return " ".join(w.t for w in self.words)

    @property
    def confidence(self) -> float:
        return round(sum(w.prob for w in self.words) / len(self.words), 3) if self.words else 0.0

    @property
    def ends_sentence(self) -> bool:
        return bool(self.words) and self.words[-1].t.endswith(_SENTENCE_END)


@dataclass
class ThoughtUnit:
    utterances: list[Utterance]

    @property
    def start(self) -> float:
        return self.utterances[0].start

    @property
    def end(self) -> float:
        return self.utterances[-1].end


def _cap(words: list[SegWord]) -> list[list[SegWord]]:
    """Split a run longer than MAX_UTTERANCE_S at its longest gap."""
    if len(words) < 2 or words[-1].end - words[0].start <= MAX_UTTERANCE_S:
        return [words]
    _, i = max((words[k + 1].start - words[k].end, k) for k in range(len(words) - 1))
    return _cap(words[:i + 1]) + _cap(words[i + 1:])


def build_utterances(segments: list[Segment]) -> list[Utterance]:
    groups: list[tuple[list[SegWord], str]] = []
    cur: list[SegWord] = []
    speaker = "A"
    for seg in segments:
        for word in seg.words:
            if cur:
                prev = cur[-1]
                if (word.start - prev.end >= PAUSE_S
                        or prev.t.endswith(_SENTENCE_END)
                        or seg.speaker != speaker):
                    groups.append((cur, speaker))
                    cur = []
            if not cur:
                speaker = seg.speaker
            cur.append(word)
    if cur:
        groups.append((cur, speaker))

    out: list[Utterance] = []
    index = 0
    for words, spk in groups:
        for part in _cap(words):
            out.append(Utterance(
                id=f"u{len(out) + 1}", first=index, last=index + len(part) - 1,
                start=part[0].start, end=part[-1].end, words=part, speaker=spk,
            ))
            index += len(part)
    return out


def flat_words(utterances: list[Utterance]) -> list[SegWord]:
    return [w for u in utterances for w in u.words]


def _is_closing(u: Utterance) -> bool:
    text = f" {' '.join(norm(w.t) for w in u.words)} "
    return any(f" {p} " in text for p in CLOSING_PHRASES)


def _bridges(prev: Utterance, nxt: Utterance) -> bool:
    return (prev.words[-1].t.endswith("?")
            or norm(prev.words[-1].t) in HANGING_END
            or norm(nxt.words[0].t) in CONTINUATION_START)


def build_thought_units(utterances: list[Utterance]) -> list[ThoughtUnit]:
    units: list[ThoughtUnit] = []
    cur: list[Utterance] = []
    bridged = 0.0
    for u in utterances:
        if cur:
            prev = cur[-1]
            gap = u.start - prev.end
            join = False
            if u.end - cur[0].start <= MAX_UNIT_S and not _is_closing(u):
                if gap < UNIT_PAUSE_S:
                    join = True
                elif (gap <= BRIDGE_MAX_GAP_S and _bridges(prev, u)
                      and bridged + (u.end - prev.end) <= BRIDGE_MAX_EXTRA_S):
                    join = True
                    bridged += u.end - prev.end
            if join:
                cur.append(u)
                continue
            units.append(ThoughtUnit(cur))
        cur, bridged = [u], 0.0
    if cur:
        units.append(ThoughtUnit(cur))
    return units
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python -m pytest -q tests/test_utterances.py`
Expected: PASS (15 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/utterances.py tests/test_utterances.py
git commit -m "Add utterances and thought units for clip selection

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Cut points and filler rules

**Files:**
- Create: `backend/pipeline/snap.py`
- Test: `tests/test_snap.py`

**Interfaces:**
- Consumes: `utterances.norm`, `segments.SegWord`.
- Produces: `Reject(reason: str)` exception with `.reason` in `{"hanging_end", "filler_start"}`; `Cut(first: int, last: int, start: float, end: float)`; `snap(words: list[SegWord], first: int, last: int) -> Cut`; helpers `back_to_pause`, `forward_to_pause`, `strip_leading_filler`, `fix_last_line`, `start_cut`, `end_cut` (all take `words` plus indices).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_snap.py`:

```python
import pytest

from backend.pipeline import segments, snap


def w(t, start, end):
    return segments.SegWord(t=t, raw=t, start=start, end=end, kind="hinglish", prob=0.9)


def line(text, start=0.0, step=0.4, dur=0.35):
    """Words back to back with 50 ms gaps (never a cut pause)."""
    return [w(t, start + i * step, start + i * step + dur) for i, t in enumerate(text.split())]


def test_back_to_pause_moves_to_previous_pause():
    words = [w("a", 0.0, 0.5), w("b", 1.0, 1.4), w("c", 1.45, 1.8), w("d", 1.85, 2.2)]
    assert snap.back_to_pause(words, 3) == 1


def test_back_to_pause_gives_up_after_three_seconds():
    words = line(" ".join(f"x{i}" for i in range(30)))
    assert snap.back_to_pause(words, 20) == 20


def test_back_to_pause_stops_at_transcript_start():
    words = line("a b c d e f")
    assert snap.back_to_pause(words, 5) == 0


def test_forward_to_pause_moves_to_next_pause():
    words = [w("a", 0.0, 0.4), w("b", 0.45, 0.8), w("c", 0.85, 1.2), w("d", 2.0, 2.4)]
    assert snap.forward_to_pause(words, 0) == 2


def test_forward_to_pause_rejects_a_run_on():
    words = line(" ".join(f"x{i}" for i in range(30)))
    with pytest.raises(snap.Reject) as e:
        snap.forward_to_pause(words, 5)
    assert e.value.reason == "hanging_end"


def test_start_cut_leads_by_220ms_without_eating_previous_word():
    words = [w("a", 0.0, 3.0), w("b", 5.0, 5.4)]
    assert snap.start_cut(words, 1) == 4.78
    words = [w("a", 0.0, 4.9), w("b", 5.0, 5.4)]
    assert snap.start_cut(words, 1) == 4.93
    assert snap.start_cut([w("a", 0.1, 0.4)], 0) == 0.0


def test_end_cut_adds_400ms_air_without_reaching_next_word():
    words = [w("a", 9.0, 10.0), w("b", 11.0, 11.4)]
    assert snap.end_cut(words, 0) == 10.4
    words = [w("a", 9.0, 10.0), w("b", 10.2, 10.6)]
    assert snap.end_cut(words, 0) == 10.15
    assert snap.end_cut([w("a", 9.0, 10.0)], 0) == 10.4


def test_strip_leading_filler_words_and_phrases():
    words = line("toh matlab " + "yeh baat sahi hai " * 6)
    assert snap.strip_leading_filler(words, 0, len(words) - 1) == 2
    words = line("you know " + "yeh baat sahi hai " * 6)
    assert snap.strip_leading_filler(words, 0, len(words) - 1) == 2
    words = line("yeh baat sahi hai " * 6)
    assert snap.strip_leading_filler(words, 0, len(words) - 1) == 0


def test_strip_leading_filler_rejects_when_too_short():
    words = line("toh yeh baat sahi hai")
    with pytest.raises(snap.Reject) as e:
        snap.strip_leading_filler(words, 0, len(words) - 1)
    assert e.value.reason == "filler_start"


def test_fix_last_line_trims_hanging_word_to_sentence_end():
    words = line("yeh baat sahi hai " * 6 + "bilkul. aur")
    last = snap.fix_last_line(words, 0, len(words) - 1)
    assert words[last].t == "bilkul."


def test_fix_last_line_strips_trailing_um():
    words = line("yeh baat sahi hai " * 6 + "bilkul. um")
    assert words[snap.fix_last_line(words, 0, len(words) - 1)].t == "bilkul."


def test_fix_last_line_rejects_hanging_end_without_sentence_end():
    words = line("yeh baat sahi hai " * 6 + "lekin")
    with pytest.raises(snap.Reject) as e:
        snap.fix_last_line(words, 0, len(words) - 1)
    assert e.value.reason == "hanging_end"


def test_snap_places_both_cuts():
    before = [w("pehle", 0.0, 0.5)]
    body = line("yeh baat sahi hai " * 6 + "bilkul.", start=2.0)
    after = [w("phir", body[-1].end + 1.0, body[-1].end + 1.3)]
    words = before + body + after
    cut = snap.snap(words, 1, len(words) - 2)
    assert (cut.first, cut.last) == (1, len(words) - 2)
    assert cut.start == 1.78
    assert cut.end == round(body[-1].end + 0.4, 3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest -q tests/test_snap.py`
Expected: FAIL with `ImportError` (no `snap` module).

- [ ] **Step 3: Implement**

Create `backend/pipeline/snap.py`:

```python
"""Cut points for a picked span, placed from word timings (spec section 3).

The ranker never supplies times. Everything here works on word indices
into the whole transcript's flat word list (utterances.flat_words).
"""
from __future__ import annotations

from dataclasses import dataclass

from .segments import SegWord
from .utterances import norm

LEAD_S = 0.22        # silence kept before the first word (spec: 180-250 ms)
AIR_S = 0.40         # silence kept after the last word (spec: 300-500 ms)
CUT_PAUSE_S = 0.30   # a gap this long is a safe place to cut
MAX_EXTEND_S = 3.0   # how far a cut may move to reach such a gap
PREV_GUARD_S = 0.03  # never start closer than this to the previous word
NEXT_GUARD_S = 0.05  # never end closer than this to the next word
MIN_SPAN_S = 8.0     # filler/last-line trims may not leave less than this

FILLER_START_WORDS = {"uh", "um", "hmm", "toh", "matlab", "acha", "achha", "haan", "so", "like", "basically"}
FILLER_START_PHRASES = {("you", "know"), ("i", "mean"), ("okay", "so"), ("ok", "so")}
HANGING_END_WORDS = {"lekin", "kyunki", "aur", "toh", "ki", "but", "because", "and", "so"}
TRAILING_FILLER = {"uh", "um"}
_SENTENCE_END = (".", "?", "!")


class Reject(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Cut:
    first: int
    last: int
    start: float
    end: float


def back_to_pause(words: list[SegWord], first: int) -> int:
    """If the speaker was mid-flow at `first`, move back to the previous
    gap >= CUT_PAUSE_S, but only within MAX_EXTEND_S."""
    i = first
    while i > 0:
        if words[i].start - words[i - 1].end >= CUT_PAUSE_S:
            return i
        if words[first].start - words[i - 1].start > MAX_EXTEND_S:
            return first
        i -= 1
    return 0


def forward_to_pause(words: list[SegWord], last: int) -> int:
    """Move forward to the next gap >= CUT_PAUSE_S within MAX_EXTEND_S;
    a speaker who never pauses there means the clip would end mid-flow."""
    i = last
    while i < len(words) - 1:
        if words[i + 1].start - words[i].end >= CUT_PAUSE_S:
            return i
        if words[i + 1].end - words[last].end > MAX_EXTEND_S:
            raise Reject("hanging_end")
        i += 1
    return i


def _filler_len(words: list[SegWord], i: int, last: int) -> int:
    here = norm(words[i].t)
    if i < last and (here, norm(words[i + 1].t)) in FILLER_START_PHRASES:
        return 2
    return 1 if here in FILLER_START_WORDS else 0


def strip_leading_filler(words: list[SegWord], first: int, last: int) -> int:
    i = first
    while i <= last:
        n = _filler_len(words, i, last)
        if n == 0:
            break
        i += n
    if i == first:
        return first
    if i > last or words[last].end - words[i].start < MIN_SPAN_S:
        raise Reject("filler_start")
    return i


def fix_last_line(words: list[SegWord], first: int, last: int) -> int:
    j = last
    while j > first and norm(words[j].t) in TRAILING_FILLER:
        j -= 1
    if norm(words[j].t) not in HANGING_END_WORDS:
        return j
    k = j - 1
    while k >= first and not words[k].t.endswith(_SENTENCE_END):
        k -= 1
    if k < first or words[k].end - words[first].start < MIN_SPAN_S:
        raise Reject("hanging_end")
    return k


def start_cut(words: list[SegWord], first: int) -> float:
    w = words[first]
    t = w.start - LEAD_S
    if first > 0:
        t = max(t, words[first - 1].end + PREV_GUARD_S)
    return round(min(max(t, 0.0), w.start), 3)


def end_cut(words: list[SegWord], last: int) -> float:
    w = words[last]
    t = w.end + AIR_S
    if last < len(words) - 1:
        t = min(t, words[last + 1].start - NEXT_GUARD_S)
    return round(max(t, w.end), 3)


def snap(words: list[SegWord], first: int, last: int) -> Cut:
    first = back_to_pause(words, first)
    last = forward_to_pause(words, last)
    first = strip_leading_filler(words, first, last)
    last = fix_last_line(words, first, last)
    return Cut(first, last, start_cut(words, first), end_cut(words, last))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python -m pytest -q tests/test_snap.py`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/snap.py tests/test_snap.py
git commit -m "Snap clip cut points to word timings with filler rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Scoring, hard rejects, QA flags, packing

**Files:**
- Create: `backend/pipeline/scoring.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `segments.SegWord`.
- Produces:
  - `Candidate(start, end, words: list[SegWord], standalone, hook, payoff, reason="", energy=0.5, duration_fit=0.0, total=0.0, flags=[])` with properties `duration`, `mean_confidence`
  - `duration_fit(seconds) -> float`, `energy(loudness: list[float], start, end) -> float`
  - `score(c: Candidate, loudness: list[float]) -> Candidate` (returns a copy with `energy`, `duration_fit`, `total` set)
  - `structural_reject(c) -> str | None` (`"too_short" | "too_long" | "late_speech" | "low_confidence"`)
  - `passes_thresholds(c) -> bool`, `near_miss(c) -> bool`, `qa_flags(c) -> list[str]`, `overlap_ratio(a, b) -> float`
  - `pack(cands: list[Candidate]) -> list[Candidate]` (sorted by start; near-miss fills carry `"weak_pick"` in `flags`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scoring.py`:

```python
import pytest

from backend.pipeline import scoring, segments


def words(start, end, prob=0.9, n=20):
    step = (end - start) / n
    return [segments.SegWord(t="baat", raw="baat", start=start + i * step, end=start + (i + 1) * step,
                             kind="hinglish", prob=prob) for i in range(n)]


def cand(start=0.0, end=20.0, standalone=0.9, hook=0.8, payoff=0.7, total=None, prob=0.9):
    c = scoring.Candidate(start=start, end=end, words=words(start, end, prob),
                          standalone=standalone, hook=hook, payoff=payoff)
    if total is not None:
        c.total = total
    return c


def test_duration_fit():
    assert scoring.duration_fit(20) == 1.0
    assert scoring.duration_fit(10) == 0.5
    assert scoring.duration_fit(8) == 0.0
    assert scoring.duration_fit(47.5) == 0.5
    assert scoring.duration_fit(61) == 0.0


def test_energy_compares_clip_with_episode_median():
    loud = [-20.0] * 200
    for i in range(20, 40):
        loud[i] = -14.0
    assert scoring.energy(loud, 10.0, 20.0) == 1.0
    assert scoring.energy(loud, 50.0, 60.0) == 0.5
    assert scoring.energy([], 0.0, 10.0) == 0.5
    assert scoring.energy([-100.0] * 50, 0.0, 10.0) == 0.5


def test_score_uses_spec_weights():
    c = scoring.score(cand(standalone=0.8, hook=0.6, payoff=0.4), [])
    assert c.energy == 0.5 and c.duration_fit == 1.0
    assert c.total == pytest.approx(0.32 + 0.15 + 0.06 + 0.05 + 0.10)


def test_structural_rejects():
    assert scoring.structural_reject(cand(0, 7)) == "too_short"
    assert scoring.structural_reject(cand(0, 61)) == "too_long"
    late = cand(0, 20)
    late.words = words(1.5, 20)
    assert scoring.structural_reject(late) == "late_speech"
    assert scoring.structural_reject(cand(prob=0.4)) == "low_confidence"
    assert scoring.structural_reject(cand()) is None


def test_qa_flags_low_confidence():
    assert scoring.qa_flags(cand(prob=0.65)) == ["low_confidence"]
    mixed = cand()
    for word in mixed.words[:4]:  # 20% of words under 0.4, mean still high
        word.prob = 0.3
    mixed.words[4].prob = 1.0
    assert scoring.qa_flags(mixed) == ["low_confidence"]
    assert scoring.qa_flags(cand(prob=0.9)) == []


def test_thresholds_and_near_miss():
    assert scoring.passes_thresholds(cand(standalone=0.7, hook=0.55))
    assert not scoring.passes_thresholds(cand(standalone=0.69, hook=0.9))
    assert scoring.near_miss(cand(standalone=0.5, hook=0.35))
    assert not scoring.near_miss(cand(standalone=0.49, hook=0.9))


def test_overlap_ratio_uses_shorter_clip():
    assert scoring.overlap_ratio(cand(0, 20), cand(10, 20)) == 1.0
    assert scoring.overlap_ratio(cand(0, 20), cand(15, 35)) == 0.25
    assert scoring.overlap_ratio(cand(0, 20), cand(30, 50)) == 0.0


def test_pack_keeps_best_non_overlapping_up_to_eight():
    cands = [cand(i * 25.0, i * 25.0 + 20, total=0.5 + i / 100) for i in range(10)]
    kept = scoring.pack(cands)
    assert len(kept) == 8
    assert [c.start for c in kept] == sorted(c.start for c in kept)
    assert min(c.total for c in kept) == 0.52


def test_pack_drops_heavy_overlap():
    best, dup, other = cand(0, 20, total=0.9), cand(5, 25, total=0.8), cand(30, 50, total=0.7)
    extra = [cand(60 + i * 25.0, 80 + i * 25.0, total=0.6) for i in range(3)]
    kept = scoring.pack([best, dup, other, *extra])
    assert dup not in kept and best in kept and other in kept


def test_pack_fills_to_five_with_flagged_near_misses():
    strong = [cand(i * 25.0, i * 25.0 + 20, total=0.9) for i in range(3)]
    weak = [cand(100 + i * 25.0, 120 + i * 25.0, standalone=0.6, hook=0.4, total=0.5) for i in range(3)]
    junk = cand(200, 220, standalone=0.3, hook=0.2, total=0.3)
    kept = scoring.pack([*strong, *weak, junk])
    assert len(kept) == 5
    assert sum("weak_pick" in c.flags for c in kept) == 2
    assert all(c.start != 200 for c in kept)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest -q tests/test_scoring.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Create `backend/pipeline/scoring.py`:

```python
"""Scores, hard rejects, QA flags and packing for clip candidates (spec
section 3). Thresholds are first guesses; the Step 6 eval tunes them."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, replace

from .segments import SegWord

W_STANDALONE, W_HOOK, W_PAYOFF, W_ENERGY, W_DURATION = 0.40, 0.25, 0.15, 0.10, 0.10

MIN_STANDALONE = 0.7
MIN_HOOK = 0.55
NEAR_MIN_STANDALONE = 0.5
NEAR_MIN_HOOK = 0.35

MIN_CLIP_S = 8.0
MAX_CLIP_S = 60.0
FIT_LOW_S = 12.0
FIT_HIGH_S = 35.0
MAX_FIRST_WORD_DELAY_S = 1.2
MIN_MEAN_CONFIDENCE = 0.45

LOW_CONF_MEAN = 0.70
LOW_CONF_WORD = 0.4
LOW_CONF_SHARE = 0.15

ENERGY_RANGE_DB = 6.0
SPEECH_FLOOR_DB = -60.0
LOUDNESS_STEP_S = 0.5

MAX_CLIPS = 8
MIN_CLIPS = 5
MAX_OVERLAP = 0.30


@dataclass
class Candidate:
    start: float
    end: float
    words: list[SegWord]
    standalone: float
    hook: float
    payoff: float
    reason: str = ""
    energy: float = 0.5
    duration_fit: float = 0.0
    total: float = 0.0
    flags: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def mean_confidence(self) -> float:
        return sum(w.prob for w in self.words) / len(self.words) if self.words else 0.0


def duration_fit(seconds: float) -> float:
    if seconds < MIN_CLIP_S or seconds > MAX_CLIP_S:
        return 0.0
    if seconds < FIT_LOW_S:
        return (seconds - MIN_CLIP_S) / (FIT_LOW_S - MIN_CLIP_S)
    if seconds > FIT_HIGH_S:
        return (MAX_CLIP_S - seconds) / (MAX_CLIP_S - FIT_HIGH_S)
    return 1.0


def energy(loudness: list[float], start: float, end: float) -> float:
    """Clip mean loudness against the episode's median speech loudness,
    -6 dB -> 0, +6 dB -> 1. Neutral 0.5 when nothing is stored."""
    speech = [v for v in loudness if v > SPEECH_FLOOR_DB]
    if not speech:
        return 0.5
    i0 = int(start / LOUDNESS_STEP_S)
    i1 = max(i0 + 1, math.ceil(end / LOUDNESS_STEP_S))
    clip = [v for v in loudness[i0:i1] if v > SPEECH_FLOOR_DB]
    if not clip:
        return 0.0
    diff = statistics.fmean(clip) - statistics.median(speech)
    return max(0.0, min(1.0, (diff + ENERGY_RANGE_DB) / (2 * ENERGY_RANGE_DB)))


def score(c: Candidate, loudness: list[float]) -> Candidate:
    e = energy(loudness, c.start, c.end)
    fit = duration_fit(c.duration)
    total = (W_STANDALONE * c.standalone + W_HOOK * c.hook + W_PAYOFF * c.payoff
             + W_ENERGY * e + W_DURATION * fit)
    return replace(c, energy=round(e, 3), duration_fit=round(fit, 3), total=round(total, 4))


def structural_reject(c: Candidate) -> str | None:
    """Rejects that the near-miss fill never relaxes. Filler starts and
    hanging ends are rejected earlier, by snap.Reject."""
    if c.duration < MIN_CLIP_S:
        return "too_short"
    if c.duration > MAX_CLIP_S:
        return "too_long"
    if not c.words or c.words[0].start - c.start > MAX_FIRST_WORD_DELAY_S:
        return "late_speech"
    if c.mean_confidence < MIN_MEAN_CONFIDENCE:
        return "low_confidence"
    return None


def passes_thresholds(c: Candidate) -> bool:
    return c.standalone >= MIN_STANDALONE and c.hook >= MIN_HOOK


def near_miss(c: Candidate) -> bool:
    return c.standalone >= NEAR_MIN_STANDALONE and c.hook >= NEAR_MIN_HOOK


def qa_flags(c: Candidate) -> list[str]:
    if not c.words:
        return []
    low_share = sum(1 for w in c.words if w.prob < LOW_CONF_WORD) / len(c.words)
    if c.mean_confidence < LOW_CONF_MEAN or low_share > LOW_CONF_SHARE:
        return ["low_confidence"]
    return []


def overlap_ratio(a: Candidate, b: Candidate) -> float:
    shared = min(a.end, b.end) - max(a.start, b.start)
    if shared <= 0:
        return 0.0
    return shared / min(a.duration, b.duration)


def _fits(c: Candidate, kept: list[Candidate]) -> bool:
    return all(overlap_ratio(c, k) < MAX_OVERLAP for k in kept)


def pack(cands: list[Candidate]) -> list[Candidate]:
    by_total = sorted(cands, key=lambda c: c.total, reverse=True)
    kept: list[Candidate] = []
    for c in by_total:
        if len(kept) >= MAX_CLIPS:
            break
        if passes_thresholds(c) and _fits(c, kept):
            kept.append(c)
    if len(kept) < MIN_CLIPS:
        for c in by_total:
            if len(kept) >= MIN_CLIPS:
                break
            if not passes_thresholds(c) and near_miss(c) and _fits(c, kept):
                kept.append(replace(c, flags=[*c.flags, "weak_pick"]))
    return sorted(kept, key=lambda c: c.start)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python -m pytest -q tests/test_scoring.py`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/scoring.py tests/test_scoring.py
git commit -m "Score, reject, flag and pack clip candidates

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Paced Groq client

**Files:**
- Create: `backend/pipeline/groq_llm.py`, `tests/llm_fakes.py`
- Test: `tests/test_groq_llm.py`

**Interfaces:**
- Produces:
  - constants `GROQ_BASE_URL`, `GROQ_MODEL = "openai/gpt-oss-20b"`, `TOKENS_PER_MINUTE = 8000`, `CHARS_PER_TOKEN = 3.2`
  - exceptions `SelectionFailed(RuntimeError)`, `BadAnswer(Exception)`, `DailyLimit(Exception)` with `.wait: str | None`
  - `ChatResult(content: str, finish_reason: str | None)`
  - `GroqChat(client, *, sleep=time.sleep, clock=time.monotonic, tokens_per_minute=8000)` with `complete(prompt: str, *, max_tokens: int) -> ChatResult`
  - `build_chat() -> GroqChat | None` (None without `GROQ_KEY`)
  - `estimate_tokens(text) -> int`, `parse_duration(text) -> float | None`, `retry_after(exc) -> float | None`, `wait_label(exc) -> str | None`, `is_rate_limit(exc) -> bool`, `is_daily_limit(exc) -> bool`
- `tests/llm_fakes.py` produces `FakeRaw`, `FakeOpenAI`, `RateLimitError`, `FakeChat` (used by Tasks 6, 7, 8).

- [ ] **Step 1: Write the shared fakes**

Create `tests/llm_fakes.py`:

```python
"""Fakes for the Groq/OpenAI client used by clip selection tests."""
from __future__ import annotations

from types import SimpleNamespace

from backend.pipeline.groq_llm import ChatResult


class RateLimitError(Exception):
    """Same class name as openai.RateLimitError, which is what
    groq_llm.is_rate_limit checks."""


class FakeRaw:
    def __init__(self, content: str = "[]", finish: str = "stop", headers: dict | None = None):
        self.content, self.finish, self.headers = content, finish, headers or {}

    def parse(self):
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=self.finish)])


class FakeOpenAI:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            with_raw_response=SimpleNamespace(create=self._create)))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeChat:
    """Stands in for groq_llm.GroqChat. Replies are strings (content with
    finish_reason "stop"), ChatResults, or exceptions to raise."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, max_tokens: int) -> ChatResult:
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, str):
            return ChatResult(reply, "stop")
        return reply
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_groq_llm.py`:

```python
import pytest

from backend.pipeline import groq_llm
from tests.llm_fakes import FakeOpenAI, FakeRaw, RateLimitError


def make(replies):
    sleeps: list[float] = []
    fake = FakeOpenAI(replies)
    chat = groq_llm.GroqChat(fake, sleep=sleeps.append, clock=lambda: 0.0)
    return chat, fake, sleeps


def test_complete_sends_model_prompt_and_low_reasoning():
    chat, fake, _ = make([FakeRaw('[{"a": 1}]')])
    res = chat.complete("hello", max_tokens=100)
    assert (res.content, res.finish_reason) == ('[{"a": 1}]', "stop")
    call = fake.calls[0]
    assert call["model"] == groq_llm.GROQ_MODEL
    assert call["messages"] == [{"role": "user", "content": "hello"}]
    assert call["max_tokens"] == 100
    assert call["extra_body"] == {"reasoning_effort": "low"}


def test_waits_for_reset_when_minute_budget_is_used_up():
    headers = {"x-ratelimit-remaining-tokens": "1000", "x-ratelimit-reset-tokens": "30s"}
    chat, _, sleeps = make([FakeRaw(headers=headers), FakeRaw()])
    chat.complete("x", max_tokens=100)
    chat.complete("y", max_tokens=2000)
    assert sleeps == [30.0]


def test_no_wait_while_budget_remains():
    headers = {"x-ratelimit-remaining-tokens": "7000", "x-ratelimit-reset-tokens": "30s"}
    chat, _, sleeps = make([FakeRaw(headers=headers), FakeRaw()])
    chat.complete("x", max_tokens=100)
    chat.complete("y", max_tokens=2000)
    assert sleeps == []


def test_per_minute_429_waits_and_retries():
    err = RateLimitError("Error code: 429 - Rate limit reached on tokens per minute (TPM). Please try again in 7.5s.")
    chat, _, sleeps = make([err, FakeRaw("ok")])
    assert chat.complete("x", max_tokens=100).content == "ok"
    assert sleeps == [7.5]


def test_daily_429_raises_daily_limit_with_wait():
    err = RateLimitError("Error code: 429 - Rate limit reached for model on tokens per day (TPD): "
                         "Limit 200000, Used 199000. Please try again in 21m0.576s.")
    chat, _, _ = make([err])
    with pytest.raises(groq_llm.DailyLimit) as e:
        chat.complete("x", max_tokens=100)
    assert e.value.wait == "about 21 minutes"


def test_other_errors_propagate():
    chat, _, _ = make([RuntimeError("boom")])
    with pytest.raises(RuntimeError, match="boom"):
        chat.complete("x", max_tokens=100)


def test_parse_duration():
    assert groq_llm.parse_duration("7.66s") == 7.66
    assert groq_llm.parse_duration("1m2.5s") == 62.5
    assert groq_llm.parse_duration("2h") == 7200.0
    assert groq_llm.parse_duration("345ms") == 0.345
    assert groq_llm.parse_duration("soon") is None


def test_wait_label_under_a_minute():
    assert groq_llm.wait_label(RateLimitError("Please try again in 20s.")) == "about a minute"
    assert groq_llm.wait_label(RuntimeError("no hint")) is None


def test_build_chat_without_key(monkeypatch):
    monkeypatch.setenv("GROQ_KEY", "")
    assert groq_llm.build_chat() is None


def test_estimate_tokens():
    assert groq_llm.estimate_tokens("a" * 32) == 10
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest -q tests/test_groq_llm.py`
Expected: FAIL with `ImportError` (no `groq_llm`).

- [ ] **Step 4: Implement**

Create `backend/pipeline/groq_llm.py`:

```python
"""Shared Groq chat client for clip selection. One place paces calls under
the free tier's per-minute token limit and turns rate-limit errors into
messages a person can act on."""
from __future__ import annotations

import math
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-20b"
# Groq free tier for gpt-oss-20b (checked 2026-09-26): 8k tokens/minute,
# 200k tokens/day.
TOKENS_PER_MINUTE = 8000
# Roman Hinglish tokenizes worse than plain English.
CHARS_PER_TOKEN = 3.2
# How often a per-minute 429 is waited out and retried.
RATE_LIMIT_RETRIES = 2
DEFAULT_RETRY_S = 10.0
MAX_RETRY_WAIT_S = 65.0
# Without rate-limit headers, assume the minute window resets after this.
DEFAULT_WINDOW_S = 60.0

_DURATION_RE = re.compile(r"(?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?(?:([\d.]+)ms)?")
_TRY_AGAIN_RE = re.compile(r"try again in\s+([0-9hms.]+)", re.IGNORECASE)


class SelectionFailed(RuntimeError):
    """Clip selection could not run at all. The message is shown to the
    user as is; the job waits in `selection_failed` for a retry."""


class BadAnswer(Exception):
    """The model answered, but not with usable JSON (cut off or unreadable)."""


class DailyLimit(Exception):
    def __init__(self, wait: str | None) -> None:
        super().__init__(f"Groq daily limit reached; try again in {wait or 'a while'}")
        self.wait = wait


@dataclass
class ChatResult:
    content: str
    finish_reason: str | None


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def parse_duration(text: str) -> float | None:
    """"7.66s", "2m59.5s", "1h", "345ms" -> seconds."""
    match = _DURATION_RE.fullmatch(text.strip())
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds, millis = (float(g) if g else 0.0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def retry_after(exc: Exception) -> float | None:
    match = _TRY_AGAIN_RE.search(str(exc))
    return parse_duration(match.group(1).rstrip(".")) if match else None


def wait_label(exc: Exception) -> str | None:
    """"try again in 21m0.576s" -> "about 21 minutes"."""
    seconds = retry_after(exc)
    if seconds is None:
        return None
    if seconds < 60:
        return "about a minute"
    return f"about {round(seconds / 60)} minutes"


def is_rate_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return type(exc).__name__ == "RateLimitError" or "429" in text or "rate limit" in text


def is_daily_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return is_rate_limit(exc) and ("per day" in text or "(tpd)" in text or "(rpd)" in text)


class GroqChat:
    def __init__(
        self, client: Any, *, sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic, tokens_per_minute: int = TOKENS_PER_MINUTE,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._clock = clock
        self._tpm = tokens_per_minute
        self._remaining = tokens_per_minute
        self._reset_at = 0.0

    def complete(self, prompt: str, *, max_tokens: int) -> ChatResult:
        need = estimate_tokens(prompt) + max_tokens
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            self._wait_for(need)
            try:
                raw = self._client.chat.completions.with_raw_response.create(
                    model=GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    # Sent via extra_body because the pinned openai client
                    # predates the field. Without it gpt-oss-20b spends the
                    # whole budget on hidden reasoning.
                    extra_body={"reasoning_effort": "low"},
                )
            except Exception as e:
                if is_daily_limit(e):
                    raise DailyLimit(wait_label(e)) from e
                if not is_rate_limit(e) or attempt == RATE_LIMIT_RETRIES:
                    raise
                self._sleep(min(retry_after(e) or DEFAULT_RETRY_S, MAX_RETRY_WAIT_S))
                self._remaining = self._tpm
                continue
            self._note_usage(raw.headers, need)
            choice = raw.parse().choices[0]
            return ChatResult(choice.message.content or "", getattr(choice, "finish_reason", None))
        raise AssertionError("unreachable")

    def _wait_for(self, need: int) -> None:
        if self._remaining >= need:
            return
        wait = self._reset_at - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._remaining = self._tpm

    def _note_usage(self, headers: Any, need: int) -> None:
        remaining = headers.get("x-ratelimit-remaining-tokens")
        reset = headers.get("x-ratelimit-reset-tokens")
        try:
            self._remaining = int(float(remaining)) if remaining is not None else self._remaining - need
        except ValueError:
            self._remaining -= need
        wait = parse_duration(reset) if reset else None
        self._reset_at = self._clock() + (wait if wait is not None else DEFAULT_WINDOW_S)


def build_chat() -> GroqChat | None:
    key = os.environ.get("GROQ_KEY")
    if not key:
        return None
    from openai import OpenAI

    # max_retries=0: GroqChat handles 429s itself, and retrying a daily
    # limit only burns requests.
    return GroqChat(OpenAI(api_key=key, base_url=GROQ_BASE_URL, max_retries=0))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python -m pytest -q tests/test_groq_llm.py`
Expected: PASS (10 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/pipeline/groq_llm.py tests/llm_fakes.py tests/test_groq_llm.py
git commit -m "Add a paced Groq client for clip selection

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: LLM ranker

**Files:**
- Create: `backend/pipeline/ranker.py`
- Test: `tests/test_ranker.py`

**Interfaces:**
- Consumes: `utterances.ThoughtUnit`/`Utterance`; `groq_llm.CHARS_PER_TOKEN`, `BadAnswer`, `DailyLimit`, `SelectionFailed`, `is_rate_limit`, `ChatResult`; any object with `complete(prompt, *, max_tokens) -> ChatResult`.
- Produces:
  - `Pick(first_unit: int, last_unit: int, standalone: float, hook: float, payoff: float, reason: str = "")` (unit indices, inclusive)
  - `Skipped(start: float, end: float, reason: str)` (`"rate limit" | "daily limit" | "error"`)
  - `RankResult(picks: list[Pick], skipped: list[Skipped])`
  - `windows(units) -> list[list[int]]`, `format_window(units, idxs) -> str`, `parse_picks(content, units, idxs) -> list[Pick]`, `rank(chat, units) -> RankResult`
  - constants `WINDOW_TOKENS = 4500`, `OVERLAP_S = 60.0`, `PICKS_PER_WINDOW = 6`, `MAX_TOKENS = 1500`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ranker.py`:

```python
import json

import pytest

from backend.pipeline import ranker, segments
from backend.pipeline.groq_llm import BadAnswer, ChatResult, DailyLimit, SelectionFailed
from backend.pipeline.utterances import ThoughtUnit, Utterance
from tests.llm_fakes import FakeChat, RateLimitError


def utt(n, start, end, text="baat chal rahi hai"):
    words = [segments.SegWord(t=t, raw=t, start=start, end=end, kind="hinglish", prob=0.9) for t in text.split()]
    return Utterance(id=f"u{n}", first=0, last=0, start=start, end=end, words=words)


def units_of(n, length=20.0, gap=5.0):
    """n one-utterance units, each `length` seconds, `gap` apart."""
    return [ThoughtUnit([utt(i + 1, i * (length + gap), i * (length + gap) + length)]) for i in range(n)]


def pick(s, e, standalone=0.9, hook=0.8, payoff=0.7, **extra):
    return {"s": s, "e": e, "standalone": standalone, "hook": hook, "payoff": payoff,
            "starts_mid": False, "ends_mid": False, "reason": "good", **extra}


def test_format_window_separates_units_with_blank_line():
    units = [ThoughtUnit([utt(1, 0, 2, "kya hua?"), utt(2, 2.5, 4, "kuch nahi")]), ThoughtUnit([utt(3, 6, 8, "chalo")])]
    assert ranker.format_window(units, [0, 1]) == "u1: kya hua?\nu2: kuch nahi\n\nu3: chalo"


def test_windows_split_with_overlap(monkeypatch):
    monkeypatch.setattr(ranker, "WINDOW_TOKENS", 30)   # ~96 chars: about 3 units per window
    units = units_of(10)
    wins = ranker.windows(units)
    assert len(wins) > 1
    assert sorted({i for w in wins for i in w}) == list(range(10))
    for prev, nxt in zip(wins, wins[1:]):
        assert nxt[0] <= prev[-1]                # consecutive windows share units
        assert units[nxt[0]].start >= units[prev[-1]].end - ranker.OVERLAP_S


def test_single_window_for_short_transcripts():
    assert ranker.windows(units_of(3)) == [[0, 1, 2]]


def test_parse_picks_maps_ids_to_units():
    units = units_of(3)
    picks = ranker.parse_picks(json.dumps([pick("u1", "u2")]), units, [0, 1, 2])
    assert [(p.first_unit, p.last_unit, p.standalone, p.hook, p.payoff) for p in picks] == [(0, 1, 0.9, 0.8, 0.7)]


def test_parse_picks_drops_bad_items():
    units = units_of(3)
    items = [
        pick("u9", "u2"),                       # unknown id
        pick("u1", "u1", starts_mid=True),      # mid-thought
        pick("u2", "u2", ends_mid=True),
        {"s": "u1", "e": "u1", "hook": 0.5, "payoff": 0.5},  # missing standalone
        pick("u3", "u1", standalone=1.7),       # reversed, clamped
        "junk",
    ]
    picks = ranker.parse_picks("Sure! " + json.dumps(items), units, [0, 1, 2])
    assert [(p.first_unit, p.last_unit, p.standalone) for p in picks] == [(0, 2, 1.0)]


def test_parse_picks_ignores_ids_outside_the_window():
    units = units_of(3)
    assert ranker.parse_picks(json.dumps([pick("u3", "u3")]), units, [0, 1]) == []


def test_parse_picks_rejects_unreadable_answers():
    units = units_of(1)
    with pytest.raises(BadAnswer):
        ranker.parse_picks("no json here", units, [0])
    with pytest.raises(BadAnswer):
        ranker.parse_picks("[{bad json]", units, [0])


def test_rank_retries_a_bad_answer_once():
    chat = FakeChat(["not json", json.dumps([pick("u1", "u1")])])
    result = ranker.rank(chat, units_of(2))
    assert len(result.picks) == 1 and result.skipped == []
    assert len(chat.prompts) == 2 and "u1: baat chal rahi hai" in chat.prompts[0]


def test_rank_treats_cut_off_answers_as_bad():
    chat = FakeChat([ChatResult("[", "length"), ChatResult("[", "length")])
    with pytest.raises(SelectionFailed, match="failed for this video"):
        ranker.rank(chat, units_of(2))


def test_rank_keeps_other_windows_when_one_fails(monkeypatch):
    monkeypatch.setattr(ranker, "WINDOW_TOKENS", 30)
    units = units_of(10)
    n = len(ranker.windows(units))
    replies = ["bad", "bad"] + [json.dumps([]) for _ in range(n - 1)]
    result = ranker.rank(FakeChat(replies), units)
    assert len(result.skipped) == 1 and result.skipped[0].reason == "error"
    assert result.skipped[0].start == units[0].start


def test_rank_stops_on_daily_limit(monkeypatch):
    monkeypatch.setattr(ranker, "WINDOW_TOKENS", 30)
    units = units_of(10)
    n = len(ranker.windows(units))
    chat = FakeChat([json.dumps([pick("u1", "u1")]), DailyLimit("about 20 minutes")])
    result = ranker.rank(chat, units)
    assert len(chat.prompts) == 2                      # nothing sent after the limit
    assert len(result.skipped) == n - 1
    assert {s.reason for s in result.skipped} == {"daily limit"}


def test_rank_all_windows_daily_limited_raises_clear_message():
    with pytest.raises(SelectionFailed, match="daily limit. Try again in about 20 minutes."):
        ranker.rank(FakeChat([DailyLimit("about 20 minutes")]), units_of(2))


def test_rank_rate_limit_error_is_labelled():
    chat = FakeChat([RateLimitError("429 tokens per minute"), RateLimitError("429 tokens per minute")])
    with pytest.raises(SelectionFailed):
        ranker.rank(chat, units_of(1))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest -q tests/test_ranker.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Create `backend/pipeline/ranker.py`:

```python
"""The LLM ranker (spec section 2). It shows the transcript to the model
in windows of thought units and gets back picks by utterance id. The
model never sees or returns timestamps; snap.py places every cut."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .groq_llm import CHARS_PER_TOKEN, BadAnswer, DailyLimit, SelectionFailed, is_rate_limit
from .utterances import ThoughtUnit

WINDOW_TOKENS = 4500
OVERLAP_S = 60.0
PICKS_PER_WINDOW = 6
MAX_TOKENS = 1500

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

PROMPT = """You pick short-form clips from a podcast transcript. Each line is one utterance: "<id>: <text>". A blank line separates complete thoughts. The text mixes English with Roman-script Hindi/Urdu.

{transcript}

Pick up to {n} clips. Each clip is a range of utterances from "s" to "e" (ids from above) that:
- makes sense to someone who has seen nothing else of this podcast;
- is one complete idea: setup and payoff, question and answer, or claim and explanation;
- lasts about 12-35 seconds;
- never starts on toh, matlab, uh, um, so or like;
- never ends on lekin, kyunki, aur, but or because.

Score each from 0 to 1: "standalone" (makes sense alone), "hook" (how hard its first 3 seconds grab a scrolling viewer), "payoff" (how satisfying its ending is). Set "starts_mid" or "ends_mid" to true if it starts or ends in the middle of a thought.

Reply with ONLY a JSON array, no prose:
[{{"s":"u12","e":"u19","standalone":0.8,"hook":0.7,"payoff":0.6,"starts_mid":false,"ends_mid":false,"reason":"at most 12 words"}}]
If nothing here is worth clipping, reply [].
"""


@dataclass
class Pick:
    first_unit: int
    last_unit: int
    standalone: float
    hook: float
    payoff: float
    reason: str = ""


@dataclass
class Skipped:
    start: float
    end: float
    reason: str  # "rate limit" | "daily limit" | "error"


@dataclass
class RankResult:
    picks: list[Pick]
    skipped: list[Skipped] = field(default_factory=list)


def _unit_chars(unit: ThoughtUnit) -> int:
    return sum(len(u.id) + 2 + len(u.text) + 1 for u in unit.utterances) + 1


def windows(units: list[ThoughtUnit]) -> list[list[int]]:
    """Unit indices per LLM call, broken only between units. Each window
    repeats the previous window's last OVERLAP_S seconds of units, so a
    clip straddling a boundary fits whole in one window."""
    budget = WINDOW_TOKENS * CHARS_PER_TOKEN
    out: list[list[int]] = []
    cur: list[int] = []
    chars = 0
    for i, unit in enumerate(units):
        size = _unit_chars(unit)
        if cur and chars + size > budget:
            out.append(cur)
            tail_from = units[cur[-1]].end - OVERLAP_S
            carry = [j for j in cur if units[j].start >= tail_from]
            if len(carry) == len(cur):
                carry = carry[1:]
            cur, chars = carry, sum(_unit_chars(units[j]) for j in carry)
        cur.append(i)
        chars += size
    if cur:
        out.append(cur)
    return out


def format_window(units: list[ThoughtUnit], idxs: list[int]) -> str:
    return "\n\n".join("\n".join(f"{u.id}: {u.text}" for u in units[i].utterances) for i in idxs)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def parse_picks(content: str, units: list[ThoughtUnit], idxs: list[int]) -> list[Pick]:
    match = _JSON_ARRAY_RE.search(content or "")
    if not match:
        raise BadAnswer("answer had no JSON array")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise BadAnswer(f"unreadable JSON: {e}") from e
    if not isinstance(data, list):
        raise BadAnswer("answer was not a list")

    unit_of = {u.id: i for i in idxs for u in units[i].utterances}
    picks: list[Pick] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        s, e = item.get("s"), item.get("e")
        if not isinstance(s, str) or not isinstance(e, str) or s not in unit_of or e not in unit_of:
            continue
        if item.get("starts_mid") is True or item.get("ends_mid") is True:
            continue
        try:
            standalone, hook, payoff = (_clamp01(float(item[k])) for k in ("standalone", "hook", "payoff"))
        except (KeyError, TypeError, ValueError):
            continue
        first, last = sorted((unit_of[s], unit_of[e]))
        picks.append(Pick(first, last, standalone, hook, payoff, reason=str(item.get("reason", ""))[:120]))
    return picks


def _rank_window(chat, units: list[ThoughtUnit], idxs: list[int]) -> list[Pick]:
    prompt = PROMPT.format(transcript=format_window(units, idxs), n=PICKS_PER_WINDOW)
    last_error: BadAnswer | None = None
    for _ in range(2):  # one retry for a cut-off or unreadable answer
        result = chat.complete(prompt, max_tokens=MAX_TOKENS)
        try:
            if result.finish_reason == "length":
                raise BadAnswer("cut off at the token limit")
            return parse_picks(result.content, units, idxs)
        except BadAnswer as e:
            last_error = e
    assert last_error is not None
    raise last_error


def rank(chat, units: list[ThoughtUnit]) -> RankResult:
    wins = windows(units)
    picks: list[Pick] = []
    skipped: list[Skipped] = []
    daily_wait: str | None = None
    daily = False
    for n, idxs in enumerate(wins):
        start, end = units[idxs[0]].start, units[idxs[-1]].end
        try:
            picks.extend(_rank_window(chat, units, idxs))
        except DailyLimit as e:
            # Spend nothing more today: skip this window and every later one.
            daily, daily_wait = True, e.wait
            skipped.extend(Skipped(units[w[0]].start, units[w[-1]].end, "daily limit") for w in wins[n:])
            break
        except Exception as e:  # noqa: BLE001
            print(f"[ranker] window {start:.0f}-{end:.0f}s skipped: {e}")
            skipped.append(Skipped(start, end, "rate limit" if is_rate_limit(e) else "error"))

    if wins and len(skipped) == len(wins):
        if daily:
            raise SelectionFailed(
                "Clip selection hit Groq's daily limit."
                + (f" Try again in {daily_wait}." if daily_wait else " Try again later.")
            )
        raise SelectionFailed("Clip selection failed for this video. Try again.")
    return RankResult(picks, skipped)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python -m pytest -q tests/test_ranker.py`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/ranker.py tests/test_ranker.py
git commit -m "Add the windowed LLM ranker that picks utterance ids

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Titles, emphasis and tags

**Files:**
- Create: `backend/pipeline/titles.py`
- Test: `tests/test_titles.py`

**Interfaces:**
- Consumes: `groq_llm.BadAnswer`, `utterances.norm`, a chat with `complete()` (or `None`).
- Produces: `TAGS: list[str]`; `Titles(hook_title: str | None, emphasis: list[str], tag: str)`; `pick_tag(text, idx) -> str`; `code_emphasis(text) -> list[str]`; `fallback(text, idx) -> Titles`; `write_titles(chat, texts: list[str]) -> tuple[list[Titles], bool]` (bool = the LLM call worked).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_titles.py`:

```python
import json

from backend.pipeline import titles
from backend.pipeline.groq_llm import ChatResult
from tests.llm_fakes import FakeChat

TEXTS = [
    "Sach yeh hai ke startup mein paisa nahi, patience chahiye.",
    "Honestly marketing budget pehle din se rakho warna product koi nahi dekhega.",
]


def test_write_titles_parses_and_validates():
    answer = json.dumps([
        {"id": "c1", "hook_title": "Startup ka asli secret jo koi nahi batata aapko yaar",
         "emphasis": ["patience", "paisa", "rocket"], "tag": "Key insight"},
        {"id": "c2", "hook_title": "Marketing pehle", "emphasis": ["marketing"], "tag": "Not a tag"},
    ])
    out, ok = titles.write_titles(FakeChat([answer]), TEXTS)
    assert ok is True
    assert out[0].hook_title == "Startup ka asli secret jo koi nahi batata"  # 8 words
    assert out[0].emphasis == ["patience", "paisa"]                          # "rocket" not in text
    assert out[0].tag == "Key insight"
    assert out[1].tag in titles.TAGS                                           # invalid tag replaced


def test_missing_clip_gets_fallback():
    answer = json.dumps([{"id": "c1", "hook_title": "Ek", "emphasis": ["paisa"], "tag": "Key insight"}])
    out, ok = titles.write_titles(FakeChat([answer]), TEXTS)
    assert ok is True
    assert out[1].hook_title is None and out[1].emphasis


def test_failure_falls_back_for_every_clip():
    for reply in [RuntimeError("boom"), "no json", ChatResult("[", "length")]:
        out, ok = titles.write_titles(FakeChat([reply]), TEXTS)
        assert ok is False
        assert [t.hook_title for t in out] == [None, None]
        assert all(t.emphasis and t.tag in titles.TAGS for t in out)


def test_no_chat_or_no_clips():
    out, ok = titles.write_titles(None, TEXTS)
    assert ok is False and len(out) == 2
    assert titles.write_titles(FakeChat([]), []) == ([], True)


def test_code_emphasis_picks_longest_non_stopwords():
    # longest first; "din"/"se" are too short and "warna" is a stopword
    assert titles.code_emphasis("Honestly marketing budget pehle din se rakho warna") == ["marketing", "honestly", "budget"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest -q tests/test_titles.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Create `backend/pipeline/titles.py`:

```python
"""Hook titles, emphasis words and tags for the final clips: one small
LLM call over the winners only (spec section 3). Failure is harmless:
clips keep code-picked emphasis and a keyword tag, and no hook title."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .groq_llm import BadAnswer
from .utterances import norm

TAGS = ["Strong opinion", "Key insight", "Funny moment", "Actionable advice", "Contrarian take", "Wild claim"]
HOOK_TITLE_MAX_WORDS = 8
MAX_EMPHASIS_WORDS = 5
CODE_EMPHASIS_WORDS = 3
MAX_TOKENS = 1200
_MIN_EMPHASIS_LEN = 4

STOPWORDS = {
    "that", "this", "with", "have", "from", "they", "there", "their", "what", "when", "where",
    "which", "would", "could", "should", "about", "just", "like", "really", "because", "then",
    "than", "them", "were", "been", "your", "into", "some", "very", "also",
    "hai", "hain", "tha", "thi", "the", "kya", "kyun", "kyunki", "lekin", "matlab", "toh",
    "yeh", "woh", "voh", "aur", "bhi", "nahi", "nahin", "mein", "main", "hum", "tum", "aap",
    "kuch", "sab", "abhi", "phir", "karo", "kar", "raha", "rahe", "rahi", "wala", "wali",
    "yaar", "bhai", "haan", "acha", "achha", "isliye", "yaani", "warna",
}

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

PROMPT = """You write short-form video metadata for podcast clips. The text mixes English with Roman-script Hindi/Urdu.

{clips}

For each clip id above return:
- "hook_title": at most 8 words, punchy, in the same language mix the speakers use;
- "emphasis": up to 5 single words copied exactly from that clip's text that carry its meaning;
- "tag": one of {tags}.

Reply with ONLY a JSON array, no prose:
[{{"id":"c1","hook_title":"...","emphasis":["..."],"tag":"Key insight"}}]
"""


@dataclass
class Titles:
    hook_title: str | None
    emphasis: list[str]
    tag: str


def pick_tag(text: str, idx: int) -> str:
    lower = text.lower()
    if "?" in text and any(w in lower for w in ["what", "how", "kya", "kaise"]):
        return "Key insight"
    if any(w in lower for w in ["lol", "funny", "haha", "hilarious"]):
        return "Funny moment"
    if any(w in lower for w in ["should", "you need to", "try this", "karo", "chahiye"]):
        return "Actionable advice"
    if any(w in lower for w in ["everyone says", "actually", "myth", "wrong"]):
        return "Contrarian take"
    if any(w in lower for w in ["insane", "crazy", "wild", "hairan"]):
        return "Wild claim"
    return TAGS[idx % len(TAGS)]


def code_emphasis(text: str) -> list[str]:
    seen: set[str] = set()
    words: list[str] = []
    for token in text.split():
        n = norm(token)
        if len(n) < _MIN_EMPHASIS_LEN or n in STOPWORDS or n in seen:
            continue
        seen.add(n)
        words.append(n)
    return sorted(words, key=len, reverse=True)[:CODE_EMPHASIS_WORDS]


def fallback(text: str, idx: int) -> Titles:
    return Titles(None, code_emphasis(text), pick_tag(text, idx))


def _parse(content: str, texts: list[str]) -> list[Titles]:
    match = _JSON_ARRAY_RE.search(content or "")
    if not match:
        raise BadAnswer("answer had no JSON array")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise BadAnswer(f"unreadable JSON: {e}") from e
    if not isinstance(data, list):
        raise BadAnswer("answer was not a list")
    by_id = {item["id"]: item for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)}

    out: list[Titles] = []
    for i, text in enumerate(texts):
        item = by_id.get(f"c{i + 1}")
        if item is None:
            out.append(fallback(text, i))
            continue
        title = item.get("hook_title")
        hook = " ".join(title.split()[:HOOK_TITLE_MAX_WORDS]) if isinstance(title, str) and title.strip() else None
        present = {norm(t) for t in text.split()}
        raw = item.get("emphasis") if isinstance(item.get("emphasis"), list) else []
        emphasis: list[str] = []
        for word in raw:
            n = norm(word) if isinstance(word, str) else ""
            if n and n in present and n not in emphasis:
                emphasis.append(n)
        tag = item.get("tag")
        out.append(Titles(
            hook_title=hook,
            emphasis=emphasis[:MAX_EMPHASIS_WORDS] or code_emphasis(text),
            tag=tag if isinstance(tag, str) and tag in TAGS else pick_tag(text, i),
        ))
    return out


def write_titles(chat, texts: list[str]) -> tuple[list[Titles], bool]:
    if not texts:
        return [], True
    if chat is None:
        return [fallback(t, i) for i, t in enumerate(texts)], False
    clips = "\n\n".join(f"c{i + 1}: {t}" for i, t in enumerate(texts))
    try:
        result = chat.complete(PROMPT.format(clips=clips, tags=", ".join(TAGS)), max_tokens=MAX_TOKENS)
        if result.finish_reason == "length":
            raise BadAnswer("cut off at the token limit")
        return _parse(result.content, texts), True
    except Exception as e:  # noqa: BLE001
        print(f"[titles] skipped: {e}")
        return [fallback(t, i) for i, t in enumerate(texts)], False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python -m pytest -q tests/test_titles.py`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/titles.py tests/test_titles.py
git commit -m "Write hook titles, emphasis and tags for the final clips

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Selection orchestrator; retire highlight.py; face check in clipprep

**Files:**
- Create: `backend/pipeline/selection.py`
- Delete: `backend/pipeline/highlight.py`, `tests/test_highlight.py`
- Modify: `backend/pipeline/clipprep.py`, `tests/test_clipprep.py`, `tests/test_transcript.py`
- Test: `tests/test_selection.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7; `ingest.duration_label`.
- Produces:
  - `selection.Clip(start, end, text, score, tag, hook_title=None, emphasis=[], flags=[], standalone=0.0, hook=0.0, payoff=0.0, energy=0.5, duration_fit=0.0)` — `score` is the 0–10 virality score
  - `selection.Selection(clips: list[Clip], note: str | None = None)`
  - `selection.select(segments: list[Segment], loudness: list[float], *, chat=None) -> Selection` — raises `selection.SelectionFailed`
  - `selection.skipped_note(skipped: list[ranker.Skipped]) -> str | None`
  - `clipprep.PreparedClip.face_at_start: bool | None` (None = unknown), `clipprep.FACE_START_S = 1.0`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_selection.py`:

```python
import json

import pytest

from backend.pipeline import ranker, segments, selection


def thought(start, n=50, text="baat"):
    """One 20 s sentence: n words, 0.4 s apart, ending in a full stop."""
    words = [segments.SegWord(t=text, raw=text, start=start + i * 0.4, end=start + i * 0.4 + 0.35,
                              kind="hinglish", prob=0.9) for i in range(n)]
    words[-1].t = f"{text}."
    return words


def transcript(n_thoughts=3):
    words = [w for i in range(n_thoughts) for w in thought(i * 25.0)]
    return [segments.Segment(id="seg_0001", start=words[0].start, end=words[-1].end, speaker="A",
                             language="hi-Latn-EN", raw="", hinglish="", words=words, confidence=0.9)]


def pick(s, e, standalone=1.0, hook=1.0, payoff=1.0, **extra):
    return {"s": s, "e": e, "standalone": standalone, "hook": hook, "payoff": payoff,
            "starts_mid": False, "ends_mid": False, "reason": "r", **extra}


def test_select_end_to_end():
    from tests.llm_fakes import FakeChat

    ranked = json.dumps([pick("u1", "u1"), pick("u2", "u2", hook=0.6), pick("u3", "u3", starts_mid=True)])
    named = json.dumps([
        {"id": "c1", "hook_title": "Pehla clip", "emphasis": ["baat"], "tag": "Key insight"},
        {"id": "c2", "hook_title": "Doosra clip", "emphasis": [], "tag": "Wild claim"},
    ])
    chat = FakeChat([ranked, named])
    result = selection.select(transcript(), [], chat=chat)

    assert [c.hook_title for c in result.clips] == ["Pehla clip", "Doosra clip"]
    first = result.clips[0]
    assert first.start == 0.0
    assert first.end == pytest.approx(19.95 + 0.4)
    assert first.score == pytest.approx(9.5)
    assert first.emphasis == ["baat"] and first.tag == "Key insight"
    assert first.flags == []
    assert result.clips[1].start == pytest.approx(25.0 - 0.22)
    assert result.note is None
    assert "u1: baat" in chat.prompts[0]


def test_select_notes_failed_titles():
    from tests.llm_fakes import FakeChat

    chat = FakeChat([json.dumps([pick("u1", "u1")]), RuntimeError("boom")])
    result = selection.select(transcript(), [], chat=chat)
    assert result.clips[0].hook_title is None
    assert result.note == "Hook titles could not be written this time."


def test_select_flags_a_weak_pick_when_short_of_five():
    from tests.llm_fakes import FakeChat

    chat = FakeChat([json.dumps([pick("u1", "u1", standalone=0.6, hook=0.4)]), "[]"])
    result = selection.select(transcript(), [], chat=chat)
    assert result.clips[0].flags == ["weak_pick"]


def test_select_without_key_fails_visibly(monkeypatch):
    monkeypatch.setenv("GROQ_KEY", "")
    with pytest.raises(selection.SelectionFailed, match="GROQ_KEY"):
        selection.select(transcript(), [])


def test_select_empty_transcript():
    from tests.llm_fakes import FakeChat

    assert selection.select([], [], chat=FakeChat([])).clips == []


def test_skipped_note_merges_ranges():
    note = selection.skipped_note([
        ranker.Skipped(750.0, 900.0, "rate limit"),
        ranker.Skipped(880.0, 1120.0, "rate limit"),
        ranker.Skipped(1500.0, 1860.0, "error"),
    ])
    assert note == "Skipped 12:30–18:40, 25:00–31:00 (error, rate limit). Some moments may be missing."
    assert selection.skipped_note([]) is None
```

In `tests/test_clipprep.py`:
- change `from backend.pipeline.highlight import Clip` to `from backend.pipeline.selection import Clip`;
- append:

```python
def test_prepare_clip_reports_a_face_at_the_start(tmp_path, monkeypatch):
    times = [round(i / 5, 3) for i in range(80)]
    frames = [[Detection(0.5, 0.4, 0.2, 0.3, 0.1)] for _ in times]
    thumbs = [np.zeros((18, 32), dtype=np.float32) for _ in times]
    _patch_media(monkeypatch, lambda path, model, sample_fps=5.0: (frames, times, thumbs))
    assert _prepare(tmp_path).face_at_start is True


def test_prepare_clip_reports_no_face_at_the_start(tmp_path, monkeypatch):
    # segment time 1.0 is the clip start; no face until segment time 3.0
    times = [round(i / 5, 3) for i in range(80)]
    frames = [[] if t < 3.0 else [Detection(0.5, 0.4, 0.2, 0.3, 0.1)] for t in times]
    thumbs = [np.zeros((18, 32), dtype=np.float32) for _ in times]
    _patch_media(monkeypatch, lambda path, model, sample_fps=5.0: (frames, times, thumbs))
    assert _prepare(tmp_path).face_at_start is False


def test_prepare_clip_face_unknown_when_detection_fails(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no mediapipe")

    _patch_media(monkeypatch, boom)
    assert _prepare(tmp_path).face_at_start is None
```

In `tests/test_transcript.py`, delete `test_adapter_output_feeds_the_highlight_scorer` (the highlight module goes away; `test_to_word_segments_uses_fixed_text` keeps covering the adapter).

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest -q tests/test_selection.py tests/test_clipprep.py`
Expected: FAIL with `ImportError` (no `selection` module).

- [ ] **Step 3: Implement selection.py**

Create `backend/pipeline/selection.py`:

```python
"""Clip selection (roadmap Step 3; spec 2026-09-26-clip-selection-design.md).

utterances -> thought units -> LLM ranker (ids only) -> cut points snapped
in code -> hard rejects -> score -> pack -> titles call.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import groq_llm, ranker, scoring, snap, titles
from .groq_llm import SelectionFailed
from .ingest import duration_label
from .segments import Segment
from .utterances import build_thought_units, build_utterances, flat_words

__all__ = ["Clip", "Selection", "SelectionFailed", "select", "skipped_note"]

TITLES_FAILED_NOTE = "Hook titles could not be written this time."


@dataclass
class Clip:
    start: float
    end: float
    text: str
    score: float  # virality score, 0-10
    tag: str
    hook_title: str | None = None
    emphasis: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    standalone: float = 0.0
    hook: float = 0.0
    payoff: float = 0.0
    energy: float = 0.5
    duration_fit: float = 0.0


@dataclass
class Selection:
    clips: list[Clip]
    note: str | None = None


def skipped_note(skipped: list[ranker.Skipped]) -> str | None:
    if not skipped:
        return None
    spans = sorted((s.start, s.end) for s in skipped)
    merged = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    ranges = ", ".join(f"{duration_label(a)}–{duration_label(b)}" for a, b in merged)
    reasons = ", ".join(sorted({s.reason for s in skipped}))
    return f"Skipped {ranges} ({reasons}). Some moments may be missing."


def select(segments: list[Segment], loudness: list[float], *, chat=None) -> Selection:
    if chat is None:
        chat = groq_llm.build_chat()
    if chat is None:
        raise SelectionFailed("Clip selection needs GROQ_KEY.")

    utterances = build_utterances(segments)
    if not utterances:
        return Selection([])
    units = build_thought_units(utterances)
    ranked = ranker.rank(chat, units)
    words = flat_words(utterances)

    candidates: list[scoring.Candidate] = []
    for p in ranked.picks:
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
        candidates.append(scoring.score(c, loudness))

    kept = scoring.pack(candidates)
    texts = [" ".join(w.t for w in c.words) for c in kept]
    meta, titles_ok = titles.write_titles(chat, texts)
    clips = [
        Clip(
            start=c.start, end=c.end, text=text, score=round(c.total * 10, 1), tag=m.tag,
            hook_title=m.hook_title, emphasis=m.emphasis, flags=[*scoring.qa_flags(c), *c.flags],
            standalone=c.standalone, hook=c.hook, payoff=c.payoff,
            energy=c.energy, duration_fit=c.duration_fit,
        )
        for c, text, m in zip(kept, texts, meta)
    ]

    notes = [skipped_note(ranked.skipped)]
    if kept and not titles_ok:
        notes.append(TITLES_FAILED_NOTE)
    return Selection(clips, " ".join(n for n in notes if n) or None)
```

- [ ] **Step 4: Update clipprep.py**

In `backend/pipeline/clipprep.py`:
- replace `from .highlight import Clip` with `from .selection import Clip`;
- change the module docstring's first line to `"""Everything that happens to one clip after it's picked: cut its`;
- after `SEGMENT_PAD_S = 1.0` add:

```python
# A face must show within this long of the clip start, or the clip gets a
# "No face at start" QA flag.
FACE_START_S = 1.0
```

- add `face_at_start: bool | None = None` as the last field of `PreparedClip`;
- in `prepare_clip`, before `on_step("framing")` add `face_at_start: bool | None = None`, and inside the `try`, directly after `kept = [...]`, add:

```python
        opening = [f for t, f, _ in kept if t <= FACE_START_S]
        face_at_start = any(len(f) > 0 for f in opening) if opening else None
```

- return `PreparedClip(spec=spec, storage_key=storage_key, face_at_start=face_at_start)`.

- [ ] **Step 5: Delete the old scorer**

```bash
git rm backend/pipeline/highlight.py tests/test_highlight.py
```

`backend/main.py` still imports `highlight` until Task 9, so the full suite cannot import `main` yet. That is expected: run only the pipeline tests in Step 6, and Task 9 fixes `main.py` next.

- [ ] **Step 6: Run the pipeline tests**

Run: `./.venv/Scripts/python -m pytest -q tests/test_selection.py tests/test_clipprep.py tests/test_transcript.py tests/test_utterances.py tests/test_snap.py tests/test_scoring.py tests/test_groq_llm.py tests/test_ranker.py tests/test_titles.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/pipeline/selection.py backend/pipeline/clipprep.py tests/test_selection.py tests/test_clipprep.py tests/test_transcript.py
git commit -m "Select clips from utterances and retire the old highlight scorer

Clip prep now records whether a face shows in the first second.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Backend wiring: pipeline, selection_failed, retry endpoint, QA flags

**Files:**
- Modify: `backend/main.py`, `backend/projects.py`
- Test: `tests/test_pipeline_run.py`, `tests/test_status.py`, `tests/test_projects.py`

**Interfaces:**
- Consumes: `selection.select`, `selection.Selection`, `selection.SelectionFailed`, `selection.Clip.flags`; `clipprep.PreparedClip.face_at_start`; `segments.from_dict`; `transcript.word_segments`; `db.save_transcript(..., loudness)`; `db.get_transcript`.
- Produces:
  - `Job.selection_note: str | None`; job status value `"selection_failed"`
  - status JSON gains `selectionNote`; clip JSON gains `qaFlags: list[str]`
  - `POST /api/jobs/{job_id}/select` → `{"job_id": ...}`; 409 when not in `selection_failed` or no stored transcript
  - helpers `main._qa_flags(flags, face_at_start)`, `main._select_and_prepare(job, meta, segs, loudness)`, `main._run_selection_retry(job, stored)`, `main._job_from_row(row)`, `main._video_meta_from_row(row)`, `main._start_thread(target, *args)`

- [ ] **Step 1: Write the failing tests**

In `tests/test_pipeline_run.py`:
- add `from backend.pipeline import selection` to the imports;
- in both existing tests, change `def fake_save_transcript(job_id, language, source, segs):` to `def fake_save_transcript(job_id, language, source, segs, loudness=None):`, rename `fake_detect_highlights(word_segments)` to `fake_select(segs, loudness)` appending `"select"` and returning `selection.Selection([])`, and replace `monkeypatch.setattr(main.highlight, "detect_highlights", fake_detect_highlights)` with `monkeypatch.setattr(main.selection, "select", fake_select)`;
- in the first test change the order assertion to `assert calls == ["save_transcript", "select"]` and its comment to `# save_transcript ran with the segment dicts, before select.`; rename the tests to `test_happy_path_persists_language_and_saves_before_selection` and `test_save_transcript_failure_fails_job_and_skips_selection`;
- update the module docstring's "highlight detection" to "clip selection";
- append:

```python
def _patch_common(monkeypatch, rows):
    monkeypatch.setattr(main.ingest, "ingest", lambda url, cache_dir, on_progress=None: _meta())
    monkeypatch.setattr(
        main.transcript, "transcribe",
        lambda audio_path, requested, on_progress=None, **kw: _transcript(),
    )
    monkeypatch.setattr(main.db, "save_transcript", lambda *a, **k: None)
    monkeypatch.setattr(main.db, "upsert_job", rows.append)
    monkeypatch.setattr(main.db, "insert_clips", lambda r: None)


def test_selection_failure_parks_the_job_for_retry(monkeypatch):
    rows = []
    _patch_common(monkeypatch, rows)

    def fail(segs, loudness):
        raise selection.SelectionFailed("Clip selection hit Groq's daily limit. Try again in about 5 minutes.")

    monkeypatch.setattr(main.selection, "select", fail)
    job = _job()
    main._run_pipeline(job)
    assert job.status == "selection_failed"
    assert job.error.startswith("Clip selection hit Groq's daily limit")
    assert rows[-1]["status"] == "selection_failed"


def test_selection_note_is_persisted(monkeypatch):
    rows = []
    _patch_common(monkeypatch, rows)
    monkeypatch.setattr(main.selection, "select", lambda segs, loudness: selection.Selection([], "Skipped 1:00–2:00 (error)."))
    job = _job()
    main._run_pipeline(job)
    assert job.status == "done" and job.selection_note == "Skipped 1:00–2:00 (error)."
    assert rows[-1]["selection_note"] == "Skipped 1:00–2:00 (error)."


def test_selection_retry_runs_from_the_stored_transcript(monkeypatch):
    got = {}
    monkeypatch.setattr(main.ingest, "ingest", lambda url, cache_dir, on_progress=None: _meta())
    monkeypatch.setattr(main.db, "upsert_job", lambda row: None)

    def fake_select(segs, loudness):
        got["segs"], got["loudness"] = segs, loudness
        return selection.Selection([], "note")

    monkeypatch.setattr(main.selection, "select", fake_select)
    job = main.Job(id="job9", url="https://youtu.be/x", status="analyzing")
    main._run_selection_retry(job, {"segments": [_segment().to_dict()], "loudness": [-20.0]})
    assert job.status == "done" and job.selection_note == "note"
    assert got["segs"] == [_segment()] and got["loudness"] == [-20.0]


def test_qa_flags_add_no_face_start_only_when_known():
    assert main._qa_flags(["weak_pick"], False) == ["weak_pick", "no_face_start"]
    assert main._qa_flags([], True) == []
    assert main._qa_flags([], None) == []
```

Append to `tests/test_status.py`:

```python
def _failed_row(**extra):
    return {**_job_row(status="selection_failed"),
            "error": "Clip selection hit Groq's daily limit. Try again later.", **extra}


def test_status_keeps_selection_failed_and_note(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _failed_row(selection_note="n"))
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [])
    body = client.get("/api/status/feed00000001").json()
    assert body["status"] == "selection_failed"
    assert body["error"].startswith("Clip selection hit")
    assert body["selectionNote"] == "n"


def test_status_clip_has_qa_flags(monkeypatch):
    row = {**_clip_row(), "qa_flags": ["low_confidence"]}
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _job_row())
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [row, _clip_row()])
    clips = client.get("/api/status/feed00000001").json()["clips"]
    assert clips[0]["qaFlags"] == ["low_confidence"] and clips[1]["qaFlags"] == []


def _start_inline(monkeypatch):
    ran = []
    monkeypatch.setattr(main, "_start_thread", lambda target, *args: ran.append((target, args)))
    return ran


def test_retry_selection_restarts_selection(monkeypatch):
    main.JOBS.pop("feed00000001", None)
    ran = _start_inline(monkeypatch)
    stored = {"segments": [{"id": "seg_0001"}], "loudness": [-20.0]}
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _failed_row())
    monkeypatch.setattr(main.db, "get_transcript", lambda job_id: stored)
    monkeypatch.setattr(main.db, "upsert_job", lambda row: None)
    r = client.post("/api/jobs/feed00000001/select")
    assert r.status_code == 200 and r.json() == {"job_id": "feed00000001"}
    job = main.JOBS.pop("feed00000001")
    assert job.status == "analyzing" and job.error is None
    assert ran == [(main._run_selection_retry, (job, stored))]


def test_retry_selection_only_after_it_failed(monkeypatch):
    main.JOBS.pop("feed00000001", None)
    _start_inline(monkeypatch)
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _job_row(status="done"))
    assert client.post("/api/jobs/feed00000001/select").status_code == 409


def test_retry_selection_needs_a_stored_transcript(monkeypatch):
    main.JOBS.pop("feed00000001", None)
    _start_inline(monkeypatch)
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _failed_row())
    monkeypatch.setattr(main.db, "get_transcript", lambda job_id: None)
    assert client.post("/api/jobs/feed00000001/select").status_code == 409


def test_retry_selection_other_team_is_not_found(monkeypatch):
    main.JOBS.pop("feed00000001", None)
    _start_inline(monkeypatch)
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _failed_row(team_id="someone-else"))
    assert client.post("/api/jobs/feed00000001/select").status_code == 404
```

Append to `tests/test_projects.py` (keep its existing imports; add `from backend import projects` if it is not already imported):

```python
def test_from_row_keeps_selection_failed():
    row = {"id": "j1", "url": "https://youtu.be/x", "status": "selection_failed", "error": "limit"}
    out = projects.from_row(row, 0)
    assert out["status"] == "selection_failed" and out["error"] == "limit"


def test_selection_failed_is_grouped_with_errors():
    assert projects._status_group("selection_failed") == "error"
    assert projects._status_group("analyzing") == "processing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest -q tests/test_pipeline_run.py tests/test_status.py tests/test_projects.py`
Expected: FAIL (`main` still imports `highlight`, which was deleted in Task 8).

- [ ] **Step 3: Implement projects.py**

In `backend/projects.py`:

```python
def _status_group(status: str) -> str:
    if status in PROCESSING_STATUSES:
        return "processing"
    # Selection failed but the transcript is kept; it lists with the
    # failures until the user retries.
    if status == "selection_failed":
        return "error"
    return status
```

and in `from_row` change `if status not in ("done", "error"):` to `if status not in ("done", "error", "selection_failed"):`.

- [ ] **Step 4: Implement main.py**

In `backend/main.py`:

1. Imports: replace `from .pipeline import clipprep, cut, highlight, ingest, transcript` with

```python
from .pipeline import clipprep, cut, ingest, selection, transcript
from .pipeline.segments import Segment
from .pipeline.segments import from_dict as segment_from_dict
```

2. `Job`: change the status comment to `# queued|transcribing|analyzing|preparing|done|error|selection_failed` and add `selection_note: str | None = None` directly above `_last_persist`.

3. `_persist_job`: add `"selection_note": job.selection_note,` to `row` after `"transcript_source"`.

4. Add after `_persist_job`:

```python
def _qa_flags(flags: list[str], face_at_start: bool | None) -> list[str]:
    out = list(flags)
    if face_at_start is False and "no_face_start" not in out:
        out.append("no_face_start")
    return out


def _video_meta_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row.get("video_title"):
        return None
    video_id = row.get("video_id") or projects.youtube_id(row.get("url"))
    return {
        "title": row.get("video_title"),
        "channel": row.get("video_channel"),
        "duration": row.get("video_duration"),
        "durationLabel": ingest.duration_label(float(row.get("video_duration") or 0)),
        "videoId": video_id,
        "thumbnailUrl": projects.thumbnail_url(video_id, row.get("thumbnail_url")),
    }


def _job_from_row(row: dict[str, Any]) -> Job:
    return Job(
        id=row["id"], url=row["url"], status=row["status"], error=row.get("error"),
        video_meta=_video_meta_from_row(row), transcript_source=row.get("transcript_source"),
        team_id=row.get("team_id"), created_by=row.get("created_by"),
        language_requested=row.get("language_requested") or "hinglish",
        language_used=row.get("language_used"), language_note=row.get("language_note"),
        selection_note=row.get("selection_note"),
        created_at=row.get("created_at") or datetime.now(timezone.utc).isoformat(),
    )


def _start_thread(target, *args) -> None:
    threading.Thread(target=target, args=args, daemon=True).start()
```

5. `_clip_record`: change the annotation to `clip: selection.Clip` and add `"qaFlags": _qa_flags(clip.flags, prepared.face_at_start),` after `"style"`.

6. `_clip_row`: add `"qa_flags": record["qaFlags"],` after `"style"`.

7. `_clip_row_to_api`: add `"qaFlags": r.get("qa_flags") or [],` after `"captionsEdited"`.

8. Replace everything in `_run_pipeline` from `db.save_transcript(job.id, ...)` down to (and including) the final `_persist_job(job)` of the `try` block with:

```python
        db.save_transcript(job.id, tr.language, tr.source, [s.to_dict() for s in tr.segments], tr.loudness)
        _select_and_prepare(job, meta, tr.segments, tr.loudness)
```

and add above `_run_pipeline`:

```python
def _select_and_prepare(job: Job, meta: ingest.VideoMeta, segs: list[Segment], loudness: list[float]) -> None:
    """Pick clips from the transcript, then cut and frame each one. A
    selection that cannot run is not an error: the transcript is kept and
    the job waits in selection_failed for Retry selection."""
    job.status = "analyzing"
    job.progress = {"stage": "analyzing", "percent": None, "note": "picking clips…"}
    _persist_job(job)
    try:
        result = selection.select(segs, loudness)
    except selection.SelectionFailed as e:
        job.status = "selection_failed"
        job.error = str(e)
        job.progress = {}
        _persist_job(job)
        return
    job.selection_note = result.note
    clips = result.clips
    word_segments = transcript.word_segments(segs)

    job.status = "preparing"
    job.progress = {"stage": "preparing", "percent": 0, "note": f"0/{len(clips)} clips prepared"}
    _persist_job(job)

    for i, c in enumerate(clips):
        def on_step(step: str, i: int = i) -> None:
            job.progress = {
                "stage": "preparing",
                "percent": i / len(clips) * 100.0,
                "note": f"clip {i + 1}/{len(clips)}: {step}",
            }
            _persist_job(job, throttle=True)

        prepared = clipprep.prepare_clip(
            job_id=job.id, idx=i, clip=c,
            video_path=meta.video_path, video_duration=meta.duration,
            segments=word_segments,
            clips_dir=CLIPS_DIR, models_dir=MODELS_DIR, on_step=on_step,
        )
        record = _clip_record(job.id, i, c, prepared)
        job.clips.append(record)
        # Saved per clip, so a failure later in the job doesn't lose
        # the clips already prepared.
        db.insert_clips([_clip_row(job.id, i, record)])

    job.status = "done"
    job.progress = {}
    _persist_job(job)


def _run_selection_retry(job: Job, stored: dict[str, Any]) -> None:
    try:
        meta = ingest.ingest(job.url, CACHE_DIR)
        segs = [segment_from_dict(d) for d in stored.get("segments") or []]
        _select_and_prepare(job, meta, segs, stored.get("loudness") or [])
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = str(e)
        job.progress = {}
        _persist_job(job)
```

9. Add the endpoint after `generate`:

```python
@app.post("/api/jobs/{job_id}/select")
def retry_selection(job_id: str, member: Member = Depends(current_member)) -> dict[str, str]:
    """Re-run clip selection from the stored transcript after it failed
    (usually Groq's daily limit). Download and transcription are skipped."""
    check_id(job_id, "job id")
    _require_job(member, job_id)
    job = JOBS.get(job_id)
    if job is None:
        row = db.get_job(job_id)
        if row is None:
            raise HTTPException(404, "job not found")
        job = _job_from_row(row)
    if job.status != "selection_failed":
        raise HTTPException(409, "Clip selection can only be retried after it failed.")
    stored = db.get_transcript(job_id)
    if not stored or not stored.get("segments"):
        raise HTTPException(409, "This video's transcript wasn't saved. Submit the video again.")
    job.status, job.error, job.selection_note, job.clips = "analyzing", None, None, []
    job.progress = {"stage": "analyzing", "percent": None, "note": "picking clips…"}
    JOBS[job_id] = job
    _persist_job(job)
    _start_thread(_run_selection_retry, job, stored)
    return {"job_id": job_id}
```

10. `status()`: in the in-memory branch add `"selectionNote": job.selection_note,` after `"languageNote"`. In the database branch change `if status_value not in ("done", "error"):` to `if status_value not in ("done", "error", "selection_failed"):`, replace the inline `video_meta = None` / `if row.get("video_title"): ...` block with `video_meta = _video_meta_from_row(row)`, and add `"selectionNote": row.get("selection_note"),` after `"languageNote"`.

- [ ] **Step 5: Run the full suite**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass. Also run `grep -rn "highlight" backend --include=*.py` and confirm nothing imports the deleted module (comments mentioning "highlight" are fine).

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/projects.py tests/test_pipeline_run.py tests/test_status.py tests/test_projects.py
git commit -m "Run the new clip selection, park failures for retry, store QA flags

Adds POST /api/jobs/{id}/select, the selection_failed state, the
selection note and qaFlags on clips.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Frontend: retry state, selection note, QA chips

**Files:**
- Modify: `frontend/src/services/highlyteApi.js`, `frontend/src/stores/jobStore.js`, `frontend/src/views/JobView.vue`, `frontend/src/components/ClipCard.vue`, `frontend/src/components/ProjectCard.vue`

**Interfaces:**
- Consumes: `POST /api/jobs/{id}/select`; status fields `status === "selection_failed"`, `error`, `selectionNote`; clip field `qaFlags`.
- Produces: `retrySelection(jobId)` API helper; store getter `selectionFailed`; store action `retrySelection()`.

This task builds the elements in the current style with the existing CSS variables. The Superdesign minimal redesign restyles them later in its own plan.

- [ ] **Step 1: API helper**

In `frontend/src/services/highlyteApi.js`, after `getJobStatus`:

```js
export function retrySelection(jobId) {
  return api.post(`/api/jobs/${jobId}/select`).then(r => r.data)
}
```

- [ ] **Step 2: Store**

In `frontend/src/stores/jobStore.js`:
- add `apiErrorMessage` and `retrySelection as apiRetrySelection` to the import from `'../services/highlyteApi'`;
- change `isProcessing` to `(state) => !!state.job && !['done', 'error', 'selection_failed'].includes(state.job.status),`;
- add the getter `selectionFailed: (state) => state.job?.status === 'selection_failed',`;
- in `refresh()`, after the `if (data.status === 'error') { ... }` block, add:

```js
        } else if (data.status === 'selection_failed') {
          this.stopPolling()
```

  so the chain reads `if (error) {...} else if (selection_failed) {...} else if (done) {...}`;
- add the action after `stopPolling()`:

```js
    async retrySelection() {
      if (!this.currentJobId) return
      this.error = null
      try {
        await apiRetrySelection(this.currentJobId)
        this.startPolling()
      } catch (e) {
        this.error = apiErrorMessage(e, 'Could not retry clip selection.')
      }
    },
```

- [ ] **Step 3: Job view**

In `frontend/src/views/JobView.vue` template, after the `lang-note` paragraph:

```html
    <div v-if="jobStore.selectionFailed" class="selection-failed">
      <p class="sf-title">Clip selection didn't finish</p>
      <p class="sf-msg">{{ jobStore.job.error }}</p>
      <p class="sf-sub">The transcript is saved, so a retry skips the download and transcription.</p>
      <button class="sf-retry" :disabled="retrying" @click="onRetry">
        {{ retrying ? 'Retrying…' : 'Retry selection' }}
      </button>
    </div>

    <p v-if="jobStore.isDone && jobStore.job?.selectionNote" class="selection-note">{{ jobStore.job.selectionNote }}</p>
```

In its script:
- change the vue import to `import { computed, onMounted, onUnmounted, ref, watch } from 'vue'`;
- add `selection_failed: 'Clip selection needs a retry',` to `STATUS_NOTES`;
- add after `statusNote`:

```js
const retrying = ref(false)
async function onRetry() {
  retrying.value = true
  try {
    await jobStore.retrySelection()
  } finally {
    retrying.value = false
  }
}
```

In its `<style scoped>`:

```css
.selection-failed {
  margin-top: 24px; padding: 20px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--surface); display: flex; flex-direction: column; gap: 6px; align-items: flex-start;
}
.sf-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--ink); }
.sf-msg { margin: 0; font-size: 14px; color: var(--ink); }
.sf-sub { margin: 0 0 8px; font-size: 13px; color: var(--ink-soft); }
.sf-retry {
  border: none; border-radius: 8px; padding: 9px 16px; font-size: 14px; font-weight: 600;
  font-family: var(--font-sans); color: #fff; background: var(--accent); cursor: pointer;
}
.sf-retry:disabled { opacity: .6; cursor: default; }
.selection-note {
  margin: 16px 0 0; padding: 10px 14px; border-radius: 8px; font-size: 13px;
  color: var(--ink-soft); background: var(--accent-soft);
}
```

- [ ] **Step 4: Clip card chips**

In `frontend/src/components/ClipCard.vue` template, directly after the closing `</div>` of `meta-row`:

```html
      <div v-if="clip.qaFlags?.length" class="qa-flags">
        <span v-for="f in clip.qaFlags" :key="f" class="qa-chip">{{ QA_LABELS[f] || f }}</span>
      </div>
```

In its script, after the imports:

```js
const QA_LABELS = {
  low_confidence: 'Low confidence — check captions',
  weak_pick: 'Weaker pick',
  no_face_start: 'No face at start',
}
```

In its `<style scoped>`:

```css
.qa-flags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.qa-chip {
  font-size: 12px; font-weight: 600; padding: 3px 9px; border-radius: 999px;
  background: #FFFAEB; color: #B54708;
}
```

- [ ] **Step 5: Project card badge**

In `frontend/src/components/ProjectCard.vue`, change the failed badge line to:

```html
        <span v-else class="badge failed" :title="project.error || ''">{{ project.status === 'selection_failed' ? 'Needs retry' : 'Failed' }}</span>
```

- [ ] **Step 6: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/services/highlyteApi.js frontend/src/stores/jobStore.js frontend/src/views/JobView.vue frontend/src/components/ClipCard.vue frontend/src/components/ProjectCard.vue
git commit -m "Show retry selection, the selection note and QA chips

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Dry-run script and docs

**Files:**
- Create: `scripts/select_dry_run.py`
- Modify: `docs/superpowers/specs/2026-09-25-hinglish-v1-roadmap.md` ("Start" section)

**Interfaces:**
- Consumes: `db.get_transcript`, `segments.from_dict`, `selection.select`, `ingest.duration_label`.

- [ ] **Step 1: Write the script**

Create `scripts/select_dry_run.py`:

```python
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
```

- [ ] **Step 2: Check it runs without a key**

Create a tiny transcript file and run the script with an empty key:

```bash
printf '{"segments": []}' > "$TMP/empty_transcript.json"
GROQ_KEY= ./.venv/Scripts/python scripts/select_dry_run.py "$TMP/empty_transcript.json"
```

Expected: `Selection failed: Clip selection needs GROQ_KEY.` (exit code 1). This spends no tokens. If `.env` sets `GROQ_KEY`, `load_dotenv` does not override the empty value set on the command line, so the message still appears.

- [ ] **Step 3: Update the roadmap**

In `docs/superpowers/specs/2026-09-25-hinglish-v1-roadmap.md`, replace the body of the final "## Start" section with:

```markdown
Steps 0–2 are done, and piece 2 (Step 3, clip selection) is built: see
`2026-09-26-clip-selection-design.md` and
`../plans/2026-09-26-clip-selection.md`. Tune its thresholds on real
episodes with `scripts/select_dry_run.py <job_id>`. Next is piece 3 (Step 4).
```

- [ ] **Step 4: Run the full suite**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/select_dry_run.py docs/superpowers/specs/2026-09-25-hinglish-v1-roadmap.md
git commit -m "Add a clip selection dry-run script and update the roadmap

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After all tasks

- Final whole-branch review on the most capable model.
- Remind the user:
  - apply the new migration locally: `npx supabase db push --db-url "$DBURL"`;
  - re-run a video to see the new selection, or try `scripts/select_dry_run.py <job_id>` on an existing job (spends Groq tokens);
  - browser checks (login needed): the QA chips on a clip card, the selection note, and the retry flow (set `GROQ_KEY` empty in the backend's environment, run a video, see "Retry selection", restore the key, retry).
