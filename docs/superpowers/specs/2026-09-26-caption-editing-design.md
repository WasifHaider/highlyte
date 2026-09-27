# Caption Editing

Date: 2026-09-26
Status: Approved by delegation ("you decide", then "start")
Roadmap: pulled forward from piece 3 ("edit one caption card")

## Goal

On a clip's card the user can fix the words of any caption line (a misheard
word, a name, spelling), see the change in the live preview immediately, and
get the same text in the exported mp4. They can undo all edits with "Reset".

## Decisions

| Topic | Decision |
|---|---|
| Editing unit | A **caption line**: the clip's words paginated with the `clean` preset's rules (max 14 words / 84 chars, break at sentence end or a pause > 0.4 s). Lines stay the same whichever caption preset is chosen, so edits don't depend on the style. |
| Where the logic lives | In the renderer (`renderer/src/captions/edit.ts`), shared by the preview through the `@renderer` alias. The backend only validates and stores the resulting word list, so the retiming logic exists once. |
| Retiming an edited line | Split the new text on whitespace. Same number of words → keep every word's start/end and emphasis, replace only the text. Different number → spread the line's own time span (first word's start to last word's end) across the new words in proportion to their length (characters + 1); a new word is emphasised only if its normalised text equals an emphasised word from the original line. Empty text → the line's words are removed (no caption in that span). Words outside the line never change. |
| Storage | The edited words replace `clips.spec.words` in Supabase. The first edit copies the untouched words into a new column `clips.words_original` (jsonb, null until the first edit). "Reset" copies them back and clears the column. |
| API | `PUT /api/clips/{clip_id}/captions` body `{"words": [Word…]}` → the stored spec. `POST /api/clips/{clip_id}/captions/reset` → the stored spec. Both team-scoped like the style endpoint, 409 for clips without a spec. |
| Validation | 1–3000 words; each word's text 1–40 characters after trimming, no newlines; `0 ≤ start ≤ end ≤ clip length + 0.5 s`; starts non-decreasing. Otherwise 422. |
| Render cache | The render dedupe key becomes a hash of the style **and** the words (`render_hash(style, words)`), so exporting after an edit renders again instead of reusing the old mp4. The `renders.style_hash` column keeps its name and now stores this combined hash. |
| In-memory jobs | If the clip belongs to a job still in `JOBS`, its in-memory record is updated too, like style saves. |
| UI | Under the style fields: an "Edit captions" button opens a list of lines, each a text input with its start time (m:ss). "Save captions" sends all lines at once; "Cancel" discards; "Reset to original" appears when the clip has been edited (`captionsEdited: true` in the clip API). While editing, the preview shows the draft immediately (before saving). |
| Scope | Text only: no dragging word timings, no splitting/merging lines, no per-word emphasis toggles, no SRT export (piece 3). |

## Data

Migration `supabase/migrations/<timestamp>_clip_words_original.sql`:

```sql
alter table clips add column if not exists words_original jsonb;
```

Clip API gains `captionsEdited` (bool): `words_original` is not null.

## Units

- `renderer/src/captions/edit.ts`: `captionLines(words) → Line[]` (`{ index, start, end, words }`, reusing `paginate` with the clean limits), `editLine(words, line, text) → Word[]`, `lineText(line) → string`.
- `backend/spec.py`: `render_hash(style, words) -> str`; `style_hash` stays for existing callers.
- `backend/render.py`: `RenderService.request(clip_id, style, words)` uses `render_hash`.
- `backend/captions.py` (new): `validate_words(words, clip_length) -> list[Word]` raising `ValueError` with a readable message.
- `backend/db.py`: `update_clip` already exists; used with `{"spec": …, "words_original": …}`.
- `backend/main.py`: the two endpoints; `_clip_row_to_api` adds `captionsEdited`; `start_render` passes words.
- Frontend: `highlyteApi.js` `saveCaptions`, `resetCaptions`; `jobStore` actions; a `CaptionEditor.vue` component used by `ClipCard.vue`.

## Testing

- Renderer (vitest): `captionLines` grouping; `editLine` same-count keeps times/emphasis, different-count spreads the span proportionally and stays inside it, emphasis carried by matching text, empty text removes the line, other lines untouched.
- Python: `validate_words` accept/reject cases; `render_hash` changes when words change and not when they don't; `RenderService.request` re-renders after a word change; endpoints: save stores words and `words_original` once, second save keeps the first original, reset restores, team scoping, 409 without spec, 422 on bad words.
- Frontend: `npm run build`; manual check in the browser by the user (login).

## Deploy note

Captions render from `spec.words`, which the renderer already uses, so no renderer redeploy is needed for editing itself; `npm run deploy:site` is only needed for the earlier shot-aware layout change.
