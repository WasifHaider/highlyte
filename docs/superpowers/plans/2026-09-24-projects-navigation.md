# Home, Projects and Clip-Page Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every processed video reachable from Home and a new Projects tab, show real YouTube thumbnails, and add a "Style all clips" bar to the clips page.

**Architecture:** The backend gains a small `projects.py` module that turns in-memory jobs and Supabase rows into one project list (thumbnail, clip count, live progress), served by `GET /api/jobs` with search/status filters. yt-dlp's thumbnail URL is saved at ingest. The Vue app replaces Library with a Projects view, adds recent videos to Home (both built on one `ProjectCard` and one polling composable), shows the thumbnail on the clips page, and adds a store action plus bar component that applies a style to every clip.

**Tech Stack:** Python 3.11, FastAPI, Supabase (PostgREST), pytest; Vue 3, Vue Router, Pinia, Vite.

**Spec:** `docs/superpowers/specs/2026-09-24-projects-navigation-design.md`

## Global Constraints

- Tabs: **Home** and **Projects** only. `/library` redirects to `/projects`. `LibraryView.vue` is deleted.
- Home shows the 6 newest projects ("Recent videos") and a "See all projects" link.
- Project list query params: `limit` (default 100, max 200), `q` (case-insensitive title match), `status` (`processing` = queued/transcribing/analyzing/preparing, `done`, `error`).
- Lists refresh every 3 s while any shown project is processing, and stop when none are. Projects search is debounced 300 ms.
- Thumbnail fallback: `https://i.ytimg.com/vi/{video_id}/hqdefault.jpg`; no id means a placeholder tile; an image load error also swaps in the placeholder.
- A Supabase job that isn't done/error and isn't in memory is reported as `error` with "Processing was interrupted by a server restart. Please submit the video again."
- "Style all clips" sets layout, caption preset, accent and show-hook on every clip that has a spec; hook title text stays per clip; a layout a clip can't use falls back to that clip's automatic layout.
- The app must keep working with Supabase unset (project list = in-memory jobs only).
- The Supabase columns `jobs.video_id` and `jobs.thumbnail_url` already exist (the user ran the migration); the plan only records the SQL in `supabase/schema.sql`.
- Comments explain *why*, in full sentences, at the density of the surrounding code.

## File Structure

```
backend/
  projects.py                 NEW  youtube_id, thumbnail_url, from_job, from_row, build_projects
  pipeline/ingest.py          MOD  VideoMeta.thumbnail_url
  db.py                       MOD  count_clips_by_job
  main.py                     MOD  Job.created_at, video_meta ids/thumbnail, persist, /api/jobs, status fallback
supabase/schema.sql           MOD  jobs.video_id / thumbnail_url
tests/test_projects.py        NEW
tests/test_jobs_api.py        NEW
frontend/src/
  utils/time.js               NEW  relativeTime
  utils/projects.js           NEW  PROCESSING_STATUSES
  utils/clipStyle.js          NEW  LAYOUTS, PRESETS, layoutAllowed (moved out of ClipCard)
  composables/useProjects.js  NEW  fetch + 3 s refresh while processing
  components/ProjectCard.vue  NEW
  components/StyleAllBar.vue  NEW
  components/VideoCard.vue    MOD  real thumbnail
  components/ClipCard.vue     MOD  import LAYOUTS/PRESETS from utils
  components/ClipList.vue     MOD  StyleAllBar above the list
  components/TopBar.vue       MOD  Projects tab
  views/HomeView.vue          MOD  recent videos
  views/ProjectsView.vue      NEW
  views/LibraryView.vue       DEL
  router/index.js             MOD
  services/highlyteApi.js     MOD  listProjects; drop listJobs/listAllClips
  stores/jobStore.js          MOD  applyStyleToAll; drop recentJobs/loadRecentJobs
```

---

### Task 1: Backend — thumbnails and the project list API

**Files:**
- Create: `backend/projects.py`, `tests/test_projects.py`, `tests/test_jobs_api.py`
- Modify: `backend/pipeline/ingest.py`, `backend/db.py`, `backend/main.py`, `supabase/schema.sql`

**Interfaces:**
- Produces:
  - `projects.PROCESSING_STATUSES: set[str]`, `projects.INTERRUPTED_ERROR: str`
  - `projects.youtube_id(url: str | None) -> str | None`
  - `projects.thumbnail_url(video_id: str | None, stored: str | None) -> str | None`
  - `projects.from_job(job) -> dict` and `projects.from_row(row: dict, clip_count: int) -> dict`, both returning the project shape `{id, url, status, error, videoTitle, videoChannel, durationLabel, thumbnailUrl, clipCount, progress, createdAt}`
  - `projects.build_projects(memory: list[dict], rows: list[dict], counts: dict[str, int], *, q=None, status=None, limit=100) -> list[dict]`
  - `db.count_clips_by_job(job_ids: list[str]) -> dict[str, int]`
  - `ingest.VideoMeta.thumbnail_url: str | None`
  - `main.Job.created_at: str` (ISO 8601 UTC)
  - `/api/status/{id}` and in-memory `job.video_meta` include `videoId` and `thumbnailUrl`
  - `GET /api/jobs?limit=&q=&status=` returns a list of project dicts

- [ ] **Step 1: Write the failing tests**

`tests/test_projects.py`:
```python
from types import SimpleNamespace

import pytest

from backend import projects


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=qt6YoGmksCc", "qt6YoGmksCc"),
    ("https://www.youtube.com/watch?feature=share&v=_aw32rFL680&t=10", "_aw32rFL680"),
    ("https://youtu.be/qt6YoGmksCc?si=abc", "qt6YoGmksCc"),
    ("https://www.youtube.com/shorts/qt6YoGmksCc", "qt6YoGmksCc"),
    ("https://vimeo.com/12345", None),
    (None, None),
])
def test_youtube_id(url, expected):
    assert projects.youtube_id(url) == expected


def test_thumbnail_url_prefers_stored_then_derives():
    assert projects.thumbnail_url("abc", "https://x/t.jpg") == "https://x/t.jpg"
    assert projects.thumbnail_url("qt6YoGmksCc", None) == "https://i.ytimg.com/vi/qt6YoGmksCc/hqdefault.jpg"
    assert projects.thumbnail_url(None, None) is None


def _row(**kw):
    base = {
        "id": "job1", "url": "https://youtu.be/qt6YoGmksCc", "status": "done", "error": None,
        "video_title": "Ep 1", "video_channel": "Pod", "video_duration": 125,
        "video_id": None, "thumbnail_url": None, "created_at": "2026-09-24T10:00:00+00:00",
    }
    base.update(kw)
    return base


def _job(**kw):
    base = dict(
        id="job2", url="https://youtu.be/_aw32rFL680", status="preparing", error=None,
        video_meta={"title": "Live one", "channel": "Chan", "durationLabel": "1:00",
                    "videoId": "_aw32rFL680", "thumbnailUrl": "https://x/live.jpg"},
        clips=[{}, {}], progress={"stage": "preparing", "percent": 50, "note": "clip 2/4"},
        created_at="2026-09-24T11:00:00+00:00",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_from_row_shape_and_fallback_thumbnail():
    p = projects.from_row(_row(), 3)
    assert p == {
        "id": "job1", "url": "https://youtu.be/qt6YoGmksCc", "status": "done", "error": None,
        "videoTitle": "Ep 1", "videoChannel": "Pod", "durationLabel": "2:05",
        "thumbnailUrl": "https://i.ytimg.com/vi/qt6YoGmksCc/hqdefault.jpg",
        "clipCount": 3, "progress": {}, "createdAt": "2026-09-24T10:00:00+00:00",
    }


def test_from_row_marks_unfinished_jobs_interrupted():
    p = projects.from_row(_row(status="transcribing"), 0)
    assert p["status"] == "error"
    assert p["error"] == projects.INTERRUPTED_ERROR


def test_from_job_uses_live_state():
    p = projects.from_job(_job())
    assert p["status"] == "preparing"
    assert p["clipCount"] == 2
    assert p["thumbnailUrl"] == "https://x/live.jpg"
    assert p["progress"]["note"] == "clip 2/4"
    assert p["createdAt"] == "2026-09-24T11:00:00+00:00"


def test_from_job_before_metadata_arrives():
    p = projects.from_job(_job(video_meta=None, url="https://youtu.be/qt6YoGmksCc", clips=[]))
    assert p["videoTitle"] is None
    assert p["thumbnailUrl"] == "https://i.ytimg.com/vi/qt6YoGmksCc/hqdefault.jpg"


def test_build_projects_merges_sorts_and_filters():
    memory = [projects.from_job(_job())]
    rows = [
        _row(),
        _row(id="job2", status="transcribing"),  # same job as memory: memory wins
        _row(id="job3", video_title="Another talk", status="error", error="boom",
             created_at="2026-09-23T09:00:00+00:00"),
    ]
    counts = {"job1": 3}
    items = projects.build_projects(memory, rows, counts)
    assert [p["id"] for p in items] == ["job2", "job1", "job3"]
    assert items[0]["status"] == "preparing"
    assert items[2]["clipCount"] == 0

    assert [p["id"] for p in projects.build_projects(memory, rows, counts, q="EP ")] == ["job1"]
    assert [p["id"] for p in projects.build_projects(memory, rows, counts, status="processing")] == ["job2"]
    assert [p["id"] for p in projects.build_projects(memory, rows, counts, status="error")] == ["job3"]
    assert len(projects.build_projects(memory, rows, counts, limit=1)) == 1
```

`tests/test_jobs_api.py`:
```python
from fastapi.testclient import TestClient

from backend import main

client = TestClient(main.app)


def _row(**kw):
    base = {
        "id": "feed00000001", "url": "https://youtu.be/qt6YoGmksCc", "status": "done", "error": None,
        "video_title": "Ep 1", "video_channel": "Pod", "video_duration": 60,
        "video_id": "qt6YoGmksCc", "thumbnail_url": None, "transcript_source": "groq",
        "created_at": "2026-09-24T10:00:00+00:00",
    }
    base.update(kw)
    return base


def test_jobs_endpoint_returns_projects(monkeypatch):
    seen = {}

    def fake_counts(ids):
        seen["ids"] = ids
        return {"feed00000001": 4}

    monkeypatch.setattr(main.db, "list_jobs", lambda limit=20: [_row()])
    monkeypatch.setattr(main.db, "count_clips_by_job", fake_counts)
    body = client.get("/api/jobs").json()
    assert seen["ids"] == ["feed00000001"]
    assert body[0]["clipCount"] == 4
    assert body[0]["thumbnailUrl"] == "https://i.ytimg.com/vi/qt6YoGmksCc/hqdefault.jpg"


def test_jobs_endpoint_filters(monkeypatch):
    monkeypatch.setattr(main.db, "list_jobs", lambda limit=20: [_row(), _row(id="feed00000002", video_title="Other", status="error")])
    monkeypatch.setattr(main.db, "count_clips_by_job", lambda ids: {})
    assert [p["id"] for p in client.get("/api/jobs?q=ep").json()] == ["feed00000001"]
    assert [p["id"] for p in client.get("/api/jobs?status=error").json()] == ["feed00000002"]
    assert client.get("/api/jobs?status=bogus").status_code == 422
    assert client.get("/api/jobs?limit=500").status_code == 422


def test_jobs_endpoint_includes_in_memory_jobs(monkeypatch):
    monkeypatch.setattr(main.db, "list_jobs", lambda limit=20: [])
    monkeypatch.setattr(main.db, "count_clips_by_job", lambda ids: {})
    main.JOBS["feed00000003"] = main.Job(id="feed00000003", url="https://youtu.be/_aw32rFL680", status="transcribing")
    try:
        body = client.get("/api/jobs").json()
        assert body[0]["id"] == "feed00000003"
        assert body[0]["status"] == "transcribing"
        assert body[0]["createdAt"]
    finally:
        main.JOBS.pop("feed00000003", None)


def test_status_fallback_includes_thumbnail(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: _row(thumbnail_url="https://x/t.jpg"))
    monkeypatch.setattr(main.db, "list_clips_for_job", lambda job_id: [])
    meta = client.get("/api/status/feed00000001").json()["videoMeta"]
    assert meta["videoId"] == "qt6YoGmksCc"
    assert meta["thumbnailUrl"] == "https://x/t.jpg"
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_projects.py tests/test_jobs_api.py -v`
Expected: FAIL — `cannot import name 'projects' from 'backend'`.

- [ ] **Step 3: Implement `backend/projects.py`**
```python
"""The project list behind the Home and Projects pages: one entry per
submitted video, built from running jobs in memory (which carry live
progress) and saved jobs in Supabase (which survive restarts).
"""
from __future__ import annotations

import re
from typing import Any

from .pipeline import ingest

PROCESSING_STATUSES = {"queued", "transcribing", "analyzing", "preparing"}
INTERRUPTED_ERROR = "Processing was interrupted by a server restart. Please submit the video again."

# Matches the 11-character id in watch?v=, youtu.be/, /shorts/, /embed/ and /live/ URLs.
_YOUTUBE_ID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")


def youtube_id(url: str | None) -> str | None:
    if not url:
        return None
    match = _YOUTUBE_ID_RE.search(url)
    return match.group(1) if match else None


def thumbnail_url(video_id: str | None, stored: str | None) -> str | None:
    """yt-dlp's thumbnail when we saved one; otherwise YouTube's standard
    thumbnail address, which exists for every public video."""
    if stored:
        return stored
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None


def _status_group(status: str) -> str:
    return "processing" if status in PROCESSING_STATUSES else status


def from_job(job: Any) -> dict[str, Any]:
    meta = job.video_meta or {}
    video_id = meta.get("videoId") or youtube_id(job.url)
    return {
        "id": job.id,
        "url": job.url,
        "status": job.status,
        "error": job.error,
        "videoTitle": meta.get("title"),
        "videoChannel": meta.get("channel"),
        "durationLabel": meta.get("durationLabel"),
        "thumbnailUrl": thumbnail_url(video_id, meta.get("thumbnailUrl")),
        "clipCount": len(job.clips),
        "progress": job.progress,
        "createdAt": job.created_at,
    }


def from_row(row: dict[str, Any], clip_count: int) -> dict[str, Any]:
    status, error = row["status"], row.get("error")
    if status not in ("done", "error"):
        # Not in memory, so its worker thread died with an old process.
        status, error = "error", INTERRUPTED_ERROR
    video_id = row.get("video_id") or youtube_id(row.get("url"))
    duration = row.get("video_duration")
    return {
        "id": row["id"],
        "url": row.get("url"),
        "status": status,
        "error": error,
        "videoTitle": row.get("video_title"),
        "videoChannel": row.get("video_channel"),
        "durationLabel": ingest.duration_label(float(duration)) if duration else None,
        "thumbnailUrl": thumbnail_url(video_id, row.get("thumbnail_url")),
        "clipCount": clip_count,
        "progress": {},
        "createdAt": row.get("created_at"),
    }


def build_projects(
    memory: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    counts: dict[str, int],
    *,
    q: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    by_id = {row["id"]: from_row(row, counts.get(row["id"], 0)) for row in rows}
    for project in memory:
        by_id[project["id"]] = project  # live state beats the last saved snapshot
    items = sorted(by_id.values(), key=lambda p: p.get("createdAt") or "", reverse=True)
    if q:
        needle = q.strip().lower()
        items = [p for p in items if needle in (p.get("videoTitle") or "").lower()]
    if status:
        items = [p for p in items if _status_group(p["status"]) == status]
    return items[:limit]
```

- [ ] **Step 4: `backend/pipeline/ingest.py`** — add the field at the end of `VideoMeta`:
```python
    video_path: str | None
    # yt-dlp's best thumbnail URL for the video, when it reports one.
    thumbnail_url: str | None = None
```
and pass it in the `return VideoMeta(...)` call:
```python
        video_path=target_video,
        thumbnail_url=info.get("thumbnail"),
    )
```

- [ ] **Step 5: `backend/db.py`** — append:
```python
def count_clips_by_job(job_ids: list[str]) -> dict[str, int]:
    """Clip count per job for the project list, in one query. PostgREST caps
    a response at its max-rows setting (1000 by default), so with more clips
    than that across the listed jobs some counts come back low; the project
    list asks for at most 200 jobs of about 8 clips each, so this is rare."""
    client = get_client()
    if client is None or not job_ids:
        return {}
    try:
        res = client.table("clips").select("job_id").in_("job_id", job_ids).execute()
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] count_clips_by_job failed: {e}")
        return {}
    counts: dict[str, int] = {}
    for r in res.data or []:
        counts[r["job_id"]] = counts.get(r["job_id"], 0) + 1
    return counts
```

- [ ] **Step 6: `backend/main.py`**

Imports: add `from datetime import datetime, timezone` and change `from . import db, render, storage` to `from . import db, projects, render, storage`.

`Job` dataclass — add after `progress`:
```python
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
```

In `_run_pipeline`, replace the `job.video_meta = {...}` block with:
```python
        job.video_meta = {
            "title": meta.title,
            "channel": meta.channel,
            "duration": meta.duration,
            "durationLabel": ingest.duration_label(meta.duration),
            "videoId": meta.video_id,
            "thumbnailUrl": projects.thumbnail_url(meta.video_id, meta.thumbnail_url),
        }
```

In `_persist_job`, inside `if job.video_meta:` add:
```python
        row["video_id"] = job.video_meta.get("videoId")
        row["thumbnail_url"] = job.video_meta.get("thumbnailUrl")
```

In the `status` endpoint's Supabase fallback, replace the interrupted-job literal with `projects.INTERRUPTED_ERROR`, and build `video_meta` as:
```python
    video_meta = None
    if row.get("video_title"):
        video_id = row.get("video_id") or projects.youtube_id(row.get("url"))
        video_meta = {
            "title": row.get("video_title"),
            "channel": row.get("video_channel"),
            "duration": row.get("video_duration"),
            "durationLabel": ingest.duration_label(float(row.get("video_duration") or 0)),
            "videoId": video_id,
            "thumbnailUrl": projects.thumbnail_url(video_id, row.get("thumbnail_url")),
        }
```

Replace the `/api/jobs` endpoint:
```python
@app.get("/api/jobs")
def list_projects(
    limit: int = Query(100, ge=1, le=200),
    q: str | None = None,
    status: Literal["processing", "done", "error"] | None = None,
) -> list[dict[str, Any]]:
    """Every submitted video for the Home and Projects pages, newest first."""
    rows = db.list_jobs(limit=200)
    counts = db.count_clips_by_job([r["id"] for r in rows])
    memory = [projects.from_job(job) for job in list(JOBS.values())]
    return projects.build_projects(memory, rows, counts, q=q, status=status, limit=limit)
```

- [ ] **Step 7: `supabase/schema.sql`** — append:
```sql
-- Projects page: YouTube id and thumbnail for each job, so the Home and
-- Projects lists can show the video's thumbnail.
alter table jobs add column if not exists video_id text;
alter table jobs add column if not exists thumbnail_url text;
```

- [ ] **Step 8: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest -v`
Expected: all PASS (the existing `tests/test_status.py` still passes with the new fallback).

- [ ] **Step 9: Commit**
```bash
git add backend/projects.py backend/pipeline/ingest.py backend/db.py backend/main.py supabase/schema.sql tests/test_projects.py tests/test_jobs_api.py
git commit -m "Serve a project list with thumbnails, clip counts and live progress"
```

---

### Task 2: Frontend — Home recent videos, Projects tab, real thumbnails

**Files:**
- Create: `frontend/src/utils/time.js`, `frontend/src/utils/projects.js`, `frontend/src/composables/useProjects.js`, `frontend/src/components/ProjectCard.vue`, `frontend/src/views/ProjectsView.vue`
- Modify: `frontend/src/views/HomeView.vue`, `frontend/src/components/VideoCard.vue`, `frontend/src/components/TopBar.vue`, `frontend/src/router/index.js`, `frontend/src/services/highlyteApi.js`, `frontend/src/stores/jobStore.js`
- Delete: `frontend/src/views/LibraryView.vue`

**Interfaces:**
- Consumes: `GET /api/jobs?limit=&q=&status=` from Task 1 (project dicts: `id, url, status, error, videoTitle, videoChannel, durationLabel, thumbnailUrl, clipCount, progress, createdAt`); `videoMeta.thumbnailUrl` in `/api/status`.
- Produces: `listProjects(params)` in `highlyteApi.js`; `useProjects(paramsGetter) -> { projects, loading, error, reload }`; `ProjectCard` (prop `project`); `relativeTime(iso)`; `PROCESSING_STATUSES`.

- [ ] **Step 1: Utilities**

`frontend/src/utils/time.js`:
```js
export function relativeTime(iso) {
  if (!iso) return ''
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (Number.isNaN(seconds)) return ''
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86400) {
    const h = Math.floor(seconds / 3600)
    return `${h} hour${h === 1 ? '' : 's'} ago`
  }
  const d = Math.floor(seconds / 86400)
  if (d < 30) return `${d} day${d === 1 ? '' : 's'} ago`
  return new Date(iso).toLocaleDateString()
}
```

`frontend/src/utils/projects.js`:
```js
// Mirrors backend/projects.py PROCESSING_STATUSES.
export const PROCESSING_STATUSES = ['queued', 'transcribing', 'analyzing', 'preparing']

export const isProcessing = (project) => PROCESSING_STATUSES.includes(project?.status)
```

- [ ] **Step 2: API client** — in `frontend/src/services/highlyteApi.js` delete `listJobs` and `listAllClips`, and add:
```js
export function listProjects(params = {}) {
  return api.get('/api/jobs', { params }).then(r => r.data)
}
```
In `frontend/src/stores/jobStore.js` remove `listJobs` from the import, the `recentJobs` state entry and the `loadRecentJobs` action (nothing else uses them; confirm with a grep).

- [ ] **Step 3: `frontend/src/composables/useProjects.js`**
```js
import { onUnmounted, ref, watch } from 'vue'
import { listProjects } from '../services/highlyteApi'
import { isProcessing } from '../utils/projects'

const REFRESH_MS = 3000

// Loads the project list for the given query params and keeps refreshing it
// every few seconds while any listed video is still processing, so progress
// bars move without a page reload. `params` is a getter; the list reloads
// whenever what it returns changes.
export function useProjects(params) {
  const projects = ref([])
  const loading = ref(true)
  const error = ref(null)
  let timer = null
  let latest = 0

  async function load() {
    const request = ++latest
    clearTimeout(timer)
    try {
      const data = await listProjects(params())
      if (request !== latest) return // a newer search replaced this one
      projects.value = data
      error.value = null
      if (data.some(isProcessing)) timer = setTimeout(load, REFRESH_MS)
    } catch {
      if (request === latest) error.value = "Couldn't load projects"
    } finally {
      if (request === latest) loading.value = false
    }
  }

  watch(params, load, { immediate: true, deep: true })
  onUnmounted(() => {
    latest++
    clearTimeout(timer)
  })

  return { projects, loading, error, reload: load }
}
```

- [ ] **Step 4: `frontend/src/components/ProjectCard.vue`**
```vue
<template>
  <router-link :to="{ name: 'job', params: { id: project.id } }" class="project-card">
    <div class="thumb">
      <img v-if="project.thumbnailUrl && !imgFailed" :src="project.thumbnailUrl" alt="" loading="lazy" @error="imgFailed = true" />
      <div v-else class="thumb-placeholder" aria-hidden="true"><span class="play"></span></div>
      <span v-if="project.durationLabel" class="duration">{{ project.durationLabel }}</span>
    </div>
    <div class="body">
      <div class="title">{{ project.videoTitle || 'Untitled video' }}</div>
      <div v-if="project.videoChannel" class="channel">{{ project.videoChannel }}</div>
      <div class="status-row">
        <template v-if="processing">
          <span class="badge processing">Processing</span>
          <span class="note">{{ project.progress?.note || '' }}</span>
        </template>
        <span v-else-if="project.status === 'done'" class="badge done">
          Done · {{ project.clipCount }} clip{{ project.clipCount === 1 ? '' : 's' }}
        </span>
        <span v-else class="badge failed" :title="project.error || ''">Failed</span>
        <span class="time">{{ relativeTime(project.createdAt) }}</span>
      </div>
      <div v-if="processing && project.progress?.percent != null" class="progress-bar">
        <div class="progress-bar-fill" :style="{ width: Math.min(100, project.progress.percent) + '%' }"></div>
      </div>
    </div>
  </router-link>
</template>

<script setup>
import { computed, ref } from 'vue'
import { relativeTime } from '../utils/time'
import { isProcessing } from '../utils/projects'

const props = defineProps({ project: { type: Object, required: true } })
const imgFailed = ref(false)
const processing = computed(() => isProcessing(props.project))
</script>

<style scoped>
.project-card {
  display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden; text-decoration: none; color: var(--ink);
  transition: border-color .15s ease, transform .15s ease;
}
.project-card:hover { border-color: var(--accent); transform: translateY(-1px); }
.thumb { position: relative; aspect-ratio: 16 / 9; background: var(--accent-soft); }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb-placeholder { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
.play { width: 0; height: 0; border-top: 12px solid transparent; border-bottom: 12px solid transparent; border-left: 18px solid var(--ink-faint); }
.duration {
  position: absolute; right: 8px; bottom: 8px; background: rgba(0,0,0,.75); color: #fff;
  font-size: 11.5px; padding: 2px 6px; border-radius: 4px;
}
.body { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 4px; }
.title { font-weight: 600; font-size: 14.5px; line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.channel { font-size: 12.5px; color: var(--ink-soft); }
.status-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; font-size: 12px; }
.badge { font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.badge.processing { background: #FFF4D6; color: #8A5A00; }
.badge.done { background: var(--accent-soft); color: var(--accent-text); }
.badge.failed { background: #FBEAE3; color: #9C3B14; }
.note { color: var(--ink-soft); }
.time { color: var(--ink-faint); margin-left: auto; }
.progress-bar { height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; margin-top: 6px; }
.progress-bar-fill { height: 100%; background: var(--accent); transition: width .3s ease; }
</style>
```

- [ ] **Step 5: `frontend/src/views/HomeView.vue`** (replace the file)
```vue
<template>
  <div class="page">
    <div class="hero">
      <div class="hero-title">Paste a YouTube podcast link above</div>
      <div class="hero-sub">
        Highlyte pulls the audio, transcribes it (Roman Urdu/Hindi + English friendly),
        and turns the best moments into vertical clips with captions.
      </div>
    </div>

    <section v-if="loading || error || projects.length" class="recent">
      <div class="section-head">
        <h2>Recent videos</h2>
        <router-link to="/projects" class="see-all">See all projects</router-link>
      </div>
      <div v-if="loading" class="state-msg">Loading…</div>
      <div v-else-if="error" class="state-msg error">
        {{ error }} <button class="retry" @click="reload">Retry</button>
      </div>
      <div v-else class="grid">
        <ProjectCard v-for="p in projects" :key="p.id" :project="p" />
      </div>
    </section>
  </div>
</template>

<script setup>
import ProjectCard from '../components/ProjectCard.vue'
import { useProjects } from '../composables/useProjects'

const RECENT_LIMIT = 6
const { projects, loading, error, reload } = useProjects(() => ({ limit: RECENT_LIMIT }))
</script>

<style scoped>
.page { max-width: 1040px; margin: 0 auto; padding: 40px 24px 120px; }
.hero { text-align: center; padding: 40px 24px 48px; }
.hero-title { font-family: var(--font-serif); font-size: 22px; font-weight: 500; }
.hero-sub { margin: 10px auto 0; font-size: 13.5px; color: var(--ink-soft); max-width: 460px; }
.section-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 16px; }
.section-head h2 { font-family: var(--font-serif); font-size: 22px; font-weight: 500; margin: 0; }
.see-all { font-size: 13px; font-weight: 600; color: var(--accent); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px; }
.state-msg { font-size: 13.5px; color: var(--ink-soft); padding: 24px 0; }
.state-msg.error { color: #9C3B14; }
.retry { margin-left: 8px; border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 3px 10px; cursor: pointer; }
</style>
```

- [ ] **Step 6: `frontend/src/views/ProjectsView.vue`**
```vue
<template>
  <div class="page">
    <div class="page-head">
      <h1>Projects</h1>
      <p class="sub">Every video you've processed. Open one to style and export its clips.</p>
    </div>

    <div class="controls">
      <input v-model="query" type="search" class="search" placeholder="Search by title" />
      <div class="status-tabs" role="tablist">
        <button
          v-for="tab in STATUS_TABS"
          :key="tab.value"
          role="tab"
          :aria-selected="status === tab.value"
          :class="{ active: status === tab.value }"
          @click="status = tab.value"
        >{{ tab.label }}</button>
      </div>
    </div>

    <div v-if="loading" class="state-msg">Loading…</div>
    <div v-else-if="error" class="state-msg error">
      {{ error }} <button class="retry" @click="reload">Retry</button>
    </div>
    <div v-else-if="projects.length === 0" class="state-msg">
      {{ filtered ? 'No projects match.' : 'No projects yet. Paste a YouTube link above to start one.' }}
    </div>
    <div v-else class="grid">
      <ProjectCard v-for="p in projects" :key="p.id" :project="p" />
    </div>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import ProjectCard from '../components/ProjectCard.vue'
import { useProjects } from '../composables/useProjects'

const STATUS_TABS = [
  { value: '', label: 'All' },
  { value: 'processing', label: 'Processing' },
  { value: 'done', label: 'Done' },
  { value: 'error', label: 'Failed' },
]
const SEARCH_DEBOUNCE_MS = 300

const query = ref('')
const search = ref('')
const status = ref('')
let debounce = null
watch(query, (value) => {
  clearTimeout(debounce)
  debounce = setTimeout(() => { search.value = value.trim() }, SEARCH_DEBOUNCE_MS)
})
onUnmounted(() => clearTimeout(debounce))

const filtered = computed(() => !!(search.value || status.value))
const { projects, loading, error, reload } = useProjects(() => ({
  q: search.value || undefined,
  status: status.value || undefined,
}))
</script>

<style scoped>
.page { max-width: 1040px; margin: 0 auto; padding: 40px 24px 120px; }
.page-head h1 { font-family: var(--font-serif); font-size: 28px; font-weight: 500; margin: 0; }
.sub { font-size: 13.5px; color: var(--ink-soft); margin: 6px 0 0; }
.controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 24px 0 20px; }
.search {
  flex: 1; min-width: 220px; font-family: var(--font-sans); font-size: 14px; color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px; background: #fff;
}
.status-tabs { display: flex; gap: 4px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 3px; }
.status-tabs button {
  border: none; background: none; font-family: var(--font-sans); font-size: 13px; color: var(--ink-soft);
  padding: 6px 12px; border-radius: 6px; cursor: pointer;
}
.status-tabs button.active { background: var(--accent); color: #fff; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px; }
.state-msg { font-size: 13.5px; color: var(--ink-soft); padding: 24px 0; }
.state-msg.error { color: #9C3B14; }
.retry { margin-left: 8px; border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 3px 10px; cursor: pointer; }
</style>
```

- [ ] **Step 7: Router and tabs**

`frontend/src/router/index.js`:
```js
import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import JobView from '../views/JobView.vue'
import ProjectsView from '../views/ProjectsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/projects', name: 'projects', component: ProjectsView },
    { path: '/jobs/:id', name: 'job', component: JobView, props: true },
    // Library was replaced by Projects; keep old links working.
    { path: '/library', redirect: '/projects' },
  ],
})

export default router
```

`frontend/src/components/TopBar.vue` — replace the Library tab link with:
```vue
        <router-link
          to="/projects"
          class="tab"
          active-class="tab-active"
          :class="{ 'tab-active': $route.path.startsWith('/jobs/') }"
        >Projects</router-link>
```
(A clips page belongs to a project, so the Projects tab stays highlighted there.)

Delete `frontend/src/views/LibraryView.vue` (`git rm`).

- [ ] **Step 8: `frontend/src/components/VideoCard.vue`** — replace `<div class="thumb">video<br />thumbnail</div>` with:
```vue
    <div class="thumb">
      <img v-if="meta.thumbnailUrl && !imgFailed" :src="meta.thumbnailUrl" alt="" @error="imgFailed = true" />
      <span v-else class="play" aria-hidden="true"></span>
    </div>
```
Script:
```js
import { ref } from 'vue'

defineProps({
  meta: { type: Object, required: true },
  statusNote: { type: String, default: '' },
})
const imgFailed = ref(false)
```
CSS: in `.thumb` add `overflow: hidden;` and remove the `font-family`, `font-size` and `text-align` lines (no text any more); add:
```css
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.play { width: 0; height: 0; border-top: 10px solid transparent; border-bottom: 10px solid transparent; border-left: 15px solid var(--ink-faint); }
```

- [ ] **Step 9: Build**

Run: `cd frontend && npm run build`
Expected: succeeds with no unresolved imports. Also `grep -rn "LibraryView\|listAllClips\|listJobs\|recentJobs" frontend/src` prints nothing.

- [ ] **Step 10: Commit**
```bash
git add frontend/src
git rm frontend/src/views/LibraryView.vue
git commit -m "Add Projects tab and recent videos on Home with real thumbnails"
```

---

### Task 3: "Style all clips" bar and end-to-end browser check

**Files:**
- Create: `frontend/src/utils/clipStyle.js`, `frontend/src/components/StyleAllBar.vue`
- Modify: `frontend/src/components/ClipCard.vue`, `frontend/src/components/ClipList.vue`, `frontend/src/stores/jobStore.js`

**Interfaces:**
- Consumes: `jobStore.updateStyle(clipId, patch)` (existing, debounced PATCH per clip); clip records with `spec.reframe.faces`, `spec.reframe.auto`, `style`.
- Produces: `LAYOUTS`, `PRESETS`, `layoutAllowed(layout, faceCount)` in `utils/clipStyle.js`; `jobStore.applyStyleToAll(patch) -> number` (clips changed).

- [ ] **Step 1: `frontend/src/utils/clipStyle.js`** (moved from `ClipCard.vue` so the bar and the card share them)
```js
export const LAYOUTS = [
  { value: 'follow', label: 'Follow face', minFaces: 1 },
  { value: 'speaker', label: 'Follow speaker', minFaces: 1 },
  { value: 'split', label: 'Split screen', minFaces: 2 },
  { value: 'fit', label: 'Fit with blur', minFaces: 0 },
]

export const PRESETS = [
  { value: 'karaoke', label: 'Karaoke highlight' },
  { value: 'pop', label: 'Pop word-by-word' },
  { value: 'clean', label: 'Clean subtitle' },
]

export function layoutAllowed(layout, faceCount) {
  const entry = LAYOUTS.find(l => l.value === layout)
  return !!entry && faceCount >= entry.minFaces
}
```
In `ClipCard.vue` delete its local `LAYOUTS` and `PRESETS` constants and add `import { LAYOUTS, PRESETS } from '../utils/clipStyle'`.

- [ ] **Step 2: Store action** — add to `actions` in `frontend/src/stores/jobStore.js`:
```js
    // Applies one style to every clip that has a vertical preview. A layout
    // a clip can't use (a face layout with no faces found) falls back to
    // that clip's automatic layout. Hook title text stays per clip.
    applyStyleToAll(patch) {
      let changed = 0
      for (const clip of this.clips) {
        if (!clip.spec) continue
        const clipPatch = { ...patch }
        if ('layout' in clipPatch && !layoutAllowed(clipPatch.layout, clip.spec.reframe.faces.length)) {
          clipPatch.layout = clip.spec.reframe.auto
        }
        this.updateStyle(clip.id, clipPatch)
        changed++
      }
      return changed
    },
```
Add `import { layoutAllowed } from '../utils/clipStyle'` at the top.

- [ ] **Step 3: `frontend/src/components/StyleAllBar.vue`**
```vue
<template>
  <div class="style-all">
    <div class="bar-title">Style all clips</div>
    <div class="fields">
      <label class="field">
        <span>Layout</span>
        <select v-model="form.layout">
          <option v-for="l in LAYOUTS" :key="l.value" :value="l.value">{{ l.label }}</option>
        </select>
      </label>
      <label class="field">
        <span>Captions</span>
        <select v-model="form.captionPreset">
          <option v-for="p in PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
        </select>
      </label>
      <label class="field color">
        <span>Accent colour</span>
        <input v-model="form.accent" type="color" />
      </label>
      <label class="check">
        <input v-model="form.showHook" type="checkbox" /> Show hook title
      </label>
      <button class="apply" @click="apply">Apply to all</button>
    </div>
    <div class="hint">
      <template v-if="appliedCount">Applied to {{ appliedCount }} clip{{ appliedCount === 1 ? '' : 's' }}.</template>
      <template v-else>Clips that can't use a face layout keep their automatic layout. Hook titles stay per clip.</template>
    </div>
  </div>
</template>

<script setup>
import { onUnmounted, reactive, ref } from 'vue'
import { useJobStore } from '../stores/jobStore'
import { LAYOUTS, PRESETS } from '../utils/clipStyle'

const APPLIED_MESSAGE_MS = 2400

const jobStore = useJobStore()
// Start from the first clip's current style so the bar reflects what's there.
const first = jobStore.clips.find(c => c.spec)?.style || {}
const form = reactive({
  layout: first.layout || 'fit',
  captionPreset: first.captionPreset || 'karaoke',
  accent: first.accent || '#FFD400',
  showHook: first.showHook ?? true,
})
const appliedCount = ref(0)
let timer = null

function apply() {
  appliedCount.value = jobStore.applyStyleToAll({ ...form })
  clearTimeout(timer)
  timer = setTimeout(() => { appliedCount.value = 0 }, APPLIED_MESSAGE_MS)
}
onUnmounted(() => clearTimeout(timer))
</script>

<style scoped>
.style-all { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; margin-bottom: 20px; }
.bar-title { font-weight: 600; font-size: 14px; margin-bottom: 10px; }
.fields { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-soft); min-width: 150px; }
.field select {
  font-family: var(--font-sans); font-size: 13.5px; color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 9px; background: #fff;
}
.field.color { min-width: 0; }
.field input[type="color"] { width: 48px; height: 34px; border: 1px solid var(--border); border-radius: 8px; padding: 2px; background: #fff; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-soft); padding-bottom: 8px; }
.apply {
  border: none; border-radius: 8px; padding: 9px 16px; font-size: 13.5px; font-weight: 600;
  font-family: var(--font-sans); color: #fff; background: var(--accent); cursor: pointer;
}
.hint { margin-top: 10px; font-size: 12px; color: var(--ink-faint); }
</style>
```

- [ ] **Step 4: `frontend/src/components/ClipList.vue`** — render the bar above the results header:
```vue
  <div>
    <StyleAllBar v-if="hasVerticalClips" />
    <div class="results-header">
```
and in the script:
```js
import { computed } from 'vue'
import StyleAllBar from './StyleAllBar.vue'

const hasVerticalClips = computed(() => jobStore.clips.some(c => c.spec))
```
(keep the existing `useJobStore` / `ClipCard` imports.)

- [ ] **Step 5: Build**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 6: Commit**
```bash
git add frontend/src
git commit -m "Add a Style all clips bar to the clips page"
```

- [ ] **Step 7: Browser verification** (backend on port 8000 and frontend on 6100 via the `backend` and `frontend` entries in `.claude/launch.json`)

1. If `GET /api/jobs` returns no `done` project, submit `https://www.youtube.com/watch?v=qt6YoGmksCc` (cached locally, so no download) and wait for it to finish (5-15 min).
2. **Home** (`/`): "Recent videos" shows cards with real YouTube thumbnails, title, channel, status and time; a processing card shows a moving progress bar; "See all projects" goes to `/projects`.
3. **Projects** (`/projects`): typing in search filters by title after a short pause; the status tabs filter; clearing both shows everything. `/library` redirects here.
4. Clicking a card opens `/jobs/:id`; the Projects tab stays highlighted; the video card at the top shows the thumbnail; each clip shows the 9:16 preview and its controls.
5. **Style all clips**: pick Pop captions and a new accent, click "Apply to all": every preview updates, the hint says "Applied to N clips", and `read_network_requests` shows one `PATCH /api/clips/<id>/style` per clip returning 200. Pick "Split screen" on a video with no two-face clips: those clips keep their automatic layout.
6. Reload the clips page: the applied styles persist.
7. `read_console_messages` shows no errors. Stop both preview servers when done. Screenshot Home and the clips page for the user.
