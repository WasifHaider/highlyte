import json
from types import SimpleNamespace

from backend.pipeline import highlight
from backend.pipeline.highlight import Clip, Sentence


def _client(content: str):
    completions = SimpleNamespace(
        create=lambda **kw: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
    )
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def _sentences():
    return [Sentence(start=i * 5.0, end=i * 5.0 + 4.8, text=f"Sentence number {i}.", idx=i) for i in range(6)]


def test_llm_window_reads_hook_title_virality_and_emphasis():
    sents = _sentences()
    content = json.dumps([{
        "start_idx": 0, "end_idx": 3, "virality_score": 8.5,
        "hook_title": "one two three four five six seven eight nine ten",
        "emphasis": ["number", "Sentence", 5, "a", "b", "c", "d"],
        "reason": "x", "tag": "Key insight",
    }])
    clips = highlight._llm_score_window(_client(content), sents, {s.idx: s for s in sents})
    assert len(clips) == 1
    c = clips[0]
    assert c.score == 8.5
    assert c.hook_title == "one two three four five six seven eight"  # capped at 8 words
    assert c.emphasis == ["number", "Sentence", "a", "b", "c"]  # strings only, max 5
    assert c.tag == "Key insight"


def test_llm_window_falls_back_to_hook_score_and_no_title():
    sents = _sentences()
    content = json.dumps([{"start_idx": 1, "end_idx": 4, "hook_score": 6, "tag": "Wild claim"}])
    c = highlight._llm_score_window(_client(content), sents, {s.idx: s for s in sents})[0]
    assert c.score == 6.0
    assert c.hook_title is None
    assert c.emphasis == []


def test_select_clips_keeps_hook_title_and_emphasis():
    sents = _sentences()
    cand = Clip(start=0.0, end=19.8, text="t", score=9.0, tag="Key insight", hook_title="Hook", emphasis=["x"])
    picked = highlight._select_clips([cand], sents)
    assert picked[0].hook_title == "Hook"
    assert picked[0].emphasis == ["x"]


def _recording_client(content: str, finish_reason: str = "stop", calls: list | None = None):
    def create(**kw):
        if calls is not None:
            calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason=finish_reason)])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_llm_window_asks_for_low_reasoning_effort():
    calls = []
    highlight._llm_score_window(_recording_client("[]", calls=calls), _sentences(), {})
    assert calls[0]["extra_body"] == {"reasoning_effort": "low"}


def test_llm_window_cut_off_answer_is_a_failure_not_an_empty_result():
    import pytest

    sents = _sentences()
    with pytest.raises(highlight.WindowFailed, match="cut off"):
        highlight._llm_score_window(_recording_client('[{"start_idx": 0', "length"), sents, {s.idx: s for s in sents})


def test_llm_window_unreadable_answer_is_a_failure():
    import pytest

    with pytest.raises(highlight.WindowFailed):
        highlight._llm_score_window(_recording_client("I think nothing here."), _sentences(), {})


def test_llm_window_empty_array_is_a_real_empty_result():
    assert highlight._llm_score_window(_recording_client("[]"), _sentences(), {}) == []


def _long_sentences(n=400):
    return [Sentence(start=i * 5.0, end=i * 5.0 + 4.8, text="word " * 40, idx=i) for i in range(n)]


def test_all_windows_rate_limited_raises_clear_error(monkeypatch):
    import pytest

    monkeypatch.setenv("GROQ_KEY", "k")

    def boom(client, window, by_idx):
        raise RuntimeError("Error code: 429 - Rate limit reached ... Please try again in 21m0.576s.")

    monkeypatch.setattr(highlight, "_llm_score_window", boom)
    with pytest.raises(highlight.ClipSelectionError, match="daily limit.*21 minutes"):
        highlight.score_chunks_llm_boundaries(_long_sentences())


def test_all_windows_cut_off_raises_generic_error(monkeypatch):
    import pytest

    monkeypatch.setenv("GROQ_KEY", "k")

    def cut(client, window, by_idx):
        raise highlight.WindowFailed("cut off at 2200 tokens")

    monkeypatch.setattr(highlight, "_llm_score_window", cut)
    with pytest.raises(highlight.ClipSelectionError, match="Clip selection failed"):
        highlight.score_chunks_llm_boundaries(_long_sentences())


def test_some_windows_failing_keeps_clips_from_the_rest(monkeypatch):
    monkeypatch.setenv("GROQ_KEY", "k")
    seen = []

    def half(client, window, by_idx):
        seen.append(window[0].idx)
        if len(seen) % 2:
            raise highlight.WindowFailed("cut off at 2200 tokens")
        return [Clip(start=window[0].start, end=window[0].start + 20, text="x", score=5, tag="Key insight")]

    monkeypatch.setattr(highlight, "_llm_score_window", half)
    clips = highlight.score_chunks_llm_boundaries(_long_sentences())
    assert len(seen) > 2 and len(clips) == len(seen) // 2
