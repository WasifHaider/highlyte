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


def test_words_from_verbose_drops_words_in_hallucinated_segments():
    """A segment with high no_speech_prob and low avg_logprob is Whisper
    inventing text over silence/music; its words must be dropped."""
    resp = {
        "segments": [
            {"start": 0.0, "end": 2.0, "avg_logprob": -0.1, "no_speech_prob": 0.05},
            {"start": 2.0, "end": 4.0, "avg_logprob": -1.5, "no_speech_prob": 0.9},
        ],
        "words": [
            {"word": " hum", "start": 0.1, "end": 0.4},
            {"word": "junk", "start": 2.2, "end": 2.6},
        ],
    }
    words = asr.words_from_verbose(resp)
    assert [w.text for w in words] == ["hum"]


def test_words_from_verbose_keeps_words_with_only_one_hallucination_signal():
    """Only dropped when BOTH no_speech_prob and avg_logprob cross their
    thresholds; either alone is not enough to call it a hallucination."""
    resp = {
        "segments": [
            {"start": 0.0, "end": 2.0, "avg_logprob": -0.1, "no_speech_prob": 0.9},
            {"start": 2.0, "end": 4.0, "avg_logprob": -1.5, "no_speech_prob": 0.1},
        ],
        "words": [
            {"word": "keep1", "start": 0.1, "end": 0.4},
            {"word": "keep2", "start": 2.2, "end": 2.6},
        ],
    }
    words = asr.words_from_verbose(resp)
    assert [w.text for w in words] == ["keep1", "keep2"]


class FakeOpenAIResponse:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self, **kwargs):  # noqa: ARG002 - accepts warnings=False
        return self._payload


class FakeTranscriptions:
    def __init__(self, payload):
        self.payload = payload

    def create(self, *, file, **kwargs):  # noqa: ARG002
        return FakeOpenAIResponse(self.payload)


class FakeAudio:
    def __init__(self, payload):
        self.transcriptions = FakeTranscriptions(payload)


class FakeOpenAIClient:
    def __init__(self, payload):
        self.audio = FakeAudio(payload)


def test_groq_asr_raises_when_segments_have_text_but_no_words(tmp_path, monkeypatch):
    """Groq sometimes returns segments (with real speech text) but no word
    list at all; returning [] would silently drop that speech instead of
    sending the chunk to the local fallback."""
    payload = {
        "segments": [{"start": 0.0, "end": 2.0, "avg_logprob": -0.1, "text": "hum yahan hain"}],
        "words": [],
    }
    monkeypatch.setattr("openai.OpenAI", lambda **kw: FakeOpenAIClient(payload))
    wav = tmp_path / "c.wav"
    wav.write_bytes(b"\x00")
    provider = asr.GroqAsr("key", "whisper-large-v3")
    with pytest.raises(RuntimeError, match="no word timestamps"):
        provider.transcribe(str(wav), prompt=None)


def test_groq_asr_returns_empty_when_segments_also_have_no_text(tmp_path, monkeypatch):
    """Genuinely silent/no-speech segments (empty text) must not raise -
    only the case where Groq has speech text but withheld word timings."""
    payload = {
        "segments": [{"start": 0.0, "end": 2.0, "avg_logprob": -0.1, "text": "  "}],
        "words": [],
    }
    monkeypatch.setattr("openai.OpenAI", lambda **kw: FakeOpenAIClient(payload))
    wav = tmp_path / "c.wav"
    wav.write_bytes(b"\x00")
    provider = asr.GroqAsr("key", "whisper-large-v3")
    assert provider.transcribe(str(wav), prompt=None) == []


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
