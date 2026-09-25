import numpy as np
import pytest

from backend.pipeline import audio, transcript
from backend.pipeline.asr import AsrWord
from backend.pipeline.audio import Chunk


class FakeAsr:
    name = "groq"

    def __init__(self, words):
        self.words, self.prompts = words, []

    def transcribe(self, wav, *, prompt):
        self.prompts.append(prompt)
        return self.words


@pytest.fixture
def fake_audio(monkeypatch):
    monkeypatch.setattr(audio, "normalize", lambda src, dst: None)
    monkeypatch.setattr(audio, "load", lambda path: np.zeros(audio.SR * 60, dtype=np.float32))
    monkeypatch.setattr(audio, "language_samples", lambda s, d: ["s1.wav", "s2.wav", "s3.wav"])
    monkeypatch.setattr(audio, "speech_chunks", lambda s, d: [Chunk("c0.wav", 0.0)])


def test_hinglish_path_uses_seed_and_spelling(fake_audio):
    asr_ = FakeAsr([AsrWord("yar", 0.0, 0.3, 0.9), AsrWord("bhoat", 0.3, 0.6, 0.9), AsrWord("acha.", 0.6, 0.9, 0.9)])
    t = transcript.transcribe("a.m4a", "hinglish", detect=lambda p: "hindi", primary=asr_, fallback=asr_)
    assert asr_.prompts == [transcript.ROMAN_URDU_HINDI_SEED]
    assert t.language == "hinglish" and t.note is None and t.source == "groq"
    assert t.segments[0].hinglish == "yaar bohat acha." and t.segments[0].raw == "yar bhoat acha."
    assert t.segments[0].language == "hi-Latn-EN"


def test_detected_english_overrides_and_drops_prompt(fake_audio):
    asr_ = FakeAsr([AsrWord("yar", 0.0, 0.3, 0.9)])
    t = transcript.transcribe("a.m4a", "hinglish", detect=lambda p: "english", primary=asr_, fallback=asr_)
    assert asr_.prompts == [None]
    assert t.language == "english" and t.note
    assert t.segments[0].hinglish == "yar" and t.segments[0].language == "en"


def test_no_speech_raises(fake_audio, monkeypatch):
    monkeypatch.setattr(audio, "speech_chunks", lambda s, d: [])
    with pytest.raises(transcript.NoSpeechError):
        transcript.transcribe("a.m4a", "english", detect=lambda p: "english",
                              primary=FakeAsr([]), fallback=FakeAsr([]))


def test_to_word_segments_uses_fixed_text(fake_audio):
    asr_ = FakeAsr([AsrWord("yar", 1.0, 1.3, 0.9), AsrWord("sun", 1.3, 1.6, 0.9)])
    t = transcript.transcribe("a.m4a", "hinglish", detect=lambda p: "hindi", primary=asr_, fallback=asr_)
    segs = transcript.to_word_segments(t)
    assert [(s.start, s.end, s.text) for s in segs] == [(1.0, 1.3, "yaar"), (1.3, 1.6, "sun")]


def test_adapter_output_feeds_the_highlight_scorer(fake_audio):
    from backend.pipeline import highlight

    words = [AsrWord(f"baat{i}.", i * 0.5, i * 0.5 + 0.4, 0.9) for i in range(200)]
    asr_ = FakeAsr(words)
    t = transcript.transcribe("a.m4a", "hinglish", detect=lambda p: "hindi", primary=asr_, fallback=asr_)
    highlight.detect_highlights(transcript.to_word_segments(t))  # must not raise
