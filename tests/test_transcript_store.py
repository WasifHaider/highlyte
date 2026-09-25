"""db.save_transcript / get_transcript against a fake supabase client."""
import pytest

from backend import db


class FakeTable:
    def __init__(self, store, fail=False):
        self.store, self.fail, self.filters = store, fail, {}

    def upsert(self, row):
        self.row = row
        return self

    def select(self, *_):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, _):
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("supabase down")
        if hasattr(self, "row"):
            self.store[self.row["job_id"]] = self.row
            return type("R", (), {"data": [self.row]})()
        row = self.store.get(self.filters.get("job_id"))
        return type("R", (), {"data": [row] if row else []})()


class FakeClient:
    def __init__(self, fail=False):
        self.store, self.fail = {}, fail

    def table(self, name):
        assert name == "transcripts"
        return FakeTable(self.store, self.fail)


def test_save_and_get_transcript(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(db, "get_client", lambda: fake)
    segs = [{"id": "seg_0001", "hinglish": "hum yahan hain"}]
    db.save_transcript("job1", "hinglish", "groq", segs)
    got = db.get_transcript("job1")
    assert got["language"] == "hinglish" and got["source"] == "groq" and got["segments"] == segs


def test_save_transcript_raises_on_error(monkeypatch):
    monkeypatch.setattr(db, "get_client", lambda: FakeClient(fail=True))
    with pytest.raises(RuntimeError):
        db.save_transcript("job1", "english", "groq", [])


def test_transcript_functions_without_supabase(monkeypatch):
    monkeypatch.setattr(db, "get_client", lambda: None)
    db.save_transcript("job1", "english", "groq", [])  # no-op
    assert db.get_transcript("job1") is None
