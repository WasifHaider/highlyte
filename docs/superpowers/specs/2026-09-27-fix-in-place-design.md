# Piece 3a: fix in place (design)

Roadmap Step 4, first half. Piece 3 was split in two: 3a (this spec) is
fixing clips in place; 3b (video upload) gets its own spec later. The user
approved sections 1 and 2 below in brainstorming and asked the agent to
decide sections 3 and 4 and go straight to the plan.

## Decisions

| Question | Decision |
|---|---|
| Split piece 3 | 3a fix-in-place now; 3b upload later, separately |
| How far a nudge reaches | Cut a wider window up front (8 s spare each side); nudges inside it are instant, no re-cut |
| "Regenerate" | Two separate actions: **Swap scene** (best saved runner-up, no LLM tokens) and **Regenerate** (re-rank the few minutes around this clip, ~one small Groq call). Plus **Reset** for nudges. |
| Caption presets | Unchanged (karaoke, pop, clean). New presets come after everything else. |
| Caption storage once bounds move | Spec v2: words and face data cover the whole cut window, times from the file start; the renderer shows only what lies between `start` and `end` |

Out of scope: video upload (3b), new caption presets, dragging word
timings, the UI redesign (it restyles these controls later).

## 1. Clip spec v2 and data

- `ClipSpec.version` becomes `2`. `start`/`end` stay positions inside the
  cut file. In v2, `words`, face `track` points, `speakerTimeline` and
  `shots` cover the whole cut file with times from the file start (v1:
  only the clip, times from the clip start). `source` gains `duration`
  (seconds of the cut file; optional, v2 only).
- One renderer path: `toClipTime(spec)` converts a v2 spec to clip time
  (subtract `start` from every time, keep only words that overlap the clip)
  and passes v1 specs through unchanged. Everything downstream of it keeps
  working in clip time as today.
- `SEGMENT_PAD_S` goes from 1 s to 8 s. Clip prep keeps words and face
  analysis for the whole cut file. `face_at_start` still checks the clip's
  own first second.
- Old v1 clips keep previewing and exporting as before, but cannot be
  nudged: their words are timed from the clip start and their real file
  length is not stored, so moving a v1 clip's start would misalign its
  captions. The Trim row says "Re-run the video to trim this clip." (This
  replaces the earlier "nudge within the 1 s margin" idea: that margin
  bought almost nothing for the extra conversion code.)
- New columns: `clips.bounds_original jsonb` (saved on the first nudge),
  `clips.reason text`, `clips.pending_action text` (`swap` or
  `regenerate` while running), `clips.action_error text`,
  `clips.revision int` (bumped when a clip is swapped or regenerated, so
  the browser reloads the replaced clip file at the same URL),
  `jobs.alternates jsonb`.
- Selection: `Clip` gains `reason`; `select()` also returns up to 10
  runner-ups (candidates that passed the structural checks but were not
  kept), best first, as `{start, end, text, score, tag, flags, reason,
  emphasis}` in source seconds. Stored in `jobs.alternates`.

## 2. Nudge, previous/next sentence, reset

- Shared TypeScript rules in `renderer/src/lib/trim.ts`:
  `nudge(spec, edge, deltaS)` (±0.5 s), `prevSentence` / `nextSentence`
  for either edge (sentences end on `. ? !`; cuts 0.22 s before the first
  word and 0.4 s after the last, never into a neighbouring word, like
  `snap.py`). Results are clamped to `[0, fileDuration]` and 8–60 s. A move
  that is not possible returns the clip unchanged with a reason.
- `PATCH /api/clips/{id}/bounds {start, end}`: team check; finite numbers;
  `0 ≤ start < end ≤ fileDuration`; 8–60 s. Saves `bounds_original` on the
  first nudge, updates `spec.start/end` and the clip record's source-time
  `start/end`. The render cache key includes the bounds; a queued render
  fails if bounds or captions changed underneath it.
  `POST /api/clips/{id}/bounds/reset` restores `bounds_original`.
- UI: a Trim row on the clip card (earlier/later sentence for each edge,
  ±0.5 s, current length, Reset). The preview updates instantly; saves are
  debounced like style changes.

## 3. Swap scene and Regenerate

- Both run in a background thread per clip. `clips.pending_action` is set
  while running; the status endpoint returns it; the frontend polls while
  any clip is pending and disables that clip's controls. A failure clears
  `pending_action` and sets `action_error` (shown on the card); the clip is
  left unchanged.
- **Swap scene** `POST /api/clips/{id}/swap`: takes the best alternate from
  `jobs.alternates` that overlaps every other clip of the job by less than
  30 %, removes it from the list, and prepares it as this clip (same index,
  same clip id, same style). No LLM call. With no usable alternate: 409
  "No other moments left to swap in."
- **Regenerate** `POST /api/clips/{id}/regenerate`: loads the stored
  transcript, takes the thought units within 120 s either side of the clip,
  runs the ranker on them (usually one small call), then the same snap,
  reject and score steps as selection. Picks the best candidate that
  overlaps other clips by less than 30 % and is not the same moment
  (overlap with the current clip under 90 %). None: "No better take found
  around this moment." Needs `GROQ_KEY`; rate limits give readable errors.
- Preparing a new clip needs the source video: `ingest.ingest` from the
  cache, downloading again if it is gone (on EC2 this fails until the
  Tailscale route exists; the error says so plainly).
- A swapped or regenerated clip resets caption edits and bounds
  (`words_original` and `bounds_original` cleared) and gets fresh
  `reason`/`qa_flags`; its style is kept.
- **Reset** (bounds) is section 2's reset.

## 4. SRT, grid card, testing

- **SRT**: `backend/srt.py` builds SubRip text from the clip's words in
  clip time using the same pagination as the caption editor lines
  (`renderer/src/captions/paginate.ts` with the editor's 14-word / 84-char
  limits), ported to Python. A shared fixture
  (`renderer/src/__fixtures__/paginate-cases.json`) is checked by both the
  TS and the Python tests so the two cannot drift.
  `GET /api/clips/{id}/captions.srt` downloads one; the renders zip adds
  `highlyte-<clipId>.srt` beside each mp4.
- **Grid card**: shows the first caption line (in clip time) and the
  stored `reason` under the time range.
- **Testing**: unit tests for `toClipTime`, `trim.ts`, `srt.py` (plus the
  shared fixture), selection alternates, the bounds endpoints (limits,
  first-nudge original, reset, render invalidation), swap and regenerate
  (fakes for the ranker and clip prep; overlap rules; failure paths;
  pending state), clip prep's v2 output, and the status fields. Frontend:
  `npm run build`.
- **Deploy**: the renderer changes need `npm run deploy:site` before Lambda
  exports can draw v2 specs; a new migration must be applied first.
