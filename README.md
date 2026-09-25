# Highlyte

Paste a YouTube podcast link, get back the meaningful moments as cut clips.
Handles episodes that mix English with Roman-script Hindi/Urdu.

## Architecture

- `backend/` — FastAPI app. Pipeline: yt-dlp ingest -> transcript (language
  check, VAD chunks, Whisper via Groq else local faster-whisper, then glossary
  and spelling fixes) -> heuristic/LLM highlight scoring -> ffmpeg cuts.
  Job/clip metadata persisted to Supabase Postgres, and logins go through
  Supabase Auth (required, see below). Clip files stay on local disk under
  `data/clips/` unless R2 is configured.
- `frontend/` — Vue 3 + Vite SPA (Pinia store, Vue Router, axios). Polls job
  status and renders the highlight list.
- `supabase/migrations/` — the database schema as ordered migration files,
  applied with the Supabase CLI (see "Database migrations" below).

## Roman Urdu/Hindi transcription

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

## Setup

### Backend
```
cd HighLyte
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # WSL/Linux
cp .env.example .env   # fill in SUPABASE_URL / SUPABASE_KEY
./.venv/Scripts/python -m uvicorn backend.main:app --reload --port 8000
```
`ffmpeg` must be on PATH (already present on this machine via winget).

### Frontend
```
cd frontend
npm install
npm run dev            # http://localhost:6100 (Vite proxies /api to the backend on :8000)
npm run build           # production build -> frontend/dist
```

The frontend calls the API on its own origin (`/api`), and Vite's dev and
preview servers proxy that to the backend. Keeping one origin is what lets
the backend's httpOnly login cookies travel with every request.

### Supabase (required)
1. Create a project at supabase.com.
2. Apply the migrations: `npx supabase db push --db-url "<connection string>"`
   (see "Database migrations" below for which connection string).
3. Put `SUPABASE_URL` and `SUPABASE_KEY` (the service-role key) in `.env` at
   the repo root.
Accounts live in Supabase Auth, so without these set login, signup and every
project endpoint answer 503 "Accounts need Supabase".

### Database migrations
Schema changes live in `supabase/migrations/` as timestamped SQL files.
Supabase records which ones a database has applied, so each file runs once
and nothing is ever re-run by hand.

- **Change the schema:** `npx supabase migration new <name>` creates an empty
  file; write only the change in it (`alter table jobs add column ...`).
  Never edit a migration that has already been applied.
- **Production:** the deploy workflow runs `supabase db push` before the new
  backend starts, on every push to master that touches
  `supabase/migrations/`. It needs the `SUPABASE_DB_URL` GitHub secret: the
  **Session pooler** connection string from the Supabase dashboard
  (Connect → Session pooler), with the database password filled in. The
  direct `db.<ref>.supabase.co` host is IPv6-only and GitHub runners can't
  reach it.
- **By hand:** `npx supabase db push --db-url "<same string>" --dry-run`
  lists what would be applied; drop `--dry-run` to apply.
- The first migration, `20260924000000_baseline.sql`, is the old
  `schema.sql`. Every statement in it is idempotent, so it applies safely to
  the existing production database.

## Team accounts

Everyone logs in, and each project belongs to a team.

- **Sign up first after deploying.** The oldest team claims every project
  made before logins existed, and signup is open to anyone who can reach
  the app, so create your own team before sharing the URL.
- **Add teammates on the Team page** (admins only). HighLyte generates a
  password and shows it once; copy it and send it to the teammate yourself.
  It is never stored or shown again.
- **Behind https, set `COOKIE_SECURE=true`** in `.env` so the login cookies
  are only ever sent over https. Leave it unset for local http development,
  where secure cookies would not be sent at all.

## Vertical clips and rendering

Each highlight becomes a 9:16 short: the crop follows faces (or the
current speaker, or shows both people split-screen, or fits the whole
frame on a blurred background), with animated word-by-word captions and
an optional hook title. The clip page previews every change live in the
browser; the final mp4 is rendered on AWS Lambda with
[Remotion](https://www.remotion.dev) only when you export.

Layouts follow the camera: face analysis detects cuts (a jump in a tiny
grayscale thumbnail between samples) and tracks faces per shot. Split
shows the left person on top and the right person below only during
wide two-person shots; close-ups show one person full-frame. Clips made
before this change keep their old behaviour until the video is re-run.
After changing anything in `renderer/src`, re-run `npm run deploy:site`
so Lambda exports use the same layout as the preview.

- `renderer/` — the Remotion composition (layouts, caption presets, hook
  title). The same code runs in the browser preview and on Lambda.
  `npm run studio` opens Remotion Studio for designing presets;
  `npm run fixture:video && npm run stills` renders a still for every
  layout × preset.
- Remotion's free license covers teams of 3 or fewer people.

### One-time AWS setup

1. `cd renderer && npm install`
2. In the AWS console create an IAM user for HighLyte. Attach the policy
   printed by `npx remotion lambda policies user` to the user, and create
   the role described by `npx remotion lambda policies role` (role name
   `remotion-lambda-role`). Create an access key for the user.
3. Put the key, secret and region in `.env` (`REMOTION_AWS_*`), and also
   export them as `REMOTION_AWS_ACCESS_KEY_ID` / `REMOTION_AWS_SECRET_ACCESS_KEY`
   in the shell for the next two commands.
4. `npm run deploy:functions` — copy the function name into `REMOTION_FUNCTION_NAME`.
5. `npm run deploy:site` — copy the Serve URL into `REMOTION_SERVE_URL`.
   Re-run this whenever anything in `renderer/src` changes.
6. Create an AWS Budget alert at $5/month (Billing → Budgets).
7. Backstop cleanup: add a lifecycle rule on the `remotionlambda-*` S3
   bucket deleting objects under `renders/` after 1 day (HighLyte deletes
   each output after copying it to R2; this catches anything missed).
8. If renders fail with throttling errors, request a Lambda concurrency
   increase (Service Quotas → Lambda → Concurrent executions).

Remotion npm packages and the Python `remotion-lambda` client must be
the exact same version (currently 4.0.527). When upgrading, change both,
then redeploy the functions and the site; the backend logs a VERSION
MISMATCH line at startup if they differ.

### Tests
```
./.venv/Scripts/pip install -r requirements-dev.txt
./.venv/Scripts/python -m pytest              # fast suite
./.venv/Scripts/python -m pytest -m slow      # downloads the face model, runs MediaPipe
cd renderer && npm test
```

## How it works

1. **Ingest** — pull the audio via `yt-dlp`, cached by video ID.
2. **Transcript** — language check, VAD chunks, Whisper (Groq, else local
   faster-whisper), then glossary and spelling fixes in code.
3. **Highlight detection** — chunk the transcript into ~45s windows, score
   each for "meaningful" content (heuristic scorer by default; optional
   LLM scorer if `GROQ_KEY` is set), keep the top ones.
4. **Cutting** — `ffmpeg -c copy` (fast path) or re-encode fallback.
5. **Frontend** — poll job status, render clip list with play/select/export.

## Open questions (carried over from original scope)

- [x] Output format: vertical 9:16 shorts (Phase 1)
- [x] Caption quality check before trusting auto-captions over Whisper (dropped: every job now uses Whisper)
- [ ] LLM highlight scoring model choice, if/when the heuristic scorer isn't
      good enough
