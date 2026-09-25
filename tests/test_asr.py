import pytest

from backend.pipeline import asr
from backend.pipeline.audio import Chunk

VERBOSE = {
    "segments": [
        {"start": 0.0, "end": 2.0, "avg_logprob": -0.1},
        {"start": 2.0, "end": 4.0, "avg_logprob": -1.0},
    ],
    "words": [
        {"word": " hum", "start": 0.1, "end": 0.4},
        {"word": "yahan", "start": 2.2, "end": 2.6},
        {"word": "  ", "start": 3.0, "end": 3.1},
    ],
}


def test_words_from_verbose_assigns_segment_confidence():
    words = asr.words_from_verbose(VERBOSE)
    assert [w.text for w in words] == ["hum", "yahan"]
    assert words[0].prob == pytest.approx(0.905, abs=1e-3)
    assert words[1].prob == pytest.approx(0.368, abs=1e-3)


def test_words_from_verbose_without_segments():
    words = asr.words_from_verbose({"words": [{"word": "a", "start": 0, "end": 1}]})
    assert words[0].prob == 1.0


class Fake:
    def __init__(self, name, answers):
        self.name, self.answers, self.calls = name, list(answers), []

    def transcribe(self, wav, *, prompt):
        self.calls.append((wav, prompt))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_transcribe_chunks_offsets_and_source():
    groq = Fake("groq", [[asr.AsrWord("a", 0.5, 0.9, 0.9)], [asr.AsrWord("b", 1.0, 1.2, 0.8)]])
    local = Fake("whisper", [])
    progress = []
    words, source = asr.transcribe_chunks(
        [Chunk("c0.wav", 0.0), Chunk("c1.wav", 100.0)], groq, local, prompt="seed",
        on_progress=lambda i, n, text: progress.append((i, n)),
    )
    assert [(w.text, w.start) for w in words] == [("a", 0.5), ("b", 101.0)]
    assert source == "groq" and progress == [(1, 2), (2, 2)]
    assert groq.calls[0] == ("c0.wav", "seed")


def test_transcribe_chunks_retries_rate_limit_then_succeeds():
    groq = Fake("groq", [RuntimeError("429 rate limit, retry in 1.5s"), [asr.AsrWord("a", 0, 1, 1.0)]])
    slept = []
    words, source = asr.transcribe_chunks([Chunk("c.wav", 0.0)], groq, Fake("whisper", []),
                                          prompt=None, sleep=slept.append)
    assert slept == [1.5] and source == "groq" and words[0].text == "a"


def test_transcribe_chunks_falls_back_to_local():
    groq = Fake("groq", [RuntimeError("server error")])
    local = Fake("whisper", [[asr.AsrWord("x", 0, 1, 0.7)]])
    words, source = asr.transcribe_chunks([Chunk("c.wav", 10.0)], groq, local, prompt=None)
    assert source == "whisper" and words[0].start == 10.0


def test_transcribe_chunks_mixed_source():
    groq = Fake("groq", [[asr.AsrWord("a", 0, 1, 1.0)], RuntimeError("boom")])
    local = Fake("whisper", [[asr.AsrWord("b", 0, 1, 1.0)]])
    _, source = asr.transcribe_chunks([Chunk("a.wav", 0), Chunk("b.wav", 5)], groq, local, prompt=None)
    assert source == "mixed"


def test_transcribe_chunks_without_groq_uses_local():
    local = Fake("whisper", [[asr.AsrWord("b", 0, 1, 1.0)]])
    _, source = asr.transcribe_chunks([Chunk("a.wav", 0)], None, local, prompt=None)
    assert source == "whisper"
