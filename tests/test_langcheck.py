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


def test_decide_survives_detector_errors():
    calls = []

    def detect(path):
        calls.append(path)
        if path == "b.wav":
            raise RuntimeError("groq down")
        return "english"

    assert lc.decide(["a.wav", "b.wav", "c.wav"], "hinglish", detect) == lc.LanguageDecision("hinglish", None)
    assert calls == ["a.wav", "b.wav", "c.wav"]
