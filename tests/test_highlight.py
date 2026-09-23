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
