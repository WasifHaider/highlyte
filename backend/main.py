from __future__ import annotations

import copy
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
from .pipeline import clipprep, cut, highlight, ingest, transcript
from .spec import default_style
from .validation import check_clip_filename, check_id

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")
CLIPS_DIR = os.path.join(BASE_DIR, "data", "clips")
MODELS_DIR = os.path.join(BASE_DIR, "data", "models")
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
    status: str = "queued"  # queued|transcribing|analyzing|preparing|done|error
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


def _clip_record(job_id: str, idx: int, clip: highlight.Clip, prepared: clipprep.PreparedClip) -> dict[str, Any]:
    spec = prepared.spec
    return {
        "id": spec.clipId,
        "start": clip.start,
        "end": clip.end,
        "startLabel": ingest.duration_label(clip.start),
        "endLabel": ingest.duration_label(clip.end),
        "durationLabel": ingest.duration_label(clip.end - clip.start),
        "text": clip.text,
        "tag": clip.tag,
        "score": clip.score,
        "hookTitle": spec.hookTitle,
        "viralityScore": spec.viralityScore,
        "downloadUrl": f"/api/clips/{job_id}/clip_{idx}.mp4",
        "storageProvider": "r2" if prepared.storage_key else "local",
        "storageKey": prepared.storage_key,
        "spec": spec.model_dump(),
        "style": default_style(spec).model_dump(),
    }


def _clip_row(job_id: str, idx: int, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "job_id": job_id,
        "idx": idx,
        "start_s": record["start"],
        "end_s": record["end"],
        "text": record["text"],
        "tag": record["tag"],
        "score": record["score"],
        "download_path": record["downloadUrl"],
        "storage_provider": record["storageProvider"],
        "storage_key": record["storageKey"],
        "hook_title": record["hookTitle"],
        "virality_score": record["viralityScore"],
        "spec": record["spec"],
        "style": record["style"],
    }


def _clip_row_to_api(r: dict[str, Any]) -> dict[str, Any]:
    start_s = float(r.get("start_s") or 0.0)
    end_s = float(r.get("end_s") or 0.0)
    return {
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
        "hookTitle": r.get("hook_title"),
        "viralityScore": r.get("virality_score"),
        "downloadUrl": r.get("download_path") or f"/api/clips/{r['job_id']}/clip_{r.get('idx', 0)}.mp4",
        "storageProvider": r.get("storage_provider", "local"),
        "storageKey": r.get("storage_key"),
        "createdAt": r.get("created_at"),
        "spec": r.get("spec"),
        "style": r.get("style"),
    }


def _with_source_url(record: dict[str, Any]) -> dict[str, Any]:
    """Copy of a clip record whose spec points the preview Player at the
    clip's own download path. That path proxies to R2 or local disk (see
    get_clip), so no expiring presigned URL ever reaches the client
    or the database."""
    out = dict(record)
    if out.get("spec"):
        out["spec"] = copy.deepcopy(out["spec"])
        out["spec"]["source"]["url"] = out["downloadUrl"]
    return out


def _find_clip(clip_id: str) -> dict[str, Any] | None:
    job_id = clip_id.rsplit("-", 1)[0]
    job = JOBS.get(job_id)
    if job is not None:
        for c in job.clips:
            if c["id"] == clip_id:
                return c
    row = db.get_clip(clip_id)
    return _clip_row_to_api(row) if row else None


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

        job.status = "preparing"
        job.progress = {"stage": "preparing", "percent": 0, "note": f"0/{len(clips)} clips prepared"}
        _persist_job(job, whisper_model)

        groq_key = os.environ.get("GROQ_KEY") or None
        # The captions transcript has no word timings, so clip words come
        # from Groq; decide once per episode whether it needs the Roman
        # Urdu seed prompt (see transcript._detect_needs_roman_urdu_hint).
        prompt = None
        if tr.source == "captions" and groq_key:
            if transcript._detect_needs_roman_urdu_hint(meta.audio_path, groq_key):
                prompt = transcript.ROMAN_URDU_HINDI_SEED

        for i, c in enumerate(clips):
            def on_step(step: str, i: int = i) -> None:
                job.progress = {
                    "stage": "preparing",
                    "percent": i / len(clips) * 100.0,
                    "note": f"clip {i + 1}/{len(clips)}: {step}",
                }
                _persist_job(job, whisper_model, throttle=True)

            prepared = clipprep.prepare_clip(
                job_id=job.id, idx=i, clip=c,
                video_path=meta.video_path, video_duration=meta.duration,
                segments=tr.segments, transcript_source=tr.source, audio_path=meta.audio_path,
                clips_dir=CLIPS_DIR, models_dir=MODELS_DIR,
                groq_key=groq_key, prompt=prompt, on_step=on_step,
            )
            record = _clip_record(job.id, i, c, prepared)
            job.clips.append(record)
            # Saved per clip, so a failure later in the job doesn't lose
            # the clips already prepared.
            db.insert_clips([_clip_row(job.id, i, record)])

        job.status = "done"
        job.progress = {}
        _persist_job(job, whisper_model)
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
    check_id(job_id, "job id")
    job = JOBS.get(job_id)
    if job is not None:
        return {
            "id": job.id,
            "status": job.status,
            "error": job.error,
            "videoMeta": job.video_meta,
            "transcriptSource": job.transcript_source,
            "clips": [_with_source_url(c) for c in job.clips],
            "progress": job.progress,
        }

    # Not in memory (e.g. the backend restarted): rebuild it from Supabase.
    row = db.get_job(job_id)
    if row is None:
        raise HTTPException(404, "job not found")
    status_value, error = row["status"], row.get("error")
    if status_value not in ("done", "error"):
        # Its worker thread died with the old process; it will never finish.
        status_value, error = "error", "Processing was interrupted by a server restart. Please submit the video again."
    video_meta = None
    if row.get("video_title"):
        video_meta = {
            "title": row.get("video_title"),
            "channel": row.get("video_channel"),
            "duration": row.get("video_duration"),
            "durationLabel": ingest.duration_label(float(row.get("video_duration") or 0)),
        }
    return {
        "id": row["id"],
        "status": status_value,
        "error": error,
        "videoMeta": video_meta,
        "transcriptSource": row.get("transcript_source"),
        "clips": [_with_source_url(_clip_row_to_api(r)) for r in db.list_clips_for_job(job_id)],
        "progress": {},
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
    out = []
    for r in db.list_clips(limit):
        job_info = r.get("jobs") or {}
        record = _clip_row_to_api(r)
        record.update({
            "videoTitle": job_info.get("video_title"),
            "videoChannel": job_info.get("video_channel"),
            "videoUrl": job_info.get("url"),
        })
        out.append(record)
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
