from backend.pipeline import langcheck as lc


def test_normalize_code():
    assert lc.normalize_code("English") == "en"
    assert lc.normalize_code("hindi") == "hi"
    assert lc.normalize_code("ur") == "ur"
    assert lc.normalize_code("french") == "other"
    assert lc.normalize_code(None) is None


def test_all_english_overrides_hinglish_choice():
    d = lc.rule(["en", "en", "en"], "hinglish")
    assert d == lc.LanguageDecision("english", lc.NOTE_ENGLISH)


def test_all_english_matching_choice_has_no_note():
    assert lc.rule(["en", "en", "en"], "english") == lc.LanguageDecision("english", None)


def test_any_hindi_or_urdu_overrides_english_choice():
    assert lc.rule(["en", "ur", "en"], "english") == lc.LanguageDecision("hinglish", lc.NOTE_HINGLISH)
    assert lc.rule(["hi", "en", "en"], "hinglish") == lc.LanguageDecision("hinglish", None)


def test_unclear_keeps_choice():
    assert lc.rule(["en", None, "en"], "hinglish") == lc.LanguageDecision("hinglish", None)
    assert lc.rule(["en", "other", "en"], "hinglish") == lc.LanguageDecision("hinglish", None)
    assert lc.rule([None, None, None], "english") == lc.LanguageDecision("english", None)


def test_groq_detector_dumps_without_pydantic_warnings(monkeypatch, tmp_path):
    """openai 1.57.4 types duration as str while Groq returns a float, so a
    plain model_dump() prints a UserWarning on every call; the detector
    must suppress it with model_dump(warnings=False)."""
    calls = []

    class FakeResp:
        def model_dump(self, **kwargs):
            calls.append(kwargs)
            return {"language": "hindi"}

    class FakeTranscriptions:
        def create(self, *, file, **kwargs):
            return FakeResp()

    class FakeAudio:
        transcriptions = FakeTranscriptions()

    class FakeClient:
        audio = FakeAudio()

    monkeypatch.setattr("openai.OpenAI", lambda **kw: FakeClient())
    path = tmp_path / "s.wav"
    path.write_bytes(b"\x00")
    detect = lc.groq_detector("key")
    assert detect(str(path)) == "hindi"
    assert calls == [{"warnings": False}]


def test_decide_survives_detector_errors():
    calls = []

    def detect(path):
        calls.append(path)
        if path == "b.wav":
            raise RuntimeError("groq down")
        return "english"

    assert lc.decide(["a.wav", "b.wav", "c.wav"], "hinglish", detect) == lc.LanguageDecision("hinglish", None)
    assert calls == ["a.wav", "b.wav", "c.wav"]
