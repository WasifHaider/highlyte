# Home, Projects and Clip-Page Navigation

Date: 2026-09-24
Status: Draft for review
Builds on: `2026-09-24-phase1-remotion-reframe-captions-design.md`

## Problem

After a video is processed, its clips page (`/jobs/:id`) is the only place with
the 9:16 preview and the per-clip style controls (hook title, show hook,
layout, captions, caption position, accent). Once the user leaves that page
there is no way back:

- Home shows only a "paste a link" message.
- Library lists clips with the old 16:9 player and none of the controls.
- The video card shows a hard-coded "video thumbnail" placeholder.

## Goal

Every processed video is reachable from Home and Projects and opens its clips
page, with the full controls, a way to style all clips at once, and a real
YouTube thumbnail everywhere a video is shown.

## Decisions

| Topic | Decision |
|---|---|
| Tabs | Two tabs: **Home** and **Projects**. Library is removed; `/library` redirects to `/projects` |
| Home | Paste-link box (unchanged) + "Recent videos": the 6 newest projects |
| Projects | Every project, with title search and a status filter |
| Clicking a project | Opens `/jobs/:id` (the existing clips page) |
| Clips page | Existing per-clip controls + a new "Style all clips" bar |
| Thumbnails | Stored from yt-dlp at ingest; YouTube's standard thumbnail URL as fallback |
| Out of scope | Deleting or renaming projects; sorting/filtering clips within a project |

## Backend

### Thumbnail and video id

- `ingest.VideoMeta` gains `thumbnail_url: str | None` from yt-dlp's
  `info["thumbnail"]`.
- `Job.video_meta` gains `videoId` and `thumbnailUrl`.
- `jobs` table gains `video_id text` and `thumbnail_url text`
  (`alter table ... add column if not exists`), written by `_persist_job`.
- Fallback: when `thumbnail_url` is missing (older jobs), the API derives
  `https://i.ytimg.com/vi/{video_id}/hqdefault.jpg`, taking `video_id` from the
  column or, for older rows, parsing the job `url` (`watch?v=`, `youtu.be/`,
  `/shorts/`). No id means no thumbnail; the UI then shows a neutral tile with a
  play icon.

### `GET /api/jobs` — project list

Returns every project, newest first:

```json
{
  "id": "8b5605d1e406",
  "url": "https://www.youtube.com/watch?v=...",
  "status": "preparing",
  "error": null,
  "videoTitle": "...",
  "videoChannel": "...",
  "durationLabel": "26:14",
  "thumbnailUrl": "https://i.ytimg.com/vi/.../hqdefault.jpg",
  "clipCount": 6,
  "progress": {"stage": "preparing", "percent": 40, "note": "clip 3/8: framing"},
  "createdAt": "2026-09-24T10:12:00Z"
}
```

- Merges running jobs from memory (live `progress`) with Supabase rows; a job in
  both uses the in-memory version.
- A Supabase job that isn't done/error and isn't in memory is reported as
  `error` ("interrupted by a server restart"), same rule as `/api/status`.
- `clipCount` comes from one grouped query on `clips` (count per `job_id`).
- Query params: `limit` (default 100, max 200), `q` (case-insensitive title
  match), `status` (`processing` = queued/transcribing/analyzing/preparing,
  `done`, `error`).
- Works without Supabase: returns only the in-memory jobs.

### `/api/status/{job_id}`

`videoMeta` gains `videoId` and `thumbnailUrl` (same fallback rule).

## Frontend

### Routing and tabs

- Routes: `/` Home, `/projects` Projects, `/jobs/:id` clips page;
  `/library` redirects to `/projects`.
- `TopBar.vue`: tabs Home and Projects.
- `LibraryView.vue` is deleted, along with the `/api/clips` library call in
  `highlyteApi.js`. The backend `/api/clips` endpoint stays (harmless, and
  covered by tests).

### `ProjectCard.vue` (new)

Used by Home and Projects: thumbnail (16:9, `object-fit: cover`, placeholder
tile if missing), title, channel · duration, status badge (Processing with a
progress bar and note / Done · N clips / Failed with the error), relative time.
The whole card is a link to `/jobs/:id`.

### `HomeView.vue`

Paste-link box as today, then "Recent videos" (6 newest from
`GET /api/jobs?limit=6`) and a "See all projects" link. While any listed
project is processing, the list refreshes every 3 s; polling stops when none
are. Empty state: the existing "Paste a YouTube podcast link" message.

### `ProjectsView.vue` (new)

Title search (debounced 300 ms) + status tabs (All / Processing / Done /
Failed) driving `GET /api/jobs?q=&status=`; grid of `ProjectCard`s. Same 3 s
refresh while anything shown is processing. Empty state per filter ("No
projects match").

### `VideoCard.vue`

Shows `meta.thumbnailUrl` as an image (placeholder tile if missing), replacing
the hard-coded text.

### "Style all clips" bar (clips page)

A bar above the clip list, shown when the job is done and at least one clip
has a spec. Controls: Layout, Captions, Accent, Show hook title, and an
**Apply to all** button. Applying sets those four fields on every clip that
has a spec (hook title text stays per clip). A layout a clip can't use
(face layouts with no faces, split with fewer than two faces) falls back to
that clip's automatic layout. Uses the existing `jobStore.updateStyle`, so
each clip is saved through `PATCH /api/clips/{id}/style` as today.

### Clips without a spec

Unchanged from Phase 1: "Re-run this video to get a vertical preview"
instead of the controls.

## Error handling

- `/api/jobs` failure: Home/Projects show "Couldn't load projects" with a
  Retry button.
- Thumbnail image fails to load: `@error` swaps in the placeholder tile.
- Opening `/jobs/:id` for an unknown id: the existing error banner
  ("job not found").

## Testing

- **pytest**: YouTube id parsing (watch, youtu.be, shorts, unknown); thumbnail
  fallback; `/api/jobs` merging memory + DB rows, interrupted-job rule,
  `clipCount`, `q` and `status` filters, no-Supabase mode; `videoMeta`
  includes `thumbnailUrl`.
- **Browser check**: Home lists recent videos with thumbnails; clicking one
  opens its clips page with controls; Projects search and status filter work;
  `/library` redirects; "Apply to all" updates every preview and sends one
  PATCH per clip; a processing project shows live progress on its card.

## Migration

```sql
alter table jobs add column if not exists video_id text;
alter table jobs add column if not exists thumbnail_url text;
```

Appended to `supabase/schema.sql`; the user runs it together with the
Phase 1 migration.
