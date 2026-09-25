# Piece 1: Language Choice and Transcription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the transcription step with a language-checked, VAD-chunked Whisper pipeline that stores Roman caption segments in the v1 data contract, while the current highlight scorer keeps working through an adapter.

**Architecture:** Small single-purpose modules in `backend/pipeline/` (`audio`, `asr`, `segments`, `hinglish`, `langcheck`), orchestrated by a slimmed `transcript.py`. `main._run_pipeline` calls the orchestrator, saves the transcript to a new `transcripts` table, and feeds the old scorer word-level `TranscriptSegment`s. The frontend adds a two-option spoken-language control and shows the detection note.

**Tech Stack:** Python 3.11, FastAPI, faster-whisper 1.1.0 (bundled Silero VAD, local fallback ASR), Groq Whisper through the `openai` client, Supabase (supabase-py), Vue 3 + Pinia, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-piece1-language-transcription-design.md` (roadmap: `docs/superpowers/specs/2026-09-25-hinglish-v1-roadmap.md`)

## Global Constraints

- Work on branch `hinglish-v1`. Commit after every task. **Never push.**
- Every commit message ends with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run tests with `./.venv/Scripts/python -m pytest -q` from the repo root (Git Bash). All 137 existing tests pass before Task 1; the suite must be green at the end of every task.
- Tests never touch the network. `tests/conftest.py` blanks `GROQ_KEY`, `SUPABASE_*`, R2 and AWS settings.
- Whisper always runs with `language="en"`. Hinglish sends the Roman seed prompt; English sends no prompt. Never `task=translate`, never `language="hi"`/`"ur"`.
- Groq models: `whisper-large-v3` for Hinglish, `whisper-large-v3-turbo` for English and for language checks. Local fallback: faster-whisper `small`, CPU, int8.
- Chunks: at most 120s, cut only in silence. VAD: min silence 250ms, min speech 400ms, pad 250ms.
- Language values in the API and DB: `"hinglish"` or `"english"`. Segment `language` codes: `"hi-Latn-EN"` or `"en"`.
- No spelling-list key may be an English word.
- Match the surrounding code: module docstrings explaining *why*, `from __future__ import annotations`, and comments only where a reader would otherwise be surprised.
- `renderer/package-lock.json` has an unrelated local change. Never stage it.

## File map

| File | Status | Responsibility |
|---|---|---|
| `supabase/migrations/20260925120000_transcripts_and_job_language.sql` | create | job language columns + `transcripts` table |
| `backend/db.py` | modify | `save_transcript`, `get_transcript` |
| `backend/pipeline/audio.py` | create | normalize, load, write wav, VAD regions, packing, chunks, language samples |
| `backend/pipeline/asr.py` | create | `AsrProvider`, Groq and local providers, chunk loop with retry and fallback |
| `backend/pipeline/segments.py` | create | `SegWord`, `Segment`, `build` |
| `backend/pipeline/hinglish.py` | create | glossary, spelling list, `classify`, `fix` |
| `backend/pipeline/data/glossary.json`, `spelling.json`, `hinglish_also_english.txt`, `english_words.txt` | create | editable data |
| `scripts/make_english_words.py` | create | one-off generator for `english_words.txt` |
| `backend/pipeline/langcheck.py` | create | detection rule and detectors |
| `backend/pipeline/transcript.py` | rewrite | orchestration and the adapter |
| `backend/pipeline/words.py`, `backend/pipeline/clipprep.py` | modify | drop captions-only branches |
| `backend/main.py`, `backend/projects.py` | modify | `language` request field, job language fields, new pipeline, status fields |
| `frontend/src/components/TopBar.vue`, `frontend/src/stores/jobStore.js`, `frontend/src/services/highlyteApi.js`, `frontend/src/views/JobView.vue` | modify | picker, API call, note |
| `README.md` | modify | transcription section |
| `tests/test_audio.py`, `test_asr.py`, `test_segments.py`, `test_hinglish.py`, `test_langcheck.py`, `test_transcript.py`, `test_transcript_store.py` | create | unit tests |
| `tests/test_words.py`, `tests/test_validation.py`, `tests/test_jobs_api.py` | modify | follow the API and words changes |

---

### Task 1: Migration and transcript storage

**Files:**
- Create: `supabase/migrations/20260925120000_transcripts_and_job_language.sql`
- Modify: `backend/db.py` (add two functions after `list_clips_for_job`)
- Test: `tests/test_transcript_store.py`

**Interfaces:**
- Produces: `db.save_transcript(job_id: str, language: str, source: str, segments: list[dict]) -> None` (no-op without Supabase; **raises** on a Supabase error); `db.get_transcript(job_id: str) -> dict | None`.

- [ ] **Step 1: Write the migration**

```sql
-- Piece 1: the spoken language a job was submitted with and the one
-- actually used, plus the stored transcript (v1 segment data contract)
-- so clips can later be nudged and regenerated without transcribing again.
alter table jobs add column if not exists language_requested text;
alter table jobs add column if not exists language_used text;
alter table jobs add column if not exists language_note text;

create table if not exists transcripts (
  job_id text primary key references jobs(id) on delete cascade,
  language text not null,          -- 'hinglish' | 'english'
  source text not null,            -- 'groq' | 'whisper' | 'mixed'
  segments jsonb not null,
  created_at timestamptz not null default now()
);
alter table transcripts enable row level security;
```

- [ ] **Step 2: Write the failing tests**

```python
"""db.save_transcript / get_transcript against a fake supabase client."""
import pytest

from backend import db


class FakeTable:
    def __init__(self, store, fail=False):
        self.store, self.fail, self.filters = store, fail, {}

    def upsert(self, row):
        self.row = row
        return self

    def select(self, *_):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, _):
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("supabase down")
        if hasattr(self, "row"):
            self.store[self.row["job_id"]] = self.row
            return type("R", (), {"data": [self.row]})()
        row = self.store.get(self.filters.get("job_id"))
        return type("R", (), {"data": [row] if row else []})()


class FakeClient:
    def __init__(self, fail=False):
        self.store, self.fail = {}, fail

    def table(self, name):
        assert name == "transcripts"
        return FakeTable(self.store, self.fail)


def test_save_and_get_transcript(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(db, "get_client", lambda: fake)
    segs = [{"id": "seg_0001", "hinglish": "hum yahan hain"}]
    db.save_transcript("job1", "hinglish", "groq", segs)
    got = db.get_transcript("job1")
    assert got["language"] == "hinglish" and got["source"] == "groq" and got["segments"] == segs


def test_save_transcript_raises_on_error(monkeypatch):
    monkeypatch.setattr(db, "get_client", lambda: FakeClient(fail=True))
    with pytest.raises(RuntimeError):
        db.save_transcript("job1", "english", "groq", [])


def test_transcript_functions_without_supabase(monkeypatch):
    monkeypatch.setattr(db, "get_client", lambda: None)
    db.save_transcript("job1", "english", "groq", [])  # no-op
    assert db.get_transcript("job1") is None
```

- [ ] **Step 3: Run to confirm failure**

Run: `./.venv/Scripts/python -m pytest tests/test_transcript_store.py -q`
Expected: FAIL, `AttributeError: module 'backend.db' has no attribute 'save_transcript'`.

- [ ] **Step 4: Implement in `backend/db.py`** (after `list_clips_for_job`)

```python
def save_transcript(job_id: str, language: str, source: str, segments: list[dict[str, Any]]) -> None:
    """Store a job's transcript. Unlike the job/clip writes above, a failure
    raises: nudging and regenerating clips later depends on this row, so a
    job without it must not be reported as done."""
    client = get_client()
    if client is None:
        return
    client.table("transcripts").upsert({
        "job_id": job_id, "language": language, "source": source, "segments": segments,
    }).execute()


def get_transcript(job_id: str) -> dict[str, Any] | None:
    client = get_client()
    if client is None:
        return None
    try:
        return _first(client.table("transcripts").select("*").eq("job_id", job_id).limit(1).execute())
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] get_transcript failed: {e}")
        return None
```

- [ ] **Step 5: Run the tests**

Run: `./.venv/Scripts/python -m pytest tests/test_transcript_store.py -q` → 3 passed. Then run the full suite → all green.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/20260925120000_transcripts_and_job_language.sql backend/db.py tests/test_transcript_store.py
git commit -m "Add the transcripts table and job language columns

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Audio preparation and VAD chunks

**Files:**
- Create: `backend/pipeline/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Produces: `SR = 16000`, `MAX_CHUNK_S = 120.0`, `Chunk(path: str, offset: float)`, `normalize(src: str, dst: str) -> None`, `load(path: str) -> np.ndarray`, `write_wav(samples: np.ndarray, path: str) -> None`, `pack_regions(regions: list[tuple[float, float]], max_s: float) -> list[tuple[float, float]]`, `speech_regions(samples, max_s=MAX_CHUNK_S) -> list[tuple[float, float]]`, `speech_chunks(samples, out_dir: str, max_s=MAX_CHUNK_S) -> list[Chunk]`, `language_samples(samples, out_dir: str, dur_s=20.0) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
import os
import subprocess
import wave

import numpy as np

from backend.pipeline import audio


def test_pack_regions_joins_until_max():
    regions = [(0.0, 50.0), (51.0, 100.0), (101.0, 130.0), (131.0, 140.0)]
    assert audio.pack_regions(regions, 120.0) == [(0.0, 100.0), (101.0, 140.0)]


def test_pack_regions_never_exceeds_max_for_short_regions():
    regions = [(i * 10.0, i * 10.0 + 8.0) for i in range(40)]
    for start, end in audio.pack_regions(regions, 120.0):
        assert end - start <= 120.0


def test_pack_regions_empty():
    assert audio.pack_regions([], 120.0) == []


def test_speech_chunks_writes_wavs_with_offsets(tmp_path, monkeypatch):
    samples = np.zeros(audio.SR * 300, dtype=np.float32)
    monkeypatch.setattr(audio, "speech_regions", lambda s, max_s=120.0: [(1.0, 60.0), (62.0, 110.0), (130.0, 200.0)])
    chunks = audio.speech_chunks(samples, str(tmp_path))
    assert [c.offset for c in chunks] == [1.0, 130.0]
    with wave.open(chunks[0].path) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        assert abs(w.getnframes() / 16000 - 109.0) < 0.01


def test_language_samples_positions(tmp_path):
    samples = np.zeros(audio.SR * 200, dtype=np.float32)
    paths = audio.language_samples(samples, str(tmp_path))
    assert len(paths) == 3 and all(os.path.exists(p) for p in paths)


def test_language_samples_short_audio(tmp_path):
    samples = np.zeros(audio.SR * 8, dtype=np.float32)
    assert len(audio.language_samples(samples, str(tmp_path))) == 1


def test_normalize_produces_16k_mono(tmp_path):
    src = tmp_path / "tone.m4a"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2:sample_rate=44100", "-ac", "2", str(src)], check=True)
    dst = tmp_path / "out.wav"
    audio.normalize(str(src), str(dst))
    with wave.open(str(dst)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
```

- [ ] **Step 2: Run to confirm failure**

Run: `./.venv/Scripts/python -m pytest tests/test_audio.py -q`
Expected: FAIL, `ImportError: cannot import name 'audio'`.

- [ ] **Step 3: Implement `backend/pipeline/audio.py`**

```python
"""Audio preparation for transcription.

Whisper gets 16kHz mono speech in chunks of at most two minutes, and a
chunk is only ever cut in a silence found by the Silero voice-activity
detector bundled with faster-whisper. The old fixed 10-minute split could
land mid-word; cutting in silence means no word is sliced and chunks never
need overlapping or de-duplicating.
"""
from __future__ import annotations

import os
import subprocess
import wave
from dataclasses import dataclass

import numpy as np

SR = 16000
MAX_CHUNK_S = 120.0


@dataclass
class Chunk:
    path: str
    offset: float  # seconds into the full audio where this chunk starts


def normalize(src: str, dst: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", src,
        "-vn", "-ac", "1", "-ar", str(SR), "-af", "loudnorm", "-c:a", "pcm_s16le", dst,
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg normalize failed: {proc.stderr.decode(errors='ignore')}")


def load(path: str) -> np.ndarray:
    from faster_whisper.audio import decode_audio

    return decode_audio(path, sampling_rate=SR)


def write_wav(samples: np.ndarray, path: str) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def pack_regions(regions: list[tuple[float, float]], max_s: float) -> list[tuple[float, float]]:
    """Greedily join consecutive speech regions while the joined span stays
    within max_s. Each boundary between chunks falls in the silence between
    two regions."""
    chunks: list[tuple[float, float]] = []
    for start, end in regions:
        if chunks and end - chunks[-1][0] <= max_s:
            chunks[-1] = (chunks[-1][0], end)
        else:
            chunks.append((start, end))
    return chunks


def speech_regions(samples: np.ndarray, max_s: float = MAX_CHUNK_S) -> list[tuple[float, float]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    # max_speech_duration_s makes Silero itself split an unbroken stretch of
    # speech at its last silence, so no single region outgrows a chunk.
    opts = VadOptions(
        min_silence_duration_ms=250, min_speech_duration_ms=400,
        speech_pad_ms=250, max_speech_duration_s=max_s - 1,
    )
    return [(t["start"] / SR, t["end"] / SR) for t in get_speech_timestamps(samples, opts)]


def speech_chunks(samples: np.ndarray, out_dir: str, max_s: float = MAX_CHUNK_S) -> list[Chunk]:
    chunks: list[Chunk] = []
    for i, (start, end) in enumerate(pack_regions(speech_regions(samples, max_s), max_s)):
        path = os.path.join(out_dir, f"chunk_{i:03d}.wav")
        write_wav(samples[int(start * SR):int(end * SR)], path)
        chunks.append(Chunk(path=path, offset=round(start, 3)))
    return chunks


def language_samples(samples: np.ndarray, out_dir: str, dur_s: float = 20.0) -> list[str]:
    """Short samples at 10%, 50% and 90% of the audio for the language
    check; the whole audio when it is shorter than one sample."""
    total = len(samples) / SR
    if total <= dur_s:
        starts = [0.0]
    else:
        starts = [min(max(total * f - dur_s / 2, 0.0), total - dur_s) for f in (0.1, 0.5, 0.9)]
    paths = []
    for i, start in enumerate(starts):
        path = os.path.join(out_dir, f"langsample_{i}.wav")
        write_wav(samples[int(start * SR):int((start + dur_s) * SR)], path)
        paths.append(path)
    return paths
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python -m pytest tests/test_audio.py -q` → 7 passed. Full suite green.

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/audio.py tests/test_audio.py
git commit -m "Add audio normalisation and VAD speech chunks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: ASR providers and the chunk loop

**Files:**
- Create: `backend/pipeline/asr.py`
- Test: `tests/test_asr.py`

**Interfaces:**
- Consumes: `audio.Chunk` (Task 2).
- Produces: `AsrWord(text: str, start: float, end: float, prob: float)`, `AsrProvider` protocol with `name: str` and `transcribe(wav: str, *, prompt: str | None) -> list[AsrWord]`, `words_from_verbose(resp: dict) -> list[AsrWord]`, `GroqAsr(key: str, model: str)`, `LocalWhisperAsr(model_size: str = "small")`, `get_local_model(model_size="small")`, `transcribe_chunks(chunks, primary: AsrProvider | None, fallback: AsrProvider, *, prompt: str | None, on_progress=None, sleep=time.sleep) -> tuple[list[AsrWord], str]` returning absolute-time words and source `"groq" | "whisper" | "mixed"`. Constants `GROQ_BASE_URL`, `GROQ_HINGLISH_MODEL = "whisper-large-v3"`, `GROQ_ENGLISH_MODEL = "whisper-large-v3-turbo"`.

Language is always `"en"` (see Global Constraints), so it is fixed inside each provider rather than passed in.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from backend.pipeline import asr
from backend.pipeline.audio import Chunk

VERBOSE = {
    "segments": [
        {"start": 0.0, "end": 2.0, "avg_logprob": -0.1},
        {"start": 2.0, "end": 4.0, "avg_logprob": -1.0},
    ],
    "words": [
        {"word": " hum", "start": 0.1, "end": 0.4},
        {"word": "yahan", "start": 2.2, "end": 2.6},
        {"word": "  ", "start": 3.0, "end": 3.1},
    ],
}


def test_words_from_verbose_assigns_segment_confidence():
    words = asr.words_from_verbose(VERBOSE)
    assert [w.text for w in words] == ["hum", "yahan"]
    assert words[0].prob == pytest.approx(0.905, abs=1e-3)
    assert words[1].prob == pytest.approx(0.368, abs=1e-3)


def test_words_from_verbose_without_segments():
    words = asr.words_from_verbose({"words": [{"word": "a", "start": 0, "end": 1}]})
    assert words[0].prob == 1.0


class Fake:
    def __init__(self, name, answers):
        self.name, self.answers, self.calls = name, list(answers), []

    def transcribe(self, wav, *, prompt):
        self.calls.append((wav, prompt))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_transcribe_chunks_offsets_and_source():
    groq = Fake("groq", [[asr.AsrWord("a", 0.5, 0.9, 0.9)], [asr.AsrWord("b", 1.0, 1.2, 0.8)]])
    local = Fake("whisper", [])
    progress = []
    words, source = asr.transcribe_chunks(
        [Chunk("c0.wav", 0.0), Chunk("c1.wav", 100.0)], groq, local, prompt="seed",
        on_progress=lambda i, n, text: progress.append((i, n)),
    )
    assert [(w.text, w.start) for w in words] == [("a", 0.5), ("b", 101.0)]
    assert source == "groq" and progress == [(1, 2), (2, 2)]
    assert groq.calls[0] == ("c0.wav", "seed")


def test_transcribe_chunks_retries_rate_limit_then_succeeds():
    groq = Fake("groq", [RuntimeError("429 rate limit, retry in 1.5s"), [asr.AsrWord("a", 0, 1, 1.0)]])
    slept = []
    words, source = asr.transcribe_chunks([Chunk("c.wav", 0.0)], groq, Fake("whisper", []),
                                          prompt=None, sleep=slept.append)
    assert slept == [1.5] and source == "groq" and words[0].text == "a"


def test_transcribe_chunks_falls_back_to_local():
    groq = Fake("groq", [RuntimeError("server error")])
    local = Fake("whisper", [[asr.AsrWord("x", 0, 1, 0.7)]])
    words, source = asr.transcribe_chunks([Chunk("c.wav", 10.0)], groq, local, prompt=None)
    assert source == "whisper" and words[0].start == 10.0


def test_transcribe_chunks_mixed_source():
    groq = Fake("groq", [[asr.AsrWord("a", 0, 1, 1.0)], RuntimeError("boom")])
    local = Fake("whisper", [[asr.AsrWord("b", 0, 1, 1.0)]])
    _, source = asr.transcribe_chunks([Chunk("a.wav", 0), Chunk("b.wav", 5)], groq, local, prompt=None)
    assert source == "mixed"


def test_transcribe_chunks_without_groq_uses_local():
    local = Fake("whisper", [[asr.AsrWord("b", 0, 1, 1.0)]])
    _, source = asr.transcribe_chunks([Chunk("a.wav", 0)], None, local, prompt=None)
    assert source == "whisper"
```

- [ ] **Step 2: Run to confirm failure**

Run: `./.venv/Scripts/python -m pytest tests/test_asr.py -q`
Expected: FAIL, `ImportError: cannot import name 'asr'`.

- [ ] **Step 3: Implement `backend/pipeline/asr.py`**

```python
"""Speech recognition behind one small interface.

An AsrProvider turns a wav chunk into words with times and a confidence.
Groq's hosted Whisper is the primary provider and local faster-whisper the
fallback; a paid ASR can be added later as another provider without
touching the rest of the pipeline. Whisper always runs with language="en":
the spike (roadmap, "Spike results") showed Hindi mode writes English words
in Devanagari and romanizing them back mangles them.
"""
from __future__ import annotations

import math
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_HINGLISH_MODEL = "whisper-large-v3"  # the model the spike validated
GROQ_ENGLISH_MODEL = "whisper-large-v3-turbo"
GROQ_MAX_RETRIES = 2  # per chunk, on rate limits, before falling back

_RETRY_AFTER_RE = re.compile(r"retry.{0,10}?(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


@dataclass
class AsrWord:
    text: str
    start: float
    end: float
    prob: float


class AsrProvider(Protocol):
    name: str

    def transcribe(self, wav: str, *, prompt: str | None) -> list[AsrWord]: ...


def words_from_verbose(resp: dict[str, Any]) -> list[AsrWord]:
    """Words from a Groq verbose_json response. Groq gives no per-word
    probability, so each word takes exp(avg_logprob) of the segment it
    falls in."""
    segs = [
        (float(s["start"]), float(s["end"]), math.exp(float(s["avg_logprob"])))
        for s in resp.get("segments") or []
    ]
    out: list[AsrWord] = []
    for w in resp.get("words") or []:
        text = w["word"].strip()
        if not text:
            continue
        start, end = float(w["start"]), float(w["end"])
        mid = (start + end) / 2
        prob = next((p for s, e, p in segs if s <= mid <= e), 1.0)
        out.append(AsrWord(text=text, start=start, end=end, prob=round(min(prob, 1.0), 3)))
    return out


class GroqAsr:
    name = "groq"

    def __init__(self, key: str, model: str) -> None:
        self.key, self.model = key, model

    def transcribe(self, wav: str, *, prompt: str | None) -> list[AsrWord]:
        from openai import OpenAI

        client = OpenAI(api_key=self.key, base_url=GROQ_BASE_URL)
        kwargs: dict[str, Any] = dict(
            model=self.model, language="en", response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )
        if prompt:
            kwargs["prompt"] = prompt
        with open(wav, "rb") as f:
            resp = client.audio.transcriptions.create(file=f, **kwargs)
        return words_from_verbose(resp.model_dump())


_local_models: dict[str, Any] = {}


def get_local_model(model_size: str = "small"):
    if model_size not in _local_models:
        from faster_whisper import WhisperModel

        _local_models[model_size] = WhisperModel(
            model_size, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4,
        )
    return _local_models[model_size]


class LocalWhisperAsr:
    name = "whisper"

    def __init__(self, model_size: str = "small") -> None:
        self.model_size = model_size

    def transcribe(self, wav: str, *, prompt: str | None) -> list[AsrWord]:
        # beam_size=1: about twice the CPU throughput for a small accuracy cost.
        segments, _info = get_local_model(self.model_size).transcribe(
            wav, language="en", initial_prompt=prompt, beam_size=1, word_timestamps=True,
        )
        return [
            AsrWord(text=w.word.strip(), start=w.start, end=w.end, prob=round(w.probability, 3))
            for s in segments for w in (s.words or []) if w.word.strip()
        ]


def _retry_after(exc: Exception) -> float:
    match = _RETRY_AFTER_RE.search(str(exc))
    return float(match.group(1)) if match else 5.0


def _is_rate_limit(exc: Exception) -> bool:
    return "rate" in str(exc).lower() or "429" in str(exc)


def transcribe_chunks(
    chunks: list,
    primary: AsrProvider | None,
    fallback: AsrProvider,
    *,
    prompt: str | None,
    on_progress: Callable[[int, int, str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[AsrWord], str]:
    """Transcribe each chunk, primary first. Rate limits are retried with
    the server's retry-after; any other failure, or retries running out,
    sends that chunk to the fallback, so a Groq outage makes a job slow
    rather than failed. Word times come back on the full audio's timeline."""
    words: list[AsrWord] = []
    used: set[str] = set()
    for i, chunk in enumerate(chunks):
        got: list[AsrWord] | None = None
        if primary is not None:
            for attempt in range(GROQ_MAX_RETRIES + 1):
                try:
                    got = primary.transcribe(chunk.path, prompt=prompt)
                    used.add(primary.name)
                    break
                except Exception as e:  # noqa: BLE001
                    if _is_rate_limit(e) and attempt < GROQ_MAX_RETRIES:
                        sleep(_retry_after(e))
                        continue
                    print(f"[asr] {primary.name} failed on chunk {i}, using {fallback.name}: {e}")
                    break
        if got is None:
            got = fallback.transcribe(chunk.path, prompt=prompt)
            used.add(fallback.name)
        for w in got:
            words.append(AsrWord(w.text, round(w.start + chunk.offset, 3), round(w.end + chunk.offset, 3), w.prob))
        if on_progress is not None:
            try:
                on_progress(i + 1, len(chunks), " ".join(w.text for w in got[-25:]))
            except Exception:
                pass  # progress reporting must never break the pipeline
    source = used.pop() if len(used) == 1 else ("mixed" if used else "groq")
    return words, source
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python -m pytest tests/test_asr.py -q` → 7 passed. Full suite green.

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/asr.py tests/test_asr.py
git commit -m "Add the swappable ASR provider interface with Groq and local Whisper

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Segment data contract

**Files:**
- Create: `backend/pipeline/segments.py`
- Test: `tests/test_segments.py`

**Interfaces:**
- Consumes: `asr.AsrWord` (Task 3).
- Produces: `SegWord(t: str, raw: str, start: float, end: float, kind: str, prob: float)` with `to_dict()`; `Segment(id, start, end, speaker, language, raw, hinglish, words: list[SegWord], confidence)` with `to_dict()`; `from_asr(words: list[AsrWord]) -> list[SegWord]` (sets `t = raw = text`, `kind = ""`); `build(words: list[SegWord], language_code: str) -> list[Segment]`; constants `PAUSE_S = 0.35`, `MAX_SEGMENT_S = 15.0`.

- [ ] **Step 1: Write the failing tests**

```python
from backend.pipeline import segments
from backend.pipeline.asr import AsrWord


def w(t, start, end, prob=0.9, raw=None):
    return segments.SegWord(t=t, raw=raw or t, start=start, end=end, kind="hinglish", prob=prob)


def test_from_asr_copies_text_to_raw():
    out = segments.from_asr([AsrWord("yar", 1.0, 1.2, 0.8)])
    assert (out[0].t, out[0].raw, out[0].kind) == ("yar", "yar", "")


def test_build_splits_on_pause_and_punctuation():
    words = [w("hum", 0.0, 0.3), w("chalein.", 0.3, 0.7), w("phir", 0.8, 1.0),
             w("dekho", 1.0, 1.3), w("yaar", 1.8, 2.0)]
    segs = segments.build(words, "hi-Latn-EN")
    assert [s.hinglish for s in segs] == ["hum chalein.", "phir dekho", "yaar"]
    assert [s.id for s in segs] == ["seg_0001", "seg_0002", "seg_0003"]
    assert segs[0].start == 0.0 and segs[0].end == 0.7


def test_build_splits_long_segments():
    words = [w(f"w{i}", i * 0.5, i * 0.5 + 0.45) for i in range(40)]  # 20s, no pauses
    for s in segments.build(words, "en"):
        assert s.end - s.start <= segments.MAX_SEGMENT_S


def test_segment_fields():
    seg = segments.build([w("yaar", 1.0, 1.5, prob=0.8, raw="yar"), w("sun", 1.5, 1.8, prob=0.6)], "hi-Latn-EN")[0]
    assert seg.raw == "yar sun" and seg.hinglish == "yaar sun"
    assert seg.speaker == "A" and seg.language == "hi-Latn-EN"
    assert seg.confidence == 0.7
    d = seg.to_dict()
    assert d["words"][0] == {"t": "yaar", "raw": "yar", "start": 1.0, "end": 1.5, "kind": "hinglish", "prob": 0.8}


def test_build_empty():
    assert segments.build([], "en") == []
```

- [ ] **Step 2: Run to confirm failure**

Run: `./.venv/Scripts/python -m pytest tests/test_segments.py -q`
Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement `backend/pipeline/segments.py`**

```python
"""The v1 segment data contract (roadmap, "Data contract").

A segment is a run of words split on a pause, a sentence end or a length
cap. `raw` is what Whisper wrote; `hinglish` is after the glossary and
spelling list. Captions, exports and the ranker read `hinglish`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .asr import AsrWord

PAUSE_S = 0.35
MAX_SEGMENT_S = 15.0


@dataclass
class SegWord:
    t: str
    raw: str
    start: float
    end: float
    kind: str  # "en" | "hinglish" | "num"; "" until hinglish.fix runs
    prob: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Segment:
    id: str
    start: float
    end: float
    speaker: str
    language: str
    raw: str
    hinglish: str
    words: list[SegWord] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["words"] = [x.to_dict() for x in self.words]
        return d


def from_asr(words: list[AsrWord]) -> list[SegWord]:
    return [SegWord(t=x.text, raw=x.text, start=x.start, end=x.end, kind="", prob=x.prob) for x in words]


def _segment(n: int, words: list[SegWord], language_code: str) -> Segment:
    return Segment(
        id=f"seg_{n:04d}",
        start=words[0].start,
        end=words[-1].end,
        speaker="A",  # no diarization in v1
        language=language_code,
        raw=" ".join(x.raw for x in words),
        hinglish=" ".join(x.t for x in words),
        words=words,
        confidence=round(sum(x.prob for x in words) / len(words), 2),
    )


def build(words: list[SegWord], language_code: str) -> list[Segment]:
    out: list[Segment] = []
    current: list[SegWord] = []
    for word in words:
        if current:
            prev = current[-1]
            if (word.start - prev.end >= PAUSE_S
                    or prev.t.endswith((".", "?", "!"))
                    or word.end - current[0].start > MAX_SEGMENT_S):
                out.append(_segment(len(out) + 1, current, language_code))
                current = []
        current.append(word)
    if current:
        out.append(_segment(len(out) + 1, current, language_code))
    return out
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python -m pytest tests/test_segments.py -q` → 5 passed. Full suite green.

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/segments.py tests/test_segments.py
git commit -m "Add the segment data contract

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Glossary, spelling list and word classes

**Files:**
- Create: `scripts/make_english_words.py`
- Create: `backend/pipeline/data/english_words.txt` (generated), `backend/pipeline/data/hinglish_also_english.txt`, `backend/pipeline/data/glossary.json`, `backend/pipeline/data/spelling.json`
- Create: `backend/pipeline/hinglish.py`
- Modify: `Dockerfile` (no change needed: `COPY backend ./backend` already includes `backend/pipeline/data/`; confirm only)
- Test: `tests/test_hinglish.py`

**Interfaces:**
- Consumes: `segments.SegWord` (Task 4).
- Produces: `hinglish.apply_glossary(words: list[SegWord]) -> list[SegWord]`, `apply_spelling(words) -> list[SegWord]`, `classify(text: str) -> str`, `fix(words: list[SegWord], language: str) -> list[SegWord]` where `language` is `"hinglish"` or `"english"` (English runs the glossary only; both set `kind`).

- [ ] **Step 1: Generate the English word list (one-off, not a runtime dependency)**

Create `scripts/make_english_words.py`:

```python
"""One-off: write backend/pipeline/data/english_words.txt, the common
English words hinglish.classify uses to tell English from Roman Hindi/Urdu.

  ./.venv/Scripts/pip install wordfreq
  ./.venv/Scripts/python scripts/make_english_words.py

wordfreq is only needed to regenerate the file; the app reads the text file.
"""
from pathlib import Path

from wordfreq import top_n_list

OUT = Path(__file__).resolve().parents[1] / "backend" / "pipeline" / "data" / "english_words.txt"
words = sorted({w for w in top_n_list("en", 10000) if w.isalpha() and w.isascii() and len(w) > 1})
OUT.write_text("\n".join(words) + "\n", encoding="utf-8")
print(f"{len(words)} words -> {OUT}")
```

Run:
```bash
mkdir -p backend/pipeline/data
./.venv/Scripts/pip install -q wordfreq
./.venv/Scripts/python scripts/make_english_words.py
```
Expected: `NNNN words -> ...english_words.txt` (about 9,000). Do **not** add wordfreq to `requirements.txt`.

- [ ] **Step 2: Write the data files**

`backend/pipeline/data/hinglish_also_english.txt`: Roman Hindi/Urdu words that are also English words, or that English web text contains often. `classify` treats these as `hinglish`, and the spelling list must never rewrite them.

```
aap
ab
aur
bhai
bhi
hai
hain
hi
is
ja
jab
ka
kar
ke
ki
ko
log
main
me
mein
na
par
pe
raha
se
so
tab
the
to
toh
us
wala
yaar
ye
```

`backend/pipeline/data/glossary.json` (lowercase phrase → fixed form; multi-word keys merge words):

```json
{
  "you tube": "YouTube",
  "youtube": "YouTube",
  "insta gram": "Instagram",
  "instagram": "Instagram",
  "tik tok": "TikTok",
  "tiktok": "TikTok",
  "whats app": "WhatsApp",
  "whatsapp": "WhatsApp",
  "face book": "Facebook",
  "facebook": "Facebook",
  "podcast": "podcast",
  "pakistan": "Pakistan",
  "india": "India",
  "karachi": "Karachi",
  "lahore": "Lahore",
  "delhi": "Delhi",
  "mumbai": "Mumbai"
}
```

`backend/pipeline/data/spelling.json` (lowercase variant → house spelling; no key may be an English word):

```json
{
  "yeh": "ye",
  "wo": "woh",
  "vo": "woh",
  "bhoat": "bohat",
  "bohot": "bohat",
  "bahut": "bohat",
  "bhot": "bohat",
  "fark": "farq",
  "kia": "kya",
  "kyaa": "kya",
  "hy": "hai",
  "hae": "hai",
  "nahin": "nahi",
  "nai": "nahi",
  "kyuki": "kyunki",
  "kyuke": "kyunki",
  "kyonki": "kyunki",
  "mjhe": "mujhe",
  "mujhay": "mujhe",
  "mjhy": "mujhe",
  "krna": "karna",
  "kerna": "karna",
  "kerti": "karti",
  "kerte": "karte",
  "cheezein": "cheezen",
  "chiz": "cheez",
  "chij": "cheez",
  "kuchh": "kuch",
  "zindgi": "zindagi",
  "jindagi": "zindagi",
  "jyada": "zyada",
  "ziada": "zyada",
  "zayada": "zyada",
  "khwaish": "khwahish",
  "jaruri": "zaroori",
  "jarur": "zaroor",
  "siraf": "sirf",
  "yar": "yaar"
}
```

- [ ] **Step 3: Write the failing tests**

```python
import json
from pathlib import Path

from backend.pipeline import hinglish
from backend.pipeline.segments import SegWord

DATA = Path(hinglish.__file__).parent / "data"


def w(t, start=0.0, end=0.1, prob=0.9):
    return SegWord(t=t, raw=t, start=start, end=end, kind="", prob=prob)


def test_no_spelling_key_is_an_english_word():
    english = set((DATA / "english_words.txt").read_text(encoding="utf-8").split())
    keys = set(json.loads((DATA / "spelling.json").read_text(encoding="utf-8")))
    assert keys & english == set()


def test_spelling_keys_avoid_ambiguous_words():
    ambiguous = set((DATA / "hinglish_also_english.txt").read_text(encoding="utf-8").split())
    keys = set(json.loads((DATA / "spelling.json").read_text(encoding="utf-8")))
    assert keys & ambiguous == set()


def test_apply_spelling_keeps_punctuation_and_capital():
    out = hinglish.apply_spelling([w("Bhoat,"), w("fark?"), w("the"), w("to")])
    assert [x.t for x in out] == ["Bohat,", "farq?", "the", "to"]
    assert [x.raw for x in out] == ["Bhoat,", "fark?", "the", "to"]


def test_apply_glossary_merges_phrases_and_keeps_timing():
    out = hinglish.apply_glossary([w("you", 1.0, 1.2, 0.9), w("tube", 1.2, 1.5, 0.5), w("pe", 1.5, 1.7)])
    assert [x.t for x in out] == ["YouTube", "pe"]
    assert (out[0].raw, out[0].start, out[0].end, out[0].prob) == ("you tube", 1.0, 1.5, 0.45)


def test_apply_glossary_single_word_keeps_punctuation():
    assert hinglish.apply_glossary([w("instagram.")])[0].t == "Instagram."


def test_classify():
    assert hinglish.classify("2026") == "num"
    assert hinglish.classify("video,") == "en"
    assert hinglish.classify("the") == "hinglish"
    assert hinglish.classify("dekho") == "hinglish"
    assert hinglish.classify("YouTube") == "en"


def test_fix_hinglish_runs_glossary_spelling_and_kind():
    out = hinglish.fix([w("yar"), w("you"), w("tube"), w("pe"), w("video"), w("bhoat")], "hinglish")
    assert [x.t for x in out] == ["yaar", "YouTube", "pe", "video", "bohat"]
    assert [x.kind for x in out] == ["hinglish", "en", "hinglish", "en", "hinglish"]


def test_fix_english_skips_spelling():
    out = hinglish.fix([w("yar"), w("youtube")], "english")
    assert [x.t for x in out] == ["yar", "YouTube"]
```

- [ ] **Step 4: Run to confirm failure**

Run: `./.venv/Scripts/python -m pytest tests/test_hinglish.py -q`
Expected: FAIL, `ImportError`. If `test_no_spelling_key_is_an_english_word` still fails after Step 5, remove the offending key from `spelling.json`. The test is the rule, not the list.

- [ ] **Step 5: Implement `backend/pipeline/hinglish.py`**

```python
"""Fix Whisper's Roman text in code: a glossary for names and brands, and
one house spelling for Roman Hindi/Urdu that Indian and Pakistani readers
both recognise (ye, woh, toh, bohat, farq, kyunki).

Both lists are plain JSON in data/ so they can grow without code changes.
A spelling key is never an English word (a test enforces it), so English
words like "to" or "the" are never rewritten.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from .segments import SegWord

DATA = Path(__file__).parent / "data"
_EDGE_RE = re.compile(r"^(\W*)(.*?)(\W*)$", re.UNICODE)


@lru_cache(maxsize=1)
def _glossary() -> dict[tuple[str, ...], str]:
    raw = json.loads((DATA / "glossary.json").read_text(encoding="utf-8"))
    return {tuple(k.split()): v for k, v in raw.items()}


@lru_cache(maxsize=1)
def _spelling() -> dict[str, str]:
    return json.loads((DATA / "spelling.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _english() -> frozenset[str]:
    return frozenset((DATA / "english_words.txt").read_text(encoding="utf-8").split())


@lru_cache(maxsize=1)
def _also_english() -> frozenset[str]:
    return frozenset((DATA / "hinglish_also_english.txt").read_text(encoding="utf-8").split())


def _split(text: str) -> tuple[str, str, str]:
    pre, core, post = _EDGE_RE.match(text).groups()
    return pre, core, post


def apply_glossary(words: list[SegWord]) -> list[SegWord]:
    glossary = _glossary()
    longest = max((len(k) for k in glossary), default=1)
    out: list[SegWord] = []
    i = 0
    while i < len(words):
        for n in range(min(longest, len(words) - i), 0, -1):
            span = words[i:i + n]
            key = tuple(_split(x.t)[1].lower() for x in span)
            if key in glossary:
                pre = _split(span[0].t)[0]
                post = _split(span[-1].t)[2]
                prob = 1.0
                for x in span:
                    prob *= x.prob
                out.append(replace(
                    span[0], t=pre + glossary[key] + post, raw=" ".join(x.raw for x in span),
                    end=span[-1].end, prob=round(prob, 3),
                ))
                i += n
                break
        else:
            out.append(words[i])
            i += 1
    return out


def apply_spelling(words: list[SegWord]) -> list[SegWord]:
    spelling = _spelling()
    out = []
    for x in words:
        pre, core, post = _split(x.t)
        fixed = spelling.get(core.lower())
        if fixed is None:
            out.append(x)
            continue
        if core[:1].isupper():
            fixed = fixed[:1].upper() + fixed[1:]
        out.append(replace(x, t=pre + fixed + post))
    return out


def classify(text: str) -> str:
    core = _split(text)[1]
    if core.replace(".", "").replace(",", "").isdigit():
        return "num"
    low = core.lower()
    if low in _also_english():
        return "hinglish"
    if low in _english() or any(core == v for v in _glossary().values()):
        return "en"
    return "hinglish"


def fix(words: list[SegWord], language: str) -> list[SegWord]:
    words = apply_glossary(words)
    if language == "hinglish":
        words = apply_spelling(words)
    return [replace(x, kind=classify(x.t)) for x in words]
```

- [ ] **Step 6: Run the tests**

Run: `./.venv/Scripts/python -m pytest tests/test_hinglish.py -q` → 8 passed. Full suite green.

- [ ] **Step 7: Commit**

```bash
git add scripts/make_english_words.py backend/pipeline/data backend/pipeline/hinglish.py tests/test_hinglish.py
git commit -m "Add the glossary, house spelling list and word classes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Language check

**Files:**
- Create: `backend/pipeline/langcheck.py`
- Test: `tests/test_langcheck.py`

**Interfaces:**
- Consumes: `asr.GROQ_BASE_URL`, `asr.GROQ_ENGLISH_MODEL`, `asr.get_local_model`, `audio.load` (Tasks 2 and 3).
- Produces: `LanguageDecision(used: str, note: str | None)`, `normalize_code(name: str | None) -> str | None`, `rule(detected: list[str | None], requested: str) -> LanguageDecision`, `decide(sample_paths: list[str], requested: str, detect: Callable[[str], str | None]) -> LanguageDecision`, `groq_detector(key: str) -> Callable[[str], str | None]`, `local_detect(path: str) -> str | None`. Constants `NOTE_ENGLISH = "Detected English audio. Captions will be in English."`, `NOTE_HINGLISH = "Detected Hindi/Urdu speech. Captions will be in Hinglish."`.

- [ ] **Step 1: Write the failing tests**

```python
from backend.pipeline import langcheck as lc


def test_normalize_code():
    assert lc.normalize_code("English") == "en"
    assert lc.normalize_code("hindi") == "hi"
    assert lc.normalize_code("ur") == "ur"
    assert lc.normalize_code("french") == "other"
    assert lc.normalize_code(None) is None


def test_all_english_overrides_hinglish_choice():
    d = lc.rule(["en", "en", "en"], "hinglish")
    assert d == lc.LanguageDecision("english", lc.NOTE_ENGLISH)


def test_all_english_matching_choice_has_no_note():
    assert lc.rule(["en", "en", "en"], "english") == lc.LanguageDecision("english", None)


def test_any_hindi_or_urdu_overrides_english_choice():
    assert lc.rule(["en", "ur", "en"], "english") == lc.LanguageDecision("hinglish", lc.NOTE_HINGLISH)
    assert lc.rule(["hi", "en", "en"], "hinglish") == lc.LanguageDecision("hinglish", None)


def test_unclear_keeps_choice():
    assert lc.rule(["en", None, "en"], "hinglish") == lc.LanguageDecision("hinglish", None)
    assert lc.rule(["en", "other", "en"], "hinglish") == lc.LanguageDecision("hinglish", None)
    assert lc.rule([None, None, None], "english") == lc.LanguageDecision("english", None)


def test_decide_survives_detector_errors():
    calls = []

    def detect(path):
        calls.append(path)
        if path == "b.wav":
            raise RuntimeError("groq down")
        return "english"

    assert lc.decide(["a.wav", "b.wav", "c.wav"], "hinglish", detect) == lc.LanguageDecision("hinglish", None)
    assert calls == ["a.wav", "b.wav", "c.wav"]
```

- [ ] **Step 2: Run to confirm failure**

Run: `./.venv/Scripts/python -m pytest tests/test_langcheck.py -q`
Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement `backend/pipeline/langcheck.py`**

```python
"""Check the user's spoken-language choice against the audio.

Three short samples go to Whisper with no language set. All three English
means the English path; any Hindi or Urdu means Hinglish; anything unclear
keeps the user's choice. When the result overrides the choice, the note is
shown on the status screen so it is never a silent surprise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import asr

NOTE_ENGLISH = "Detected English audio. Captions will be in English."
NOTE_HINGLISH = "Detected Hindi/Urdu speech. Captions will be in Hinglish."

_CODES = {"english": "en", "en": "en", "hindi": "hi", "hi": "hi", "urdu": "ur", "ur": "ur"}


@dataclass(frozen=True)
class LanguageDecision:
    used: str            # "hinglish" | "english"
    note: str | None


def normalize_code(name: str | None) -> str | None:
    if not name:
        return None
    return _CODES.get(name.strip().lower(), "other")


def rule(detected: list[str | None], requested: str) -> LanguageDecision:
    if any(d in ("hi", "ur") for d in detected):
        return LanguageDecision("hinglish", NOTE_HINGLISH if requested == "english" else None)
    if detected and all(d == "en" for d in detected):
        return LanguageDecision("english", NOTE_ENGLISH if requested == "hinglish" else None)
    return LanguageDecision(requested, None)


def decide(sample_paths: list[str], requested: str, detect: Callable[[str], str | None]) -> LanguageDecision:
    detected: list[str | None] = []
    for path in sample_paths:
        try:
            detected.append(normalize_code(detect(path)))
        except Exception as e:  # noqa: BLE001
            print(f"[langcheck] detection failed on {path}: {e}")
            detected.append(None)
    return rule(detected, requested)


def groq_detector(key: str) -> Callable[[str], str | None]:
    def detect(path: str) -> str | None:
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=asr.GROQ_BASE_URL)
        with open(path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model=asr.GROQ_ENGLISH_MODEL, file=f, response_format="verbose_json",
            )
        return resp.model_dump().get("language")

    return detect


def local_detect(path: str) -> str | None:
    from . import audio

    lang, _prob, _all = asr.get_local_model().detect_language(audio.load(path))
    return lang
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python -m pytest tests/test_langcheck.py -q` → 6 passed. Full suite green.

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/langcheck.py tests/test_langcheck.py
git commit -m "Add the spoken-language check

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Transcript orchestration and the adapter

**Files:**
- Rewrite: `backend/pipeline/transcript.py`
- Test: `tests/test_transcript.py`

**Interfaces:**
- Consumes: everything from Tasks 2–6.
- Produces: `ROMAN_URDU_HINDI_SEED` (unchanged text), `TranscriptSegment(start, end, text)` (unchanged, still imported by `highlight.py`, `clipprep.py`, `words.py`), `Transcript(segments: list[Segment], language: str, note: str | None, source: str)`, `NoSpeechError(RuntimeError)`, `transcribe(audio_path: str, requested: str, on_progress=None, *, detect=None, primary=..., fallback=...) -> Transcript`, `to_word_segments(t: Transcript) -> list[TranscriptSegment]`. `transcribe` picks providers itself when `primary`/`fallback`/`detect` are not given; tests inject them.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pytest

from backend.pipeline import audio, transcript
from backend.pipeline.asr import AsrWord
from backend.pipeline.audio import Chunk


class FakeAsr:
    name = "groq"

    def __init__(self, words):
        self.words, self.prompts = words, []

    def transcribe(self, wav, *, prompt):
        self.prompts.append(prompt)
        return self.words


@pytest.fixture
def fake_audio(monkeypatch):
    monkeypatch.setattr(audio, "normalize", lambda src, dst: None)
    monkeypatch.setattr(audio, "load", lambda path: np.zeros(audio.SR * 60, dtype=np.float32))
    monkeypatch.setattr(audio, "language_samples", lambda s, d: ["s1.wav", "s2.wav", "s3.wav"])
    monkeypatch.setattr(audio, "speech_chunks", lambda s, d: [Chunk("c0.wav", 0.0)])


def test_hinglish_path_uses_seed_and_spelling(fake_audio):
    asr_ = FakeAsr([AsrWord("yar", 0.0, 0.3, 0.9), AsrWord("bhoat", 0.3, 0.6, 0.9), AsrWord("acha.", 0.6, 0.9, 0.9)])
    t = transcript.transcribe("a.m4a", "hinglish", detect=lambda p: "hindi", primary=asr_, fallback=asr_)
    assert asr_.prompts == [transcript.ROMAN_URDU_HINDI_SEED]
    assert t.language == "hinglish" and t.note is None and t.source == "groq"
    assert t.segments[0].hinglish == "yaar bohat acha." and t.segments[0].raw == "yar bhoat acha."
    assert t.segments[0].language == "hi-Latn-EN"


def test_detected_english_overrides_and_drops_prompt(fake_audio):
    asr_ = FakeAsr([AsrWord("yar", 0.0, 0.3, 0.9)])
    t = transcript.transcribe("a.m4a", "hinglish", detect=lambda p: "english", primary=asr_, fallback=asr_)
    assert asr_.prompts == [None]
    assert t.language == "english" and t.note
    assert t.segments[0].hinglish == "yar" and t.segments[0].language == "en"


def test_no_speech_raises(fake_audio, monkeypatch):
    monkeypatch.setattr(audio, "speech_chunks", lambda s, d: [])
    with pytest.raises(transcript.NoSpeechError):
        transcript.transcribe("a.m4a", "english", detect=lambda p: "english",
                              primary=FakeAsr([]), fallback=FakeAsr([]))


def test_to_word_segments_uses_fixed_text(fake_audio):
    asr_ = FakeAsr([AsrWord("yar", 1.0, 1.3, 0.9), AsrWord("sun", 1.3, 1.6, 0.9)])
    t = transcript.transcribe("a.m4a", "hinglish", detect=lambda p: "hindi", primary=asr_, fallback=asr_)
    segs = transcript.to_word_segments(t)
    assert [(s.start, s.end, s.text) for s in segs] == [(1.0, 1.3, "yaar"), (1.3, 1.6, "sun")]


def test_adapter_output_feeds_the_highlight_scorer(fake_audio):
    from backend.pipeline import highlight

    words = [AsrWord(f"baat{i}.", i * 0.5, i * 0.5 + 0.4, 0.9) for i in range(200)]
    asr_ = FakeAsr(words)
    t = transcript.transcribe("a.m4a", "hinglish", detect=lambda p: "hindi", primary=asr_, fallback=asr_)
    highlight.detect_highlights(transcript.to_word_segments(t))  # must not raise
```

- [ ] **Step 2: Run to confirm failure**

Run: `./.venv/Scripts/python -m pytest tests/test_transcript.py -q`
Expected: FAIL, `AttributeError: module ... has no attribute 'transcribe'`.

- [ ] **Step 3: Rewrite `backend/pipeline/transcript.py`**

Replace the whole file:

```python
"""Transcription: audio in, v1 caption segments out.

  normalize (16kHz mono, loudnorm)
  -> language check on three samples (langcheck)
  -> VAD chunks of at most 120s, cut in silence (audio)
  -> Whisper per chunk, Groq first with local fallback (asr)
  -> glossary and house spelling in code (hinglish)
  -> segments (the v1 data contract)

Whisper always runs with language="en". On the Hinglish path it also gets
ROMAN_URDU_HINDI_SEED as a prompt: Whisper treats the prompt as "text so
far" and keeps writing Roman Hindi/Urdu in Latin letters instead of
switching script or translating to English. The spike (roadmap, "Spike
results") compared this with Hindi mode plus transliteration and this path
won clearly on English words, names and Urdu vocabulary. The prompt is not
sent on English audio, where it can make Whisper invent Urdu-looking words.

YouTube's own captions are no longer used: they have no word timings, the
English track on Hindi/Urdu videos is often a translation, and the captions
API is blocked on the server like yt-dlp.
"""
from __future__ import annotations

import os

# Must be set before faster_whisper/huggingface_hub is imported anywhere.
# On this environment the hf_xet accelerated transfer backend silently
# stalls at 0 bytes on large model files (plain HTTPS to the same host
# works fine) — forcing the plain-HTTP downloader avoids the hang.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import shutil
import tempfile
from dataclasses import dataclass
from typing import Callable

from . import asr, audio, hinglish, langcheck, segments

ROMAN_URDU_HINDI_SEED = (
    "Yeh podcast Roman Urdu aur Hindi mein baat karta hai, jaise "
    "'mujhe yeh cheez bohat pasand hai' ya 'hum log kal milenge'. "
    "Kabhi kabhi English words bhi beech mein aa jate hain, jaise "
    "'that's actually a great point' ya 'I totally agree with you'. "
    "Log apni baat normal tareeke se karte hain, bina kisi script ke, "
    "sirf Roman letters mein."
)

LANGUAGE_CODES = {"hinglish": "hi-Latn-EN", "english": "en"}


@dataclass
class TranscriptSegment:
    """One timed piece of text for the highlight scorer and clip prep.
    Built one per word by to_word_segments until piece 2 replaces them."""
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    segments: list[segments.Segment]
    language: str        # "hinglish" | "english", the path actually used
    note: str | None     # set when detection overrode the user's choice
    source: str          # "groq" | "whisper" | "mixed"


class NoSpeechError(RuntimeError):
    pass


def _providers(language: str) -> tuple[asr.AsrProvider | None, asr.AsrProvider]:
    key = os.environ.get("GROQ_KEY")
    model = asr.GROQ_HINGLISH_MODEL if language == "hinglish" else asr.GROQ_ENGLISH_MODEL
    return (asr.GroqAsr(key, model) if key else None), asr.LocalWhisperAsr("small")


def transcribe(
    audio_path: str,
    requested: str,
    on_progress: Callable[[int, int, str], None] | None = None,
    *,
    detect: Callable[[str], str | None] | None = None,
    primary: asr.AsrProvider | None = None,
    fallback: asr.AsrProvider | None = None,
) -> Transcript:
    tmp_dir = tempfile.mkdtemp(prefix="highlyte_asr_")
    try:
        wav = os.path.join(tmp_dir, "audio.wav")
        audio.normalize(audio_path, wav)
        samples = audio.load(wav)

        if detect is None:
            key = os.environ.get("GROQ_KEY")
            detect = langcheck.groq_detector(key) if key else langcheck.local_detect
        decision = langcheck.decide(audio.language_samples(samples, tmp_dir), requested, detect)

        chunks = audio.speech_chunks(samples, tmp_dir)
        if not chunks:
            raise NoSpeechError("No speech found in this video.")

        if primary is None and fallback is None:
            primary, fallback = _providers(decision.used)
        prompt = ROMAN_URDU_HINDI_SEED if decision.used == "hinglish" else None
        words, source = asr.transcribe_chunks(
            chunks, primary, fallback or primary, prompt=prompt, on_progress=on_progress,
        )

        fixed = hinglish.fix(segments.from_asr(words), decision.used)
        return Transcript(
            segments=segments.build(fixed, LANGUAGE_CODES[decision.used]),
            language=decision.used, note=decision.note, source=source,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def to_word_segments(t: Transcript) -> list[TranscriptSegment]:
    return [TranscriptSegment(w.start, w.end, w.t) for s in t.segments for w in s.words]
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python -m pytest tests/test_transcript.py -q` → 5 passed.
Run the full suite. `main.py` still calls `transcript.get_transcript`, `transcript._detect_needs_roman_urdu_hint` and `transcript.ROMAN_URDU_HINDI_SEED`, and `words.py` imports `_transcribe_chunk_groq`, so **import errors are expected** in `tests/test_words.py` and the API tests until Tasks 8 and 9. Do not commit until Task 8 fixes `words.py`; continue straight to Task 8.

---

### Task 8: Drop the captions-only paths

**Files:**
- Modify: `backend/pipeline/words.py` (remove `spread_words`, `extract_audio_span`, the Groq branch; simplify `clip_words`)
- Modify: `backend/pipeline/clipprep.py:36-68` (drop `transcript_source`, `audio_path`, `groq_key`, `prompt` parameters)
- Modify: `tests/test_words.py`
- Test: `tests/test_words.py`, `tests/test_clipprep.py`

**Interfaces:**
- Produces: `words.clip_words(segments: list[TranscriptSegment], clip_start: float, clip_end: float, emphasis: list[str]) -> list[Word]`; `clipprep.prepare_clip(*, job_id, idx, clip, video_path, video_duration, segments, clips_dir, models_dir, on_step) -> PreparedClip` (spec `wordsApprox` is always `False`).

- [ ] **Step 1: Update `tests/test_words.py`**

Delete `test_spread_words_even_split_and_clamp`, `test_clip_words_calls_groq_for_caption_source`, `test_clip_words_falls_back_to_even_spread` and `test_clip_words_without_key_is_approx`. Replace `test_clip_words_uses_transcript_words_for_whisper_sources` with:

```python
def test_clip_words_slices_and_marks_emphasis():
    segs = [Seg(10.1, 10.4, "hey"), Seg(10.4, 10.9, "world")]
    out = words_mod.clip_words(segs, 10.0, 20.0, ["world"])
    assert [(w.text, w.start, w.emphasis) for w in out] == [("hey", 0.1, False), ("world", 0.4, True)]
```

- [ ] **Step 2: Run to confirm failure**

Run: `./.venv/Scripts/python -m pytest tests/test_words.py -q`
Expected: FAIL (import error on `_transcribe_chunk_groq`, then signature mismatch).

- [ ] **Step 3: Rewrite `backend/pipeline/words.py`**

```python
"""Word-level timings for one clip, relative to the clip's start.

Every transcript is word-level now (see transcript.py), so a clip's words
are sliced straight from it.
"""
from __future__ import annotations

import re

from ..spec import Word
from .transcript import TranscriptSegment

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


def mark_emphasis(words: list[Word], keywords: list[str]) -> list[Word]:
    targets = {_norm(tok) for kw in keywords for tok in kw.split()} - {""}
    return [w.model_copy(update={"emphasis": _norm(w.text) in targets}) for w in words]


def clip_words(
    segments: list[TranscriptSegment], clip_start: float, clip_end: float, emphasis: list[str]
) -> list[Word]:
    return mark_emphasis(words_from_segments(segments, clip_start, clip_end), emphasis)
```

- [ ] **Step 4: Update `backend/pipeline/clipprep.py`**

In `prepare_clip`, remove the `transcript_source: str`, `audio_path: str`, `groq_key: str | None` and `prompt: str | None` parameters. Replace the "timing captions" block with:

```python
    on_step("timing captions")
    clip_word_list = words.clip_words(segments, clip.start, clip.end, clip.emphasis)
```

In the `ClipSpec(...)` call, change `wordsApprox=approx,` to `wordsApprox=False,`.

Then run `grep -n "prepare_clip\|transcript_source\|groq_key\|prompt" tests/test_clipprep.py` and remove those four keyword arguments from every `prepare_clip(...)` call in that test file.

- [ ] **Step 5: Run the tests**

Run: `./.venv/Scripts/python -m pytest tests/test_words.py tests/test_clipprep.py tests/test_transcript.py -q` → all pass. The API tests still fail on `main.py` until Task 9.

- [ ] **Step 6: Commit Tasks 7 and 8 together**

```bash
git add backend/pipeline/transcript.py backend/pipeline/words.py backend/pipeline/clipprep.py tests/test_transcript.py tests/test_words.py tests/test_clipprep.py
git commit -m "Orchestrate transcription through the new pipeline and drop captions paths

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: API and job wiring

**Files:**
- Modify: `backend/main.py` (`GenerateRequest` ~line 60, `Job` ~line 67, `_persist_job` ~line 106, `_run_pipeline` ~lines 257–346, `generate` ~line 359, `status` ~lines 369–412)
- Modify: `backend/projects.py` (`from_job`, `from_row`)
- Modify: `tests/test_validation.py:42-44`, `tests/test_jobs_api.py`
- Test: `tests/test_validation.py`, `tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `transcript.transcribe`, `transcript.to_word_segments`, `transcript.NoSpeechError`, `db.save_transcript` (Tasks 1 and 7), `clipprep.prepare_clip` (Task 8 signature).
- Produces: `POST /api/generate` body `{url: str, language: "hinglish" | "english" = "hinglish"}`; status and project JSON gain `language` and `languageNote`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_validation.py`, replace `test_generate_rejects_unknown_whisper_model` with:

```python
def test_generate_rejects_unknown_language():
    r = client.post("/api/generate", json={"url": "https://youtu.be/x", "language": "french"})
    assert r.status_code == 422


def test_generate_accepts_language_and_defaults_to_hinglish(monkeypatch):
    started = []
    monkeypatch.setattr(main.threading, "Thread", lambda target, args, daemon: type(
        "T", (), {"start": lambda self: started.append(args[0])})())
    client.post("/api/generate", json={"url": "https://youtu.be/x"})
    client.post("/api/generate", json={"url": "https://youtu.be/y", "language": "english"})
    assert [j.language_requested for j in started] == ["hinglish", "english"]
    for j in started:
        main.JOBS.pop(j.id, None)
```

Add `from backend import main` at the top of `tests/test_validation.py` if it isn't imported yet.

Append to `tests/test_jobs_api.py`:

```python
def test_status_includes_language_note_from_memory():
    main.JOBS["feed00000004"] = main.Job(
        id="feed00000004", url="https://youtu.be/_aw32rFL680", status="done", team_id=TEST_TEAM_ID,
        language_used="english", language_note="Detected English audio. Captions will be in English.",
    )
    try:
        body = client.get("/api/status/feed00000004").json()
        assert body["language"] == "english"
        assert body["languageNote"].startswith("Detected English")
    finally:
        main.JOBS.pop("feed00000004", None)


def test_status_fallback_includes_language(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _row(language_used="hinglish", language_note=None))
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [])
    body = client.get("/api/status/feed00000001").json()
    assert body["language"] == "hinglish" and body["languageNote"] is None


def test_project_list_includes_language(monkeypatch):
    monkeypatch.setattr(main.db, "list_jobs", lambda team_id, limit=20: [_row(language_used="english")])
    monkeypatch.setattr(main.db, "count_clips_by_job", lambda ids: {})
    assert client.get("/api/jobs").json()[0]["language"] == "english"
```

- [ ] **Step 2: Run to confirm failure**

Run: `./.venv/Scripts/python -m pytest tests/test_validation.py tests/test_jobs_api.py -q`
Expected: FAIL (import errors from `main.py` referencing removed transcript functions, then missing fields).

- [ ] **Step 3: Edit `backend/main.py`**

`GenerateRequest`: replace the `whisper_model` field and its comment with:

```python
    language: Literal["hinglish", "english"] = "hinglish"
```

`Job`: add after `created_by`:

```python
    language_requested: str = "hinglish"
    language_used: str | None = None
    language_note: str | None = None
```

`_persist_job`: change the signature to `def _persist_job(job: Job, *, throttle: bool = False) -> None:`. In `row`, replace `"whisper_model": whisper_model,` with:

```python
        "language_requested": job.language_requested,
        "language_used": job.language_used,
        "language_note": job.language_note,
```

In the whole file, replace every `_persist_job(job, whisper_model, throttle=True)` with `_persist_job(job, throttle=True)` and every `_persist_job(job, whisper_model)` with `_persist_job(job)`.

`_run_pipeline`: change the signature to `def _run_pipeline(job: Job) -> None:`. Replace everything from `job.progress = {"stage": "transcribing", "percent": 0, "note": "loading model…"}` through the `for i, c in enumerate(clips):` loop's `prepare_clip(...)` call with:

```python
        def on_transcribe_progress(part: int, total: int, latest_text: str) -> None:
            job.progress = {
                "stage": "transcribing",
                "percent": (part / total * 100.0) if total else None,
                "note": f"part {part} of {total}",
                "chunk": part,
                "totalChunks": total,
                "latestText": latest_text[:160],
            }
            _persist_job(job, throttle=True)

        job.progress = {"stage": "transcribing", "percent": 0, "note": "checking language…"}
        _persist_job(job)
        tr = transcript.transcribe(meta.audio_path, job.language_requested, on_progress=on_transcribe_progress)
        job.language_used, job.language_note = tr.language, tr.note
        job.transcript_source = tr.source
        _persist_job(job)
        db.save_transcript(job.id, tr.language, tr.source, [s.to_dict() for s in tr.segments])
        word_segments = transcript.to_word_segments(tr)

        job.status = "analyzing"
        job.progress = {"stage": "analyzing", "percent": None, "note": "scoring highlights…"}
        _persist_job(job)
        clips = highlight.detect_highlights(word_segments)

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
```

(The existing lines after `prepare_clip(...)`, `record = _clip_record(...)` onwards, stay as they are. The old `groq_key`/`prompt`/captions block and the old `on_transcribe_progress` are removed by this replacement. Remove the now-unused `import os` only if nothing else in `main.py` uses `os`; check with `grep -n "os\." backend/main.py`.)

`generate`: create the job with the language and start the thread without a model:

```python
    job = Job(id=job_id, url=req.url, team_id=member.team_id, created_by=member.user_id,
              language_requested=req.language)
    JOBS[job_id] = job
    t = threading.Thread(target=_run_pipeline, args=(job,), daemon=True)
```

`status`: in the in-memory return dict add

```python
            "language": job.language_used,
            "languageNote": job.language_note,
```

and in the Supabase fallback return dict add

```python
        "language": row.get("language_used"),
        "languageNote": row.get("language_note"),
```

- [ ] **Step 4: Edit `backend/projects.py`**

In the dict returned by `from_job`, add `"language": job.language_used, "languageNote": job.language_note,`. In the dict returned by `from_row`, add `"language": row.get("language_used"), "languageNote": row.get("language_note"),`.

- [ ] **Step 5: Run the tests**

Run: `./.venv/Scripts/python -m pytest -q` → the whole suite passes. Then `grep -rn "whisper_model\|get_transcript(\|_detect_needs\|fetch_captions" backend tests` must print nothing except `db.get_transcript` definitions and uses.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/projects.py tests/test_validation.py tests/test_jobs_api.py
git commit -m "Take a spoken language per job and store its transcript

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Frontend picker and language note

**Files:**
- Modify: `frontend/src/services/highlyteApi.js:30-32`
- Modify: `frontend/src/stores/jobStore.js:40-42`
- Modify: `frontend/src/components/TopBar.vue` (template around the URL input, script, styles)
- Modify: `frontend/src/views/JobView.vue` (under `ProcessingSteps`)

**Interfaces:**
- Consumes: `POST /api/generate {url, language}`, status `languageNote` (Task 9).

- [ ] **Step 1: API and store**

`highlyteApi.js`:

```js
export function createJob(url, language = 'hinglish') {
  return api.post('/api/generate', { url, language }).then(r => r.data)
}
```

`jobStore.js`, in `submitUrl`:

```js
    async submitUrl(url, language = 'hinglish') {
      this.error = null
      const { job_id } = await createJob(url, language)
```

- [ ] **Step 2: Picker in `TopBar.vue`**

Insert right after the `<input ... />` element:

```html
      <div class="lang" role="group" aria-label="Spoken language">
        <button
          v-for="opt in LANGUAGES"
          :key="opt.value"
          type="button"
          class="lang-opt"
          :class="{ 'lang-active': language === opt.value }"
          :aria-pressed="language === opt.value"
          @click="language = opt.value"
        >{{ opt.label }}</button>
      </div>
```

In `<script setup>`, after `const url = ref('')`:

```js
// The language spoken in the video; the server checks it against the audio.
const LANGUAGES = [
  { value: 'hinglish', label: 'Hinglish' },
  { value: 'english', label: 'English' },
]
const language = ref('hinglish')
```

In `onGenerate`, change `jobStore.submitUrl(url.value)` to `jobStore.submitUrl(url.value, language.value)`.

Add to `<style scoped>` before `.generate {`:

```css
.lang { display: flex; flex-shrink: 0; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.lang-opt { border: 0; background: transparent; padding: 6px 10px; font-size: 12.5px; font-weight: 600; color: var(--ink-soft); cursor: pointer; }
.lang-opt + .lang-opt { border-left: 1px solid var(--border); }
.lang-active { background: var(--accent-soft); color: var(--accent-text); }
```

- [ ] **Step 3: Note in `JobView.vue`**

After the `<ProcessingSteps ... />` line add:

```html
    <p v-if="jobStore.job?.languageNote" class="lang-note">{{ jobStore.job.languageNote }}</p>
```

and to its `<style scoped>`:

```css
.lang-note { margin: 12px 0 0; font-size: 13px; color: var(--ink-soft); }
```

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 5: Check in the browser**

Start the backend (`./.venv/Scripts/python -m uvicorn backend.main:app --port 8000`) and the frontend dev server via the preview tools. Log in, confirm the Hinglish/English control appears next to the link box, that the selection toggles, and that submitting sends `language` (check the network request). Take a screenshot.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/services/highlyteApi.js frontend/src/stores/jobStore.js frontend/src/components/TopBar.vue frontend/src/views/JobView.vue
git commit -m "Add the spoken-language picker and detection note

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: README and end-to-end check

**Files:**
- Modify: `README.md` (the "Roman Urdu/Hindi transcription" and "How it works" sections)

- [ ] **Step 1: Update the README**

Replace the "Roman Urdu/Hindi transcription" section body with:

```markdown
Every job asks for the spoken language: **Hinglish** (default) or
**English**. Three short samples are checked with Whisper first; clear
English audio switches to English captions and clear Hindi/Urdu speech
switches to Hinglish, and the job page says so when that happens.

Transcription (`backend/pipeline/transcript.py`) normalises the audio,
splits it into chunks of at most two minutes at silences (Silero VAD
bundled with faster-whisper), and runs Whisper with `language="en"` on
each chunk: Groq when `GROQ_KEY` is set, local faster-whisper otherwise or
when Groq fails. Hinglish chunks get a Roman Urdu/Hindi seed prompt so
Whisper writes Roman letters instead of switching script or translating.
A glossary (`backend/pipeline/data/glossary.json`) and a house spelling
list (`spelling.json`) are then applied in code; both are plain JSON and
can grow without code changes. The transcript is stored in the
`transcripts` table.

Hindi mode plus transliteration was tested and rejected; see "Spike
results" in `docs/superpowers/specs/2026-09-25-hinglish-v1-roadmap.md`.
```

In "How it works", replace step 2 with:

```markdown
2. **Transcript** — language check, VAD chunks, Whisper (Groq, else local
   faster-whisper), then glossary and spelling fixes in code.
```

- [ ] **Step 2: End-to-end run on real audio**

With the backend running locally (home connection, `GROQ_KEY` set in `.env`, Supabase configured), submit `https://www.youtube.com/watch?v=PCcoly7EHgU` as Hinglish. Confirm:
- the job reaches `done` and produces clips;
- the status progress showed "part N of M";
- the `transcripts` row exists (Supabase table editor) with `language = hinglish` and segments containing `raw`, `hinglish` and `words`.

Apply the migration first if it isn't applied yet: `npx supabase db push --db-url "$DBURL"` (the user sets `DBURL` themselves; never ask for or print the password).

- [ ] **Step 3: Full test run and commit**

Run: `./.venv/Scripts/python -m pytest -q` → all pass.

```bash
git add README.md
git commit -m "Document the language choice and new transcription pipeline

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Spec coverage check

| Spec item | Task |
|---|---|
| `en` + seed prompt, no prompt on English | 7 |
| Groq `whisper-large-v3` / turbo | 3, 7 |
| YouTube captions dropped | 7, 8, 9 |
| VAD chunks ≤120s cut in silence | 2 |
| Language check, three samples, Groq with local fallback, rule and note | 6, 7 |
| Glossary, spelling list, no English keys, `classify` | 5 |
| LLM cleanup not built | — (deferred to Step 6) |
| `whisper_model` removed | 9, 10 |
| Data contract | 4 |
| Migration, `save_transcript`/`get_transcript`, save failure fails the job | 1, 9 |
| API `language`, status and project fields | 9 |
| Picker, note, "part N of M" | 9, 10 |
| Adapter feeds the current scorer | 7 |
| Errors: rate-limit retry, fallback, no speech | 3, 7 |

Deviation from the spec, noted for the reviewer: a single long unbroken stretch of speech is split by Silero's own `max_speech_duration_s` (it cuts at the last silence it saw) rather than at "its quietest point"; the effect is the same and needs no extra code. The picker sits next to the link box in the top bar, which is where the link box actually lives, not on the Home page.
