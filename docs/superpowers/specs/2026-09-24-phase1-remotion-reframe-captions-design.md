# Phase 1 — Vertical Reframe + Animated Captions (Remotion on Lambda)

Date: 2026-09-24
Status: Draft for review

## Goal

Turn HighLyte's output from horizontal 16:9 audio-first clips into
OpusClip-style vertical shorts: 9:16 reframed video that follows faces,
animated word-level captions in selectable presets, and an LLM hook title
and virality score per clip. The team previews every style change live in
the browser and renders final mp4s on AWS Lambda via Remotion.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Caption/visual engine | Remotion (free license: team is 3 people or fewer) |
| Source footage | Mixed: solo, 2-person podcast, screen share. Automatic layout per clip, user can override |
| Style workflow | Live Remotion Player preview in the browser; mp4 rendered only on Export |
| Frontend | Stay on Vue; mount the Remotion Player as a React island |
| Rendering | Remotion Lambda only (AWS). No local render service |
| Caption presets | `karaoke`, `pop`, `clean` |
| Hosting | App stays on the developer PC in Phase 1; AWS deployment is the next spec |

## Out of scope

Trim/caption-text editing, brand kits, auth/workspaces, a Redis job
queue, app deployment, direct platform posting.

## Architecture

The core change: Python stops producing finished video and instead
produces a per-clip **spec** (data). Remotion draws that spec. The same
composition code runs in the browser (Player preview) and on Lambda
(final render), so preview and export are identical.

```
                ┌──────────────── Python (analysis) ────────────────┐
Vue ──► FastAPI ─► ingest ► transcript ► highlight ► words ► reframe ► segment cut ─► ClipSpec ─► Supabase
 │                                                                        │ upload       │
 │                                                                        ▼              │
 │  live preview: Remotion <Player> (React island) ◄── presigned R2 URL ◄─ R2 ◄──────────┘
 │
 └─ Export ─► FastAPI ─► remotion-lambda (Python) ─► AWS Lambda ─► S3 ─► copy to R2 ─► renders table
```

### Components

**Python backend (`backend/`) — analysis only**

- `pipeline/ingest.py` — constrain the yt-dlp format to H.264 (`avc1`) at
  1080p or lower, so segments decode in every browser and seek quickly.
- `pipeline/highlight.py` — LLM additionally returns `hook_title` (at most
  8 words), `virality_score` (0-10) and up to 5 `emphasis` keywords per
  span. Heuristic path: `hook_title = null`, `virality_score` = normalized
  heuristic score, no emphasis words.
- `pipeline/words.py` (new) — per clip, send the clip's audio span to
  Groq Whisper (`whisper-large-v3-turbo`, word timestamps, same Roman
  Urdu prompt logic as `transcript.py`) and return word timings relative
  to clip start. Needed because the YouTube-captions transcript path only
  has segment-level timing. Fallback: spread each sentence's duration
  evenly across its words and set `wordsApprox: true`.
- `pipeline/reframe.py` (new) — sample frames at 5 fps over the clip span,
  run MediaPipe face detection and face landmarks, build per-face tracks
  (normalized 0-1 coordinates), smooth them (moving average plus
  dead-zone), derive `speakerTimeline` from lip-openness variance with a
  1.5 s minimum hold, and choose the automatic layout (rules below).
  Failure: `auto = "fit"`, `faces = []`.
- `pipeline/cut.py` — reused to cut each clip's 16:9 source **segment**
  (clip span plus 1 s padding each side, H.264/AAC) for upload to R2.
  It is no longer the final output.
- `spec.py` (new) — Pydantic models for `ClipSpec` and `ClipStyle`.
- `render.py` (new) — wraps the `remotion-lambda` Python client: start a
  render, poll progress, copy the finished output S3→R2, delete the S3 object.
- `main.py` — new endpoints (below); pipeline gains the stages
  `words` → `reframe` → `uploading`; job ends at `done` with clip specs
  and **no rendered mp4**.

**`renderer/` (new Node/TypeScript package, build-time only)**

- `src/Root.tsx` — registers composition `Clip` (1080x1920, 30 fps,
  duration from spec, `calculateMetadata`), with a zod schema.
- `src/ClipComposition.tsx` — picks a layout, then draws captions and hook title.
- `src/layouts/{Follow,Speaker,Split,Fit}.tsx`
- `src/captions/{Karaoke,Pop,Clean}.tsx` plus `src/captions/paginate.ts`
- `src/HookTitle.tsx`
- `src/schema.ts` — zod `ClipSpec` / `ClipStyle`, exported for the frontend.
- Scripts: `deploy:functions` (`remotion lambda functions deploy`),
  `deploy:site` (`remotion lambda sites create --site-name=highlyte`),
  `studio` (Remotion Studio for preset development), `test` (vitest),
  `stills` (renderStill smoke images).

**Frontend (`frontend/`, Vue)**

- `vite.config.js` — add `@vitejs/plugin-react` scoped to `.tsx` files
  and `renderer/src`, alongside `@vitejs/plugin-vue`; alias
  `@renderer` → `../renderer/src`.
- `components/RemotionPreview.vue` — creates a React root and mounts
  `@remotion/player` with `component={ClipComposition}` and
  `inputProps={{spec, style}}`; re-renders the root when props change;
  unmounts on destroy.
- `components/ClipCard.vue` (replaces `ClipRow.vue`) — 9:16 preview,
  hook title (editable text), virality badge, tag, layout picker,
  caption preset picker, accent colour, show-hook toggle, render
  status/progress, download button.
- `components/ExportBar.vue` — queue renders for selected clips; when
  all are done, offer a single zip download.
- Remove the `<audio>` player and the decorative waveform.

**Data (`supabase/schema.sql`)**

```sql
alter table clips add column if not exists spec jsonb;
alter table clips add column if not exists hook_title text;
alter table clips add column if not exists virality_score numeric;
alter table clips add column if not exists style jsonb;  -- ClipStyle; null = defaults
alter table clips add column if not exists segment_key text;  -- R2 key of the 16:9 source segment

create table if not exists renders (
  id text primary key,
  clip_id text not null references clips(id) on delete cascade,
  style jsonb not null,
  style_hash text not null,
  status text not null default 'queued',  -- queued|rendering|done|error
  progress numeric default 0,
  lambda_render_id text,
  lambda_bucket text,
  storage_key text,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists renders_clip_style_idx on renders(clip_id, style_hash);
```

In-memory mirrors are kept so the app still runs without Supabase, as today.

## The ClipSpec contract

Analysis data (`spec`, written once) is kept separate from user choices
(`style`, freely edited). Remotion input props are `{spec, style}`.
Validated by Pydantic (Python) and zod (TypeScript); a shared fixture
JSON generated by Python is tested against the zod schema.

```ts
type ClipSpec = {
  version: 1
  clipId: string
  source: { url: string; width: number; height: number; fps: number }
  // segment-relative: the segment starts 1 s (or less, at video start) before the clip
  start: number
  end: number
  words: { text: string; start: number; end: number; emphasis?: boolean }[] // relative to clip start
  wordsApprox: boolean
  hookTitle: string | null
  viralityScore: number // 0-10
  reframe: {
    auto: 'follow' | 'speaker' | 'split' | 'fit'
    faces: { id: number; track: { t: number; cx: number; cy: number; w: number; h: number }[] }[] // normalized, smoothed, t relative to clip start
    speakerTimeline: { t: number; faceId: number }[]
  }
}

type ClipStyle = {
  layout: 'follow' | 'speaker' | 'split' | 'fit' // default: spec.reframe.auto
  captionPreset: 'karaoke' | 'pop' | 'clean'   // default: 'karaoke'
  showHook: boolean                            // default: true when hookTitle present
  hookTitle: string | null                     // default: spec.hookTitle (user may edit text)
  accent: string                               // hex, default '#FFD400'
  captionPosition: 'lower' | 'middle'          // default: 'lower'; forced 'middle' for split
}
```

`source.url` is a presigned R2 URL minted when the clip is served by the
API (never persisted); the stored spec keeps `segment_key` only.

## Layouts (output 1080x1920, input 16:9)

| Layout | Rendering |
|---|---|
| `follow` | Crop a 9:16 window (608x1080 of 1920x1080) horizontally centred on the primary face track's `cx`, clamped to the frame; scale to fill 1080x1920 |
| `speaker` | Same crop, hard-cutting to the face given by `speakerTimeline` at each time |
| `split` | Two stacked 1080x960 panels, each a crop centred on one of the two largest faces |
| `fit` | Full frame scaled to 1080 wide and vertically centred, over a blurred, cover-scaled copy |

Face-track gaps hold the last position; after more than 2 s without a
face, the crop eases back to centre. Positions between samples are
linearly interpolated.

**Automatic layout rules** (fractions are of sampled frames in the clip):

1. Faces are present in less than 40% of frames, or the largest face is
   smaller than 3% of frame area (screen share with a small webcam): `fit`.
2. Two distinct face tracks are each present in at least 50% of frames:
   `speaker` if the speaker timeline has at least one switch, else `split`.
3. Otherwise: `follow`.

## Caption presets

Shared: words are grouped into pages, breaking at sentence punctuation,
at gaps longer than 0.4 s, or at the preset's page limit. Fonts load via
`@remotion/google-fonts` so preview and render match.

| Preset | Page size | Look |
|---|---|---|
| `karaoke` | 3-5 words | Bold uppercase (Montserrat 900), thick outline; active word in accent colour |
| `pop` | 1-2 words | Large, spring scale-in 0.8→1; `emphasis` words in accent colour |
| `clean` | up to 2 lines, about 40 characters | White sentence-case text with a soft shadow; page fades in and out |

The hook title shows for the first 2.5 s in a rounded box near the top
when `showHook` is on. With no words, no captions are drawn.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status/{job_id}` | Unchanged shape plus per-clip `spec`, `style`, `hookTitle`, `viralityScore`; falls back to Supabase when the job isn't in memory |
| PATCH | `/api/clips/{clip_id}/style` | Save the user's `ClipStyle` (validated) |
| POST | `/api/clips/{clip_id}/render` | Body `ClipStyle`. Returns an existing `done` render with the same `style_hash`, or starts a new one. Returns `{renderId}` |
| GET | `/api/renders/{render_id}` | Status/progress; advances state by polling Lambda and runs the S3→R2 copy on completion |
| GET | `/api/renders/{render_id}/file` | Redirect to presigned R2 URL (local-file fallback not needed: Lambda-only) |
| GET | `/api/renders/zip?ids=a,b,c` | Stream a zip of finished renders |

Every path parameter is validated against a strict pattern (ids:
`^[a-z0-9-]{1,64}$`). `whisper_model` in `/api/generate` is restricted to
`tiny|base|small|medium`.

## Rendering on Lambda

- Python client `remotion-lambda`, pinned to exactly the same version as
  the `remotion` / `@remotion/*` npm packages. FastAPI checks at startup
  that the deployed site/function version matches and logs a clear
  error if it doesn't.
- Start: `render_media_on_lambda(composition="Clip", input_props={spec, style}, codec="h264", crf=20, frames_per_lambda=<tuned>)`
  with `serve_url` of the `highlyte` site and the deployed function name.
- FastAPI starts at most 2 renders at a time; extra requests stay
  `queued` and start as others finish. The same logic runs whenever
  `/api/renders/*` is polled, so no background thread is required.
- On success: copy the output from S3 to R2 at `renders/{render_id}.mp4`,
  delete the S3 object. An S3 lifecycle rule (1 day) on the Remotion
  bucket is a backstop.
- Configuration (`.env`): `REMOTION_AWS_ACCESS_KEY_ID`,
  `REMOTION_AWS_SECRET_ACCESS_KEY`, `REMOTION_AWS_REGION` (e.g.
  `ap-south-1`), `REMOTION_FUNCTION_NAME`, `REMOTION_SERVE_URL`. R2 is
  now required for Phase 1 (segments and renders live there).
- If Lambda isn't configured, the Export button is disabled with the
  message "Rendering not configured"; analysis and preview still work.

### One-time AWS setup (documented in README)

1. Create an IAM user with Remotion's user policy and a role with its
   role policy (`npx remotion lambda policies user` / `role`).
2. Fill in the `.env` values above.
3. `npm run deploy:functions` then `npm run deploy:site` in `renderer/`.
4. Create an AWS Budget alert at $5/month.
5. Optionally request a Lambda concurrency increase if new-account
   limits cause throttling.

## Error handling

| Failure | Behaviour |
|---|---|
| Groq word timing fails | Evenly spread word times, `wordsApprox: true`; UI shows "approximate sync" |
| Face analysis fails | `auto = fit`, empty faces; other layouts disabled in the picker |
| Segment upload to R2 fails | Clip marked `preview unavailable`; job still completes |
| Lambda not configured | Export disabled with message |
| Lambda render error | Render `error` with Remotion's error message; Retry button |
| Throttling / concurrency limit | Retried by the queue with backoff; surfaced if it keeps failing |
| Render stuck `rendering` over 30 min | Marked `error: timed out` when polled |

## Testing

- **Python (pytest, new `tests/`)**: automatic layout rules, track
  smoothing, speaker-timeline hold, even-spread word fallback,
  `ClipSpec` Pydantic validation, style hash stability, render
  queue/dedupe logic with a mocked Lambda client, path-parameter validation.
- **TypeScript (vitest in `renderer/`)**: caption pagination, crop and
  clamp maths per layout, interpolation, zod validation of the
  Python-generated fixture spec.
- **Visual smoke**: `npm run stills` renders one still per preset ×
  layout from the fixture spec; reviewed once, then compared by eye when
  it changes.
- **End-to-end (manual, real AWS)**: a roughly 20 s two-face test video
  through analysis and a Lambda render; `ffprobe` confirms 1080x1920,
  30 fps, and the expected duration.

## Performance expectations (CPU-only developer PC)

- Word timing per clip: a few seconds (Groq).
- Face analysis: about 20-40% of clip length per clip.
- Lambda render of a 60 s clip: roughly 15-40 s, well inside the Lambda
  always-free allowance (about 600 GB-seconds per render against 400,000
  per month).
