# HighLyte v1 Roadmap: Hinglish Clips

Date: 2026-09-25
Status: Approved scope; each numbered piece gets its own spec and plan

## Product

Paste a YouTube URL or upload a video, and pick the spoken language
(Hinglish by default, or English). HighLyte returns 5–8 vertical
1080×1920 clips a creator would actually post, with accurate Roman
captions. Success: a stranger can watch one exported clip on mute and get
the point. Fewer strong clips beat many weak ones.

### User flow

1. Input: a URL or a file, plus the spoken-language choice. No model settings.
2. Status: downloading → transcribing → picking moments → ready. If
   detection overrides the chosen language, the status screen says so.
3. Review grid: thumbnail, duration, first caption line, one-line reason.
4. Open a clip: live vertical preview with captions.
5. Fix in place without rerunning the whole video: nudge start/end, "use
   previous sentence" / "include next sentence", edit one caption card,
   regenerate that clip only.
6. Download 1080×1920 MP4 + SRT; batch download checked clips. Never
   auto-publish.

## Decisions

These are where v1 deliberately differs from the original scope draft.

| Topic | Decision |
|---|---|
| Rendering | Stay on Remotion: live in-browser preview, MP4 rendered on Lambda at export. FFmpeg burn-in for export only if the Remotion license (more than 3 people) or volume demands it. HyperFrames is not used: user edits are structured data, not AI-written visuals. |
| Language choice | A spoken-language picker (Hinglish / English) is kept. It describes the audio, never the caption language; nothing is translated. |
| Language detection | Local faster-whisper `detect_language` on three 20s samples (start, middle, end) checks the choice. All-English with high confidence forces the English path; any Hindi/Urdu forces the Hinglish path; otherwise the user's choice wins. An override is shown as `language_note`. Inside the Hinglish path each VAD chunk is detected too, so English stretches take the English path. |
| Hindi and Urdu speakers | One path for both: Whisper `language="hi"` → glossary → IndicXlit on Indic tokens only → a fixed spelling list → constrained LLM cleanup. No per-chunk Hindi/Urdu routing, which would make spelling inconsistent inside one clip. |
| Spelling | `spelling.json` fixes chat shortcuts (hy→hai, kia→kya, mjhy→mujhe) and Urdu-origin sounds that Whisper drops the nukta from (jindagi→zindagi, jyada→zyada, khwaish→khwahish). Plain data, editable without code, grows from eval misses. |
| VAD | faster-whisper's bundled Silero VAD (ONNX). No PyTorch dependency for VAD. |
| Rendering timing | Clips are not rendered upfront. Preview is live; the MP4 renders only on export, so nudges are instant. |
| Database changes | Supabase CLI migrations in `supabase/migrations/`, applied by `supabase db push` in the deploy workflow. No Prisma: the backend is Python and the schema uses `auth.users` foreign keys and triggers. |
| YouTube blocking | EC2 downloads through teammates' home laptops via Tailscale exit nodes (sidecar SOCKS5 proxies, ordered failover), with upload as the fallback. |

## Quality bar per clip

- First frame is a face; first second is speech. The first caption is a
  claim, question, contrast or name, never toh / matlab / uh.
- One complete idea, setup and payoff inside the window. Ends on a finished
  sentence with 300–500ms of air after the last word; never on
  lekin / kyunki / aur.
- 12–35s by default; hard limits 8–60s.
- Captions 8–12 words per card, synced to words. English words stay English;
  yaar / bhai / matlab / scene / vibe are kept.
- Face-locked vertical crop without jitter; high-contrast captions above
  platform UI.
- QA shows "low confidence — check captions" instead of hiding failure.

## Build order

| Step | Piece | Size | Outcome |
|---|---|---|---|
| 0 | Groundwork: Supabase CLI migrations (baseline + `db push` in CI); untrack committed log files and ignore `*.log` | ½ day | No more manual SQL |
| 1 | Spike (throwaway): IndicXlit on Python 3.11 in Docker; compare the current path (`en` + seed prompt) against `hi` + xlit + spelling list on 2 Indian and 2 Pakistani episodes; also try `ur` on the Pakistani ones | 1–2 days | Go / no-go on the new transcription path |
| 2 | Piece 1, language and transcription: picker, detection, audio normalisation, VAD, `AsrProvider` (Groq + local), `hinglish.py`, `cleanup.py`, segment data contract, `transcripts` table. A temporary adapter feeds the current highlight scorer so the app keeps working. | ~1 week | Accurate Roman captions for all speakers |
| 3 | Piece 2, clip selection: utterances, LLM ranker, cut points snapped in code, scoring and packing, QA gate. Replaces `highlight.py`. | ~1 week | 5–8 clips that start and end cleanly |
| 4 | Piece 3, review and nudge: single-clip edits and regeneration, caption card editing, SRT export, video upload. Caption presets trimmed to clean / outline / bold. | ~1 week | The fix-in-place loop |
| 5 | Tailscale download route: sidecars, `YTDLP_PROXIES` failover, clear errors, teammate setup guide | 1–2 days | Production downloads work again |
| 6 | Eval and tuning: 30 labelled clips split between Indian and Pakistani speakers; native WER, Roman readability 1–5, entity hit rate, English-preserved %, cold-watchable %, clean start/end %. Paid ASR only if the sheet shows real mishearing after the glossary and spelling list are good. | ongoing | Measured quality |

Step 5 is independent and can move earlier if teammates need the deployed
app before the pipeline work lands.

## Data contract

Every utterance and clip uses one object per segment:

```json
{
  "id": "seg_01",
  "start": 12.41,
  "end": 16.08,
  "speaker": "A",
  "language": "hi-Latn-EN",
  "native": "हम YouTube पर ये video upload कर रहे थे यार",
  "hinglish": "hum YouTube par ye video upload kar rahe the yaar",
  "words": [{"t": "hum", "src": "हम", "start": 12.41, "end": 12.62, "kind": "indic"}],
  "confidence": 0.91
}
```

Captions and exports use `hinglish` only (for English videos it equals
`native`). The ranker may read both.

## Pipeline rules kept from the original scope

- Do not collapse the pipeline into one model. ASR hears, the script layer
  writes Hinglish, the LLM edits text or scores clips, and code owns cut
  points and romanization.
- Never ask Whisper to emit Roman on the Hinglish path, never use
  `task=translate`, never cut on fixed 30s chunks.
- Cleanup may not add or drop words; an edit that changes the token count
  (other than brand merges such as "you tube" → "YouTube") is rejected and
  the uncleaned text is kept.
- The ranker picks utterance ids only; its timestamps are ignored and start
  and end are snapped in code.
- Keep `AsrProvider` swappable from day one.

## Deferred past v1

Speaker diarization for two faces (the existing `split` layout covers
two-person videos), laugh/applause extension, mouth-open end extension,
AI style editing, caption translation, auto-posting, multi-language UI,
B-roll, custom Roman-Urdu Whisper.

## Start

Step 0, then Step 1. Every later piece adds database changes, and the spike
is the largest risk: if IndicXlit will not install or the `hi` path is not
clearly better, piece 1 changes.
