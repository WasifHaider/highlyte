from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from . import db, storage
from .pipeline import cut, highlight, ingest, transcript
from .validation import check_clip_filename, check_id

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")
CLIPS_DIR = os.path.join(BASE_DIR, "data", "clips")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)

# Minimum interval between progress-triggered Supabase writes — download
# progress hooks can fire many times per second, and we don't want to
# hammer the DB. Progress is always available immediately in-memory via
# /api/status regardless of this throttle.
PROGRESS_PERSIST_INTERVAL_S = 2.0

app = FastAPI(title="Highlyte")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:6100", "http://127.0.0.1:6100"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    url: str
    # Allowlisted: this is passed straight to faster-whisper, which would
    # otherwise download whatever model name a client sends.
    whisper_model: Literal["tiny", "base", "small", "medium"] = "small"


@dataclass
class Job:
    id: str
    url: str
    status: str = "queued"  # queued|transcribing|analyzing|cutting|done|error
    error: str | None = None
    video_meta: dict[str, Any] | None = None
    transcript_source: str | None = None
    clips: list[dict[str, Any]] = field(default_factory=list)
    # Live progress within the current status, e.g. download %, whisper
    # chunk N/M. Always in-memory/fresh; only sampled into Supabase.
    progress: dict[str, Any] = field(default_factory=dict)
    _last_persist: float = field(default=0.0, repr=False)


JOBS: dict[str, Job] = {}


def _clip_id(job_id: str, idx: int) -> str:
    return f"{job_id}-{idx}"


def _persist_job(job: Job, whisper_model: str, *, throttle: bool = False) -> None:
    now = time.monotonic()
    if throttle and (now - job._last_persist) < PROGRESS_PERSIST_INTERVAL_S:
        return
    job._last_persist = now
    row: dict[str, Any] = {
        "id": job.id,
        "url": job.url,
        "status": job.status,
        "error": job.error,
        "whisper_model": whisper_model,
        "transcript_source": job.transcript_source,
    }
    if job.video_meta:
        row["video_title"] = job.video_meta.get("title")
        row["video_channel"] = job.video_meta.get("channel")
        row["video_duration"] = job.video_meta.get("duration")
    db.upsert_job(row)


def _run_pipeline(job: Job, whisper_model: str) -> None:
    _persist_job(job, whisper_model)
    try:
        job.status = "transcribing"
        job.progress = {"stage": "downloading", "percent": 0, "note": "starting download…"}
        _persist_job(job, whisper_model)

        def on_ingest_progress(stage: str, percent: float | None, note: str) -> None:
            job.progress = {"stage": stage, "percent": percent, "note": note}
            _persist_job(job, whisper_model, throttle=True)

        meta = ingest.ingest(job.url, CACHE_DIR, on_progress=on_ingest_progress)
        job.video_meta = {
            "title": meta.title,
            "channel": meta.channel,
            "duration": meta.duration,
            "durationLabel": ingest.duration_label(meta.duration),
        }
        job.progress = {"stage": "downloading", "percent": 100, "note": "download complete"}
        _persist_job(job, whisper_model)

        def on_transcribe_progress(chunk_idx: int, total_chunks: int, latest_text: str) -> None:
            pct = (chunk_idx / total_chunks * 100.0) if total_chunks else None
            job.progress = {
                "stage": "transcribing",
                "percent": pct,
                "note": f"chunk {chunk_idx}/{total_chunks}",
                "chunk": chunk_idx,
                "totalChunks": total_chunks,
                "latestText": latest_text[:160],
            }
            _persist_job(job, whisper_model, throttle=True)

        job.progress = {"stage": "transcribing", "percent": 0, "note": "loading model…"}
        _persist_job(job, whisper_model)
        tr = transcript.get_transcript(
            meta.video_id, meta.audio_path, whisper_model, on_progress=on_transcribe_progress
        )
        job.transcript_source = tr.source

        job.status = "analyzing"
        job.progress = {"stage": "analyzing", "percent": None, "note": "scoring highlights…"}
        _persist_job(job, whisper_model)
        clips = highlight.detect_highlights(tr.segments)

        job.status = "cutting"
        job.progress = {"stage": "cutting", "percent": 0, "note": f"0/{len(clips)} clips cut"}
        _persist_job(job, whisper_model)
        job_clip_dir = os.path.join(CLIPS_DIR, job.id)
        results = []
        for i, c in enumerate(clips):
            out_name = f"clip_{i}.mp4"
            out_path = os.path.join(job_clip_dir, out_name)
            cut.cut_clip(meta.video_path, c.start, c.end, out_path)

            # Upload to R2 when configured, then drop the local copy — the
            # clip is served back out of the bucket, not local disk (see
            # get_clip below). If the upload fails, keep the local file so
            # the clip is still servable rather than losing it.
            storage_provider = "local"
            storage_key = None
            if storage.is_enabled():
                try:
                    storage_key = storage.clip_key(job.id, out_name)
                    storage.upload_clip(out_path, storage_key)
                    os.remove(out_path)
                    storage_provider = "r2"
                except Exception as e:  # noqa: BLE001
                    storage_key = None
                    print(f"[r2] upload failed for {job.id}/{out_name}, keeping local copy: {e}")

            results.append({
                "id": _clip_id(job.id, i),
                "start": c.start,
                "end": c.end,
                "startLabel": ingest.duration_label(c.start),
                "endLabel": ingest.duration_label(c.end),
                "durationLabel": ingest.duration_label(c.end - c.start),
                "text": c.text,
                "tag": c.tag,
                "score": c.score,
                "downloadUrl": f"/api/clips/{job.id}/{out_name}",
                "storageProvider": storage_provider,
                "storageKey": storage_key,
            })
            job.progress = {
                "stage": "cutting",
                "percent": (i + 1) / len(clips) * 100.0 if clips else 100.0,
                "note": f"{i + 1}/{len(clips)} clips cut",
            }
            _persist_job(job, whisper_model, throttle=True)
        job.clips = results
        job.status = "done"
        job.progress = {}
        _persist_job(job, whisper_model)
        db.insert_clips([
            {
                "id": r["id"],
                "job_id": job.id,
                "idx": i,
                "start_s": r["start"],
                "end_s": r["end"],
                "text": r["text"],
                "tag": r["tag"],
                "score": r["score"],
                "download_path": r["downloadUrl"],
                "storage_provider": r["storageProvider"],
                "storage_key": r["storageKey"],
            }
            for i, r in enumerate(results)
        ])
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = str(e)
        job.progress = {}
        _persist_job(job, whisper_model)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "supabase": db.is_enabled()}


@app.post("/api/generate")
def generate(req: GenerateRequest) -> dict[str, str]:
    job_id = uuid.uuid4().hex[:12]
    job = Job(id=job_id, url=req.url)
    JOBS[job_id] = job
    t = threading.Thread(target=_run_pipeline, args=(job, req.whisper_model), daemon=True)
    t.start()
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
def status(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return {
        "id": job.id,
        "status": job.status,
        "error": job.error,
        "videoMeta": job.video_meta,
        "transcriptSource": job.transcript_source,
        "clips": job.clips,
        "progress": job.progress,
    }


@app.get("/api/jobs")
def jobs() -> list[dict[str, Any]]:
    return db.list_jobs()


@app.get("/api/clips")
def list_all_clips(limit: int = 100) -> list[dict[str, Any]]:
    """Every clip the user has generated, newest first, with its parent
    video's title/channel attached — backs the Library tab. Requires
    Supabase (db.py); returns [] if it isn't configured, same as the
    other list endpoints, since there's nowhere else this history is
    durably tracked (the in-memory JOBS dict is lost on restart)."""
    rows = db.list_clips(limit)
    out = []
    for r in rows:
        job_info = r.get("jobs") or {}
        start_s = r.get("start_s") or 0.0
        end_s = r.get("end_s") or 0.0
        out.append({
            "id": r["id"],
            "jobId": r["job_id"],
            "start": start_s,
            "end": end_s,
            "startLabel": ingest.duration_label(start_s),
            "endLabel": ingest.duration_label(end_s),
            "durationLabel": ingest.duration_label(end_s - start_s),
            "text": r.get("text"),
            "tag": r.get("tag"),
            "score": r.get("score"),
            "downloadUrl": r.get("download_path") or f"/api/clips/{r['job_id']}/clip_{r.get('idx', 0)}.mp4",
            "storageProvider": r.get("storage_provider", "local"),
            "createdAt": r.get("created_at"),
            "videoTitle": job_info.get("video_title"),
            "videoChannel": job_info.get("video_channel"),
            "videoUrl": job_info.get("url"),
        })
    return out


@app.get("/api/clips/{job_id}/{filename}")
def get_clip(job_id: str, filename: str):
    # This path is what's persisted as each clip's downloadUrl, so it
    # stays stable regardless of where the bytes actually live — R2 or
    # local disk — and regardless of a presigned URL's expiry, since a
    # fresh one is generated per request here rather than stored.
    check_id(job_id, "job id")
    check_clip_filename(filename)
    path = os.path.join(CLIPS_DIR, job_id, filename)
    if storage.is_enabled():
        key = storage.clip_key(job_id, filename)
        # clip_url() doesn't verify the object exists (a presigned URL is
        # just a signed request, not a lookup), so check first — otherwise
        # an upload that failed and fell back to the local copy would
        # still redirect to a 404 in the bucket instead of falling
        # through to that local copy below.
        if storage.clip_exists(key):
            url = storage.clip_url(key)
            if url is not None:
                return RedirectResponse(url)
    if not os.path.exists(path):
        raise HTTPException(404, "clip not found")
    return FileResponse(path, media_type="video/mp4", filename=filename)
