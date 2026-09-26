# Caption Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users fix the text of any caption line on a clip card, see it live in the preview, get it in the export, and can reset to the original.

**Architecture:** Line grouping and retiming live once in the renderer (`captions/edit.ts`), used by the Vue editor through the `@renderer` alias. The backend validates and stores the edited word list in `clips.spec.words`, keeps the untouched words in `clips.words_original`, and includes the words in the render dedupe hash.

**Tech Stack:** Remotion/React/TS + vitest (renderer), FastAPI + Pydantic + Supabase (backend), Vue 3 + Pinia + Vite (frontend).

**Spec:** `docs/superpowers/specs/2026-09-26-caption-editing-design.md`

## Global Constraints

- Branch `hinglish-v1`; commit after every task; **never push**; never stage `renderer/package-lock.json` or `frontend/dist`; never git stash / checkout other commits / reset / rebase / amend; never kill or stop any process; do not open or drive a browser.
- Every commit message ends with a blank line and exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Python: `./.venv/Scripts/python -m pytest -q` (222 pass + 1 pre-existing starlette warning). Renderer: `cd renderer && npm test && npm run typecheck`. Frontend: `cd frontend && npm run build`.
- Caption line limits: 14 words, 84 characters (the `clean` preset), breaks at sentence end or a pause > 0.4 s (existing `paginate`).
- Validation: 1–3000 words; word text 1–40 chars after trimming, no newline; `0 ≤ start ≤ end ≤ clip length + 0.5`; starts non-decreasing. Clip length = `spec.end - spec.start`; word times are clip-relative.
- Word shape everywhere: `{ text, start, end, emphasis }`.

---

### Task 1: Caption lines and retiming (renderer)

**Files:** Create `renderer/src/captions/edit.ts`, `renderer/src/captions/edit.test.ts`.

**Produces:** `LINE_MAX_WORDS = 14`, `LINE_MAX_CHARS = 84`, `type Line = { index: number; from: number; start: number; end: number; words: Word[] }` (`from` = index of the line's first word in the input array), `captionLines(words: Word[]): Line[]`, `lineText(line: Line): string`, `editLine(words: Word[], line: Line, text: string): Word[]`.

- [ ] **Step 1: Failing tests** — `renderer/src/captions/edit.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { Word } from '../schema'
import { captionLines, editLine, lineText } from './edit'

const w = (text: string, start: number, end: number, emphasis = false): Word => ({ text, start, end, emphasis })
// Two lines: a sentence ending in "." and a second sentence.
const words: Word[] = [
  w('hum', 0.0, 0.3), w('YouTube', 0.3, 0.8, true), w('pe', 0.8, 1.0), w('hain.', 1.0, 1.4),
  w('bohat', 1.5, 1.9), w('acha', 1.9, 2.3), w('laga.', 2.3, 2.8),
]

describe('captionLines', () => {
  it('groups words into lines with their first-word index', () => {
    const lines = captionLines(words)
    expect(lines.map(lineText)).toEqual(['hum YouTube pe hain.', 'bohat acha laga.'])
    expect(lines.map(l => [l.index, l.from, l.start, l.end])).toEqual([[0, 0, 0.0, 1.4], [1, 4, 1.5, 2.8]])
  })
  it('caps a line at 14 words', () => {
    const many = Array.from({ length: 20 }, (_, i) => w(`w${i}`, i * 0.3, i * 0.3 + 0.25))
    expect(captionLines(many)[0].words).toHaveLength(14)
  })
})

describe('editLine', () => {
  const [first, second] = captionLines(words)

  it('same word count keeps timings and emphasis', () => {
    const out = editLine(words, first, 'hum YouTube par hain.')
    expect(out.slice(0, 4)).toEqual([w('hum', 0, 0.3), w('YouTube', 0.3, 0.8, true), w('par', 0.8, 1.0), w('hain.', 1.0, 1.4)])
    expect(out.slice(4)).toEqual(words.slice(4))
  })

  it('different word count spreads the line span by word length', () => {
    const out = editLine(words, second, 'bohat zyada acha laga.')
    const edited = out.slice(4)
    expect(edited.map(x => x.text)).toEqual(['bohat', 'zyada', 'acha', 'laga.'])
    expect(edited[0].start).toBe(1.5)
    expect(edited[edited.length - 1].end).toBe(2.8)
    for (let i = 1; i < edited.length; i++) expect(edited[i].start).toBeCloseTo(edited[i - 1].end, 3)
    // "zyada" (6 incl. space) gets more time than "acha" (5)
    expect(edited[1].end - edited[1].start).toBeGreaterThan(edited[2].end - edited[2].start)
    expect(out.slice(0, 4)).toEqual(words.slice(0, 4))
  })

  it('carries emphasis to a matching word when the count changes', () => {
    const out = editLine(words, first, 'hum YouTube pe sab hain.')
    expect(out.find(x => x.text === 'YouTube')?.emphasis).toBe(true)
    expect(out.find(x => x.text === 'sab')?.emphasis).toBe(false)
  })

  it('empty text removes the line', () => {
    const out = editLine(words, first, '   ')
    expect(out).toEqual(words.slice(4))
  })
})
```

- [ ] **Step 2:** `cd renderer && npx vitest run src/captions/edit.test.ts` → FAIL (module not found).

- [ ] **Step 3: Implement** `renderer/src/captions/edit.ts`:

```ts
import type { Word } from '../schema'
import { paginate } from './paginate'

// Caption lines for editing use the clean preset's limits, so a line is the
// same whichever caption style the clip uses.
export const LINE_MAX_WORDS = 14
export const LINE_MAX_CHARS = 84

export type Line = { index: number; from: number; start: number; end: number; words: Word[] }

export function captionLines(words: Word[]): Line[] {
  let from = 0
  return paginate(words, LINE_MAX_WORDS, LINE_MAX_CHARS).map((page, index) => {
    const line = { index, from, start: page.start, end: page.end, words: page.words }
    from += page.words.length
    return line
  })
}

export const lineText = (line: Line) => line.words.map(x => x.text).join(' ')

const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}']+/gu, '')
const round3 = (n: number) => Math.round(n * 1000) / 1000

// Replaces one line's words with the edited text. Same word count keeps
// every timing; otherwise the line's own time span is shared out by word
// length, so the rest of the clip never moves.
export function editLine(words: Word[], line: Line, text: string): Word[] {
  const tokens = text.split(/\s+/).filter(Boolean)
  const before = words.slice(0, line.from)
  const after = words.slice(line.from + line.words.length)
  let replaced: Word[]
  if (tokens.length === line.words.length) {
    replaced = line.words.map((x, i) => ({ ...x, text: tokens[i] }))
  } else if (tokens.length === 0) {
    replaced = []
  } else {
    const emphasised = new Set(line.words.filter(x => x.emphasis).map(x => norm(x.text)))
    const weights = tokens.map(t => t.length + 1)
    const total = weights.reduce((a, b) => a + b, 0)
    const span = line.end - line.start
    let acc = 0
    replaced = tokens.map((t, i) => {
      const start = line.start + (span * acc) / total
      acc += weights[i]
      const end = i === tokens.length - 1 ? line.end : line.start + (span * acc) / total
      return { text: t, start: round3(start), end: round3(end), emphasis: emphasised.has(norm(t)) }
    })
  }
  return [...before, ...replaced, ...after]
}
```

- [ ] **Step 4:** `npm test && npm run typecheck` green.
- [ ] **Step 5:** Commit `Add caption line editing and retiming` (+ trailer).

---

### Task 2: Word validation, render hash including words (backend)

**Files:** Create `backend/captions.py`, `tests/test_captions.py`; modify `backend/spec.py`, `backend/render.py`, `backend/main.py` (`start_render`), `tests/test_render.py`, `tests/test_render_api.py`; create `supabase/migrations/20260926120000_clip_words_original.sql`.

**Produces:** `captions.validate_words(raw: list[dict], clip_length: float) -> list[Word]` (raises `ValueError` with a readable message), constants `MAX_WORDS = 3000`, `MAX_WORD_CHARS = 40`, `END_SLACK_S = 0.5`; `spec.render_hash(style: ClipStyle, words: list[Word]) -> str`; `RenderService.request(clip_id, style, words: list[Word] | None = None)`.

- [ ] **Step 1: Migration** `supabase/migrations/20260926120000_clip_words_original.sql`:

```sql
-- Caption editing: the clip's words as generated, kept from the first edit
-- so "Reset to original" can restore them. Null until the captions are edited.
alter table clips add column if not exists words_original jsonb;
```

- [ ] **Step 2: Failing tests.** `tests/test_captions.py`:

```python
import pytest

from backend import captions


def _w(text, start, end, emphasis=False):
    return {"text": text, "start": start, "end": end, "emphasis": emphasis}


def test_validate_words_accepts_and_trims():
    out = captions.validate_words([_w(" hum ", 0.0, 0.3), _w("hain.", 0.3, 0.8)], clip_length=10.0)
    assert [w.text for w in out] == ["hum", "hain."]


@pytest.mark.parametrize("words, message", [
    ([], "at least one"),
    ([_w("", 0, 1)], "empty"),
    ([_w("x" * 41, 0, 1)], "too long"),
    ([_w("a\nb", 0, 1)], "line break"),
    ([_w("a", -0.1, 1)], "time"),
    ([_w("a", 1.0, 0.5)], "time"),
    ([_w("a", 0, 10.6)], "time"),
    ([_w("a", 1.0, 1.2), _w("b", 0.5, 0.7)], "order"),
])
def test_validate_words_rejects(words, message):
    with pytest.raises(ValueError, match=message):
        captions.validate_words(words, clip_length=10.0)


def test_validate_words_rejects_too_many():
    with pytest.raises(ValueError, match="at most"):
        captions.validate_words([_w("a", 0, 0.01)] * 3001, clip_length=10.0)
```

Append to `tests/test_render.py` (reuse its `setup` fixture and existing imports; add `from backend.spec import Word` if needed):

```python
def test_request_rerenders_when_words_change(setup):
    svc = setup[0] if isinstance(setup, tuple) else setup
    words = [Word(text="hum", start=0.0, end=0.3)]
    a = svc.request("job1-9", ClipStyle(layout="fit"), words)
    b = svc.request("job1-9", ClipStyle(layout="fit"), words)
    c = svc.request("job1-9", ClipStyle(layout="fit"), [Word(text="ham", start=0.0, end=0.3)])
    assert a.id == b.id and c.id != a.id
```

(Adjust the first line to however the existing `setup` fixture exposes the service — read the fixture; do not change its behaviour.)

Append to `tests/test_spec.py`:

```python
def test_render_hash_depends_on_words_and_style():
    from backend.spec import ClipStyle, Word, render_hash

    s = ClipStyle(layout="fit")
    w1 = [Word(text="a", start=0.0, end=0.1)]
    assert render_hash(s, w1) == render_hash(s, list(w1))
    assert render_hash(s, w1) != render_hash(s, [Word(text="b", start=0.0, end=0.1)])
    assert render_hash(s, w1) != render_hash(ClipStyle(layout="follow"), w1)
```

- [ ] **Step 3:** Run → FAIL.

- [ ] **Step 4: Implement.** `backend/captions.py`:

```python
"""Validation for caption text edited on a clip card.

The editor (renderer/src/captions/edit.ts) retimes words in the browser;
the backend only checks the result is sane before storing it as the
clip's spec.words, which both the preview and the Lambda export read.
"""
from __future__ import annotations

from typing import Any

from .spec import Word

MAX_WORDS = 3000
MAX_WORD_CHARS = 40
# Word ends may run a touch past the clip end (the tail padding).
END_SLACK_S = 0.5


def validate_words(raw: list[dict[str, Any]], clip_length: float) -> list[Word]:
    if not raw:
        raise ValueError("Captions need at least one word.")
    if len(raw) > MAX_WORDS:
        raise ValueError(f"Captions can have at most {MAX_WORDS} words.")
    out: list[Word] = []
    prev_start = 0.0
    for i, item in enumerate(raw, start=1):
        word = Word.model_validate(item)
        text = word.text.strip()
        if not text:
            raise ValueError(f"Word {i} is empty.")
        if "\n" in text or "\r" in text:
            raise ValueError(f"Word {i} contains a line break.")
        if len(text) > MAX_WORD_CHARS:
            raise ValueError(f"Word {i} is too long (max {MAX_WORD_CHARS} characters).")
        if word.start < 0 or word.end < word.start or word.end > clip_length + END_SLACK_S:
            raise ValueError(f"Word {i} has a time outside the clip.")
        if word.start < prev_start:
            raise ValueError(f"Word {i} is out of order.")
        prev_start = word.start
        out.append(word.model_copy(update={"text": text}))
    return out
```

`backend/spec.py`, after `style_hash`:

```python
def render_hash(style: ClipStyle, words: list[Word]) -> str:
    """Fingerprint of everything an export depends on that a user can
    change: the style and the caption words. Editing captions must not
    reuse the mp4 rendered with the old text."""
    payload = json.dumps(
        {"style": style.model_dump(), "words": [w.model_dump() for w in words]},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
```

`backend/render.py`: import `Word, render_hash`; change `request`:

```python
    def request(self, clip_id: str, style: ClipStyle, words: list[Word] | None = None) -> Render:
        hash_value = style_hash(style) if words is None else render_hash(style, words)
```

(rest unchanged; `style_hash` column keeps storing this value).

`backend/main.py` `start_render`: before the request, `words = [Word.model_validate(w) for w in record["spec"]["words"]]` and call `RENDER_SERVICE.request(clip_id, style, words)`; import `Word` from `.spec`.

- [ ] **Step 5:** Full Python suite green (existing render API tests still pass).
- [ ] **Step 6:** Commit `Validate edited captions and re-render when words change` (+ trailer).

---

### Task 3: Caption endpoints

**Files:** Modify `backend/main.py`; create `tests/test_captions_api.py`.

**Consumes:** `captions.validate_words`, `_clip_for_style`, `_find_clip`, `db.update_clip`. **Produces:** `PUT /api/clips/{clip_id}/captions` body `{"words": [...]}` → `{"words": [...], "captionsEdited": true}`; `POST /api/clips/{clip_id}/captions/reset` → `{"words": [...], "captionsEdited": false}`; clip API field `captionsEdited`.

- [ ] **Step 1: Failing tests** — `tests/test_captions_api.py`:

```python
import json
import os

import pytest

from backend import main
from backend.spec import ClipSpec, default_style
from tests.support import TEST_TEAM_ID, api_client

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "renderer", "src", "__fixtures__", "clip-spec.json")
JOB_ID = "cap123def456"
CLIP_ID = f"{JOB_ID}-0"
client = api_client()


@pytest.fixture
def env(monkeypatch):
    with open(FIXTURE, encoding="utf-8") as f:
        spec = ClipSpec.model_validate(json.load(f)).model_copy(update={"clipId": CLIP_ID})
    record = {"id": CLIP_ID, "spec": spec.model_dump(), "style": default_style(spec).model_dump(),
              "downloadUrl": f"/api/clips/{JOB_ID}/clip_0.mp4"}
    main.JOBS[JOB_ID] = main.Job(id=JOB_ID, url="u", status="done", clips=[record], team_id=TEST_TEAM_ID)
    updates = []
    monkeypatch.setattr(main.db, "update_clip", lambda clip_id, fields: updates.append((clip_id, fields)))
    yield record, updates
    main.JOBS.pop(JOB_ID, None)


def _edited(record):
    words = [dict(w) for w in record["spec"]["words"]]
    words[0]["text"] = "Honestly,"
    return words


def test_save_captions_stores_words_and_original_once(env):
    record, updates = env
    original = [dict(w) for w in record["spec"]["words"]]
    r = client.put(f"/api/clips/{CLIP_ID}/captions", json={"words": _edited(record)})
    assert r.status_code == 200 and r.json()["captionsEdited"] is True
    assert r.json()["words"][0]["text"] == "Honestly,"
    assert record["spec"]["words"][0]["text"] == "Honestly,"
    assert updates[-1][1]["words_original"] == original
    second = _edited(record)
    second[1]["text"] = "changed"
    client.put(f"/api/clips/{CLIP_ID}/captions", json={"words": second})
    assert updates[-1][1]["words_original"] == original  # first original kept


def test_reset_restores_original(env):
    record, updates = env
    original = [dict(w) for w in record["spec"]["words"]]
    client.put(f"/api/clips/{CLIP_ID}/captions", json={"words": _edited(record)})
    r = client.post(f"/api/clips/{CLIP_ID}/captions/reset")
    assert r.json() == {"words": original, "captionsEdited": False}
    assert record["spec"]["words"] == original
    assert updates[-1][1] == {"spec": record["spec"], "words_original": None}


def test_save_captions_validates(env):
    record, _ = env
    bad = _edited(record)
    bad[0]["text"] = ""
    r = client.put(f"/api/clips/{CLIP_ID}/captions", json={"words": bad})
    assert r.status_code == 422 and "empty" in r.json()["detail"]


def test_captions_need_a_spec(env):
    record, _ = env
    record["spec"] = None
    assert client.put(f"/api/clips/{CLIP_ID}/captions", json={"words": []}).status_code == 409


def test_captions_are_team_scoped(env, monkeypatch):
    main.JOBS[JOB_ID].team_id = "00000000-0000-0000-0000-0000000other"
    assert client.put(f"/api/clips/{CLIP_ID}/captions", json={"words": []}).status_code == 404


def test_clip_row_reports_captions_edited():
    row = {"id": "a-0", "job_id": "a", "start_s": 1, "end_s": 2, "words_original": [{"text": "x", "start": 0, "end": 1}]}
    assert main._clip_row_to_api(row)["captionsEdited"] is True
    assert main._clip_row_to_api({**row, "words_original": None})["captionsEdited"] is False
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Implement** in `backend/main.py` (import `captions` from `.`; `BaseModel` from pydantic if not imported):

In `_clip_row_to_api` add `"wordsOriginal": r.get("words_original"), "captionsEdited": r.get("words_original") is not None,`.

Add after `update_style`:

```python
class CaptionsBody(BaseModel):
    words: list[dict[str, Any]]


def _captions_reply(record: dict[str, Any]) -> dict[str, Any]:
    return {"words": record["spec"]["words"], "captionsEdited": record.get("wordsOriginal") is not None}


@app.put("/api/clips/{clip_id}/captions")
def save_captions(clip_id: str, body: CaptionsBody = Body(...), member: Member = Depends(current_member)) -> dict[str, Any]:
    record = _clip_for_style(clip_id, member)
    spec = record["spec"]
    try:
        words = captions.validate_words(body.words, spec["end"] - spec["start"])
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if record.get("wordsOriginal") is None:
        record["wordsOriginal"] = spec["words"]  # kept from the first edit, for Reset
    record["spec"] = {**spec, "words": [w.model_dump() for w in words]}
    db.update_clip(record["id"], {"spec": record["spec"], "words_original": record["wordsOriginal"]})
    return _captions_reply(record)


@app.post("/api/clips/{clip_id}/captions/reset")
def reset_captions(clip_id: str, member: Member = Depends(current_member)) -> dict[str, Any]:
    record = _clip_for_style(clip_id, member)
    if record.get("wordsOriginal") is not None:
        record["spec"] = {**record["spec"], "words": record["wordsOriginal"]}
        record["wordsOriginal"] = None
        db.update_clip(record["id"], {"spec": record["spec"], "words_original": None})
    return _captions_reply(record)
```

Note: `_clip_for_style` raises 409 when the spec is missing and 404 for another team — exactly what the tests expect; a save with an empty word list on a valid clip is a 422 from `validate_words`.

- [ ] **Step 4:** Full Python suite green.
- [ ] **Step 5:** Commit `Add endpoints to save and reset clip captions` (+ trailer).

---

### Task 4: Caption editor in the clip card (frontend)

**Files:** Modify `frontend/src/services/highlyteApi.js`, `frontend/src/stores/jobStore.js`, `frontend/src/components/ClipCard.vue`; create `frontend/src/components/CaptionEditor.vue`.

**Consumes:** `captionLines`, `editLine`, `lineText` from `@renderer/captions/edit`; the Task 3 endpoints.

- [ ] **Step 1: API** (`highlyteApi.js`):

```js
export function saveCaptions(clipId, words) {
  return api.put(`/api/clips/${clipId}/captions`, { words }).then(r => r.data)
}

export function resetCaptions(clipId) {
  return api.post(`/api/clips/${clipId}/captions/reset`).then(r => r.data)
}
```

- [ ] **Step 2: Store actions** (`jobStore.js`; import the two functions as `apiSaveCaptions`, `apiResetCaptions`):

```js
    async saveCaptions(clipId, words) {
      const clip = this.clips.find(c => c.id === clipId)
      if (!clip) return
      const res = await apiSaveCaptions(clipId, words)
      clip.spec = { ...clip.spec, words: res.words }
      clip.captionsEdited = res.captionsEdited
    },
    async resetCaptions(clipId) {
      const clip = this.clips.find(c => c.id === clipId)
      if (!clip) return
      const res = await apiResetCaptions(clipId)
      clip.spec = { ...clip.spec, words: res.words }
      clip.captionsEdited = res.captionsEdited
    },
```

- [ ] **Step 3: `CaptionEditor.vue`**:

```vue
<template>
  <div class="captions-edit">
    <div class="row">
      <button v-if="!open" class="btn" @click="start">Edit captions</button>
      <button v-if="!open && edited" class="btn ghost" :disabled="busy" @click="reset">Reset to original</button>
    </div>
    <div v-if="open" class="lines">
      <label v-for="(line, i) in lines" :key="line.index" class="line">
        <span class="time">{{ clock(line.start) }}</span>
        <input v-model="texts[i]" type="text" />
      </label>
      <div class="row">
        <button class="btn" :disabled="busy" @click="save">{{ busy ? 'Saving…' : 'Save captions' }}</button>
        <button class="btn ghost" :disabled="busy" @click="cancel">Cancel</button>
      </div>
    </div>
    <div v-if="error" class="error">{{ error }}</div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { captionLines, editLine, lineText } from '@renderer/captions/edit'
import { useJobStore } from '../stores/jobStore'

const props = defineProps({
  clipId: { type: String, required: true },
  words: { type: Array, required: true },
  edited: { type: Boolean, default: false },
})
const emit = defineEmits(['draft'])
const jobStore = useJobStore()

const open = ref(false)
const busy = ref(false)
const error = ref('')
const texts = ref([])
const lines = computed(() => captionLines(props.words))

// Applied last line first, so each line's word index stays valid.
const draft = computed(() => {
  if (!open.value) return null
  let out = props.words
  for (let i = lines.value.length - 1; i >= 0; i--) {
    const line = lines.value[i]
    if (texts.value[i] !== lineText(line)) out = editLine(out, line, texts.value[i] ?? '')
  }
  return out
})
watch(draft, d => emit('draft', d))

const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

function start() {
  texts.value = lines.value.map(lineText)
  error.value = ''
  open.value = true
}
function cancel() {
  open.value = false
}
async function save() {
  busy.value = true
  error.value = ''
  try {
    await jobStore.saveCaptions(props.clipId, draft.value)
    open.value = false
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Failed to save captions'
  } finally {
    busy.value = false
  }
}
async function reset() {
  busy.value = true
  error.value = ''
  try {
    await jobStore.resetCaptions(props.clipId)
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Failed to reset captions'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.captions-edit { margin-top: 10px; }
.row { display: flex; gap: 8px; margin-top: 8px; }
.lines { display: flex; flex-direction: column; gap: 6px; max-height: 280px; overflow-y: auto; }
.line { display: flex; align-items: center; gap: 8px; }
.time { font-family: monospace; font-size: 11.5px; color: var(--ink-soft); width: 36px; flex-shrink: 0; }
.line input { flex: 1; min-width: 0; border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font-size: 13px; }
.btn { border: 1px solid var(--border); background: var(--accent-soft); color: var(--accent-text); border-radius: 6px; padding: 4px 10px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.btn.ghost { background: transparent; color: var(--ink-soft); }
.btn:disabled { opacity: .6; cursor: default; }
.error { color: #9C3B14; font-size: 12.5px; margin-top: 6px; }
</style>
```

- [ ] **Step 4: `ClipCard.vue`**: import `CaptionEditor` and `ref`/`computed` as needed; add `const draftWords = ref(null)` and `const previewSpec = computed(() => draftWords.value ? { ...props.clip.spec, words: draftWords.value } : props.clip.spec)` (use the component's existing props/`clip` access pattern — read the script first); pass `:spec="previewSpec"` to `RemotionPreview`; inside the `<template v-if="clip.spec">` block, after the accent/position row, add `<CaptionEditor :clip-id="clip.id" :words="clip.spec.words" :edited="!!clip.captionsEdited" @draft="draftWords = $event" />`.

- [ ] **Step 5:** `cd frontend && npm run build` succeeds; renderer and Python suites unaffected.
- [ ] **Step 6:** Commit `Add a caption editor to the clip card` (+ trailer).

---

## Spec coverage

| Spec item | Task |
|---|---|
| Caption lines (clean limits), retiming rules, emphasis, empty removes | 1 |
| Logic once in renderer, used by frontend | 1, 4 |
| `words_original`, save/reset endpoints, captionsEdited | 2 (migration), 3 |
| Validation | 2 |
| Render hash includes words | 2 |
| In-memory jobs updated | 3 (record mutated in place) |
| UI with live draft preview | 4 |
