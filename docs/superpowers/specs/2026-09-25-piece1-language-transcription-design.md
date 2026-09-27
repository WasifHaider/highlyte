# Piece 1: Language Choice and Transcription

Date: 2026-09-25
Status: Draft for review
Roadmap: `2026-09-25-hinglish-v1-roadmap.md`, Step 2

## Goal

Replace today's transcription step with one that produces the v1 segment
data contract: Roman captions with word timings and confidence, a
user-chosen spoken language checked by detection, a glossary and a house
spelling list applied in code, and the result stored so later pieces can
nudge and regenerate clips without transcribing again.

The current highlight scorer and clip preparation keep working unchanged
through a small adapter. Piece 2 replaces the scorer.

## Decisions

| Topic | Decision |
|---|---|
| Transcription path | Kept from today, as the spike decided: Whisper `language="en"`; Hinglish adds the Roman Hindi/Urdu seed prompt, English sends no prompt. |
| Groq model | `whisper-large-v3` for Hinglish (the model the spike validated; turbo is weaker on non-English speech). `whisper-large-v3-turbo` for English. |
| YouTube captions | **Dropped.** They have no word timings (the contract needs them), on Hindi/Urdu videos the English track is often a translation, and the captions API is IP-blocked on EC2 like yt-dlp. Every job goes through Whisper. |
| Chunking | Fixed 10-minute chunks are replaced by VAD: speech regions from faster-whisper's bundled Silero VAD, packed into chunks of at most 120s that are only ever cut in a silence, so no word is sliced and no overlap de-duplication is needed. |
| Language check | Three 20s samples (10%, 50%, 90% of the audio) sent to Groq Whisper with no language set. Groq instead of local `detect_language` (the roadmap's plan): per-chunk detection was dropped after the spike, so it is only three short calls, and it avoids loading a local model on the server. Without `GROQ_KEY`, local faster-whisper `detect_language` does the same check. |
| Language rule | All three samples English → English path. Any sample Hindi or Urdu → Hinglish path. Check failed or mixed otherwise → the user's choice. When the result differs from the choice, `language_note` says so. |
| Glossary | Roman phrase map applied in code: merges and fixes names and brands (`you tube` → `YouTube`). Plain JSON, grows per niche. |
| Spelling list | House spellings (ye, woh, toh, cheez, kuch, bohat, farq, kyunki) and Whisper chat shortcuts (bhoat → bohat, fark → farq, kia → kya, hy → hai). Plain JSON. **No key may be an English word** (a test enforces it), so `to`, `the`, `main`, `me` are never rewritten. |
| LLM cleanup | **Not built in piece 1.** The spike showed it near useless as specified. It moves to Step 6: built and measured only if the eval shows mishearing that the spelling list can't fix. |
| Model settings | The `whisper_model` request field and its frontend argument are removed. The server always uses the local `small` model as its fallback. |

## Flow

```
ingest (unchanged) ─▶ audio.normalize: 16kHz mono wav, loudnorm
  ─▶ langcheck: 3 samples ─▶ language_used (+ language_note)
  ─▶ audio.speech_chunks: VAD regions packed into ≤120s chunks
  ─▶ per chunk: AsrProvider.transcribe(wav, prompt) ─▶ words + confidence
       (Groq, retried on rate limits; local faster-whisper if Groq fails)
  ─▶ hinglish.fix: glossary, then spelling list (Hinglish path only;
       the glossary also runs on English)
  ─▶ segments.build: words ─▶ segments (contract below)
  ─▶ db.save_transcript
  ─▶ adapter ─▶ today's highlight.detect_highlights + clipprep
```

## Units

All new files are in `backend/pipeline/`.

**`audio.py`**
- `normalize(src, dst)` runs ffmpeg to produce a 16kHz mono wav with `loudnorm`.
- `speech_chunks(wav, max_s=120) -> list[Chunk]` loads audio with
  `faster_whisper.decode_audio` and finds speech with
  `faster_whisper.vad.get_speech_timestamps` (min silence 250ms, min speech
  400ms, pad 250ms). It greedily packs regions into chunks no longer than
  `max_s`, writes each chunk to a wav, and returns `Chunk(path, offset)`.
  A single region longer than `max_s` is cut at its quietest point.
- `sample(wav, at_s, dur_s, dst)` cuts a short sample for the language check.

**`langcheck.py`**
- `decide(wav, requested) -> LanguageDecision(used, note)` applies the
  language rule above. Detection goes through a `detect(sample_path) -> str`
  callable (Groq, or local when there's no key), so tests inject answers.

**`asr.py`**
- `AsrWord(text, start, end, prob)` and `AsrResult(words, language)`.
- `AsrProvider` protocol: `transcribe(wav, *, language, prompt) -> AsrResult`.
- `GroqAsr(model, key)` uses `verbose_json` with word and segment
  timestamps. Each word gets `exp(avg_logprob)` of its segment as `prob`.
- `LocalWhisperAsr(model_size)` uses faster-whisper with word timestamps,
  and `prob` is the word probability.
- `transcribe_chunks(chunks, primary, fallback, on_progress)` runs the
  retry and fallback behaviour today's `transcribe_whisper` has, and offsets
  word times by each chunk's offset.

**`hinglish.py`**
- `apply_glossary(words)` matches phrases case-insensitively. Merged words
  take the first start and last end, and multiply their probs.
- `apply_spelling(words)` maps whole words only, keeping surrounding
  punctuation and a leading capital.
- `classify(word) -> "num" | "en" | "hinglish"`. `num` means digits;
  `en` means the word is in `english_words.txt` (about 10k common words,
  generated once and checked in) and not in a short list of Roman Hindi
  words that are also English (`main`, `the`, `to`, `me`, `hi`, `par`,
  `is`); everything else is `hinglish`.
- Data files: `pipeline/data/glossary.json`, `pipeline/data/spelling.json`,
  `pipeline/data/english_words.txt`.

**`segments.py`**
- `Segment` and `SegWord` dataclasses, matching the contract.
- `build(raw_words, fixed_words, language) -> list[Segment]`. A new segment
  starts on a pause of at least 350ms, after a word ending in `.`, `?` or
  `!`, or when the segment would pass 15s. `speaker` is always `"A"` (no
  diarization in v1). `confidence` is the mean word prob.

**`transcript.py`** shrinks to orchestration: `transcribe(audio_path,
requested_language, on_progress) -> Transcript(segments, language_used,
language_note, source)`. The captions code, fixed-length splitting and the
single-sample probe are removed.

**Adapter** (in `transcript.py`): `to_word_segments(transcript) ->
list[TranscriptSegment]` gives one `TranscriptSegment` per word, using the
fixed text, with source `groq` or `whisper`. `highlight.py`, `clipprep.py`
and `words.py` then take their existing word-level branch unchanged. The
captions-only branches in `main.py` (the per-clip seed prompt probe) and
`words.py` become unreachable and are removed.

## Data contract

```json
{
  "id": "seg_0007",
  "start": 12.41,
  "end": 16.08,
  "speaker": "A",
  "language": "hi-Latn-EN",
  "raw": "hum YouTube pe ye video upload kar rahe the yar",
  "hinglish": "hum YouTube pe ye video upload kar rahe the yaar",
  "words": [{"t": "yaar", "raw": "yar", "start": 15.70, "end": 16.08, "kind": "hinglish", "prob": 0.88}],
  "confidence": 0.91
}
```

`language` is `hi-Latn-EN` on the Hinglish path and `en` on the English
path. On the English path `hinglish` equals `raw` apart from glossary fixes.

## Storage (first real migration)

`supabase/migrations/<timestamp>_transcripts_and_job_language.sql`:

```sql
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

`db.save_transcript(job_id, transcript)` and `db.get_transcript(job_id)`.
An hour of speech is roughly 1–2MB of JSON, which is fine for `jsonb`.

## API and UI

- `POST /api/generate` takes `{url, language: "hinglish" | "english"}`,
  with `hinglish` as the default. `whisper_model` is removed.
- `GET /api/status/{id}` and the project list add `language` (the one
  used) and `languageNote`.
- **Home:** a two-option control under the URL box: "Spoken language:
  **Hinglish** / English". Plain buttons, not a dropdown.
- **Status:** if `languageNote` is set, it shows under the progress steps,
  e.g. "Detected English audio. Captions will be in English."
- **Progress:** transcription progress counts VAD chunks ("part 3 of 21").

## Errors

- Groq rate limit: retry with the server's retry-after, as today. Other
  Groq errors, or retries exhausted: that chunk goes to local faster-whisper.
- Language check failure: fall back to the user's choice, with no note.
- VAD finds no speech: the job fails with "No speech found in this video."
- Transcript save failure: the job fails. Piece 3 depends on the stored
  transcript, so a job without one is not reported as done.

## Testing

pytest with no network. Groq, faster-whisper and ffmpeg are stubbed where
they're slow; `audio.py` gets one test on a generated two-tone wav.

- `langcheck`: every branch of the rule, both override directions, and
  failure falling back to the choice.
- `audio.speech_chunks`: packing never exceeds `max_s`, cuts only in
  silences, and offsets are correct.
- `asr.transcribe_chunks`: offsets, the rate-limit retry, and fallback to
  local.
- `hinglish`: glossary merges keep timings, spelling keeps punctuation and
  capitals, `classify` edge cases, and **no spelling key is an English
  word**.
- `segments.build`: split rules, ids, confidence, and the English-path
  equality.
- API: `language` is accepted and defaulted, `whisper_model` is gone, and
  status returns `languageNote`.
- The adapter output feeds `highlight.detect_highlights` without error.

## Out of scope

LLM cleanup (Step 6), utterance packing and the ranker (piece 2), nudging,
regeneration, SRT and upload (piece 3), diarization, and the YouTube block
(Tailscale, Step 5).
