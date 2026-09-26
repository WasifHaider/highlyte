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
| Language detection | Groq Whisper with no language set (local faster-whisper `detect_language` without a key) on three 20s samples (start, middle, end) checks the choice. All-English with high confidence forces the English path; any Hindi/Urdu forces the Hinglish path; otherwise the user's choice wins. An override is shown as `language_note`. No per-chunk detection: after the spike both paths use Whisper's English mode, so there is nothing to route per chunk. |
| Hindi and Urdu speakers | One path for both, decided by the spike (below): Whisper `language="en"` with the Roman Hindi/Urdu seed prompt, which is what the app already does, then the glossary, the spelling list and optional LLM cleanup, all on Roman text. The English choice uses `language="en"` without the seed prompt. |
| Spelling | `spelling.json` sets one house spelling for chat forms both Indian and Pakistani readers recognise (ye, woh, toh, cheez, kuch, bohat, farq, kyunki) and fixes Whisper's chat shortcuts (bhoat→bohat, fark→farq, kia→kya, hy→hai). English words are never touched. Plain data, editable without code, grows from eval misses. |
| VAD | faster-whisper's bundled Silero VAD (ONNX). No PyTorch dependency. |
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
| 1 | Spike (throwaway): **done, no-go on the `hi` path.** See "Spike results" below. | done | Keep the current `en` + seed prompt transcription |
| 2 | Piece 1, language and transcription: picker, upfront detection, audio normalisation, VAD, `AsrProvider` (Groq + local), `hinglish.py` (glossary + spelling list on Roman text), segment data contract, `transcripts` table. A temporary adapter feeds the current highlight scorer so the app keeps working. | ~3–4 days | Accurate Roman captions for all speakers |
| 3 | Piece 2, clip selection: utterances, LLM ranker, cut points snapped in code, scoring and packing, QA gate. Replaces `highlight.py`. | ~1 week | 5–8 clips that start and end cleanly |
| 4 | Piece 3, review and nudge: single-clip edits and regeneration, caption card editing, SRT export, video upload. Caption presets trimmed to clean / outline / bold. | ~1 week | The fix-in-place loop |
| 5 | Tailscale download route: sidecars, `YTDLP_PROXIES` failover, clear errors, teammate setup guide | 1–2 days | Production downloads work again |
| 6 | Eval and tuning (LLM cleanup is built here only if the eval shows mishearing the spelling list cannot fix): 30 labelled clips split between Indian and Pakistani speakers, from more than one channel each; word error rate on Roman text after spelling normalisation (so bohat and bahut are not errors), Roman readability 1–5, entity hit rate, English-preserved %, cold-watchable %, clean start/end %. Paid ASR only if the sheet shows real mishearing after the glossary and spelling list are good. | ongoing | Measured quality |

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
  "raw": "hum YouTube pe ye video upload kar rahe the yar",
  "hinglish": "hum YouTube pe ye video upload kar rahe the yaar",
  "words": [{"t": "yaar", "raw": "yar", "start": 15.70, "end": 16.08, "kind": "hinglish"}],
  "confidence": 0.91
}
```

`raw` is Whisper's Roman output as heard; `hinglish` is after the glossary,
spelling list and optional cleanup. Word `kind` is `en`, `hinglish` or
`num`; spelling fixes never touch `en` words. There is no native-script
field (see "Spike results"). Captions, exports and the ranker use
`hinglish`; for English videos it equals `raw` apart from glossary fixes.

## Pipeline rules kept from the original scope

- Do not collapse the pipeline into one model. ASR hears, the script layer
  fixes spelling, the LLM edits text or scores clips, and code owns cut
  points.
- Never use `task=translate`, never cut on fixed 30s chunks.
- Cleanup may fix a clearly misheard word from context but never
  translates, and code checks every change: if more than 15% of a
  segment's words change, the edit is rejected and the uncleaned text is
  kept.
- The ranker picks utterance ids only; its timestamps are ignored and start
  and end are snapped in code.
- Keep `AsrProvider` swappable from day one.

## Spike results (2026-09-25)

Four podcasts, 38 one-minute chunks (18 from two Indian episodes of one
channel, 20 from two Pakistani episodes), all on Groq `whisper-large-v3`.
Script and report: `scripts/spike/` (throwaway).

| Path | Result |
|---|---|
| A: `en` + Roman seed prompt (current code) | Best. English words and names correct (September, control, content, Telegraph); Urdu vocabulary in natural Pakistani spelling (sirf, raftaar, qeemat, zaroor). No drift into English translation: common-English-word rate equal to B (about 4%). Weak spots: a few mishearings and chat spellings (fark, bhoat). |
| B: `hi` → Aksharamukha → spelling list | Rejected. Whisper `hi` wrote 93–94% of all tokens in Devanagari, English words included, so the scope's "Latin tokens pass through" assumption fails: September→sitambar, control→kantrol, culture→kalchar, provide→pravaid. Loses z/q/f sounds (sirf→siriph, qeemat→kimat). Better than A only on a few Hindi words (farq, kyunki, rakh), which a spelling list can fix on A. |
| E: `hi` → IndicXlit | Rejected. Turns function words into English lookalikes (के→key, थे→they, कर→curr, है→haye). Only runs on Python 3.10 (fairseq crashes on 3.11) and needs a 2.6GB PyTorch image. |
| D: `ur` → Aksharamukha | Rejected. Unconverted Urdu letters left in all 20 chunks; Urdu script omits short vowels. |
| LLM cleanup as specified | Near useless: changed 1 word of 3,516; 12 of 38 calls errored. The same-word-count rule makes it too timid. |

A and B agreed on only 52% (Indian) and 45% (Pakistani) of words, so the
choice matters. Two scope rules were overturned by this evidence: "never
`language="en"` as the Hinglish default" and "do not ask Whisper to emit
Roman". The sample is small; the Step 6 eval confirms or reopens this.

## Deferred past v1

Speaker diarization for two faces (the existing `split` layout covers
two-person videos), laugh/applause extension, mouth-open end extension,
AI style editing, caption translation, auto-posting, multi-language UI,
B-roll, custom Roman-Urdu Whisper.

## Start

Steps 0–3 are done. Piece 2 (Step 3, clip selection) is built: see
`2026-09-26-clip-selection-design.md` and
`../plans/2026-09-26-clip-selection.md`. Tune its thresholds on real
episodes with `scripts/select_dry_run.py <job_id>`.

Piece 3a (Step 4, fix in place) is built: see
`2026-09-27-fix-in-place-design.md` and
`../plans/2026-09-27-fix-in-place.md`. Deploy the migration
`supabase/migrations/20260927120000_fix_in_place.sql` and run
`npm run deploy:site` in `renderer/` before exports can draw spec v2.

Next are piece 3b (video upload) and the UI redesign.
