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
