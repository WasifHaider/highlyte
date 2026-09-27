from __future__ import annotations

import contextlib
import copy
import os
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import math

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, ValidationError

from . import accounts, captions, db, projects, render, srt, storage
from .accounts import Member, current_member
from .pipeline import clipprep, cut, groq_llm, ingest, scoring, selection, transcript
from .pipeline.segments import Segment
from .pipeline.segments import from_dict as segment_from_dict
from .spec import ClipStyle, Word, default_style, window_duration
from . import validation
from .validation import check_clip_filename, check_id

MIN_CLIP_S = 8.0
MAX_CLIP_S = 60.0

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
    # Production traffic arrives through the Vercel /api rewrite, which is
    # same-origin, so CORS_ORIGINS is only for callers hitting the API directly.
    allow_origins=["http://localhost:6100", "http://127.0.0.1:6100"]
    + [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(accounts.session_middleware)
app.include_router(accounts.router)

RENDERER_PACKAGE_JSON = os.path.join(BASE_DIR, "renderer", "package.json")
MAX_ZIP_RENDERS = 20
# How long a browser may reuse /api/clips's redirect to a presigned R2 URL.
CLIP_REDIRECT_MAX_AGE_S = 600


class GenerateRequest(BaseModel):
    url: str
    language: Literal["hinglish", "english"] = "hinglish"


@dataclass
class Job:
    id: str
    url: str
    status: str = "queued"  # queued|transcribing|analyzing|preparing|done|error|selection_failed
    error: str | None = None
    video_meta: dict[str, Any] | None = None
    transcript_source: str | None = None
    clips: list[dict[str, Any]] = field(default_factory=list)
    # Live progress within the current status, e.g. download %, whisper
    # chunk N/M. Always in-memory/fresh; only sampled into Supabase.
    progress: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    team_id: str | None = None
    created_by: str | None = None
    language_requested: str = "hinglish"
    language_used: str | None = None
    language_note: str | None = None
    selection_note: str | None = None
    alternates: list[dict[str, Any]] = field(default_factory=list)
    _last_persist: float = field(default=0.0, repr=False)


JOBS: dict[str, Job] = {}

_MISSING = object()

# Guards the check-then-set on Job.status in retry_selection: without it, two
# concurrent POSTs (a double-click, or two requests racing after a restart,
# each building their own Job from the row) could both see "selection_failed"
# and both start a selection thread, doubling Groq quota use and writing the
# same clip ids twice.
_SELECTION_LOCK = threading.Lock()


def _require_job(member: Member, job_id: str) -> None:
    """404 unless the job exists and belongs to the caller's team. Another
    team's job gets the same answer as a missing one, so ids can't be probed."""
    job = JOBS.get(job_id)
    if job is not None:
        team_id = job.team_id
    else:
        row = db.get_job(job_id)
        team_id = row.get("team_id") if row is not None else _MISSING
    if team_id != member.team_id:
        raise HTTPException(404, "job not found")


def _job_id_of_clip(clip_id: str) -> str:
    return clip_id.rsplit("-", 1)[0]


def _persist_job(job: Job, *, throttle: bool = False) -> None:
    now = time.monotonic()
    if throttle and (now - job._last_persist) < PROGRESS_PERSIST_INTERVAL_S:
        return
    job._last_persist = now
    row: dict[str, Any] = {
        "id": job.id,
        "url": job.url,
        "status": job.status,
        "error": job.error,
        "language_requested": job.language_requested,
        "language_used": job.language_used,
        "language_note": job.language_note,
        "transcript_source": job.transcript_source,
        "selection_note": job.selection_note,
        "team_id": job.team_id,
        "created_by": job.created_by,
        "alternates": job.alternates,
    }
    if job.video_meta:
        row["video_title"] = job.video_meta.get("title")
        row["video_channel"] = job.video_meta.get("channel")
        row["video_duration"] = job.video_meta.get("duration")
        row["video_id"] = job.video_meta.get("videoId")
        row["thumbnail_url"] = job.video_meta.get("thumbnailUrl")
    db.upsert_job(row)


def _qa_flags(flags: list[str], face_at_start: bool | None) -> list[str]:
    out = list(flags)
    if face_at_start is False and "no_face_start" not in out:
        out.append("no_face_start")
    return out


def _video_meta_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row.get("video_title"):
        return None
    video_id = row.get("video_id") or projects.youtube_id(row.get("url"))
    return {
        "title": row.get("video_title"),
        "channel": row.get("video_channel"),
        "duration": row.get("video_duration"),
        "durationLabel": ingest.duration_label(float(row.get("video_duration") or 0)),
        "videoId": video_id,
        "thumbnailUrl": projects.thumbnail_url(video_id, row.get("thumbnail_url")),
    }


def _job_from_row(row: dict[str, Any]) -> Job:
    return Job(
        id=row["id"], url=row["url"], status=row["status"], error=row.get("error"),
        video_meta=_video_meta_from_row(row), transcript_source=row.get("transcript_source"),
        team_id=row.get("team_id"), created_by=row.get("created_by"),
        language_requested=row.get("language_requested") or "hinglish",
        language_used=row.get("language_used"), language_note=row.get("language_note"),
        selection_note=row.get("selection_note"),
        alternates=row.get("alternates") or [],
        created_at=row.get("created_at") or datetime.now(timezone.utc).isoformat(),
    )


def _start_thread(target, *args) -> None:
    threading.Thread(target=target, args=args, daemon=True).start()


def _clip_record(
    job_id: str, idx: int, clip: selection.Clip, prepared: clipprep.PreparedClip, revision: int = 0,
) -> dict[str, Any]:
    spec = prepared.spec
    filename = prepared.filename or clipprep.clip_filename(idx, revision)
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
        "downloadUrl": f"/api/clips/{job_id}/{filename}",
        "storageProvider": "r2" if prepared.storage_key else "local",
        "storageKey": prepared.storage_key,
        "spec": spec.model_dump(),
        "style": default_style(spec).model_dump(),
        "qaFlags": _qa_flags(clip.flags, prepared.face_at_start),
        "reason": clip.reason,
        "pendingAction": None,
        "actionError": None,
        "boundsOriginal": None,
        "boundsEdited": False,
        "revision": revision,
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
        "qa_flags": record["qaFlags"],
        "reason": record["reason"],
        "revision": record["revision"],
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
        "wordsOriginal": r.get("words_original"),
        "captionsEdited": r.get("words_original") is not None,
        "qaFlags": r.get("qa_flags") or [],
        "reason": r.get("reason") or "",
        "pendingAction": r.get("pending_action"),
        "actionError": r.get("action_error"),
        "boundsOriginal": r.get("bounds_original"),
        "boundsEdited": r.get("bounds_original") is not None,
        "revision": r.get("revision") or 0,
    }


def _with_source_url(record: dict[str, Any]) -> dict[str, Any]:
    """Copy of a clip record whose spec points the preview Player at the
    clip's own download path. That path proxies to R2 or local disk (see
    get_clip), so no expiring presigned URL ever reaches the client
    or the database."""
    out = dict(record)
    out.pop("wordsOriginal", None)
    out.pop("boundsOriginal", None)
    if out.get("spec"):
        out["spec"] = copy.deepcopy(out["spec"])
        download_url = out["downloadUrl"]
        revision = record.get("revision") or 0
        out["spec"]["source"]["url"] = f"{download_url}?r={revision}" if revision > 0 else download_url
        # The card's poster, next to the segment (clip_2.mp4 -> clip_2.jpg).
        # Clips cut before posters existed 404 here; the card falls back.
        out["thumbUrl"] = storage.thumb_filename(download_url)
    return out


def _clear_orphaned_pending_action(row: dict[str, Any], record: dict[str, Any]) -> None:
    """A clip rebuilt from the database (job not in memory, e.g. after a
    restart) may still carry a pending_action from before: the thread that
    would have cleared it is gone, so left alone it would 409 every action
    and edit on this clip forever. Clear it here, in memory and in the row,
    the same way the status DB fallback already reports it."""
    if row.get("pending_action"):
        record["pendingAction"] = None
        record["actionError"] = "Interrupted by a server restart. Try again."
        db.update_clip(row["id"], {"pending_action": None, "action_error": record["actionError"]})


def _find_clip(clip_id: str) -> dict[str, Any] | None:
    job_id = clip_id.rsplit("-", 1)[0]
    job = JOBS.get(job_id)
    if job is not None:
        for c in job.clips:
            if c["id"] == clip_id:
                return c
    row = db.get_clip(clip_id)
    if row is None:
        return None
    record = _clip_row_to_api(row)
    _clear_orphaned_pending_action(row, record)
    return record


def _build_props(clip_id: str, style: dict[str, Any]) -> tuple[dict[str, Any], float]:
    """Remotion input props for a Lambda render. Lambda can't reach this
    machine, so the source must be a presigned R2 URL (fresh, since those
    expire)."""
    record = _find_clip(clip_id)
    if record is None or not record.get("spec"):
        raise RuntimeError("clip has no spec")
    if not record.get("storageKey"):
        raise RuntimeError("clip source is not in R2")
    spec = copy.deepcopy(record["spec"])
    spec["source"]["url"] = storage.clip_url(record["storageKey"])
    return {"spec": spec, "style": style}, spec["end"] - spec["start"]


RENDER_SERVICE = render.build_service(_build_props, storage.upload_fileobj)
if RENDER_SERVICE is not None:
    for _problem in render.check_versions(RENDERER_PACKAGE_JSON, os.environ.get("REMOTION_FUNCTION_NAME")):
        print(f"[render] VERSION MISMATCH: {_problem}")


def _clip_for_style(clip_id: str, member: Member) -> dict[str, Any]:
    check_id(clip_id, "clip id")
    _require_job(member, _job_id_of_clip(clip_id))
    record = _find_clip(clip_id)
    if record is None:
        raise HTTPException(404, "clip not found")
    if not record.get("spec"):
        raise HTTPException(409, "This clip was made before vertical clips existed. Re-run the video to get one.")
    return record


def _save_style(record: dict[str, Any], style: ClipStyle) -> dict[str, Any]:
    record["style"] = style.model_dump()
    db.update_clip(record["id"], {"style": record["style"]})
    return record["style"]


def _select_and_prepare(job: Job, meta: ingest.VideoMeta, segs: list[Segment], loudness: list[float]) -> None:
    """Pick clips from the transcript, then cut and frame each one. A
    selection that cannot run is not an error: the transcript is kept and
    the job waits in selection_failed for Retry selection."""
    job.status = "analyzing"
    job.progress = {"stage": "analyzing", "percent": None, "note": "picking clips…"}
    _persist_job(job)
    try:
        result = selection.select(segs, loudness)
    except selection.SelectionFailed as e:
        job.status = "selection_failed"
        job.error = str(e)
        job.progress = {}
        _persist_job(job)
        return
    job.selection_note = result.note
    job.alternates = result.alternates
    clips = result.clips
    word_segments = transcript.word_segments(segs)

    job.status = "preparing"
    job.progress = {"stage": "preparing", "percent": 0, "note": f"0/{len(clips)} clips prepared"}
    _persist_job(job)

    for i, c in enumerate(clips):
        def on_step(step: str, i: int = i) -> None:
            job.progress = {
                "stage": "preparing",
                "percent": i / len(clips) * 100.0,
                "note": f"clip {i + 1}/{len(clips)}: {step}",
            }
            _persist_job(job, throttle=True)

        prepared = clipprep.prepare_clip(
            job_id=job.id, idx=i, clip=c,
            video_path=meta.video_path, video_duration=meta.duration,
            segments=word_segments,
            clips_dir=CLIPS_DIR, models_dir=MODELS_DIR, on_step=on_step,
        )
        record = _clip_record(job.id, i, c, prepared)
        job.clips.append(record)
        # Saved per clip, so a failure later in the job doesn't lose
        # the clips already prepared.
        db.insert_clips([_clip_row(job.id, i, record)])

    job.status = "done"
    job.progress = {}
    _persist_job(job)


def _run_selection_retry(job: Job, stored: dict[str, Any]) -> None:
    try:
        meta = ingest.ingest(job.url, CACHE_DIR)
    except Exception as e:  # noqa: BLE001
        # The video is still there and Retry selection will try the
        # download again, so this stays retryable rather than a dead end.
        job.status = "selection_failed"
        job.error = f"Couldn't fetch the video again: {e}. Try again."
        job.progress = {}
        _persist_job(job)
        return
    try:
        segs = [segment_from_dict(d) for d in stored.get("segments") or []]
        _select_and_prepare(job, meta, segs, stored.get("loudness") or [])
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = str(e)
        job.progress = {}
        _persist_job(job)


def _run_pipeline(job: Job) -> None:
    _persist_job(job)
    try:
        job.status = "transcribing"
        job.progress = {"stage": "downloading", "percent": 0, "note": "starting download…"}
        _persist_job(job)

        def on_ingest_progress(stage: str, percent: float | None, note: str) -> None:
            job.progress = {"stage": stage, "percent": percent, "note": note}
            _persist_job(job, throttle=True)

        meta = ingest.ingest(job.url, CACHE_DIR, on_progress=on_ingest_progress)
        job.video_meta = {
            "title": meta.title,
            "channel": meta.channel,
            "duration": meta.duration,
            "durationLabel": ingest.duration_label(meta.duration),
            "videoId": meta.video_id,
            "thumbnailUrl": projects.thumbnail_url(meta.video_id, meta.thumbnail_url),
        }
        job.progress = {"stage": "downloading", "percent": 100, "note": "download complete"}
        _persist_job(job)

        def on_transcribe_progress(part: int, total: int, latest_text: str) -> None:
            job.progress = {
                "stage": "transcribing",
                "percent": (part / total * 100.0) if total else None,
                "note": f"part {part} of {total}",
                "chunk": part,
                "totalChunks": total,
                "latestText": latest_text[:160],
            }
            _persist_job(job, throttle=True)

        job.progress = {"stage": "transcribing", "percent": 0, "note": "checking language…"}
        _persist_job(job)
        tr = transcript.transcribe(meta.audio_path, job.language_requested, on_progress=on_transcribe_progress)
        job.language_used, job.language_note = tr.language, tr.note
        job.transcript_source = tr.source
        _persist_job(job)
        db.save_transcript(job.id, tr.language, tr.source, [s.to_dict() for s in tr.segments], tr.loudness)
        _select_and_prepare(job, meta, tr.segments, tr.loudness)
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = str(e)
        job.progress = {}
        _persist_job(job)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "supabase": db.is_enabled(),
        "auth": db.is_enabled(),
        "rendering": RENDER_SERVICE is not None,
    }


@app.post("/api/generate")
def generate(req: GenerateRequest, member: Member = Depends(current_member)) -> dict[str, str]:
    job_id = uuid.uuid4().hex[:12]
    job = Job(id=job_id, url=req.url, team_id=member.team_id, created_by=member.user_id,
              language_requested=req.language)
    JOBS[job_id] = job
    t = threading.Thread(target=_run_pipeline, args=(job,), daemon=True)
    t.start()
    return {"job_id": job_id}


@app.post("/api/jobs/{job_id}/select")
def retry_selection(job_id: str, member: Member = Depends(current_member)) -> dict[str, str]:
    """Re-run clip selection from the stored transcript after it failed
    (usually Groq's daily limit). Download and transcription are skipped."""
    check_id(job_id, "job id")
    _require_job(member, job_id)
    with _SELECTION_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            row = db.get_job(job_id)
            if row is None:
                raise HTTPException(404, "job not found")
            # Built locally and only installed into JOBS (below, still under
            # the lock) once the status check passes: installing first would
            # leave e.g. a done job in memory with no clips, or an
            # interrupted one reported as still processing. The lock is what
            # stops a racing second request from re-passing the check.
            job = _job_from_row(row)
        if job.status != "selection_failed":
            raise HTTPException(409, "Clip selection can only be retried after it failed.")
        previous_error = job.error
        job.status, job.error, job.selection_note, job.clips = "analyzing", None, None, []
        job.progress = {"stage": "analyzing", "percent": None, "note": "picking clips…"}
        JOBS[job_id] = job
        _persist_job(job)

    # The Supabase round trip runs outside the lock so it can't block other
    # requests; a missing transcript just puts the job back where it was.
    stored = db.get_transcript(job_id)
    if not stored or not stored.get("segments"):
        with _SELECTION_LOCK:
            job.status, job.error = "selection_failed", previous_error
            _persist_job(job)
        raise HTTPException(409, "This video's transcript wasn't saved. Submit the video again.")
    _start_thread(_run_selection_retry, job, stored)
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
def status(job_id: str, member: Member = Depends(current_member)) -> dict[str, Any]:
    check_id(job_id, "job id")
    _require_job(member, job_id)
    job = JOBS.get(job_id)
    if job is not None:
        return {
            "id": job.id,
            "status": job.status,
            "error": job.error,
            "videoMeta": job.video_meta,
            "transcriptSource": job.transcript_source,
            "language": job.language_used,
            "languageNote": job.language_note,
            "selectionNote": job.selection_note,
            "clips": [_with_source_url(c) for c in job.clips],
            "progress": job.progress,
            "alternatesLeft": len(job.alternates),
        }

    # Not in memory (e.g. the backend restarted): rebuild it from Supabase.
    row = db.get_job(job_id)
    if row is None:
        raise HTTPException(404, "job not found")
    status_value, error = row["status"], row.get("error")
    if status_value not in ("done", "error", "selection_failed"):
        # Its worker thread died with the old process; it will never finish.
        status_value, error = "error", projects.INTERRUPTED_ERROR
    video_meta = _video_meta_from_row(row)
    clips = []
    for r in db.list_clips_for_job(job_id):
        c = _clip_row_to_api(r)
        # Its action thread died with the old process too, but unlike the
        # job status above this doesn't fail the whole job — just that one
        # clip, which is safe to retry.
        _clear_orphaned_pending_action(r, c)
        clips.append(c)
    return {
        "id": row["id"],
        "status": status_value,
        "error": error,
        "videoMeta": video_meta,
        "transcriptSource": row.get("transcript_source"),
        "language": row.get("language_used"),
        "languageNote": row.get("language_note"),
        "selectionNote": row.get("selection_note"),
        "clips": [_with_source_url(c) for c in clips],
        "progress": {},
        "alternatesLeft": len(row.get("alternates") or []),
    }


@app.get("/api/jobs")
def list_projects(
    limit: int = Query(100, ge=1, le=200),
    q: str | None = None,
    status: Literal["processing", "done", "error"] | None = None,
    member: Member = Depends(current_member),
) -> list[dict[str, Any]]:
    """Every submitted video for the Home and Projects pages, newest first."""
    rows = db.list_jobs(member.team_id, limit=200)
    counts = db.count_clips_by_job([r["id"] for r in rows])
    memory = [projects.from_job(job) for job in list(JOBS.values()) if job.team_id == member.team_id]
    return projects.build_projects(memory, rows, counts, q=q, status=status, limit=limit)


@app.get("/api/clips")
def list_all_clips(limit: int = 100, member: Member = Depends(current_member)) -> list[dict[str, Any]]:
    """Every clip the user has generated, newest first, with its parent
    video's title/channel attached (kept for API consumers; the Library
    tab was replaced by Projects). Requires Supabase (db.py); returns []
    if it isn't configured, same as the other list endpoints, since
    there's nowhere else this history is durably tracked (the in-memory
    JOBS dict is lost on restart)."""
    out = []
    for r in db.list_clips(member.team_id, limit=limit):
        job_info = r.get("jobs") or {}
        record = _with_source_url(_clip_row_to_api(r))
        record.update({
            "videoTitle": job_info.get("video_title"),
            "videoChannel": job_info.get("video_channel"),
            "videoUrl": job_info.get("url"),
        })
        out.append(record)
    return out


# Declared before /api/clips/{job_id}/{filename} so "captions.srt" isn't
# taken as a clip filename (both routes have two path segments; Starlette
# matches whichever route was registered first).
@app.get("/api/clips/{clip_id}/captions.srt")
def get_captions_srt(clip_id: str, member: Member = Depends(current_member)) -> Response:
    spec = _clip_for_style(clip_id, member)["spec"]
    return Response(
        srt.build_srt(spec), media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="highlyte-{clip_id}.srt"'},
    )


@app.get("/api/clips/{job_id}/{filename}")
def get_clip(job_id: str, filename: str, member: Member = Depends(current_member)):
    # This path is what's persisted as each clip's downloadUrl, so it
    # stays stable regardless of where the bytes actually live — R2 or
    # local disk — and regardless of a presigned URL's expiry, since a
    # fresh one is generated per request here rather than stored.
    check_id(job_id, "job id")
    check_clip_filename(filename)
    _require_job(member, job_id)
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
                # Lets the browser reuse the redirect for a few minutes
                # instead of asking again per video element; kept below a
                # cached presigned URL's minimum remaining life.
                return RedirectResponse(url, headers={"Cache-Control": f"private, max-age={CLIP_REDIRECT_MAX_AGE_S}"})
    if not os.path.exists(path):
        raise HTTPException(404, "clip not found")
    if filename.endswith(".jpg"):
        return FileResponse(path, media_type="image/jpeg")
    return FileResponse(path, media_type="video/mp4", filename=filename)


@app.patch("/api/clips/{clip_id}/style")
def update_style(clip_id: str, style: ClipStyle = Body(...), member: Member = Depends(current_member)) -> dict[str, Any]:
    record = _clip_for_style(clip_id, member)
    if record.get("pendingAction"):
        raise HTTPException(409, "This clip is being replaced. Wait for it to finish.")
    return _save_style(record, style)


class CaptionsBody(BaseModel):
    words: list[dict[str, Any]]


def _captions_reply(record: dict[str, Any]) -> dict[str, Any]:
    return {"words": record["spec"]["words"], "captionsEdited": record.get("wordsOriginal") is not None}


@app.put("/api/clips/{clip_id}/captions")
def save_captions(clip_id: str, body: CaptionsBody = Body(...), member: Member = Depends(current_member)) -> dict[str, Any]:
    record = _clip_for_style(clip_id, member)
    if record.get("pendingAction"):
        raise HTTPException(409, "This clip is being replaced. Wait for it to finish.")
    spec = record["spec"]
    try:
        words = captions.validate_words(body.words, window_duration(spec) or (spec["end"] - spec["start"]))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    words_original = record["wordsOriginal"] if record.get("wordsOriginal") is not None else spec["words"]
    new_spec = {**spec, "words": [w.model_dump() for w in words]}
    try:
        db.update_clip_checked(record["id"], {"spec": new_spec, "words_original": words_original})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, "Couldn't save captions. Try again.") from e
    record["wordsOriginal"] = words_original  # kept from the first edit, for Reset
    record["spec"] = new_spec
    record["captionsEdited"] = record.get("wordsOriginal") is not None
    return _captions_reply(record)


@app.post("/api/clips/{clip_id}/captions/reset")
def reset_captions(clip_id: str, member: Member = Depends(current_member)) -> dict[str, Any]:
    record = _clip_for_style(clip_id, member)
    if record.get("pendingAction"):
        raise HTTPException(409, "This clip is being replaced. Wait for it to finish.")
    if record.get("wordsOriginal") is not None:
        new_spec = {**record["spec"], "words": record["wordsOriginal"]}
        try:
            db.update_clip_checked(record["id"], {"spec": new_spec, "words_original": None})
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, "Couldn't save captions. Try again.") from e
        record["spec"] = new_spec
        record["wordsOriginal"] = None
        record["captionsEdited"] = record.get("wordsOriginal") is not None
    return _captions_reply(record)


class BoundsBody(BaseModel):
    start: float
    end: float


def _bounds_reply(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "start": record["spec"]["start"],
        "end": record["spec"]["end"],
        "boundsEdited": record.get("boundsOriginal") is not None,
    }


def _apply_bounds(record: dict[str, Any], new_start: float, new_end: float, bounds_original: dict[str, float] | None) -> None:
    """Move the spec's window to new_start/new_end, shifting the record's
    source-time start/end by the same deltas, and persist. Shared by the
    PATCH and reset handlers, which differ only in what they pass here."""
    spec = record["spec"]
    old_start, old_end = spec["start"], spec["end"]
    new_spec = {**spec, "start": new_start, "end": new_end}
    new_record_start = record["start"] + (new_start - old_start)
    new_record_end = record["end"] + (new_end - old_end)
    fields = {
        "spec": new_spec,
        "bounds_original": bounds_original,
        "start_s": new_record_start,
        "end_s": new_record_end,
    }
    try:
        db.update_clip_checked(record["id"], fields)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, "Couldn't save the trim. Try again.") from e
    record["spec"] = new_spec
    record["boundsOriginal"] = bounds_original
    record["boundsEdited"] = bounds_original is not None
    record["start"] = new_record_start
    record["end"] = new_record_end
    record["startLabel"] = ingest.duration_label(new_record_start)
    record["endLabel"] = ingest.duration_label(new_record_end)
    record["durationLabel"] = ingest.duration_label(new_record_end - new_record_start)


@app.patch("/api/clips/{clip_id}/bounds")
def update_bounds(clip_id: str, body: BoundsBody = Body(...), member: Member = Depends(current_member)) -> dict[str, Any]:
    record = _clip_for_style(clip_id, member)
    spec = record["spec"]
    window = window_duration(spec)
    if window is None:
        raise HTTPException(409, "Re-run the video to trim this clip.")
    if record.get("pendingAction"):
        raise HTTPException(409, "This clip is being replaced. Wait for it to finish.")
    start, end = body.start, body.end
    if not (math.isfinite(start) and math.isfinite(end)) or not (0 <= start < end <= window + 1e-6):
        raise HTTPException(422, "That is outside the spare video.")
    length = end - start
    if length < MIN_CLIP_S:
        raise HTTPException(422, "Clips must be at least 8 s.")
    if length > MAX_CLIP_S:
        raise HTTPException(422, "Clips can be at most 60 s.")
    start, end = round(start, 3), round(end, 3)
    bounds_original = record.get("boundsOriginal") or {"start": spec["start"], "end": spec["end"]}
    _apply_bounds(record, start, end, bounds_original)
    return _bounds_reply(record)


@app.post("/api/clips/{clip_id}/bounds/reset")
def reset_bounds(clip_id: str, member: Member = Depends(current_member)) -> dict[str, Any]:
    record = _clip_for_style(clip_id, member)
    if record.get("pendingAction"):
        raise HTTPException(409, "This clip is being replaced. Wait for it to finish.")
    original = record.get("boundsOriginal")
    if original is not None:
        _apply_bounds(record, original["start"], original["end"], None)
    return _bounds_reply(record)


def pick_alternate(
    alternates: list[dict[str, Any]], current: tuple[float, float], others: list[tuple[float, float]],
) -> int | None:
    """Index of the best saved runner-up (list is best first) that isn't
    substantially the clip it would replace, and doesn't clash with any of
    the job's other clips."""
    for i, a in enumerate(alternates):
        span = (a["start"], a["end"])
        if scoring.span_overlap(span, current) >= selection.SAME_MOMENT_OVERLAP:
            continue
        if any(scoring.span_overlap(span, o) >= scoring.MAX_OVERLAP for o in others):
            continue
        return i
    return None


def _start_clip_action(clip_id: str, kind: str, member: Member) -> dict[str, Any]:
    check_id(clip_id, "clip id")
    job_id = _job_id_of_clip(clip_id)
    _require_job(member, job_id)
    with _SELECTION_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            row = db.get_job(job_id)
            if row is None:
                raise HTTPException(404, "job not found")
            # Only installed into JOBS once it is known to be done, with its
            # clips loaded: a job whose worker died with the old process
            # must keep being reported by the status fallback as
            # interrupted, not as still processing.
            if row.get("status") != "done":
                raise HTTPException(409, "Clips can be changed once the video is done.")
            job = _job_from_row(row)
            new_clips = []
            for r in db.list_clips_for_job(job_id):
                c = _clip_row_to_api(r)
                _clear_orphaned_pending_action(r, c)
                new_clips.append(c)
            job.clips = new_clips
            JOBS[job_id] = job
        if job.status != "done":
            raise HTTPException(409, "Clips can be changed once the video is done.")
        record = next((c for c in job.clips if c["id"] == clip_id), None)
        if record is None:
            raise HTTPException(404, "clip not found")
        if not record.get("spec"):
            raise HTTPException(409, "This clip has no vertical version. Re-run the video.")
        if record.get("pendingAction"):
            raise HTTPException(409, "This clip is already being replaced.")
        if any(c.get("pendingAction") for c in job.clips if c["id"] != clip_id):
            raise HTTPException(409, "Another clip is being replaced. Wait for it to finish.")
        if kind == "swap":
            current = (record["start"], record["end"])
            others = [(c["start"], c["end"]) for c in job.clips if c["id"] != clip_id]
            if pick_alternate(job.alternates, current, others) is None:
                raise HTTPException(409, "No other moments left to swap in.")
        else:
            if groq_llm.build_chat() is None:
                raise HTTPException(409, "Regenerate needs GROQ_KEY.")
        record["pendingAction"] = kind
        record["actionError"] = None
    try:
        db.update_clip(clip_id, {"pending_action": kind, "action_error": None})
    except Exception:
        record["pendingAction"] = None
        raise
    _start_thread(_run_clip_action, job, clip_id, kind)
    return {"clipId": clip_id, "pendingAction": kind}


def _delete_clip_media(job_id: str, filename: str, storage_key: str | None) -> None:
    """Best-effort removal of a clip segment's local file and R2 object.
    Never raises: a leftover file only costs space, while raising here
    would fail an action whose result is already saved."""
    try:
        if validation.CLIP_FILENAME_RE.fullmatch(filename or ""):
            path = os.path.join(CLIPS_DIR, job_id, filename)
            if os.path.exists(path):
                os.remove(path)
    except Exception as e:  # noqa: BLE001
        print(f"[clips] couldn't delete {job_id}/{filename}: {e}")
    try:
        if validation.CLIP_FILENAME_RE.fullmatch(filename or ""):
            thumb = os.path.join(CLIPS_DIR, job_id, storage.thumb_filename(filename))
            if os.path.exists(thumb):
                os.remove(thumb)
    except Exception as e:  # noqa: BLE001
        print(f"[clips] couldn't delete poster for {job_id}/{filename}: {e}")
    if storage_key:
        for key in (storage_key, storage.thumb_filename(storage_key)):
            try:
                storage.delete_clip(key)
            except Exception as e:  # noqa: BLE001
                print(f"[r2] couldn't delete {key}: {e}")


def _run_clip_action(job: Job, clip_id: str, kind: str) -> None:
    record = next((c for c in job.clips if c["id"] == clip_id), None)
    idx = int(clip_id.rsplit("-", 1)[1])

    def fail(message: str) -> None:
        if record is not None:
            record["pendingAction"] = None
            record["actionError"] = message
        db.update_clip(clip_id, {"pending_action": None, "action_error": message})

    picked_alt: dict[str, Any] | None = None
    new_record: dict[str, Any] | None = None
    prepared: clipprep.PreparedClip | None = None
    # The replacement is cut to its own file name / R2 key, so the current
    # clip keeps playing (and rendering) from untouched media until the new
    # one is committed, and a failure leaves it exactly as it was.
    new_revision = ((record.get("revision") or 0) if record is not None else 0) + 1
    new_filename = clipprep.clip_filename(idx, new_revision)
    try:
        stored = db.get_transcript(job.id)
        if stored is None:
            fail("This video's transcript wasn't saved. Submit the video again.")
            return
        segs = [segment_from_dict(d) for d in stored["segments"]]
        current = (record["start"], record["end"])
        others = [(c["start"], c["end"]) for c in job.clips if c["id"] != clip_id]

        if kind == "swap":
            alt_idx = pick_alternate(job.alternates, current, others)
            if alt_idx is None:
                fail("No other moments left to swap in.")
                return
            # Captured by value rather than by this index: the long
            # prepare_clip below can take a while, and only one action per
            # job runs at a time now, but removing by value rather than a
            # possibly-stale index is cheap insurance against ever popping
            # the wrong alternate (or raising IndexError) if that changes.
            picked_alt = job.alternates[alt_idx]
            new_clip = selection.alternate_to_clip(picked_alt)
        else:
            try:
                new_clip = selection.regenerate(segs, stored.get("loudness") or [], current, others)
            except selection.SelectionFailed as e:
                fail(str(e))
                return
            if new_clip is None:
                fail("No better take found around this moment.")
                return

        try:
            meta = ingest.ingest(job.url, CACHE_DIR)
        except Exception as e:  # noqa: BLE001
            fail(f"Couldn't fetch the video again: {e}.")
            return

        prepared = clipprep.prepare_clip(
            job_id=job.id, idx=idx, clip=new_clip, video_path=meta.video_path,
            video_duration=meta.duration, segments=transcript.word_segments(segs),
            clips_dir=CLIPS_DIR, models_dir=MODELS_DIR, on_step=lambda s: None,
            revision=new_revision,
        )
        new_record = _clip_record(job.id, idx, new_clip, prepared, revision=new_revision)
        old_style = record["style"]
        new_record["style"] = {
            **new_record["style"],
            "captionPreset": old_style["captionPreset"],
            "accent": old_style["accent"],
            "captionPosition": old_style["captionPosition"],
        }
        fields = {k: v for k, v in _clip_row(job.id, idx, new_record).items() if k != "id"}
        fields |= {"words_original": None, "bounds_original": None, "pending_action": None, "action_error": None}
        db.update_clip_checked(clip_id, fields)
    except Exception as e:  # noqa: BLE001
        # Never committed: drop the half-made replacement; the old clip's
        # own file and object were never touched.
        _delete_clip_media(job.id, new_filename, prepared.storage_key if prepared is not None else None)
        fail(f"Couldn't {'swap' if kind == 'swap' else 'regenerate'} this clip: {e}")
        return

    for pos, c in enumerate(job.clips):
        if c["id"] == clip_id:
            job.clips[pos] = new_record
            break
    # Saved and swapped in, so nothing points at the old media any more.
    old_filename = (record.get("downloadUrl") or "").rsplit("/", 1)[-1]
    old_key = record.get("storageKey")
    if old_filename != new_filename:
        _delete_clip_media(job.id, old_filename, old_key if old_key != new_record["storageKey"] else None)
    if kind == "swap":
        try:
            job.alternates.remove(picked_alt)
        except ValueError:
            pass  # already gone somehow; nothing left to remove
        _persist_job(job)


@app.post("/api/clips/{clip_id}/swap")
def swap_clip(clip_id: str, member: Member = Depends(current_member)) -> dict[str, Any]:
    return _start_clip_action(clip_id, "swap", member)


@app.post("/api/clips/{clip_id}/regenerate")
def regenerate_clip(clip_id: str, member: Member = Depends(current_member)) -> dict[str, Any]:
    return _start_clip_action(clip_id, "regenerate", member)


@app.post("/api/clips/{clip_id}/render")
def start_render(clip_id: str, style: ClipStyle = Body(...), member: Member = Depends(current_member)) -> dict[str, Any]:
    record = _clip_for_style(clip_id, member)
    if record.get("pendingAction"):
        raise HTTPException(409, "This clip is being replaced. Wait for it to finish.")
    if RENDER_SERVICE is None:
        raise HTTPException(503, "Rendering not configured")
    if not record.get("storageKey"):
        raise HTTPException(409, "This clip's source isn't in R2, which Lambda rendering needs.")
    _save_style(record, style)
    try:
        words = [Word.model_validate(w) for w in record["spec"]["words"]]
    except (KeyError, TypeError, ValidationError):
        raise HTTPException(409, "This clip's captions can't be read. Re-run the video.")
    spec = record["spec"]
    return RENDER_SERVICE.request(clip_id, style, words, bounds=(spec["start"], spec["end"])).to_api()


def _get_render(render_id: str, member: Member) -> render.Render:
    check_id(render_id, "render id")
    if RENDER_SERVICE is None:
        raise HTTPException(503, "Rendering not configured")
    existing = RENDER_SERVICE.store.get(render_id)
    if existing is None:
        raise HTTPException(404, "render not found")
    # Checked before refresh() so another team can't even advance the render.
    _require_job(member, _job_id_of_clip(existing.clip_id))
    return RENDER_SERVICE.refresh(render_id)


# Declared before /api/renders/{render_id} so "zip" isn't taken as an id.
@app.get("/api/renders/zip")
def renders_zip(ids: str = Query(...), member: Member = Depends(current_member)) -> StreamingResponse:
    render_ids = [i for i in ids.split(",") if i][:MAX_ZIP_RENDERS]
    renders = [_get_render(i, member) for i in render_ids]
    if not renders or any(r.status != "done" for r in renders):
        raise HTTPException(409, "all renders must be finished")
    # Spools to disk past 64 MB; mp4s are already compressed, so store them as-is.
    buf = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for r in renders:
            with zf.open(f"highlyte-{r.clip_id}.mp4", "w") as dest, contextlib.closing(storage.open_object(r.storage_key)) as src:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    dest.write(chunk)
            clip_record = _find_clip(r.clip_id)
            if clip_record is not None and clip_record.get("spec"):
                zf.writestr(f"highlyte-{r.clip_id}.srt", srt.build_srt(clip_record["spec"]))
    buf.seek(0)

    def stream():
        try:
            yield from iter(lambda: buf.read(1024 * 1024), b"")
        finally:
            buf.close()

    return StreamingResponse(
        stream(), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="highlyte-clips.zip"'},
    )


@app.get("/api/renders/{render_id}")
def get_render(render_id: str, member: Member = Depends(current_member)) -> dict[str, Any]:
    return _get_render(render_id, member).to_api()


@app.get("/api/renders/{render_id}/file")
def get_render_file(render_id: str, member: Member = Depends(current_member)):
    r = _get_render(render_id, member)
    if r.status != "done" or not r.storage_key:
        raise HTTPException(409, "render not finished")
    url = storage.clip_url(r.storage_key)
    if url is None:
        raise HTTPException(503, "R2 not configured")
    return RedirectResponse(url)
