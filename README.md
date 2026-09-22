# Highlyte

Paste a YouTube podcast link, get back the meaningful moments as cut clips.
Handles episodes that mix English with Roman-script Hindi/Urdu.

## Architecture

- `backend/` — FastAPI app. Pipeline: yt-dlp ingest -> transcript (YouTube
  captions, else local faster-whisper) -> heuristic/LLM highlight scoring ->
  ffmpeg cuts. Job/clip metadata persisted to Supabase Postgres (optional —
  app runs fully offline without it, see below). Clip audio files stay on
  local disk under `backend/data/clips/`.
- `frontend/` — Vue 3 + Vite SPA (Pinia store, Vue Router, axios). Polls job
  status and renders the highlight list.
- `supabase/schema.sql` — jobs/clips tables + indexes. Run in the Supabase
  SQL editor for your project.

## Roman Urdu/Hindi transcription

The fallback ASR path (`backend/pipeline/transcript.py`) uses
`faster-whisper` (free, local, CPU-capable) with `language="en"` and a
Roman-Urdu/Hindi `initial_prompt` seed. This keeps Whisper decoding
code-switched speech in Latin letters instead of switching to
Devanagari/Nastaliq script or silently translating to English. See the
docstring in that file for the mechanism and hard constraints (do not set
`language="ur"`/`"hi"`, do not strip the seed prompt).

YouTube captions are tried first (fast, free, no model download); Whisper
only runs when captions are unavailable/disabled.

## Setup

### Backend
```
cd HighLyte
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # WSL/Linux
cp .env.example .env   # fill in SUPABASE_URL / SUPABASE_KEY (optional)
./.venv/Scripts/python -m uvicorn backend.main:app --reload --port 7000
```
`ffmpeg` must be on PATH (already present on this machine via winget).

### Frontend
```
cd frontend
npm install
npm run dev            # http://localhost:6100 (talks to backend via VITE_API_BASE_URL)
npm run build           # production build -> frontend/dist
```

### Supabase (optional but recommended for scaling)
1. Create a project at supabase.com.
2. Run `supabase/schema.sql` in the SQL editor.
3. Put `SUPABASE_URL` and `SUPABASE_KEY` in `.env` at the repo root.
Without these set, the backend still works — job/clip metadata just isn't
persisted (everything runs in-memory for the life of the process).

## How it works

1. **Ingest** — pull the audio via `yt-dlp`, cached by video ID.
2. **Transcript** — YouTube captions first; local faster-whisper fallback
   with Roman Urdu/Hindi decoding (see above).
3. **Highlight detection** — chunk the transcript into ~45s windows, score
   each for "meaningful" content (heuristic scorer by default; optional
   LLM scorer if `OPENAI_API_KEY` is set), keep the top ones.
4. **Cutting** — `ffmpeg -c copy` (fast path) or re-encode fallback.
5. **Frontend** — poll job status, render clip list with play/select/export.

## Open questions (carried over from original scope)

- [ ] Output format: long-form highlight reel vs. vertical short-form clips
- [ ] Caption quality check before trusting auto-captions over Whisper
- [ ] LLM highlight scoring model choice, if/when the heuristic scorer isn't
      good enough
