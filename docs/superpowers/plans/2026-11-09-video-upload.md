# Video Upload (3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a teammate upload a video file (up to 5 GB) instead of pasting a YouTube link, and get the same clips.

**Architecture:** The browser uploads straight to R2 with presigned multipart URLs (Cloudflare Tunnel caps bodies at 100 MB). The job's source becomes `upload:{id}`; `ingest.ingest` and `ingest.SectionSource` hand such sources to a new `backend/pipeline/uploads.py`, so the rest of the pipeline is unchanged.

**Tech Stack:** FastAPI, boto3 (S3 API on R2), ffmpeg/ffprobe, Vue 3 + Pinia + axios.

**Spec:** `docs/superpowers/specs/2026-11-09-video-upload-design.md`

## Global Constraints

- Max size 5 GB (5 * 1024**3 bytes); extensions `.mp4 .mov .mkv .webm .m4v` (case-insensitive).
- Part size 64 MiB; presigned part URLs valid 6 hours.
- R2 keys: `uploads/{id}/source{.ext}` and `uploads/{id}/thumb.jpg`; upload id = 12 lowercase hex chars.
- Job source string: `upload:{id}`. Video id: `up-{id}`. Channel: `Uploaded video`.
- Error copy: "File is over 5 GB.", "That file type isn't supported. Use MP4, MOV, MKV, WebM or M4V.", "Upload failed. Check your connection and try again."
- Run Python with `.venv/Scripts/python -m pytest`; frontend check with `npm run build` in `frontend/`.

---

### Task 1: `uploads.py` storage and ingest

**Files:**
- Create: `backend/pipeline/uploads.py`
- Test: `tests/test_uploads.py`

**Interfaces:**
- Produces:
  - `MAX_BYTES: int`, `PART_SIZE: int`, `ALLOWED_EXTS: tuple[str, ...]`, `PREFIX = "upload:"`
  - `is_upload(url: str | None) -> bool`
  - `upload_id_of(url: str) -> str` (raises `ValueError` if not a valid `upload:` source)
  - `source_key(upload_id, ext) -> str`, `thumb_key(upload_id) -> str`
  - `start(upload_id, filename, size, content_type, team_id) -> dict` with `{"key", "r2UploadId", "partSize", "partUrls"}`
  - `complete(key, r2_upload_id, parts: list[dict]) -> None`, `abort(key, r2_upload_id) -> None`
  - `ingest_upload(upload_id, cache_dir) -> ingest.VideoMeta`
  - `source_path(upload_id, cache_dir) -> str`
  - `delete_upload(upload_id) -> None`
  - `open_thumb(upload_id)` -> readable stream
  - `class UploadError(ValueError)` for size/type validation (`check(filename, size) -> str` returns the ext)

Steps:
- [ ] Write tests with a `FakeR2` (in-memory objects with metadata, multipart create/complete/abort, presign returns fake URLs, `download_file`, `upload_file`, `head_object`, `list_objects_v2`, `delete_object`, `get_object`) monkeypatched as `storage.get_client`, and a 2-second test video generated with ffmpeg (`testsrc` + `sine`). Cover: validation (size 0, > 5 GB, bad ext); `start` makes one presigned URL per 64 MiB part and stores filename metadata; `ingest_upload` pulls the source, makes audio, duration ~2 s, title from filename, thumbnail uploaded once and `thumbnail_url == "/api/uploads/{id}/thumb.jpg"`; second call reuses the cache (no second R2 download); `source_path` re-downloads after the cached file is deleted; `delete_upload` removes source and thumb; `upload_id_of` rejects bad ids.
- [ ] Run, see them fail. Implement. Run, see them pass.

### Task 2: route uploads through ingest

**Files:**
- Modify: `backend/pipeline/ingest.py` (`ingest()` and `SectionSource._video`)
- Test: `tests/test_uploads.py`

**Interfaces:**
- Consumes: `uploads.is_upload`, `uploads.upload_id_of`, `uploads.ingest_upload`, `uploads.source_path` (imported lazily inside the functions to avoid a circular import, since `uploads` imports `VideoMeta` from `ingest`).

Steps:
- [ ] Test: `ingest.ingest("upload:{id}", cache)` returns the upload's meta without touching yt-dlp; `SectionSource("upload:{id}", ...)(0, 1, out)` cuts from the uploaded file.
- [ ] Implement; run full ingest + uploads tests.

### Task 3: API endpoints, purge and retry

**Files:**
- Modify: `backend/main.py` (new endpoints, `_purge_job(keep_upload)`, `retry_failed`, `/api/generate` url check, `/api/health`)
- Test: `tests/test_uploads_api.py`

**Interfaces:**
- `POST /api/uploads` body `{filename, size, contentType}` -> `{uploadId, partSize, partUrls}`; 400 with spec copy on bad size/type; 503 without R2.
- `POST /api/uploads/{id}/complete` body `{parts: [{partNumber, etag}], language}` -> `{job_id}`; 404 unknown/other team.
- `DELETE /api/uploads/{id}` -> 204; 404 unknown/other team.
- `GET /api/uploads/{id}/thumb.jpg` -> image stream; 404 unless a job of the caller's team has source `upload:{id}` (checked via in-memory JOBS, then `db.find_job_by_url`).
- `/api/health` gains `"uploads": storage.is_enabled()`.
- `/api/generate` -> 422 unless url starts with `http://` or `https://`.

Steps:
- [ ] Tests for each behaviour above, plus: purge of an upload job calls `uploads.delete_upload`; retry of a failed upload job keeps the upload and the new job has the same `upload:` url.
- [ ] Implement; add `db.find_job_by_url(url) -> dict | None` (Supabase `jobs` select by url, limit 1; None when DB disabled). Run the whole suite.

### Task 4: frontend upload

**Files:**
- Create: `frontend/src/services/uploader.js`
- Modify: `frontend/src/services/highlyteApi.js`, `frontend/src/stores/jobStore.js`, `frontend/src/composables/useGenerate.js`, `frontend/src/views/HomeView.vue`, `frontend/src/components/TopBar.vue`

**Interfaces:**
- `highlyteApi`: `startUpload({filename, size, contentType})`, `completeUpload(uploadId, parts, language)`, `abortUpload(uploadId)`.
- `uploader.uploadFile(file, {onProgress(loaded, total), signal}) -> {uploadId, parts}`: PUTs parts with `fetch` (no credentials, no custom headers), 3 at a time, 3 retries each, reads `ETag`.
- `jobStore.submitUpload(file, language, {onProgress, signal}) -> jobId` (resets like `submitUrl`).
- `useGenerate` adds `uploading`, `uploadProgress {name, percent, speed}`, `uploadsEnabled`, `onUpload(file)`, `cancelUpload()`, plus client-side size/type checks with the spec copy.

Steps:
- [ ] Implement; Home hero: "Upload a video" button, hidden file input, drag-and-drop on the form, progress row with Cancel. TopBar: small upload icon button with the same behaviour.
- [ ] `npm run build` passes.

### Task 5: setup doc and final checks

**Files:**
- Create: `docs/video-upload-setup.md` (R2 CORS JSON, lifecycle rule, local origin)
- Modify: `README.md` (one line pointing to it)

Steps:
- [ ] Write doc. Run full pytest and frontend build. Review the whole diff.
