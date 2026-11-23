# Better picking, finished clips, and a preview that doesn't hang

Status: proposed, nothing built yet. Ordered so each phase can ship alone and make the next one safer. One branch and one PR per phase; each phase lists what "done" means.

Order: 0 preview hang, 1 measure picking, 2 stronger selection, 3 audio and visual polish, 4 aspect ratios, 5 background music, 6 pacing. Aspect ratios come before pacing so silence trimming is tested against every output size once, not retrofitted.

Tests that already exist and must stay green: `pytest` for the backend, `vitest` in `renderer/` (`lib/*.test.ts`, `captions/*.test.ts`, `schema.test.ts`). Remotion is pinned at 4.0.527 in both `renderer/` and `frontend/`; keep them in step.

## Phase 0: fix the preview hang (bug, do first)

Symptom: opening a clip, the video lags or freezes while captions and hook title keep going; switching layout (follow, speaker, split, fit) freezes it again; only a refresh or reopening recovers.

Suspected causes, from reading the code (not yet reproduced, so step 1 comes first):

- Too many media elements on one file. `LayoutView.tsx` mounts a separate `<Audio>` plus one or two `OffthreadVideo` elements, all pointing at the same clip file. Fit mounts three (audio, blurred background, foreground). The Player keeps each one in sync with the frame by seeking, so several decoders of a 1080p file compete and playback stalls. Captions and the hook title are plain overlays, which is why they keep moving.
- Layout switches remount. Fit returns a different element tree from follow/speaker/split, so switching to or from fit unmounts the audio and every video and loads the source again. A remounted element has to re-buffer, which looks like a hang.
- Preview decodes the full-quality segment: the same 1080p file the final render uses, with 8 s of padding on each side.
- Extra redraws. `RemotionPreview.vue` deep-watches `spec` and `clipStyle` and calls `root.render` with fresh copies on every change, including each status poll while a clip action is pending.
- Stuck until refresh suggests stalled media connections (several elements requesting ranges of the same redirected R2 URL, abandoned ones not released). Hypothesis only.

Steps:

1. Reproduce and measure in the browser: count media requests per layout, check for 206 (range) versus 200 responses on the video URL, read Remotion's console warnings about buffering and seeking, and see whether requests pile up after a layout switch. Record the findings in this file before changing code, and drop any cause above that the measurements rule out.
2. One element tree for every layout. Fit uses the same primary `CroppedVideo` with a full-frame crop placed in a letterboxed box (its box is `OUT_W` by `OUT_W * srcH / srcW`, centred), so a layout change only changes props and never mounts or unmounts a video element. Keep the stable `key`s already used for the primary and secondary panels.
3. One decoder for picture and sound: the primary video carries the audio and the separate `<Audio>` goes. The secondary muted element stays, for split only.
4. Preview-only fit background: in the Player, the blurred background is the clip's poster image with a CSS blur instead of a second video. This is a deliberate, limited difference from the final render, which keeps the video background; branch on Remotion's environment check (`getRemotionEnvironment()`), not on a prop, so the render can never pick the preview path by mistake. Note it in `spec.py`'s "preview and render draw the same thing" comment.
5. Buffering: use the buffering options of Remotion 4.0.527 (check its docs for `pauseWhenBuffering` on the media elements and the Player's buffering and poster props) so a slow load shows as loading, not a frozen frame.
6. Fewer redraws: build the Player's input props once per real change (compare the style fields and the spec revision) instead of on every deep-watch tick.
7. Only if it still stutters on slower machines: during clip prep, also write a small preview rendition (about 540p) of each segment for the Player; the final render keeps the full-quality file. Costs one extra ffmpeg pass and some storage per clip, and clips made before the change have no rendition, so the Player must fall back to the full file.

Findings (2026-11-23, branch `fix/preview-hang`). Reproduced with a local harness page mounting the real `RemotionPreview` on a generated 46 s 1080p segment, served through a throttled range server (10 Mbps and 2.5 Mbps, 120 ms latency):

- Confirmed: fit, and every shot of kind `none` even without touching the layout, remounted the video elements. Each remount left the video about 0.6 s behind the audio for good.
- Confirmed, and the main cause of the permanent hang: Remotion 4's `pauseWhenBuffering` defaults to off. While a media element loads, the timeline (captions, hook title) keeps running; once the video is more than 0.45 s behind, Remotion seeks it, which starts another load. At 2.5 Mbps this looped: 32 seeks in 14 s, the picture frozen at readyState 1, the split panel black.
- Confirmed: every media element downloads the file separately (parallel identical range requests), so the separate `<Audio>` doubled the bandwidth needed.
- Not a factor in the harness: the 200 versus 206 question (all 206) and redraws on unchanged props (no seeks when idle), though a redraw with changed props can trigger one seek.

Fixed: steps 2 to 6 (step 7 not needed so far). Results at 2.5 Mbps: 11.3 s of playback in 16 s instead of 6.4 s, 8 seeks instead of 31, video and timeline in step. At 10 Mbps the primary video stays within 0.01 s of the timeline through cuts and layout switches. Remaining minor effect: when the split panel first loads, playback can step back about 0.4 s once. Exports are unchanged: follow, split and fit stills render pixel-identical to master, and audio is still present in a rendered mp4.

Done when: on a real clip from a long podcast, switching layout five times in a row never freezes playback and the clip starts within a couple of seconds on a normal connection, in both Chrome and one other browser. Checked by hand, since no automated test covers browser playback; renderer tests still pass.

## Phase 1: measure picking before changing it

- Comparison script: rerun selection from stored transcripts (`db.get_transcript`) for three to five known videos and print the current picks next to the new ones, with scores and reasons. No download or transcription involved.
  - The LLM is not deterministic. Run each version two or three times and look at picks that recur, or a change will be confused with noise.
  - Save each run's raw LLM answers, so later scoring changes can be replayed without spending Groq quota.
  - Every run spends the Groq key's daily quota; keep the video set small.
- Gold set: for those videos, mark by hand which moments are good clips (start and end times). The script then reports how many marked moments each version found, which turns "looks better" into a number.
- Prompt rewrite (`backend/pipeline/ranker.py`): concrete hook patterns, explicit reject cases (intros, sponsor reads, "as I said earlier", answers whose question is missing), one or two few-shot examples from real good and bad clips, score anchors (0.9 means "I would post this", 0.5 okay, 0.2 weak), and the reason before the scores. Watch the window budget: few-shot examples take tokens away from transcript per window (`WINDOW_TOKENS`), which means more windows and more calls.
- `parse_picks` stays compatible with the old answer shape; add tests for the new fields.

Done when: the new prompt finds at least as many gold moments as the old one across repeated runs, and the tests pass.

Status (2026-11-23): built `backend/eval/compare_selection.py` (`--replay` rescoring from saved answers in `eval-runs/`, gitignored) and the `v2` prompt in `backend/eval/prompts.py`, with start times shown to the model. Production still uses the current prompt.

- Found and fixed: Groq word timings have no gaps (median 0.0 s on all 21 stored transcripts), so `snap.forward_to_pause` rejected picks ending on a clean sentence. A sentence end now counts as a cut point. On the Tenerife video this took 16 picks from 3 candidates to 9.
- First comparison on four videos, one run each: v2 drops the sponsor reads the current prompt kept and picks more story moments, but some v2 picks open on earlier context, and it tends to pick 40-56 s spans. No clear overall win. The Groq daily limit ended the v2 run on the 2 h video early.
- Still open: two runs per prompt, and a gold set from the user.

## Phase 2: stronger selection

- Two-pass ranking: after the per-window picks, one call ranks the shortlisted texts against each other. If it fails or hits a rate limit, fall back to today's `scoring.pack` order. Try a larger model for this call only, since its input is small.
- Clip count scales with video length: floor 5, ceiling decided from the gold set. Pass the duration into `pack`. More clips means a longer job (each one is downloaded, cut, face-analysed and uploaded) and more storage, so pick the ceiling with that in mind.
- Picks flagged `starts_mid` or `ends_mid` are dropped today (`ranker.py`, `parse_picks`). Every pick is already widened to whole thought units (picks are unit indices), so the model is saying the unit boundary itself is wrong. Instead of dropping them, try one extra unit before (for `starts_mid`) or after (for `ends_mid`), keep it only if the result still fits `MAX_CLIP_S` and the hard rejects, and otherwise drop as today. Tests in the ranker or selection suite.
- Optional: per-video percentile thresholds instead of the fixed 0.7 and 0.55 gates, tuned only against the gold set.

Done when: the gold-set score improves over Phase 1 across repeated runs, the fallback path is covered by a test, and the job time for a long podcast is measured before and after.

Status (2026-11-23):

- Over-long picks are shortened to their last sentence end that fits 60 s instead of being dropped (`snap.shorten`), and flagged `shortened` ("Shortened, check the ending" on the card). Replaying the saved runs: 0 picks lost to length instead of 21 of 90; 1 to 2 kept clips per video are shortened.
- Clip cap: 8 up to 80 minutes, then one per 10 minutes, up to 12 (`scoring.max_clips`, ceiling provisional). The titles call budget grows with the clip count. The 2 h video now gets 12 clips.
- Mid-thought picks take in one neighbouring thought instead of being dropped. Rare in practice: 2 of 134 saved picks.
- Two-pass shortlist ranking (`pipeline/shortlist.py`) is built with its fallback and tests, but only the comparison script turns it on (`current+rerank`, `v2+rerank`) until it is measured.
- Not done: percentile thresholds; job-time measurement for 12 clips.

## Phase 3: finished-clip polish, audio first

- Loudness and voice cleanup in clip prep, not at render time: rendering happens on Remotion Lambda, which has no ffmpeg step of ours. `cut.reencode_segment` currently copies the audio unchanged; have it apply loudness normalization to about -14 LUFS (resampled back to 48 kHz, since `loudnorm` raises the sample rate) and a light high-pass and compressor. The preview and the export then both get it, and timings are unaffected because nothing is trimmed. Clips made before the change stay as they are unless regenerated.
- Brand kit per team: logo, accent colour, font, progress bar. Needs a small team settings record in the database and an upload for the logo, then style fields in `spec.py` and `schema.ts`. Extends the existing `accent` field.
- Captions: safe areas so text stays clear of platform buttons, more presets, emphasis icons.

Done when: exported clips measure close to -14 LUFS, the brand kit shows in both preview and export, and old clips without brand settings render exactly as before.

Status (2026-11-23):

- Loudness and voice cleanup done in `cut.reencode_segment`: high-pass, gentle compression, two-pass loudnorm with one steady gain (single-pass undershot on short audio), 48 kHz. On four real 45 s podcast excerpts: -11.8 to -17.3 LUFS in, -14.0 out, peaks about -1.4 dBFS (one excerpt was clipping before), zero timing offset, same duration. Silent or soundless segments are re-encoded without normalising. Applies to clips prepared from now on; existing clips keep their audio.
- Caption safe areas done (`renderer/src/lib/safe.ts`): text stays out of the bottom 480 px, the right 140 px and the top 250 px. Lower captions grow upward from the safe line; the hook title starts below the top band. This changes exported frames on purpose.
- Brand kit done, scoped with the user: per member (not per team), with accent colour, caption font (Montserrat, Poppins, Anton, Bebas Neue) and progress bar (off, top, bottom); no logo. Stored in `team_members.brand_kit` (migration `20261123120000_member_brand_kit.sql`); new jobs start their clips from the creator's kit; Swap and Regenerate keep the clip's font and bar. Settings has a "My brand kit" section; the clip editor and the style-all bar have font and progress bar controls. Styles without the new fields render exactly as before, and their render fingerprints are unchanged, so existing exports are reused.
- Needs a Lambda site redeploy (`npm run deploy:site`) before exports show fonts, the progress bar and the safe-area caption placement.
