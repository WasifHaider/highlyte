# Shot-Aware Layout (split screen that follows camera cuts)

Date: 2026-09-26
Status: Approved by delegation ("you decide") — user to review after build

## Problem

Podcasts cut between a wide two-person shot and single-person close-ups.
The reframe analysis treats a clip as one continuous shot:

- Face tracks are matched only by horizontal position, so a track carries
  on across a camera cut and ends up describing a different person
  (seen on job 9f63335a3729: clip 0's face 0 drifts from x=0.29 to 0.54
  after the cut at ~18 s; clip 1 merges faces across cuts at 2.4 s and
  16.4 s).
- Split picks its two faces once, at the clip start. After a cut to a
  close-up the right-hand face disappears and the bottom panel keeps
  cropping where it last was, showing an empty or half-cut frame.
- The automatic layout is decided for the whole clip.

What the user wants: split **only while the frame is a wide shot with two
people — left person on top, right person below** — and one person
full-frame otherwise.

## Measurement

Sampled at 5 fps on the cached 74-minute episode, 32×18 grayscale
thumbnails, mean absolute difference between consecutive samples:
normal motion median 0.004–0.008, p95 ≈ 0.022; the three real cuts
0.17–0.29. A threshold of **0.08** separates them with wide margin.

## Decisions

| Topic | Decision |
|---|---|
| Cut detection | During the existing 5 fps face sampling, store a 32×18 grayscale thumbnail per sample; a cut is a sample whose mean absolute difference from the previous one exceeds `CUT_THRESHOLD = 0.08`. No extra video decode. |
| Shots | Consecutive samples between cuts. Shots shorter than 0.6 s (3 samples) are merged into the previous shot (flash frames, transitions). |
| Face tracks | Built **per shot**: tracking never continues across a cut. Track ids stay unique across the clip. Existing per-shot rules apply (presence ≥ 10 % of the shot's samples, at most 4 tracks, smoothing, dead zone). |
| Shot kind | `two`: at least two tracks each present in ≥ 50 % of the shot's samples → the two most present, ordered **left to right** by median x. `one`: one such track (or only one track at all) → that face. `none`: no track → fit. |
| Speaker timeline | Unchanged in shape; computed per shot over that shot's faces and concatenated. |
| Auto layout | `split` when two-person shots cover ≥ 50 % of the clip; else `speaker` when the talker changes inside at least one two-person shot (whole-clip turn counts are inflated by cuts); else `follow`; `fit` rules unchanged. |
| Renderer | Each frame looks up the active shot. **split**: two-person shot → left face top panel, right face bottom panel; one-person shot → that face full-frame; no face → fit. **follow**: the active shot's main face. **speaker**: the timeline's face if it is in the active shot, else the shot's main face. **fit**: unchanged. |
| Old clips | `shots` defaults to `[]`; a spec without shots renders exactly as today. Re-running a video produces the new data. |
| Captions in split | Unchanged: split's default caption position stays "middle" (the seam). During a one-person shot captions stay where the style puts them. |

## Data contract

`Reframe` gains one field (Pydantic and zod, default empty list):

```json
"shots": [
  {"start": 0.0, "end": 18.4, "kind": "two", "faceIds": [2, 1]},
  {"start": 18.4, "end": 34.6, "kind": "one", "faceIds": [0]}
]
```

`start`/`end` are clip-relative seconds (same timeline as face tracks);
`faceIds` refer to `faces[].id`, ordered left to right for `two`. The last
shot's `end` is the last sample time; the renderer treats the last shot
as open-ended.

## Units

- `backend/pipeline/face_detect.py`: `sample_detections` also returns one
  thumbnail per sample (`np.ndarray` 18×32 float32 0–1).
- `backend/pipeline/shots.py` (new, pure): `cut_times(thumbs, times) ->
  list[float]`, `split_shots(times, cuts, min_len_s=0.6) ->
  list[tuple[int, int]]` (sample index ranges).
- `backend/pipeline/reframe.py`: `analyze(frames, times, cuts=None)`
  builds tracks and timelines per shot, classifies shots, chooses auto.
  `cuts=None` keeps today's single-shot behaviour for callers and tests.
- `backend/spec.py` + `renderer/src/schema.ts`: `Shot` model, `shots`
  field with default `[]`; fixture regenerated with a two-shot example.
- `backend/pipeline/clipprep.py`: pass thumbnails through `shots.cut_times`
  into `reframe.analyze`, re-based to the clip start like the face samples.
- `renderer/src/lib/shots.ts` (new): `activeShot(shots, t)`.
- `renderer/src/layouts/LayoutView.tsx`: per-frame layout from the active
  shot as in the table above.

## Testing

- Python: cut detection on synthetic thumbnails (static, noisy motion, one
  hard cut); shot splitting incl. merging a too-short shot; per-shot
  tracks never cross a cut; shot kinds and left-to-right ordering; auto
  layout rule; `analyze` without cuts equals today's behaviour; spec
  round-trip with and without `shots`.
- Renderer (vitest): `activeShot` boundaries; schema accepts specs with
  and without `shots`; fixture parses.
- Frontend build succeeds (the preview imports the renderer directly).
- Real-footage check: run analysis on job 9f63335a3729's clip 0 source
  span from the cached video and confirm a `two` shot then a `one` shot
  split near 18 s.

## Deploy note

Lambda renders use the deployed Remotion site, so `npm run deploy:site`
in `renderer/` must be re-run before exports use the new layout (the
in-browser preview picks it up immediately).

## Out of scope

Speaker diarization, more than two people in split, animated transitions
between layouts, re-analysing existing clips automatically.
