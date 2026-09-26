"""Coverage for backend.main._run_pipeline: the wiring between ingest,
transcript, persistence and clip selection that nothing else in the
test suite exercises end to end.
"""
from __future__ import annotations

from backend import main
from backend.pipeline import segments, selection
from backend.pipeline.ingest import VideoMeta
from backend.pipeline.transcript import Transcript


def _meta() -> VideoMeta:
    return VideoMeta(
        video_id="vid123", title="A Video", channel="A Channel", duration=90.0,
        audio_path="/tmp/a.wav", video_path="/tmp/a.mp4", thumbnail_url=None,
    )


def _segment() -> segments.Segment:
    word = segments.SegWord(t="hi", raw="hi", start=0.0, end=0.5, kind="hinglish", prob=0.9)
    return segments.Segment(
        id="seg_0000", start=0.0, end=0.5, speaker="A", language="hi-Latn-EN",
        raw="hi", hinglish="hi", words=[word], confidence=0.9,
    )


def _transcript() -> Transcript:
    return Transcript(
        segments=[_segment()], language="hinglish", note="Detected Hindi/Urdu speech.",
        source="groq",
    )


def _job() -> main.Job:
    return main.Job(id="job1", url="https://youtu.be/x", language_requested="english")


def test_happy_path_persists_language_and_saves_before_selection(monkeypatch):
    calls: list[str] = []
    saved = {}
    upserted_rows = []

    monkeypatch.setattr(main.ingest, "ingest", lambda url, cache_dir, on_progress=None: _meta())
    monkeypatch.setattr(
        main.transcript, "transcribe",
        lambda audio_path, requested, on_progress=None, **kw: _transcript(),
    )

    def fake_save_transcript(job_id, language, source, segs, loudness=None):
        calls.append("save_transcript")
        saved["job_id"], saved["language"], saved["source"], saved["segments"] = job_id, language, source, segs

    def fake_select(segs, loudness):
        calls.append("select")
        return selection.Selection([])

    def fake_upsert_job(row):
        upserted_rows.append(row)

    monkeypatch.setattr(main.db, "save_transcript", fake_save_transcript)
    monkeypatch.setattr(main.selection, "select", fake_select)
    monkeypatch.setattr(main.db, "upsert_job", fake_upsert_job)
    monkeypatch.setattr(main.db, "insert_clips", lambda rows: None)

    job = _job()
    main._run_pipeline(job)

    assert job.status == "done"
    assert job.error is None
    assert job.language_used == "hinglish"
    assert job.language_note == "Detected Hindi/Urdu speech."
    assert job.transcript_source == "groq"

    # save_transcript ran with the segment dicts, before select.
    assert calls == ["save_transcript", "select"]
    assert saved["job_id"] == "job1"
    assert saved["language"] == "hinglish"
    assert saved["source"] == "groq"
    assert saved["segments"] == [_segment().to_dict()]

    # The persisted job row carries the language fields through to Supabase.
    final_row = upserted_rows[-1]
    assert final_row["language_requested"] == "english"
    assert final_row["language_used"] == "hinglish"
    assert final_row["language_note"] == "Detected Hindi/Urdu speech."


def test_save_transcript_failure_fails_job_and_skips_selection(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(main.ingest, "ingest", lambda url, cache_dir, on_progress=None: _meta())
    monkeypatch.setattr(
        main.transcript, "transcribe",
        lambda audio_path, requested, on_progress=None, **kw: _transcript(),
    )

    def fake_save_transcript(job_id, language, source, segs, loudness=None):
        calls.append("save_transcript")
        raise RuntimeError("supabase is down")

    def fake_select(segs, loudness):
        calls.append("select")
        return selection.Selection([])

    monkeypatch.setattr(main.db, "save_transcript", fake_save_transcript)
    monkeypatch.setattr(main.selection, "select", fake_select)
    monkeypatch.setattr(main.db, "upsert_job", lambda row: None)
    monkeypatch.setattr(main.db, "insert_clips", lambda rows: None)

    job = _job()
    main._run_pipeline(job)

    assert job.status == "error"
    assert "supabase is down" in job.error
    assert calls == ["save_transcript"]  # select never runs


def _patch_common(monkeypatch, rows):
    monkeypatch.setattr(main.ingest, "ingest", lambda url, cache_dir, on_progress=None: _meta())
    monkeypatch.setattr(
        main.transcript, "transcribe",
        lambda audio_path, requested, on_progress=None, **kw: _transcript(),
    )
    monkeypatch.setattr(main.db, "save_transcript", lambda *a, **k: None)
    monkeypatch.setattr(main.db, "upsert_job", rows.append)
    monkeypatch.setattr(main.db, "insert_clips", lambda r: None)


def test_selection_failure_parks_the_job_for_retry(monkeypatch):
    rows = []
    _patch_common(monkeypatch, rows)

    def fail(segs, loudness):
        raise selection.SelectionFailed("Clip selection hit Groq's daily limit. Try again in about 5 minutes.")

    monkeypatch.setattr(main.selection, "select", fail)
    job = _job()
    main._run_pipeline(job)
    assert job.status == "selection_failed"
    assert job.error.startswith("Clip selection hit Groq's daily limit")
    assert rows[-1]["status"] == "selection_failed"


def test_selection_note_is_persisted(monkeypatch):
    rows = []
    _patch_common(monkeypatch, rows)
    monkeypatch.setattr(main.selection, "select", lambda segs, loudness: selection.Selection([], "Skipped 1:00–2:00 (error)."))
    job = _job()
    main._run_pipeline(job)
    assert job.status == "done" and job.selection_note == "Skipped 1:00–2:00 (error)."
    assert rows[-1]["selection_note"] == "Skipped 1:00–2:00 (error)."


def test_selection_retry_runs_from_the_stored_transcript(monkeypatch):
    got = {}
    monkeypatch.setattr(main.ingest, "ingest", lambda url, cache_dir, on_progress=None: _meta())
    monkeypatch.setattr(main.db, "upsert_job", lambda row: None)

    def fake_select(segs, loudness):
        got["segs"], got["loudness"] = segs, loudness
        return selection.Selection([], "note")

    monkeypatch.setattr(main.selection, "select", fake_select)
    job = main.Job(id="job9", url="https://youtu.be/x", status="analyzing")
    main._run_selection_retry(job, {"segments": [_segment().to_dict()], "loudness": [-20.0]})
    assert job.status == "done" and job.selection_note == "note"
    assert got["segs"] == [_segment()] and got["loudness"] == [-20.0]


def test_selection_retry_ingest_failure_stays_retryable(monkeypatch):
    def fail_ingest(url, cache_dir, on_progress=None):
        raise RuntimeError("network blip")

    monkeypatch.setattr(main.ingest, "ingest", fail_ingest)
    job = main.Job(id="job9", url="https://youtu.be/x", status="analyzing")
    main._run_selection_retry(job, {"segments": [_segment().to_dict()], "loudness": [-20.0]})
    assert job.status == "selection_failed"
    assert job.error == "Couldn't fetch the video again: network blip. Try again."


def test_qa_flags_add_no_face_start_only_when_known():
    assert main._qa_flags(["weak_pick"], False) == ["weak_pick", "no_face_start"]
    assert main._qa_flags([], True) == []
    assert main._qa_flags([], None) == []
