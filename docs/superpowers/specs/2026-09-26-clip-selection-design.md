# Piece 2: clip selection (design)

Roadmap Step 3. Replaces the span selection in `backend/pipeline/highlight.py`.
Goal: 5–8 clips per video that start and end cleanly, chosen by an LLM that picks
utterance ids only, with every cut point placed by code. Must fit the Groq free
tier and must fail visibly, never silently.

## Decisions made during brainstorming

| Question | Decision |
|---|---|
| Face term in the score | Dropped from ranking. Face detection still runs per clip in `clipprep` after selection; no face in the first 1 s adds a `no_face_start` QA flag, never a reject. |
| Ranker cannot run (no key, daily limit, every call failed) | Job ends in a new `selection_failed` state with a clear message; the transcript is kept; a **Retry selection** button re-runs only selection + clip prep. Partial failure keeps the clips from the calls that worked and notes the skipped time ranges. No heuristic fallback. |
| Hook title, emphasis words, tag | A second small LLM call over the final clips only. If it fails, clips ship without titles, with code-picked emphasis and a heuristic tag; the job never fails because of it. |
| Fewer than 5 clips pass | Fill up to 5 with near-misses that failed only the score thresholds, flagged `weak_pick`. Structural rejects never relax. |
| Approach | Windowed ranker over utterances, with thought units marked in the prompt; code widens every pick to whole thought units. |

## Constraints

- Groq free tier for `openai/gpt-oss-20b`: **8k tokens/minute, 200k tokens/day,
  30 requests/minute, 1k requests/day** (console.groq.com/docs/rate-limits,
  checked 2026-09-26). Every call must stay near 6k tokens including reasoning.
- Budget target for a 74-minute podcast: about 5 ranker calls (~6k each) plus one
  titles call (~3k), about 31k tokens against 47k for the old scorer. At 8k
  tokens/minute this is about 4–5 minutes of selection for that video.
- Speaker is always `"A"` (no diarization in v1), so the speaker-change rule is
  written but inert.
- Existing segments (`backend/pipeline/segments.py`) already split on pauses
  ≥ 350 ms and on `. ? !`, but also cap at 15 s, which can split mid-sentence.

## 1. Modules and data flow

New files in `backend/pipeline/`. All except `groq_llm.py` and the calls inside
`ranker.py` / `titles.py` are pure code with no network.

| File | Responsibility |
|---|---|
| `utterances.py` | `Segment`s → utterances → thought units |
| `ranker.py` | Windowing, prompt, parsing and validating picks; returns picks and skipped time ranges |
| `groq_llm.py` | Shared Groq client: pacing against the per-minute token limit using Groq's rate-limit response headers; rate-limit error parsing ("try again in N min"). Takes over `_is_rate_limit` and `_wait_label` from `highlight.py` |
| `snap.py` | Word-level start and end cut points; first-line and last-line filler rules |
| `scoring.py` | Energy, duration fit, weighted score, hard rejects, near-miss fill, packing |
| `titles.py` | Second call for `hook_title`, `emphasis`, `tag`, with fallback |
| `selection.py` | Orchestrates the above: `select(segments, loudness) -> Selection(clips, notes)`; raises `SelectionFailed` |

`highlight.py` is deleted. `Clip` moves to `selection.py` and gains `flags:
list[str]` and its score parts (`standalone`, `hook`, `payoff`, `energy`,
`duration_fit`, `total`). `clipprep` keeps reading `start`, `end`, `score`,
`tag`, `hook_title`, `emphasis`.

```
transcribe ──> Segments (words keep kind + prob) ──> transcripts.segments
          └──> loudness: one dB value per 0.5 s  ──> transcripts.loudness (new)
select(segments, loudness)
  utterances ─> thought units ─> ranker windows (paced) ─> picks
  ─> widen to thought units ─> snap cut points ─> hard rejects
  ─> score ─> pack (<30% overlap, max 8, near-miss fill to 5)
  ─> titles call ─> Clips with flags
clipprep (face check) ─> may add no_face_start
```

- Selection takes the full `Segment` objects, not `to_word_segments` output,
  because it needs each word's `kind` and `prob`.
- Loudness is computed inside `transcript.transcribe` from the 16 kHz samples
  already in memory (RMS per 0.5 s, in dB, rounded to 0.1). Stored, so a retry
  needs no audio. Old transcripts have no loudness: energy is 0.5 for them.

## 2. Utterances, thought units, ranker

### Utterances
- Flatten all segment words, keeping `t`, `kind`, `prob`, `start`, `end`.
- New utterance before a word when the pause before it is ≥ 350 ms, the
  previous word ends in `. ? !`, or the speaker changes.
- Safety cap: an utterance over 20 s with no break is split at its longest
  internal gap.
- Fields: `id` (`u1`…`uN`), `start`, `end`, `words`, `text` (the `hinglish`
  form), `confidence` (mean word `prob`), `ends_sentence`.

### Thought units
Greedy grouping. The next utterance joins the current unit if any holds:
- the gap before it is < 800 ms;
- the previous utterance ends with `?` (an answer follows);
- the previous utterance ends on a hanging word: `lekin kyunki aur toh but
  because and so`;
- the next utterance starts with a continuation word: `kyunki lekin matlab
  yaani isliye because but so`.

The last three may bridge a long pause only if it is ≤ 2 s, and together they
may pull in at most 12 s of extra speech. The unit always closes on a closing
phrase (`chalo next`, `chalo aage`, `moving on`, `next question`) or when adding
the next utterance would take it past 45 s. A pause ≥ 800 ms with no connector
word is the stand-in for a topic shift; no semantic topic detection.

### Windows
- One line per utterance, `u123: text`, blank line between thought units, no
  timestamps.
- About 4.5k input tokens per window (estimate: characters ÷ 3.2); windows break
  only between thought units.
- Consecutive windows overlap by the last ~60 s of thought units.

### Prompt and output
Up to 6 picks per window, JSON array only:
```json
[{"s":"u12","e":"u19","standalone":0.8,"hook":0.7,"payoff":0.6,
  "starts_mid":false,"ends_mid":false,"reason":"<=12 words"}]
```
The prompt states: prefer 12–35 s; never start on toh / matlab / uh / so / like
/ um; never end on lekin / kyunki / aur / but / because; each pick must make
sense to someone who has seen nothing else of the podcast. `max_tokens` 1500,
`reasoning_effort: "low"` via `extra_body`.

### Validation
- Ids must exist and lie inside the window; `s > e` is swapped; anything else
  invalid is dropped.
- `starts_mid` or `ends_mid` true → rejected.
- Scores are clamped to 0–1; missing scores → pick dropped.
- Survivors are widened to whole thought units. Duplicate picks from overlapping
  windows are removed in packing.

### Pacing and failure (`groq_llm.py`)
- Before each call, compare the call's estimated tokens with the last response's
  `x-ratelimit-remaining-tokens` / `x-ratelimit-reset-tokens` headers (read via
  `with_raw_response`) and sleep until there is room.
- Cut-off (`finish_reason == "length"`) or unreadable answer: retry that window
  once, then skip it.
- Per-minute 429: wait for the reset time, retry.
- Daily-limit 429: stop all remaining windows (spend nothing more), mark them
  skipped with the "try again in N min" wording.
- Some windows skipped: keep the rest; `selection_note` lists the skipped time
  ranges, e.g. "Skipped 12:30–18:40 (rate limit). Some moments may be missing."
- Every window skipped, or no `GROQ_KEY`: raise `SelectionFailed` with a message
  the UI shows as is.

## 3. Cut points, filler rules, scoring, packing, titles

### Cut points (`snap.py`)
From the widened pick's first word `w0` and last word `wN`. The LLM sends no
timestamps and none are read.
- **Start.** If the gap before `w0` is < 300 ms, move back over earlier words to
  the previous gap ≥ 300 ms, only if that gap is at most 3 s back; otherwise keep
  `w0`. Then `cut = max(w0.start − 0.22, prev_word.end + 0.03, 0)`.
- **End.** If the gap after `wN` is < 300 ms, move forward to the next gap
  ≥ 300 ms if it is at most 3 s away; otherwise reject as a hanging end. Then
  `cut = min(wN.end + 0.40, next_word.start − 0.05)`.

### Filler rules
- **First line.** Remove leading filler words (uh, um, hmm, toh, matlab, acha,
  haan, so, like, basically, "you know", "I mean", "okay so") by moving the start
  to the first real word, only if the clip stays ≥ 8 s. If it still starts on
  filler, reject.
- **Last line.** If the last word is hanging (lekin, kyunki, aur, toh, ki, but,
  because, and, so), trim back to the last sentence end inside the clip; if that
  leaves < 8 s, reject. Trailing uh/um is stripped; tags such as "hai na" and
  "yaar" stay.
- Start/end cuts are recomputed after any trim.

### Score
`total = 0.40·standalone + 0.25·hook + 0.15·payoff + 0.10·energy + 0.10·duration_fit`
- `energy`: clip mean loudness minus episode median speech loudness, mapped
  linearly from −6 dB → 0 to +6 dB → 1, clamped. 0.5 when no loudness stored.
- `duration_fit`: 1.0 for 12–35 s, linear to 0 at 8 s and at 60 s.
- `viralityScore = round(total × 10, 1)`.

### Hard rejects
- Structural, never relaxed: filler start; hanging end; < 8 s or > 60 s after
  snapping; first word more than 1.2 s after the start cut; mean word confidence
  < 0.45.
- Score thresholds, relaxable only by the near-miss fill: standalone < 0.7,
  hook < 0.55.

### Packing
1. Sort by `total`, highest first.
2. Keep a clip if its overlap with every kept clip is < 30 % of the shorter one.
3. Stop at 8.
4. If fewer than 5 kept, fill to 5 from clips that failed only the score
   thresholds with standalone ≥ 0.5 and hook ≥ 0.35, same overlap rule, flagged
   `weak_pick`.
5. Sort the final list by start time.

### QA flags
- `low_confidence` ("Low confidence — check captions"): mean word confidence
  < 0.70 or more than 15 % of words under 0.4.
- `weak_pick` ("Weaker pick"): added by the near-miss fill.
- `no_face_start` ("No face at start"): added by `clipprep`.

Thresholds are first guesses; the Step 6 eval tunes them. They live as named
constants at the top of `scoring.py`.

### Titles (`titles.py`)
- One call over the final clips: each as its id plus full text (~90 words for a
  35 s clip, ~1.5k tokens for 8 clips).
- Returns per clip: `hook_title` (≤ 8 words, the speakers' own language mix),
  `emphasis` (≤ 5 words, each checked to exist in the clip text), `tag` (one of
  the existing `TAGS`).
- On failure: no hook titles; emphasis = the 3 longest non-stopword words in the
  clip; tag from the old keyword heuristic (moved from `highlight.py`); a line
  added to `selection_note`. Never fails the job.

## 4. API, UI, migration, testing

### Job flow (`backend/main.py`)
- `_run_pipeline`: save the transcript with loudness, then
  `selection.select(...)`. On success clipprep runs as today and each clip
  record gets `qaFlags`. On `SelectionFailed`: status `selection_failed`,
  `error` = its message, transcript kept.
- New `POST /api/jobs/{id}/select`: team-checked; allowed only in
  `selection_failed`. Rebuilds the job from the DB if the server restarted,
  loads the stored transcript and loudness, calls `ingest` (cache hit by video
  id, or a fresh download if the file is gone), then runs select + clipprep in a
  thread like the main pipeline.
- Status response gains `selectionNote`; each clip gains `qaFlags`.

### Migration
`supabase/migrations/<timestamp>_clip_selection.sql`:
- `transcripts.loudness jsonb`
- `jobs.selection_note text`
- `clips.qa_flags jsonb not null default '[]'`

The plan confirms `jobs.status` is plain text (no enum change needed).

### Frontend
- Job view in `selection_failed`: the message plus a **Retry selection** button
  that calls the endpoint and resumes polling.
- `selectionNote`: one quiet line above the clip grid.
- Clip card chips for the three QA flags. Old clips have `[]` and show nothing.

### UI design (Superdesign)
The whole frontend is being redesigned to a minimal style in parallel
(Superdesign project "Highlyte minimal redesign", state in
`.superdesign/resume.json`, design system in `.superdesign/design-system.md`).
The redesigned clips page draft already includes this piece's UI: QA chips on
cards, the skipped-range note above the grid, and the retry state is planned as
a flow page. Piece 2's frontend tasks build these elements in the redesign's
style if the redesign lands first, otherwise in the current style with the same
content; the redesign itself is a separate plan.

### Old data
Old clips are untouched. Re-running an old video uses the new selection. Old
transcripts lack loudness, so their energy term is 0.5.

### Testing
- Pure unit tests with made-up word lists: utterance splits; thought-unit joins
  and closes (question, connectors, 800 ms, 2 s / 12 s limits, 45 s cap, closing
  phrase); snap maths including no-overlap clamps; filler rules; score, rejects,
  packing, near-miss fill.
- Ranker with a fake client: windowing and overlap, JSON parsing and validation,
  widening, retry-once on bad JSON, pacing with fake sleep and headers, daily
  limit stopping remaining windows, partial and total failure.
- Titles: parsing, emphasis existence check, fallback.
- One end-to-end `select()` test with a fake LLM.
- API: retry endpoint (wrong state, wrong team, happy path) and the new status
  fields.
- Dev script `scripts/select_dry_run.py <job_id|transcript.json>`: runs
  selection on a stored transcript and prints each clip's times, score parts,
  flags and text. Spends real Groq tokens.

### Out of scope
Speaker diarization, laugh/applause extension, the Step 6 eval sheet,
single-clip regeneration (piece 3), the full UI redesign (its own plan).
