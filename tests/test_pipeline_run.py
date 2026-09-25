"""Coverage for backend.main._run_pipeline: the wiring between ingest,
transcript, persistence and highlight detection that nothing else in the
test suite exercises end to end.
"""
from __future__ import annotations

from backend import main
from backend.pipeline import segments
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


def test_happy_path_persists_language_and_saves_before_highlights(monkeypatch):
    calls: list[str] = []
    saved = {}
    upserted_rows = []

    monkeypatch.setattr(main.ingest, "ingest", lambda url, cache_dir, on_progress=None: _meta())
    monkeypatch.setattr(
        main.transcript, "transcribe",
        lambda audio_path, requested, on_progress=None, **kw: _transcript(),
    )

    def fake_save_transcript(job_id, language, source, segs):
        calls.append("save_transcript")
        saved["job_id"], saved["language"], saved["source"], saved["segments"] = job_id, language, source, segs

    def fake_detect_highlights(word_segments):
        calls.append("detect_highlights")
        return []

    def fake_upsert_job(row):
        upserted_rows.append(row)

    monkeypatch.setattr(main.db, "save_transcript", fake_save_transcript)
    monkeypatch.setattr(main.highlight, "detect_highlights", fake_detect_highlights)
    monkeypatch.setattr(main.db, "upsert_job", fake_upsert_job)
    monkeypatch.setattr(main.db, "insert_clips", lambda rows: None)

    job = _job()
    main._run_pipeline(job)

    assert job.status == "done"
    assert job.error is None
    assert job.language_used == "hinglish"
    assert job.language_note == "Detected Hindi/Urdu speech."
    assert job.transcript_source == "groq"

    # save_transcript ran with the segment dicts, before detect_highlights.
    assert calls == ["save_transcript", "detect_highlights"]
    assert saved["job_id"] == "job1"
    assert saved["language"] == "hinglish"
    assert saved["source"] == "groq"
    assert saved["segments"] == [_segment().to_dict()]

    # The persisted job row carries the language fields through to Supabase.
    final_row = upserted_rows[-1]
    assert final_row["language_requested"] == "english"
    assert final_row["language_used"] == "hinglish"
    assert final_row["language_note"] == "Detected Hindi/Urdu speech."


def test_save_transcript_failure_fails_job_and_skips_highlights(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(main.ingest, "ingest", lambda url, cache_dir, on_progress=None: _meta())
    monkeypatch.setattr(
        main.transcript, "transcribe",
        lambda audio_path, requested, on_progress=None, **kw: _transcript(),
    )

    def fake_save_transcript(job_id, language, source, segs):
        calls.append("save_transcript")
        raise RuntimeError("supabase is down")

    def fake_detect_highlights(word_segments):
        calls.append("detect_highlights")
        return []

    monkeypatch.setattr(main.db, "save_transcript", fake_save_transcript)
    monkeypatch.setattr(main.highlight, "detect_highlights", fake_detect_highlights)
    monkeypatch.setattr(main.db, "upsert_job", lambda row: None)
    monkeypatch.setattr(main.db, "insert_clips", lambda rows: None)

    job = _job()
    main._run_pipeline(job)

    assert job.status == "error"
    assert "supabase is down" in job.error
    assert calls == ["save_transcript"]  # detect_highlights never runs
